"""Live CTA engine (sub-project G): short-carry family from phase-2b. Signals
from Binance-venue data (Coinalyze OI+LSR, Binance klines) via data.py;
execution on Hyperliquid perps via the aggressive-IoC-limit shape proven in
momentum/carry. The drawdown breaker is polled every SYNC_INTERVAL_SECONDS; the
signal recomputes/rebalances only every REBALANCE_INTERVAL_HOURS (4h bars —
rebalancing more often just churns on an unclosed bar).

Order shape: "market" = aggressive IoC limit at mid +/- ORDER_SLIPPAGE, rounded
to venue tick rules (round_price/round_size), the same shape momentum/live.py
documents. Non-reduce-only OPENS are non-idempotent -> single attempt through
ResilientExchange.order (a lost response self-heals next cycle when positions
are re-read from HL); reduce-only CLOSES are idempotent -> ResilientExchange
retries them.

Cross-venue staleness (spec): if a coin's Binance/Coinalyze data is stale we
skip NEW entries for it this cycle but STILL manage its existing exits/stops
from HL state and STILL run the portfolio drawdown breaker.

Bookkeeping crash-safety: HL does not report our entry price/time, so the
2xATR stop and 14d max-hold anchors live ONLY in the state file's `entries`.
Three invariants keep a real position and its bookkeeping in lockstep:
(1) an entry is recorded only after _place_order confirms a submission, and
is persisted to disk IMMEDIATELY, not at loop end; (2) a failed exit close
RETAINS its entry — loud log + alert, and the exit re-fires next cycle;
(3) a universe position with NO entry record (entry-side crash window) is
reconciled at the next rebalance by flattening it (_reconcile_orphans)."""
from __future__ import annotations

import argparse
import logging
import time

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from hlvault.gridbot.exchange_utils import get_mid_price, get_sz_decimals, round_price, round_size
from hlvault.gridbot.resilience import ResilientExchange
from hlvault.notify.telegram import send_alert

from . import config as cfg
from . import data, risk, signals
from .state import load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cta")

# The crowding percentile needs a full trailing window
# (CROWD_WINDOW_DAYS * BARS_PER_DAY = 90*6 = 540 bars) plus the trend warmup
# before the rank is trusted; computed from config so it can never be smaller
# than the crowd window (or crowd_percentile returns NaN and no coin trades).
LOOKBACK_BARS = cfg.CROWD_WINDOW_DAYS * cfg.BARS_PER_DAY + cfg.TREND_WARMUP_BARS + 60


