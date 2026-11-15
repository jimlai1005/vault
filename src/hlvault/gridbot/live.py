"""Live grid engine — independent of hl-copytrader, trades on its own agent
wallet/capital. Polling-based (not sub-second HFT like the target wallet;
see reports/target-strategy-analysis.md for why that's not replicable via a
periodic Python poller) but keeps the same core mechanic: dense percentage
grid, paired reduce-only take-profits, trailing window — plus risk controls
the target doesn't appear to have (volatility-adaptive spacing, hard stop,
portfolio drawdown circuit breaker). See reports/gridbot-design.md.
"""
from __future__ import annotations

import argparse
import logging
import math
import time

import pandas as pd
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info
from hlvault.notify.telegram import send_alert

from . import config as cfg
from .allocator import allocate_capital
from .exchange_utils import (
    MAX_LEVERAGE_FALLBACK, equity_breakdown, get_full_account_equity, get_max_leverage, get_mid_price,
    get_sz_decimals, read_positions, round_price, round_size,
)
from .resilience import ResilientExchange
from .state import default_state, load_state, save_state
from .strategy import GridConfig, desired_armed_levels, level_index, level_price
from .volatility import adaptive_step_pct, atr_pct

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gridbot")

FLATTEN_MAX_ROUNDS = 3   # cancel -> close -> read back; one round per attempt inside a single call
FLATTEN_SETTLE_SECONDS = 1   # pause between sending a round's cancels/closes and reading back (R-D: query lag
                             # must not read as a false "not flat"); live only, tests patch it to 0
GAP_ALERT_CYCLES = 2     # a position gap must persist this many consecutive cycles before alert + buy halt
RECONCILE_FAIL_ALERT_CYCLES = 5   # R-H: this many consecutive unreadable reconciles -> one Telegram alert
_SYNC_NOT_COUNTED = object()   # _sync_coin outcome: stop-exit / cooldown cycle — not a failure, not a recovery
CAP_REL_EPS = 1e-9       # float slack on the notional-cap inequality (6 * (budget / 6) must not trip it)


def _fetch_1h_candles(info_url: str, coin: str, days: int) -> pd.DataFrame:
    import json
    import urllib.request

    end = int(time.time() * 1000)
    start = end - days * 86400 * 1000
    body = {"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": start, "endTime": end}}
    req = urllib.request.Request(f"{info_url}/info", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        candles = json.loads(r.read())
    df = pd.DataFrame(candles)
    if df.empty:
        return df
    for col in ("o", "h", "l", "c"):
        df[col] = pd.to_numeric(df[col])
    return df


class GridBotEngine:
    def __init__(self, live_trading: bool | None = None):
        if not cfg.WALLET_PRIVATE_KEY or not cfg.WALLET_ADDRESS:
            raise RuntimeError("WALLET_PRIVATE_KEY / WALLET_ADDRESS not set in .env.gridbot")
        self.live_trading = cfg.LIVE_TRADING if live_trading is None else live_trading
        account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
        self.info = Info(cfg.HL_API_URL, skip_ws=True)
        raw_exchange = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
        self.exchange = ResilientExchange(raw_exchange)
        self.state = load_state(cfg.STATE_FILE)
        self._sz_dec: dict = {}
        self._leverage_set: set = set()

    def sz_decimals(self, coin: str) -> int:
        if coin not in self._sz_dec:
            self._sz_dec[coin] = get_sz_decimals(self.info, coin)
        return self._sz_dec[coin]

    # ---- setup -----------------------------------------------------
    def bootstrap_if_needed(self) -> None:
        if self.state["coins"]:
            return
        logger.info("First run — sizing the grid from recent volatility per coin")
        vols = {}
        for coin in cfg.COIN_UNIVERSE:
            candles = _fetch_1h_candles(cfg.HL_API_URL, coin, days=14)
            vols[coin] = atr_pct(candles, lookback=len(candles)) if not candles.empty else 0.01
        budgets = allocate_capital(vols, cfg.ALLOCATED_CAPITAL, cfg.MAX_COIN_ALLOCATION_PCT)
        for coin in cfg.COIN_UNIVERSE:
            step_pct = adaptive_step_pct(vols[coin], cfg.VOL_K, cfg.MIN_STEP_PCT, cfg.MAX_STEP_PCT)
            mid = get_mid_price(self.info, coin)
            budget = budgets[coin]
            self.state["coins"][coin] = {
                "anchor": mid,
                "step_pct": step_pct,
                "notional_per_level": budget / cfg.NUM_LEVELS,
                "max_position_notional": budget,
                "armed": {}, "open_lots": {}, "stopped_until_ms": None,
            }
            logger.info(f"{coin}: anchor={mid:.6g} step={step_pct*100:.3f}% "
                       f"budget=${budget:.2f} notional/level=${budget/cfg.NUM_LEVELS:.2f}")
        self.state["peak_equity"] = cfg.ALLOCATED_CAPITAL
        save_state(cfg.STATE_FILE, self.state)

    def grid_cfg(self, coin: str) -> GridConfig:
        c = self.state["coins"][coin]
        return GridConfig(
            coin=coin, step_pct=c["step_pct"], num_levels=cfg.NUM_LEVELS,
            notional_per_level=c["notional_per_level"], max_position_notional=c["max_position_notional"],
            stop_buffer_pct=cfg.STOP_BUFFER_PCT, cooldown_candles=0,
        )

    # ---- alerting ---------------------------------------------------
    def _alert(self, msg: str) -> None:
        """Telegram, never raises (notify.telegram contract); prefix identifies the engine."""
        send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID, f"[hl-gridbot] {msg}")

    def _halted_reminder(self, pending_detail: str = "") -> None:
        """While halted, re-send the reminder every HALT_ALERT_INTERVAL_MINUTES so a
        halt cannot go unnoticed (2026-09-22: 13 days). Includes a fresh equity
        read when possible so the owner can judge whether a restart will re-arm."""
        now_ms = int(time.time() * 1000)
        last = int(self.state.get("last_halt_alert_ms", 0))
        if now_ms - last < cfg.HALT_ALERT_INTERVAL_MINUTES * 60_000:
            return
        peak = self.state.get("peak_equity", 0.0)
        try:
            current = get_full_account_equity(self.info, cfg.WALLET_ADDRESS)
            dd = (peak - current) / peak if peak > 0 else 0.0
            reading = f"now ${current:,.2f}, drawdown {dd:.1%} vs peak ${peak:,.2f}"
        except Exception as e:
            reading = f"equity unreadable ({e!r}), peak ${peak:,.2f}"
        pending = (f" FLATTEN STILL PENDING (retrying every cycle) — remaining: {pending_detail}."
                   if pending_detail else "")
        # R-M: a stop-loss exit that never verified flat is not retried while halted (D3: no exchange
        # action without flatten_pending). The owner must hear which coins may still hold a position.
        stops = [k for k, cc in self.state["coins"].items() if cc.get("stop_pending", False)]
        if stops:
            # with flatten_pending the whole-universe flatten above IS retrying these coins too;
            # without it nothing touches the exchange while halted (D3) — say which one is true
            how = ("covered by the flatten retry above" if pending_detail
                   else "it is NOT retried while halted")
            pending += (f" STOP-LOSS EXIT NEVER VERIFIED for {', '.join(stops)} — {how}; "
                        "check those perp positions and orders on the exchange.")
        self._alert(f"HALTED — not trading. {reading}.{pending} "
                    f"To re-arm: sudo systemctl restart hl-gridbot "
                    f"(resumes only if drawdown < {cfg.MAX_DRAWDOWN_PCT:.0%}; otherwise edit the state file).")
        self.state["last_halt_alert_ms"] = now_ms
        save_state(cfg.STATE_FILE, self.state)

    # ---- portfolio circuit breaker ----------------------------------
    def check_drawdown(self) -> bool:
        """Returns True if halted (caller must stop trading this cycle)."""
        if self.state.get("halted"):
            logger.error("HALTED — restart the service to re-arm (resumes only if drawdown "
                         "has recovered); or clear 'halted' in the state file after review")
            if self.state.get("flatten_pending", False):
                # the trip-time flatten never verified flat: keep retrying until the
                # exchange itself reads back zero. Without the flag we touch nothing
                # (the owner may have opened positions by hand while the bot is halted).
                flattened = self._flatten_everything()
                self.state["flatten_pending"] = not flattened
                save_state(cfg.STATE_FILE, self.state)
                if flattened:
                    self._alert(f"FLATTEN COMPLETED (retry while halted): verified {', '.join(cfg.COIN_UNIVERSE)} "
                                "perp positions are 0 and no open orders remain on the exchange.")
                else:
                    self._halted_reminder(pending_detail=self._flatten_detail)
            else:
                self._halted_reminder()
            return True
        try:
            current = get_full_account_equity(self.info, cfg.WALLET_ADDRESS)
        except Exception as e:
            return self._equity_read_failed(f"EQUITY READ FAILED ({e!r})")
        if current <= 0.0:
            # 2026-07-21 incident: flat book + cash parked in perp free margin
            # reads as $0 through this basis (spot USDC + position economics),
            # indistinguishable from a wiped account. A reading this implausible
            # is a failed read, not a drawdown — any real gradual loss trips
            # MAX_DRAWDOWN_PCT long before equity crosses zero.
            return self._equity_read_failed(
                f"EQUITY READ IMPLAUSIBLE (${current:,.2f}, peak ${self.state.get('peak_equity', 0.0):,.2f})"
            )
        self.state["bad_equity_reads"] = 0
        peak = max(self.state.get("peak_equity", 0.0), current)
        drawdown = (peak - current) / peak if peak > 0 else 0.0
        self.state["peak_equity"] = peak
        if drawdown >= cfg.MAX_DRAWDOWN_PCT:
            breach = int(self.state.get("drawdown_breach_cycles", 0)) + 1
            self.state["drawdown_breach_cycles"] = breach
            logger.error(f"DRAWDOWN CIRCUIT BREAKER: {drawdown:.1%} "
                         f"(peak ${peak:,.2f} -> now ${current:,.2f}) — "
                         f"breach cycle {breach}/{cfg.DRAWDOWN_CONFIRM_CYCLES}, "
                         "not trading this cycle")
            if breach >= cfg.DRAWDOWN_CONFIRM_CYCLES:
                self.state["halted"] = True
                self.state["last_halt_alert_ms"] = int(time.time() * 1000)
                # persist halt AND pending flatten BEFORE flattening (a crash mid-flatten
                # must lose neither; the pending flag makes the next cycle finish the job)
                self.state["flatten_pending"] = True
                save_state(cfg.STATE_FILE, self.state)
                flattened = self._flatten_everything()
                self.state["flatten_pending"] = not flattened
                # alert only AFTER flatten: a slow Telegram (up to ~33s) must never delay the close
                head = (f"DRAWDOWN CIRCUIT BREAKER TRIPPED: {drawdown:.1%} "
                        f"(peak ${peak:,.2f} -> now ${current:,.2f})")
                if flattened:
                    self._alert(f"{head} — halted. Flatten verified: {', '.join(cfg.COIN_UNIVERSE)} perp positions "
                                "read back as 0 and no open orders remain on the exchange.")
                else:
                    self._alert(f"{head} — halted, flatten NOT verified.")
                    self._alert(f"FLATTEN INCOMPLETE — remaining on exchange: {self._flatten_detail or 'unknown'}. "
                                "Retrying every cycle while halted; manual check required.")
            save_state(cfg.STATE_FILE, self.state)
            return True
        self.state["drawdown_breach_cycles"] = 0
        return False

    def rearm_if_recovered(self) -> None:
        """A service (re)start is the operator's re-arm request — the one
        self-service lever that needs no state-file surgery (2026-07-21: the
        owner had no way to clear a halt themselves). Re-run the drawdown
        check against the persisted peak: resume only if the breach has
        actually cleared; a failed or implausible read, or a drawdown still
        past the threshold, keeps the halt. peak_equity is never reset here,
        so an ongoing drawdown is still measured against the true high.
        Called from run_forever() only — --status/--once stay side-effect
        free."""
        if not self.state.get("halted"):
            return
        if self.state.get("flatten_pending", False):
            # the trip-time flatten never verified flat: a restart must not re-arm on top of
            # unprotected exchange positions. Flat first; only a verified flat may go on.
            flattened = self._flatten_everything()
            self.state["flatten_pending"] = not flattened
            self.state["last_halt_alert_ms"] = int(time.time() * 1000)
            save_state(cfg.STATE_FILE, self.state)
            if not flattened:
                logger.error(f"HALTED with flatten still pending and NOT verified on restart "
                             f"({self._flatten_detail or 'unknown'}) — staying halted")
                self._alert(f"Restart requested but flatten is still NOT verified — remaining on exchange: "
                            f"{self._flatten_detail or 'unknown'}. Still halted; manual check required.")
                return
        try:
            current = get_full_account_equity(self.info, cfg.WALLET_ADDRESS)
        except Exception as e:
            logger.error(f"HALTED and equity re-check failed ({e!r}) — staying halted")
            self._alert(f"Restart requested but equity re-check failed ({e!r}) — still halted.")
            self.state["last_halt_alert_ms"] = int(time.time() * 1000)
            save_state(cfg.STATE_FILE, self.state)
            return
        peak = self.state.get("peak_equity", 0.0)
        if current <= 0.0 or peak <= 0.0:
            logger.error(f"HALTED and equity re-check implausible (${current:,.2f}) — staying halted")
            self._alert(f"Restart requested but equity re-check implausible (${current:,.2f}) — still halted.")
            self.state["last_halt_alert_ms"] = int(time.time() * 1000)
            save_state(cfg.STATE_FILE, self.state)
            return
        drawdown = (peak - current) / peak
        if drawdown >= cfg.MAX_DRAWDOWN_PCT:
            logger.error(f"HALTED and still breaching: drawdown {drawdown:.1%} >= "
                         f"{cfg.MAX_DRAWDOWN_PCT:.0%} (peak ${peak:,.2f} -> ${current:,.2f}) "
                         "— staying halted")
            self._alert(f"Restart requested but still breaching: drawdown {drawdown:.1%} >= {cfg.MAX_DRAWDOWN_PCT:.0%} "
                        f"(peak ${peak:,.2f} -> ${current:,.2f}) — still halted. "
                        "Recover equity or reset peak in the state file.")
            self.state["last_halt_alert_ms"] = int(time.time() * 1000)
            save_state(cfg.STATE_FILE, self.state)
            return
        logger.warning(f"RE-ARMED on restart: drawdown {drawdown:.1%} < {cfg.MAX_DRAWDOWN_PCT:.0%} "
                       f"(peak ${peak:,.2f} -> ${current:,.2f}) — resuming trading")
        self._alert(f"RE-ARMED on restart: drawdown {drawdown:.1%} < {cfg.MAX_DRAWDOWN_PCT:.0%} "
                    f"(peak ${peak:,.2f} -> ${current:,.2f}) — resuming trading.")
        self.state["halted"] = False
        # flatten_pending needs no reset here: a pending flatten was already run above and
        # only a verified flat gets this far (its success path cleared the flag)
        self.state["bad_equity_reads"] = 0
        self.state["drawdown_breach_cycles"] = 0
        save_state(cfg.STATE_FILE, self.state)

    def _equity_read_failed(self, reason: str) -> bool:
        """A non-positive or failed equity read is a read failure, not a
        drawdown — never flatten on it (2026-07-21: flat book + cash parked
        in perp free margin reads $0 through this basis and is
        indistinguishable from a wiped account). Skip the cycle loudly; after
        MAX_BAD_EQUITY_READS consecutive failures stop idling invisibly and
        halt (still no flatten) so the operator's manual re-arm gate takes
        over instead of a silent forever-skip. The counter lives in the state
        file, not in memory — a crash/restart loop (systemd Restart=on-failure)
        must not keep resetting the countdown."""
        bad_reads = int(self.state.get("bad_equity_reads", 0)) + 1
        self.state["bad_equity_reads"] = bad_reads
        logger.error(f"{reason} — treated as failed read "
                     f"({bad_reads}/{cfg.MAX_BAD_EQUITY_READS} consecutive): "
                     "skipping cycle, no flatten")
        if bad_reads >= cfg.MAX_BAD_EQUITY_READS:
            logger.error("EQUITY UNREADABLE for %d consecutive cycles — halting WITHOUT flatten; "
                         "manual re-arm required (clear 'halted' in state file after review)",
                         bad_reads)
            self.state["halted"] = True
            self._alert(f"EQUITY UNREADABLE for {bad_reads} consecutive cycles — halted WITHOUT flatten. "
                        f"Last error: {reason}. Check the API/wallet, then: sudo systemctl restart hl-gridbot")
            self.state["last_halt_alert_ms"] = int(time.time() * 1000)
        save_state(cfg.STATE_FILE, self.state)
        return True

    _flatten_detail: str = ""   # human-readable leftover after the last _flatten_everything (for alerts)

    def _universe_orders(self, universe: list[str]) -> list[tuple[str, object]]:
        """(coin, oid) of every resting order in `universe`, straight from the exchange.
        Raises on an unreadable/malformed payload — never an empty list as a stand-in."""
        return [(o["coin"], o["oid"]) for o in self.info.open_orders(cfg.WALLET_ADDRESS)
                if o["coin"] in universe]

    def _flatten_round(self, universe: list[str]) -> None:
        """One cancel+close pass driven by the EXCHANGE's orders and szi (never state).
        Outcomes are not trusted here — _verify_flat reads the result back. Never
        raises: an unreadable side is logged loudly and the other side still runs."""
        try:
            for coin, oid in self._universe_orders(universe):
                self._cancel(coin, oid)
        except Exception as e:
            logger.error(f"SAFETY-CRITICAL flatten: could not read/cancel open orders ({e!r})")
        try:
            positions = read_positions(self.info, cfg.WALLET_ADDRESS, universe)
        except Exception as e:
            logger.error(f"SAFETY-CRITICAL flatten: could not read positions ({e!r}) — nothing closed this round")
            return
        for coin, szi in positions.items():
            if szi != 0.0:
                self._market_flatten(coin, abs(szi))   # reduce-only; size = exchange szi

    def _verify_flat(self, universe: list[str]) -> tuple[bool, str]:
        """Fresh read of orders and positions. (True, "") only when both were READ
        and universe has no resting order and every szi == 0."""
        try:
            # ORDER MATTERS: orders first, positions second. An order that is no longer resting at the
            # moment the order list is read can never fill afterwards, so the szi read after it already
            # contains any fill it had. Reading szi first would leave a window in which a buy fills
            # between the two reads: szi looks 0, the order looks gone, the position is not.
            orders = self._universe_orders(universe)
            positions = read_positions(self.info, cfg.WALLET_ADDRESS, universe)
        except Exception as e:
            return False, f"exchange state unreadable ({e!r})"
        parts = []
        for coin in universe:
            n_orders = sum(1 for c, _ in orders if c == coin)
            if positions[coin] != 0.0 or n_orders:
                parts.append(f"{coin} szi={positions[coin]:g} open_orders={n_orders}")
        return (not parts), "; ".join(parts)

    def _flatten_everything(self) -> bool:
        """Flat means: on the EXCHANGE, every COIN_UNIVERSE perp szi == 0 and no
        resting order, confirmed by a read-back (2026-11-05: flatten followed the
        bot's own books, never read szi, and left $1.5k of untracked longs to bleed).
        Returns True only then. Otherwise False with state's armed/open_lots kept,
        state["flatten_pending"] = True (check_drawdown retries every cycle while
        halted) and self._flatten_detail listing what remains. "Could not read" is
        a failure, never "nothing there". Only cancels and reduce-only closes are sent.
        Dry-run sends and reads nothing: it logs, clears the tracked books (as the
        old dry-run did) and reports True — there is nothing on the exchange to verify."""
        self._flatten_detail = ""
        universe = list(cfg.COIN_UNIVERSE)
        if not self.live_trading:
            logger.info(f"[DRY RUN] flatten: would cancel all {universe} orders and market-close every "
                        "exchange position; nothing sent")
            self._clear_tracked_books()
            self.state["flatten_pending"] = False
            return True
        detail = "no flatten round ran"
        for rnd in range(1, FLATTEN_MAX_ROUNDS + 1):
            self._flatten_round(universe)
            time.sleep(FLATTEN_SETTLE_SECONDS)   # let the venue's read side catch up before verifying
            ok, detail = self._verify_flat(universe)
            if ok:
                logger.warning(f"FLATTEN VERIFIED on round {rnd}: {universe} szi all 0, no open orders")
                self._clear_tracked_books()
                self.state["flatten_pending"] = False
                return True
            logger.error(f"flatten round {rnd}/{FLATTEN_MAX_ROUNDS} not flat: {detail}")
        self._flatten_detail = detail
        self.state["flatten_pending"] = True
        logger.error(f"SAFETY-CRITICAL: flatten NOT verified after {FLATTEN_MAX_ROUNDS} rounds — "
                     f"remaining: {detail}. State books kept; retrying every cycle.")
        return False

    def _clear_tracked_books(self) -> None:
        for c in self.state["coins"].values():
            c["armed"] = {}
            c["open_lots"] = {}
            # a verified-flat exchange settles any stop-loss exit in flight (R-G) and any gap episode (R-I)
            c["stop_pending"] = False
            c["stop_alerted"] = False
            c["gap_cycles"] = 0
            c["gap_alerted"] = False

    # ---- per-coin sync ----------------------------------------------
    def _target_leverage(self, coin: str) -> int:
        """Notional order size is computed independently from leverage
        (notional_per_level / price) — raising leverage only reduces margin
        reserved per order, it does not raise position size/risk, matching
        hl-copytrader's ORDER_LEVERAGE=max rationale."""
        if cfg.LEVERAGE != "max":
            try:
                return max(1, int(cfg.LEVERAGE))
            except ValueError:
                return MAX_LEVERAGE_FALLBACK
        max_lev = get_max_leverage(self.info, coin)
        return max_lev if max_lev > 0 else MAX_LEVERAGE_FALLBACK

    def _ensure_leverage(self, coin: str) -> None:
        if coin in self._leverage_set:
            return
        if not self.live_trading:
            self._leverage_set.add(coin)
            return
        leverage = self._target_leverage(coin)
        try:
            result = self.exchange.update_leverage(leverage, coin, is_cross=True)
            logger.info(f"{coin}: leverage set to {leverage}x cross: {result}")
        except Exception as e:
            logger.error(f"{coin}: failed to set leverage: {e}")
        self._leverage_set.add(coin)

    def sync_coin(self, coin: str) -> None:
        """One coin's cycle. Wraps _sync_coin so the consecutive-failure counter (R-K) covers the WHOLE
        coin cycle, once per cycle, and is persisted even when the cycle raised (the exception is
        re-raised: run_once isolates it per coin). stop_pending / cooldown cycles neither count nor reset."""
        c = self.state["coins"][coin]
        try:
            outcome = self._sync_coin(coin)
        except Exception as e:
            if not c.get("stop_pending", False):   # a stop-exit cycle has its own alert path
                self._track_sync_health(coin, c, f"sync_coin raised {e!r}")
            raise
        if outcome is not _SYNC_NOT_COUNTED:
            self._track_sync_health(coin, c, outcome)

    def _track_sync_health(self, coin: str, c: dict, failure: str | None) -> None:
        """R-H / R-K: the single place that records a coin cycle's health. failure None = the cycle ran
        to the end with a readable reconcile -> counter back to 0. A reason string = one failed cycle:
        count it, persist BEFORE the (slow) alert, and alert once when the streak reaches
        RECONCILE_FAIL_ALERT_CYCLES (== fires once per episode: recovery zeroes the counter).
        Nothing is flattened or halted by this: it only makes a silent stall loud."""
        if failure is None:
            had_failures = int(c.get("reconcile_fail_cycles", 0)) > 0
            c["reconcile_fail_cycles"] = 0
            if had_failures:
                save_state(cfg.STATE_FILE, self.state)
            return
        fails = int(c.get("reconcile_fail_cycles", 0)) + 1
        c["reconcile_fail_cycles"] = fails
        logger.error(f"{coin}: SAFETY coin cycle failed ({failure}) — no new buys this cycle "
                     f"(consecutive {fails}/{RECONCILE_FAIL_ALERT_CYCLES})")
        save_state(cfg.STATE_FILE, self.state)
        if fails == RECONCILE_FAIL_ALERT_CYCLES and self.live_trading:
            self._alert(f"COIN CYCLE FAILING {coin} for {fails} consecutive cycles — no new {coin} buys "
                        f"until it runs clean again (nothing is flattened or halted by this). Last error: {failure}")

    def _sync_coin(self, coin: str):
        """Returns None for a cycle that ran to the end with a readable reconcile, a reason string for a
        degraded one, or _SYNC_NOT_COUNTED for a cycle that did not try the normal flow at all."""
        c = self.state["coins"][coin]
        now_ms = int(time.time() * 1000)
        if c.get("stop_pending", False):
            # R-G: a stop-loss exit that never verified flat keeps running whatever the price does
            # (a bounce above the stop must not let the normal flow read the cancelled TP as "filled"
            # and delete the lot). Nothing else runs this cycle: no reconcile, no orders. Sits BEFORE
            # the cooldown gate and the leverage call so neither can skip it.
            self._run_stop_exit(coin, c, now_ms)
            return _SYNC_NOT_COUNTED
        self._ensure_leverage(coin)
        if c["stopped_until_ms"] and now_ms < c["stopped_until_ms"]:
            return _SYNC_NOT_COUNTED
        c["stopped_until_ms"] = None

        mid = get_mid_price(self.info, coin)
        if mid <= 0:
            logger.warning(f"{coin}: no mid price, skipping this cycle")
            return f"no mid price (mid={mid})"
        gc = self.grid_cfg(coin)

        # stop-loss: deepest open lot's entry, per strategy.step's rationale
        if c["open_lots"]:
            bottom_level = min(int(k) for k in c["open_lots"])
            stop_px = level_price(c["anchor"], c["step_pct"], bottom_level) * (1 - cfg.STOP_BUFFER_PCT)
            if mid <= stop_px:
                logger.error(f"{coin}: STOP-LOSS triggered at {mid:.6g} <= {stop_px:.6g}")
                # persist the pending flag BEFORE the exit: a crash or a half-done exit must leave
                # the next cycle knowing it still owes a verified flat
                c["stop_pending"] = True
                c["stop_alerted"] = False
                save_state(cfg.STATE_FILE, self.state)
                self._run_stop_exit(coin, c, now_ms)
                return _SYNC_NOT_COUNTED

        # reconcile against actual resting orders (exchange = source of truth).
        # BUG (found after ~15h live): a TP placed by _on_buy_filled() below was
        # then checked in the SAME cycle against this same pre-fetch `resting`
        # snapshot — which obviously can't contain an order created after the
        # snapshot was taken — so every fresh TP was immediately misread as
        # "already filled" and dropped from open_lots. Net effect: open_lots
        # was permanently empty, silently disabling the stop-loss (guarded by
        # `if c["open_lots"]:`) and the position-notional cap (summed from
        # open_lots) for the whole run, while real exchange positions kept
        # growing. Fix: only check TP-fill status for lots that existed
        # BEFORE this cycle touched anything; a lot created this cycle gets
        # checked against a fresh snapshot next cycle instead.
        resting = {o["oid"]: o for o in self.info.open_orders(cfg.WALLET_ADDRESS) if o["coin"] == coin}
        pre_existing_lots = list(c["open_lots"].items())
        for lvl, oid in list(c["armed"].items()):
            if oid not in resting:
                self._resolve_buy(coin, int(lvl), oid)
        for lvl, lot in pre_existing_lots:
            if lvl in c["open_lots"] and lot["tp_oid"] not in resting:
                self._on_tp_filled(coin, int(lvl))

        # position truth (T4): the exchange's szi, not the books, is the exposure; the books
        # are checked against it every cycle. Unreadable -> szi is None -> no new buys.
        szi, buys_blocked = self._reconcile(coin, c, resting)
        lot_keys_at_read = set(c["open_lots"])

        center_k = level_index(c["anchor"], c["step_pct"], mid)
        desired = set(desired_armed_levels(center_k, gc))

        # A level may only leave `armed` once its buy is accounted for: the order's
        # final state is read back after every cancel, confirmed or not (never pop
        # first — a cancel that races a fill answers with an error and the fill
        # would be forgotten, 2026-11-05; a confirmed cancel may still follow a
        # partial fill whose filled part needs a lot + TP).
        for lvl in list(c["armed"]):
            if int(lvl) not in desired:
                oid = c["armed"][lvl]
                self._cancel(coin, oid)                    # result is advisory: the order's own
                self._resolve_buy(coin, int(lvl), oid)     # final state decides (a cancelled buy may be part-filled)

        npl = c["notional_per_level"]
        cap_limit = c["max_position_notional"] * (1 + CAP_REL_EPS)
        if szi is not None:
            # exposure = what the exchange holds, plus fills that landed on lots created
            # AFTER the szi read this cycle (conservative: may double count a part-fill).
            exposure = abs(szi) * mid + sum(
                lot["size"] * mid for k, lot in c["open_lots"].items() if k not in lot_keys_at_read)

            # R-F cap: exposure + every resting buy must fit under the cap, so that even if all
            # armed buys fill the coin stays <= max_position_notional. Shed the deepest first.
            # A buy whose cancel the exchange just confirmed no longer rests, even while its order
            # status still reads "open" for a moment (the armed record is then kept for the next
            # cycle to settle). Counting it as resting made this loop shed EVERY buy instead of just
            # the excess (2026-11-15 live: 6 cancelled where 3 were enough).
            #
            # But such a buy may have part-filled between the szi read and the cancel, and that
            # fill is in neither `exposure` nor a lot yet. At most ONE shed buy can be in that
            # state (a sell deep enough to touch it fills every shallower buy completely, and a
            # fully filled buy's cancel is not confirmed, so it is never shed), so one level of
            # notional is held back while any shed record is unsettled.
            shed = 0
            for lvl in sorted(c["armed"], key=int):
                n_buys = len(c["armed"]) - shed + (1 if shed else 0)
                if exposure + n_buys * npl <= cap_limit:
                    break
                oid = c["armed"][lvl]
                logger.warning(f"{coin}: exposure ${exposure:,.2f} + {n_buys} resting buys x ${npl:,.2f} "
                               f"> cap ${c['max_position_notional']:,.2f} — cancelling deepest buy level {lvl}")
                outcome = self._cancel(coin, oid)
                self._resolve_buy(coin, int(lvl), oid)
                if lvl in c["open_lots"] and lvl not in lot_keys_at_read:
                    exposure += c["open_lots"][lvl]["size"] * mid   # it filled while we were cancelling
                if lvl in c["armed"] and outcome == "cancelled":
                    shed += 1                                       # gone from the book, record pending

            if buys_blocked:
                logger.warning(f"{coin}: position gap persists — not placing new buys this cycle")
            else:
                # nearest-to-price first; each placed buy counts against the cap for the next one
                for lvl in sorted(desired, reverse=True):
                    skey = str(lvl)
                    if skey in c["armed"] or skey in c["open_lots"]:
                        continue
                    if exposure + (len(c["armed"]) + 1) * npl > cap_limit:
                        continue
                    px = round_price(level_price(c["anchor"], c["step_pct"], lvl), self.sz_decimals(coin))
                    size = round_size(npl / px, self.sz_decimals(coin))
                    if size * px < cfg.MIN_ORDER_NOTIONAL:
                        continue
                    oid = self._place_buy(coin, px, size)
                    if oid:
                        c["armed"][skey] = oid
        else:
            logger.error(f"{coin}: position unreadable this cycle — no new buys (existing resolution still ran)")

        save_state(cfg.STATE_FILE, self.state)
        return None if szi is not None else f"reconcile unreadable: {self._reconcile_error}"

    # ---- position reconciliation (T4) ------------------------------------
    @staticmethod
    def _partial_filled(order: dict) -> float:
        """Filled part of a resting order: origSz - sz (sz is the remaining size). Raises on
        a payload that lacks either field — an unparseable order must not read as 'untouched'."""
        filled = float(order["origSz"]) - float(order["sz"])
        if not math.isfinite(filled):
            raise ValueError(f"non-finite fill on order {order!r}")
        return max(filled, 0.0)

    def _expected_position(self, coin: str, resting: dict) -> float:
        """What the books say the exchange should hold: sum(open_lots) minus the part of each
        resting TP already filled, plus the part of each resting armed buy already filled."""
        c = self.state["coins"][coin]
        expected = sum(lot["size"] for lot in c["open_lots"].values())
        for lot in c["open_lots"].values():
            o = resting.get(lot["tp_oid"])
            if o is not None:
                expected -= self._partial_filled(o)
        for oid in c["armed"].values():
            o = resting.get(oid)
            if o is not None:
                expected += self._partial_filled(o)
        return expected

    def position_report(self, coin: str, resting: dict) -> tuple[float, float, float]:
        """(szi, expected, gap = szi - expected). Pure read, raises if anything is unreadable."""
        szi = read_positions(self.info, cfg.WALLET_ADDRESS, [coin])[coin]
        expected = self._expected_position(coin, resting)
        return szi, expected, szi - expected

    _reconcile_error: str = ""   # repr of the last unreadable-reconcile error (read by _sync_coin for the health record)

    def _reconcile(self, coin: str, c: dict, resting: dict) -> tuple[float | None, bool]:
        """Compare exchange szi with the books. Returns (szi, buys_blocked); szi None means
        the read failed (buys blocked, gap counters untouched — a failed read is not a gap).
        A gap (>= half a size unit) seen GAP_ALERT_CYCLES cycles in a row alerts once and
        blocks new buys until it clears. Nothing is ever traded to close the gap (owner D2):
        no TP is placed for it, no difference is sold."""
        try:
            tol = 0.5 * 10 ** -self.sz_decimals(coin)
            szi, expected, gap = self.position_report(coin, resting)
        except Exception as e:
            # counting + alerting is _track_sync_health's job (R-K): one record per coin cycle
            self._reconcile_error = repr(e)
            logger.error(f"{coin}: SAFETY position/books reconcile unreadable ({e!r}) — no new buys this cycle")
            return None, True
        if abs(gap) < tol:
            c["gap_cycles"] = 0
            c["gap_alerted"] = False
            return szi, False
        if not self.live_trading:
            # dry-run books are fictional (nothing is ever placed on the exchange): a gap here is
            # expected and must not alert, count, or block
            logger.info(f"[DRY RUN] {coin}: szi={szi:g} tracked={expected:g} gap={gap:+g} (not acted on)")
            return szi, False
        cycles = int(c.get("gap_cycles", 0)) + 1
        c["gap_cycles"] = cycles
        logger.warning(f"{coin}: position gap szi={szi:g} tracked={expected:g} gap={gap:+g} "
                       f"(cycle {cycles}/{GAP_ALERT_CYCLES})")
        if cycles >= GAP_ALERT_CYCLES and not c.get("gap_alerted", False):
            # flag, not `== N` (R-I): a counter carried over from before a halt/flatten/stop must not
            # step past the alert. Persist counter + flag before the (slow) alert: no repeat after a crash.
            c["gap_alerted"] = True
            save_state(cfg.STATE_FILE, self.state)
            self._alert(f"POSITION GAP {coin}: exchange szi={szi:g}, bot tracks {expected:g}, gap={gap:+g} "
                        f"for {cycles} consecutive cycles. New {coin} buys are paused until the gap clears. "
                        "Nothing is traded automatically for untracked size (no TP, no close) — check the position.")
        return szi, cycles >= GAP_ALERT_CYCLES

    _stop_detail: str = ""   # human-readable leftover after the last _stop_loss_exit (for alerts)

    def _run_stop_exit(self, coin: str, c: dict, now_ms: int) -> None:
        """One attempt of the stop-loss exit for a coin whose stop_pending is True. Verified flat ->
        drop the coin's books (every szi is closed and no order of the coin rests, so nothing in
        armed/open_lots can still matter), start the cooldown, clear stop_pending (+ gap episode state),
        and ALWAYS tell the owner (R-L: a realised stop-loss is money lost). Not verified -> everything
        stays as it is (lots tracked, stop_pending True), one alert on the first failure only, and the
        next cycle runs this again regardless of price."""
        if self._stop_loss_exit(coin):
            c["armed"] = {}
            c["open_lots"] = {}
            c["stopped_until_ms"] = now_ms + int(cfg.COOLDOWN_HOURS * 3600 * 1000)
            c["stop_pending"] = False
            c["stop_alerted"] = False
            c["gap_cycles"] = 0
            c["gap_alerted"] = False
            c["reconcile_fail_cycles"] = 0   # a failure streak from before the stop must not resume after the cooldown
            save_state(cfg.STATE_FILE, self.state)
            if self.live_trading:   # dry-run verified nothing on an exchange: nothing to announce
                self._alert(f"STOP-LOSS EXIT {coin}: verified — {coin} szi reads 0 and no {coin} order rests "
                            f"on the exchange. Cooldown {cfg.COOLDOWN_HOURS:g}h.")
            return
        logger.error(f"{coin}: SAFETY-CRITICAL stop-loss exit not verified — keeping position tracked, "
                     "re-running the exit every cycle until the read-back is flat")
        if not c.get("stop_alerted", False):
            c["stop_alerted"] = True
            save_state(cfg.STATE_FILE, self.state)   # persist before the (slow) alert: no repeat after a crash
            self._alert(f"STOP-LOSS EXIT NOT VERIFIED {coin}: {self._stop_detail or 'unknown'}. "
                        "Retrying every cycle until the exchange reads flat; no new orders for this coin meanwhile.")
            return
        save_state(cfg.STATE_FILE, self.state)

    def _stop_loss_exit(self, coin: str) -> bool:
        """Stop-loss exit = the circuit breaker's flatten restricted to one coin (R-J): cancel EVERY
        resting order of the coin on the exchange (whether or not state knows it), close the coin's
        whole szi, wait for the venue's read side, then read back. True only when the read-back shows
        no order of the coin and szi == 0 (_verify_flat; an unreadable side is False). One round per
        call: a failed exit is simply run again next cycle (stop_pending). The caller drops the coin's
        books on True — nothing here consults state, so there is no per-order settlement and a buy that
        filled unseen cannot produce a TP on a flat position. Dry-run sends and reads nothing."""
        self._stop_detail = ""
        if not self.live_trading:
            logger.info(f"[DRY RUN] stop-loss exit {coin}: would cancel all {coin} orders and market-close "
                        f"the {coin} position; nothing sent")
            return True
        self._flatten_round([coin])
        time.sleep(FLATTEN_SETTLE_SECONDS)   # let the venue's read side catch up before verifying (R-D)
        ok, detail = self._verify_flat([coin])
        if not ok:
            logger.error(f"{coin}: stop-loss exit not flat: {detail}")
            self._stop_detail = detail
        return ok

    def _resolve_buy(self, coin: str, level: int, oid) -> None:
        """Settle an armed buy that is no longer in the resting snapshot (or
        whose cancel was not confirmed). The armed record leaves state in
        exactly two ways: filled quantity > 0 and the lot + TP exist, or zero
        fill on an order that is no longer open. Anything else (unknown oid,
        query error, unparseable payload, still open, TP placement failed)
        KEEPS the record so the next cycle asks again — never forget a fill.
        Fill quantity = origSz - sz (sz is the remaining size); no fill price
        is returned, and buys are Alo (maker), so entry = limitPx."""
        c = self.state["coins"][coin]
        skey = str(level)
        if isinstance(oid, str) and oid.startswith("dryrun-"):
            # dry-run orders never existed on the exchange: nothing to settle
            c["armed"].pop(skey, None)
            return
        try:
            resp = self.info.query_order_by_oid(cfg.WALLET_ADDRESS, oid)
        except Exception as e:
            logger.warning(f"{coin} level {level}: order status query for oid={oid} failed ({e!r}) — "
                           "keeping armed record, will re-check next cycle")
            return
        try:
            if resp.get("status") != "order":
                raise ValueError(f"outer status {resp.get('status')!r}")
            wrapper = resp["order"]
            inner_status = wrapper["status"]
            o = wrapper["order"]
            orig = float(o["origSz"])
            remaining = float(o["sz"])
            limit_px = float(o["limitPx"])
            if not isinstance(inner_status, str) or not all(math.isfinite(x) for x in (orig, remaining, limit_px)):
                raise ValueError("non-finite or non-string field")
            filled = orig - remaining
            if filled < -1e-9:
                raise ValueError(f"negative fill {filled}")
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            logger.warning(f"{coin} level {level}: unusable order status for oid={oid} ({e!r}): {resp!r} — "
                           "keeping armed record, will re-check next cycle")
            return
        if inner_status == "open":
            return   # still resting (possibly part-filled): settle once it is fully filled or gone
        filled = round(max(filled, 0.0), self.sz_decimals(coin))
        if filled <= 0:
            logger.info(f"{coin} level {level}: oid={oid} ended '{inner_status}' with zero fill — dropping armed record")
            c["armed"].pop(skey, None)
            return
        if skey in c["open_lots"]:
            logger.error(f"{coin} level {level}: oid={oid} filled {filled} but the level already has an open lot — "
                         "keeping armed record for manual review")
            return
        tp_price = round_price(level_price(c["anchor"], c["step_pct"], level + 1), self.sz_decimals(coin))
        tp_oid = self._place_tp(coin, tp_price, filled, is_buy=False)
        if not tp_oid:
            logger.error(f"{coin} level {level}: SAFETY-CRITICAL filled {filled} @ {limit_px:.6g} but TP placement "
                         "failed — keeping armed record, will retry next cycle")
            return
        c["open_lots"][skey] = {"entry_price": limit_px, "size": filled,
                                "tp_price": tp_price, "tp_oid": tp_oid}
        c["armed"].pop(skey, None)
        logger.info(f"{coin}: level {level} filled {filled} @ {limit_px:.6g} ({inner_status}), TP placed @ {tp_price:.6g}")

    def _on_tp_filled(self, coin: str, level: int) -> None:
        c = self.state["coins"][coin]
        lot = c["open_lots"].pop(str(level), None)
        if lot:
            logger.info(f"{coin}: level {level} TP filled @ {lot['tp_price']:.6g}, pnl locked in")

    # ---- exchange calls ------------------------------------------------
    def _place_buy(self, coin: str, px: float, size: float):
        if not self.live_trading:
            logger.info(f"[DRY RUN] buy {coin} size={size} @ {px}")
            return f"dryrun-{coin}-{px}"
        try:
            result = self.exchange.order(coin, True, size, px, order_type={"limit": {"tif": "Alo"}},
                                         reduce_only=False)
            oid = _extract_oid(result)
            if oid:
                logger.info(f"{coin}: placed buy size={size} @ {px} oid={oid}")
            return oid
        except Exception as e:
            logger.error(f"{coin}: place buy failed: {e}")
            return None

    def _place_tp(self, coin: str, px: float, size: float, is_buy: bool):
        if not self.live_trading:
            logger.info(f"[DRY RUN] TP {coin} size={size} @ {px}")
            return f"dryrun-tp-{coin}-{px}"
        try:
            result = self.exchange.order(coin, is_buy, size, px, order_type={"limit": {"tif": "Gtc"}},
                                         reduce_only=True)
            return _extract_oid(result)
        except Exception as e:
            logger.error(f"{coin}: place TP failed: {e}")
            return None

    def _cancel(self, coin: str, oid) -> str:
        """"cancelled" only when the exchange reported every status "success".
        "unconfirmed": any other response (error status, odd shape) — the order
        may have filled meanwhile, so the caller must read its state back via
        _resolve_buy. "failed": the call raised. Never keyed on error text."""
        if not self.live_trading:
            logger.info(f"[DRY RUN] cancel {coin} oid={oid}")
            return "cancelled"
        try:
            result = self.exchange.cancel(coin, oid)
        except Exception as e:
            logger.warning(f"{coin}: cancel {oid} failed: {e}")
            return "failed"
        try:
            statuses = result["response"]["data"]["statuses"]
            if result["status"] == "ok" and statuses and all(st == "success" for st in statuses):
                return "cancelled"
        except (KeyError, TypeError):
            pass
        logger.warning(f"{coin}: cancel {oid} not confirmed: {result}")
        return "unconfirmed"

    def _market_flatten(self, coin: str, size: float) -> bool:
        """True only when the exchange confirmed the close (or reports no position
        left to close — SDK market_close returns None then). Pre-2026-10 this never
        returned True: 2026-09-22 the ETH lot WAS closed on the exchange but state
        logged 'FLATTEN FAILED (flatten=None)' and kept the lot forever."""
        if not self.live_trading:
            logger.info(f"[DRY RUN] flatten {coin} size={size}")
            return True
        try:
            result = self.exchange.market_close(coin, size)
        except Exception as e:
            logger.error(f"{coin}: SAFETY-CRITICAL flatten failed, manual intervention needed: {e}")
            return False
        if result is None:
            logger.warning(f"{coin}: market_close found no position to close — treating as flat")
            return True
        if result.get("status") != "ok":
            logger.error(f"{coin}: SAFETY-CRITICAL flatten rejected: {result}")
            return False
        statuses = (result.get("response", {}).get("data", {}) or {}).get("statuses", [])
        errors = [s["error"] for s in statuses if isinstance(s, dict) and "error" in s]
        if errors:
            logger.error(f"{coin}: SAFETY-CRITICAL flatten rejected: {errors}")
            return False
        filled = sum(float(s["filled"].get("totalSz", 0.0)) for s in statuses
                     if isinstance(s, dict) and "filled" in s)
        if filled + 1e-9 < size * 0.995:   # IOC partial fill: remainder was cancelled by the exchange
            logger.error(f"{coin}: SAFETY-CRITICAL flatten PARTIAL: filled {filled} of {size} — position still open")
            return False
        return True

    # ---- main loop -------------------------------------------------
    def run_once(self) -> None:
        self.bootstrap_if_needed()
        if self.check_drawdown():
            return
        for coin in cfg.COIN_UNIVERSE:
            try:
                self.sync_coin(coin)
            except Exception:
                # R-K: one coin's failure (already counted/persisted by sync_coin) must not skip the
                # other coins' cycles — they may owe a stop-loss exit or have orders to settle.
                logger.exception(f"{coin}: sync cycle failed — continuing with the other coins")
        self.state["last_fill_check_ms"] = int(time.time() * 1000)
        save_state(cfg.STATE_FILE, self.state)

    def run_forever(self) -> None:
        self.rearm_if_recovered()
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("sync cycle failed")
            time.sleep(cfg.SYNC_INTERVAL_SECONDS)