class CtaEngine:
    def __init__(self, live_trading: bool | None = None):
        if not cfg.WALLET_PRIVATE_KEY or not cfg.WALLET_ADDRESS:
            raise RuntimeError("WALLET_PRIVATE_KEY / WALLET_ADDRESS not set in .env.cta")
        self.live_trading = cfg.LIVE_TRADING if live_trading is None else live_trading
        account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
        self.info = Info(cfg.HL_API_URL, skip_ws=True)
        raw = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
        self.exchange = ResilientExchange(raw)
        self.state = load_state(cfg.STATE_FILE)

    # ---- safety ------------------------------------------------------
    def bootstrap_if_needed(self) -> None:
        if self.state.get("peak_equity", 0.0) > 0:
            return
        equity = risk.account_equity(self.info, cfg.WALLET_ADDRESS)
        self.state["peak_equity"] = equity
        save_state(cfg.STATE_FILE, self.state)
        logger.info(f"bootstrap: starting equity ${equity:,.2f}")

    def check_drawdown(self) -> bool:
        halted, self.state = risk.check_drawdown(
            self.info, cfg.WALLET_ADDRESS, self.state, cfg.MAX_DRAWDOWN_PCT)
        if not halted:
            save_state(cfg.STATE_FILE, self.state)
            return False
        # Persist the halt BEFORE attempting to flatten (risk.check_drawdown's
        # documented caller obligation): a crash mid-flatten must not lose the
        # halt flag and cause a restart to skip re-checking drawdown.
        save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_alerted_this_halt"):
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                      "CTA DRAWDOWN CIRCUIT BREAKER TRIPPED — flattening and halting.")
            self.state["_alerted_this_halt"] = True
            save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_flatten_complete"):
            if self._flatten_everything():
                self.state["_flatten_complete"] = True
            else:
                send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                          "CTA FLATTEN INCOMPLETE — positions may remain, will retry next cycle.")
            save_state(cfg.STATE_FILE, self.state)
        return True

    def _flatten_everything(self) -> bool:
        """Close every open HL position (reduce-only, idempotent -> retried by
        ResilientExchange). Dry-run logs and skips (the --dry-run operator
        contract: no real exchange writes, matching momentum/carry). Returns
        True only when all confirmed closed; clears entries bookkeeping on full
        success so a re-arm starts clean."""
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        any_failed = False
        for p in user_state.get("assetPositions", []):
            pos = p["position"]
            size = float(pos["szi"])
            coin = pos["coin"]
            if abs(size) < 1e-9:
                continue
            if not self.live_trading:
                logger.info(f"[DRY RUN] would flatten {coin} size={abs(size)}")
                continue
            try:
                self.exchange.market_close(coin, abs(size))
            except Exception as e:
                any_failed = True
                logger.error(f"SAFETY-CRITICAL: flatten failed for {coin}: {e}")
        if any_failed:
            logger.error("SAFETY-CRITICAL: not everything could be flattened — will retry next cycle")
        if not any_failed and self.live_trading:
            self.state["entries"] = {}
        return not any_failed

    # ---- execution ---------------------------------------------------
    def _place_order(self, coin: str, is_buy: bool, size: float, reduce_only: bool) -> bool:
        """Returns True only when an order was actually submitted (dry-run
        counts as a simulated submission). Every nothing-happened path — no
        mid, size rounding to zero, the submit raising — returns False so the
        caller never records entry bookkeeping for a position that does not
        exist on the exchange."""
        if not self.live_trading:
            logger.info(f"[DRY RUN] {coin} is_buy={is_buy} size={size} reduce_only={reduce_only}")
            return True
        try:
            mid = get_mid_price(self.info, coin)
            if mid <= 0:
                logger.warning(f"{coin}: no mid, skipping order this cycle")
                return False
            sz_dec = get_sz_decimals(self.info, coin)
            raw_px = mid * (1 + cfg.ORDER_SLIPPAGE) if is_buy else mid * (1 - cfg.ORDER_SLIPPAGE)
            limit_px = round_price(raw_px, sz_dec)
            sz = round_size(size, sz_dec)
            if sz <= 0:
                logger.warning(f"{coin}: size {size} rounds to zero, skipping order")
                return False
            self.exchange.order(coin, is_buy, sz, limit_px,
                                order_type={"limit": {"tif": "Ioc"}}, reduce_only=reduce_only)
            logger.info(f"{coin}: placed is_buy={is_buy} size={sz} @ {limit_px} reduce_only={reduce_only}")
            return True
        except Exception as e:
            logger.error(f"{coin}: order failed: {e} (next cycle re-reconciles)")
            return False

    # ---- orphan reconciliation ---------------------------------------
    def _reconcile_orphans(self, pos_by_coin: dict, entries: dict) -> None:
        """Flatten any universe coin holding an HL position with NO `entries`
        record. An orphan means the bookkeeping already failed (a crash in the
        window between an open landing and its entry being persisted, or a
        lost order response whose write actually landed): the true entry
        price/time are unknown, so its 2xATR stop and max-hold clock can never
        be evaluated again — only the 20% portfolio breaker would remain. For
        a forward-test engine, honestly closing the position is safer than
        managing it against a reconstructed (wrong) stop anchor. Note the exit
        path RETAINS its entry when a close fails (the exit re-fires next
        cycle), so a failed EXIT never lands here — this path only catches
        entry-side crashes. Reduce-only close is idempotent -> retried by
        ResilientExchange; dry-run gated like every other exchange write. The
        coin keeps its position in pos_by_coin this cycle, so the per-coin
        loop will not immediately re-enter it."""
        for coin in cfg.COIN_UNIVERSE:
            size = pos_by_coin.get(coin, 0.0)
            if abs(size) < 1e-9 or coin in entries:
                continue
            logger.error(f"SAFETY-CRITICAL: orphan position {coin} (size {size}) "
                         "has no entry bookkeeping — flattening")
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                       f"CTA ORPHAN POSITION {coin} (size {size}): no entry bookkeeping — "
                       "flattening reduce-only.")
            if not self.live_trading:
                logger.info(f"[DRY RUN] would flatten orphan {coin} size={abs(size)}")
                continue
            try:
                self.exchange.market_close(coin, abs(size))
            except Exception as e:
                logger.error(f"SAFETY-CRITICAL: orphan flatten failed for {coin}: {e} "
                             "(will retry next rebalance)")

    # ---- rebalance ---------------------------------------------------
    def maybe_rebalance(self) -> None:
        now_ms = int(time.time() * 1000)
        interval_ms = int(cfg.REBALANCE_INTERVAL_HOURS * 3600 * 1000)
        if now_ms - self.state.get("last_rebalance_ms", 0) < interval_ms:
            return

        feed = data.CtaData(cfg.COIN_UNIVERSE, LOOKBACK_BARS)
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        pos_by_coin = {p["position"]["coin"]: float(p["position"]["szi"])
                       for p in user_state.get("assetPositions", [])}
        # entries must alias self.state["entries"] BEFORE the loop so the
        # immediate per-entry/per-exit save_state calls persist the live dict.
        entries = self.state.setdefault("entries", {})

        self._reconcile_orphans(pos_by_coin, entries)

        for coin in cfg.COIN_UNIVERSE:
            # Per-coin isolation: one coin's transient failure (mid lookup,
            # data hiccup, anything in its path) must not abort exit/stop
            # management for every OTHER coin this cycle.
            try:
                self._process_coin(coin, feed, pos_by_coin, entries, now_ms)
            except Exception:
                logger.exception(f"{coin}: cycle processing failed; continuing with next coin")

        self.state["last_rebalance_ms"] = now_ms
        self.state["_alerted_this_halt"] = False
        self.state["_flatten_complete"] = False
        save_state(cfg.STATE_FILE, self.state)

    def _process_coin(self, coin: str, feed, pos_by_coin: dict, entries: dict,
                      now_ms: int) -> None:
        """One coin's rebalance step: manage exits/stops on an existing
        position first, then consider a fresh entry. `entries` aliases
        self.state["entries"] so the immediate save_state calls persist it."""
        crowd_window_bars = cfg.CROWD_WINDOW_DAYS * cfg.BARS_PER_DAY
        crowd_warmup_bars = cfg.CROWD_WARMUP_DAYS * cfg.BARS_PER_DAY
        fuel_lb_bars = max(1, round(cfg.FUEL_LOOKBACK_HOURS / 24 * cfg.BARS_PER_DAY))

        try:
            frame = feed.frame_for(coin)
        except Exception as e:
            logger.error(f"{coin}: data fetch failed ({e}); managing existing pos only")
            frame = None

        mid = get_mid_price(self.info, coin)
        cur_sz = pos_by_coin.get(coin, 0.0)
        direction = 1 if cur_sz > 0 else (-1 if cur_sz < 0 else 0)

        # closed-bar signal: drop the final (still-forming) bar so the live
        # signal is computed from CLOSED bars only, matching the backtest.
        sig = None
        if frame is not None and len(frame) > cfg.TREND_WARMUP_BARS + 2:
            closed = frame.iloc[:-1]
            sig = signals.compute_signals(
                closed, ema_fast=cfg.EMA_FAST, ema_slow=cfg.EMA_SLOW,
                trend_warmup_bars=cfg.TREND_WARMUP_BARS, crowd_pctile=cfg.CROWD_PCTILE,
                crowd_window_bars=crowd_window_bars, crowd_warmup_bars=crowd_warmup_bars,
                fuel_lookback_bars=fuel_lb_bars, atr_period=cfg.ATR_PERIOD)

        # 1. ALWAYS manage exits/stops on an existing position (even if stale)
        if abs(cur_sz) > 1e-9 and coin in entries:
            ent = entries[coin]
            held_days = (now_ms - ent.get("entry_ms", now_ms)) / 86400_000
            exit_reason = None
            if risk.stop_hit(direction, ent.get("stop", 0.0), mid):
                exit_reason = "stop"
            elif sig is not None:
                exit_reason = signals.should_exit(
                    direction, sig["trend_up"], sig["trend_dn"], sig["fuel"],
                    held_days, cfg.MAX_HOLD_DAYS)
            elif held_days >= cfg.MAX_HOLD_DAYS:
                # Data outage (sig is None): max-hold is purely time-based —
                # it needs only entry_ms, never fresh venue data — so it must
                # still fire, or a stale coin could be held indefinitely.
                exit_reason = "maxhold"
            if exit_reason is not None:
                logger.info(f"{coin}: exiting ({exit_reason})")
                # reduce-only close via market_close (idempotent -> retried
                # by ResilientExchange). Dry-run gated: --dry-run must not
                # write to the exchange (operator contract, matching
                # _flatten_everything / _place_order).
                closed_ok = True
                if self.live_trading:
                    try:
                        self.exchange.market_close(coin, abs(cur_sz))
                    except Exception as e:
                        closed_ok = False
                        # Safety-critical failure must be LOUD, and the entry
                        # record must SURVIVE: popping it here would end all
                        # future stop/max-hold evaluation of a position that
                        # is still open on the exchange. Keeping it means the
                        # exit condition re-fires and retries next cycle.
                        logger.error(f"SAFETY-CRITICAL: exit close failed for {coin}: {e} "
                                     "— keeping entry bookkeeping, retrying next cycle")
                        send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                                   f"CTA exit close FAILED for {coin} ({exit_reason}) — "
                                   "position still open, entry retained, retrying next cycle.")
                else:
                    logger.info(f"[DRY RUN] would close {coin} size={abs(cur_sz)} ({exit_reason})")
                if closed_ok:
                    # pop ONLY on a confirmed close (dry-run counts as a
                    # simulated success) and persist immediately: a crash
                    # after the close but before the loop-end save must not
                    # leave a phantom entry for a closed position.
                    entries.pop(coin, None)
                    save_state(cfg.STATE_FILE, self.state)
                return  # exited (or exit pending retry); do not also open this cycle

        # 2. NEW entries only when data is fresh and no existing position
        if abs(cur_sz) > 1e-9:
            return
        if frame is None or sig is None or feed.is_coin_stale(coin, cfg.DATA_STALENESS_HOURS):
            logger.info(f"{coin}: stale/no data -> skipping new entry this cycle")
            return
        decision = signals.decide(
            sig["trend_up"], sig["trend_dn"], sig["crowd_long"], sig["crowd_short"],
            sig["fuel"], enable_long=cfg.ENABLE_LONG, enable_short=cfg.ENABLE_SHORT)
        if decision == "flat" or mid <= 0:
            return
        d = -1 if decision == "short" else 1
        # atr>0 entry gate: NaN (warmup) or non-positive ATR -> no valid
        # stop can be set, so do not open (spec relay item A).
        if not risk.atr_gate_ok(sig["atr"]):
            logger.info(f"{coin}: no valid ATR, skipping entry")
            return
        atr = sig["atr"]
        size = risk.position_size(cfg.NOTIONAL_PER_TRADE, mid)
        if size <= 0:
            return
        if not self._place_order(coin, is_buy=(d == 1), size=size, reduce_only=False):
            logger.warning(f"{coin}: open not confirmed placed — NOT recording entry")
            return
        entries[coin] = {"dir": d, "entry_px": mid,
                         "stop": risk.stop_level(d, mid, atr, cfg.STOP_ATR_MULT),
                         "entry_ms": now_ms}
        # Persist IMMEDIATELY (before the next coin is processed): a crash
        # after the open landed but before the loop-end save would leave a
        # REAL position with no stop/max-hold anchor. The orphan path would
        # flatten it next rebalance, but the crash window itself must stay
        # as small as one order.
        save_state(cfg.STATE_FILE, self.state)

    # ---- loop --------------------------------------------------------
    def run_once(self) -> None:
        self.bootstrap_if_needed()
        if self.check_drawdown():
            return
        # Healthy cycle: re-arm the halt bookkeeping HERE (like carry's
        # run_once), not only inside maybe_rebalance. The breaker polls every
        # SYNC_INTERVAL_SECONDS but a rebalance only runs every
        # REBALANCE_INTERVAL_HOURS; if re-arming lived solely in
        # maybe_rebalance, an operator who clears `halted` between rebalances
        # would leave _alerted_this_halt/_flatten_complete stale, so a SECOND
        # halt episode would be SILENT — no alert, no flatten. Re-arm on every
        # healthy cycle so the next halt always alerts and flattens fresh.
        if self.state.get("_alerted_this_halt") or self.state.get("_flatten_complete"):
            self.state["_alerted_this_halt"] = False
            self.state["_flatten_complete"] = False
            save_state(cfg.STATE_FILE, self.state)
        self.maybe_rebalance()

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("cta cycle failed")
            time.sleep(cfg.SYNC_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    engine = CtaEngine(live_trading=False if args.dry_run else None)
    if args.status:
        equity = risk.account_equity(engine.info, cfg.WALLET_ADDRESS)
        print(f"equity ${equity:,.2f} | halted={engine.state.get('halted')} "
              f"peak={engine.state.get('peak_equity')} "
              f"open_entries={list(engine.state.get('entries', {}).keys())} "
              f"long={cfg.ENABLE_LONG} short={cfg.ENABLE_SHORT}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