def _extract_oid(result):
    try:
        statuses = result["response"]["data"]["statuses"]
        for s in statuses:
            if "resting" in s:
                return s["resting"]["oid"]
            if "filled" in s:
                return s["filled"]["oid"]
        logger.warning(f"order not resting/filled: {result}")
        return None
    except Exception:
        logger.warning(f"could not extract oid from: {result}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    engine = GridBotEngine(live_trading=False if args.dry_run else None)
    if args.status:
        engine.bootstrap_if_needed()
        bd = equity_breakdown(engine.info, cfg.WALLET_ADDRESS)
        try:
            equity = get_full_account_equity(engine.info, cfg.WALLET_ADDRESS)
            eq_str = f"${equity:,.2f}"
        except Exception as e:
            eq_str = f"UNREADABLE ({e})"
        print(f"equity: {eq_str}  basis={cfg.EQUITY_SPOT_BASIS}  halted={engine.state.get('halted')}  "
              f"peak=${engine.state.get('peak_equity', 0.0):,.2f}")
        print(f"  portfolio_value      ${bd['portfolio_value']:,.2f}  (HL UI number, abstraction={bd['abstraction']})")
        print(f"  spot_usdc_total      ${bd['spot_usdc_total']:,.2f}  (hold ${bd['spot_usdc_hold']:,.2f})")
        print(f"  spot_coins           ${bd['spot_coins']:,.2f}" + (f"  unpriced={bd['unpriced_coins']}" if bd['unpriced_coins'] else ""))
        print(f"  perp_account_value   ${bd['perp_account_value']:,.2f}")
        try:
            resting_by_coin: dict | None = {}
            for o in engine.info.open_orders(cfg.WALLET_ADDRESS):
                resting_by_coin.setdefault(o["coin"], {})[o["oid"]] = o
        except Exception as e:
            resting_by_coin, resting_err = None, e
        for coin, c in engine.state["coins"].items():
            try:
                if resting_by_coin is None:
                    raise resting_err
                szi, tracked, gap = engine.position_report(coin, resting_by_coin.get(coin, {}))
                truth = f"szi={szi:g} tracked={tracked:g} gap={gap:+g}"
            except Exception as e:   # --status must never crash on an unreadable exchange
                truth = f"szi=UNREADABLE ({e!r}) tracked=? gap=?"
            print(f"  {coin}: anchor={c['anchor']:.6g} step={c['step_pct']*100:.3f}% "
                  f"armed={len(c['armed'])} open_lots={len(c['open_lots'])} {truth}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
