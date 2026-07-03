"""Live carry engine: delta-neutral HYPE carry (long spot @107 / short perp),
funding-gated, with liquidation-defense rebalancing. Cycle: snapshot ->
drawdown gate -> hourly funding refresh -> plan_actions -> execute -> save.

Transfers (usd_class_transfer) are NON-idempotent: executed with a single
attempt through gridbot.resilience.run (no blind retry — a lost response
self-corrects next cycle when the snapshot re-reads real balances)."""
from __future__ import annotations

import argparse
import logging
import time

from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from hlvault.gridbot.exchange_utils import get_sz_decimals, round_price, round_size
from hlvault.gridbot.resilience import ResilientExchange, run as resilient_run
from hlvault.notify.telegram import send_alert

from . import config as cfg
from .engine import Action, plan_actions
from .equity import take_snapshot
from .funding import funding_ok, trailing_funding_apr
from .state import load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("carry")


def _round_spot_price(px: float, spot_sz_decimals: int) -> float:
    """HL SPOT price rule: <=5 significant figures AND <=(8 - szDecimals)
    decimals — differs from the perp rule (6 - szDecimals) implemented in
    gridbot.exchange_utils.round_price, hence a local helper. Matches the
    SDK's own Exchange._slippage_price rounding for spot assets."""
    if px <= 0:
        return 0.0
    sig = float(f"{px:.5g}")
    return round(sig, max(8 - spot_sz_decimals, 0))


class CarryEngine:
    def __init__(self, live_trading: bool | None = None):
        if not cfg.WALLET_PRIVATE_KEY or not cfg.WALLET_ADDRESS:
            raise RuntimeError("WALLET_PRIVATE_KEY / WALLET_ADDRESS not set in .env.carry")
        self.live_trading = cfg.LIVE_TRADING if live_trading is None else live_trading
        account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
        self.info = Info(cfg.HL_API_URL, skip_ws=True)
        raw = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
        self.exchange = ResilientExchange(raw)
        self.exchange_raw = raw
        self.state = load_state(cfg.STATE_FILE)

    # ---- safety ------------------------------------------------------
    def bootstrap_if_needed(self, snapshot) -> None:
        if self.state.get("peak_equity", 0.0) > 0:
            return
        self.state["peak_equity"] = snapshot.equity
        save_state(cfg.STATE_FILE, self.state)
        logger.info(f"bootstrap: starting equity ${snapshot.equity:,.2f}")

    def check_drawdown(self) -> bool:
        snapshot = take_snapshot(self.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        self.bootstrap_if_needed(snapshot)
        if not self.state.get("halted"):
            peak = max(self.state.get("peak_equity", 0.0), snapshot.equity)
            self.state["peak_equity"] = peak
            dd = (peak - snapshot.equity) / peak if peak > 0 else 0.0
            if dd < cfg.MAX_DRAWDOWN_PCT:
                save_state(cfg.STATE_FILE, self.state)
                return False
            logger.error(f"CARRY DRAWDOWN BREAKER: {dd:.1%} "
                        f"(peak ${peak:,.2f} -> ${snapshot.equity:,.2f})")
            self.state["halted"] = True
        # persist halt BEFORE flatten (crash mid-flatten must not lose it)
        save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_alerted_this_halt"):
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                      "CARRY DRAWDOWN CIRCUIT BREAKER TRIPPED — unwinding and halting.")
            self.state["_alerted_this_halt"] = True
            save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_flatten_complete"):
            if self._flatten_everything():
                self.state["_flatten_complete"] = True
            else:
                send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                          "CARRY UNWIND INCOMPLETE — will retry next cycle.")
            save_state(cfg.STATE_FILE, self.state)
        return True

    def _flatten_everything(self) -> bool:
        """Close the short, sell all spot coin. Returns True only when both
        legs confirmed flat (or already flat). Dry-run logs and skips —
        same operator contract as momentum/gridbot: --dry-run means no real
        exchange writes, even for the emergency path."""
        s = take_snapshot(self.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        ok = True
        if s.perp_short_size * s.mid > cfg.MIN_ORDER_NOTIONAL:
            if not self.live_trading:
                logger.info(f"[DRY RUN] would close short {s.perp_short_size}")
            else:
                try:
                    self.exchange.market_close(cfg.COIN, s.perp_short_size)
                except Exception as e:
                    ok = False
                    logger.error(f"SAFETY-CRITICAL: close short failed: {e}")
        if s.spot_coin_ntl > cfg.MIN_ORDER_NOTIONAL:
            if not self.live_trading:
                logger.info(f"[DRY RUN] would sell spot {s.spot_coin_size}")
            else:
                try:
                    self._spot_order(is_buy=False, size=s.spot_coin_size, mid=s.mid)
                except Exception as e:
                    ok = False
                    logger.error(f"SAFETY-CRITICAL: spot sell failed: {e}")
        return ok

    # ---- execution ---------------------------------------------------
    def _spot_order(self, is_buy: bool, size: float, mid: float) -> None:
        raw_px = mid * (1 + cfg.ORDER_SLIPPAGE) if is_buy else mid * (1 - cfg.ORDER_SLIPPAGE)
        px = _round_spot_price(raw_px, cfg.SPOT_SZ_DECIMALS)
        sz = round_size(size, cfg.SPOT_SZ_DECIMALS)
        self.exchange.order(cfg.SPOT_PAIR, is_buy, sz, px,
                            order_type={"limit": {"tif": "Ioc"}}, reduce_only=False)

    def _perp_order(self, is_buy: bool, size: float, mid: float, reduce_only: bool) -> None:
        sz_dec = get_sz_decimals(self.info, cfg.COIN)
        raw_px = mid * (1 + cfg.ORDER_SLIPPAGE) if is_buy else mid * (1 - cfg.ORDER_SLIPPAGE)
        px = round_price(raw_px, sz_dec)
        sz = round_size(size, sz_dec)
        self.exchange.order(cfg.COIN, is_buy, sz, px,
                            order_type={"limit": {"tif": "Ioc"}}, reduce_only=reduce_only)

    def _execute(self, action: Action) -> None:
        if not self.live_trading:
            logger.info(f"[DRY RUN] {action}")
            return
        mids = self.info.all_mids()
        mid = float(mids.get(cfg.COIN) or 0.0)
        if mid <= 0:
            logger.warning("no mid price; skipping action this cycle")
            return
        try:
            if action.kind == "buy_spot":
                self._spot_order(True, action.size, mid)
            elif action.kind == "sell_spot":
                self._spot_order(False, action.size, mid)
            elif action.kind == "open_short":
                self._perp_order(False, action.size, mid, reduce_only=False)
            elif action.kind == "close_short":
                self._perp_order(True, action.size, mid, reduce_only=True)
            elif action.kind == "to_perp":
                resilient_run(lambda: self.exchange_raw.usd_class_transfer(action.amount, True),
                              what="usd_class_transfer", idempotent=False)
            elif action.kind == "to_spot":
                resilient_run(lambda: self.exchange_raw.usd_class_transfer(action.amount, False),
                              what="usd_class_transfer", idempotent=False)
            logger.info(f"executed {action}")
        except Exception as e:
            logger.error(f"action {action} failed: {e} (next cycle re-plans)")

    # ---- signal ------------------------------------------------------
    def _refresh_funding_if_due(self) -> bool:
        now_ms = int(time.time() * 1000)
        if now_ms - self.state.get("last_funding_check_ms", 0) >= cfg.FUNDING_REFRESH_SECONDS * 1000:
            apr = trailing_funding_apr(cfg.COIN, cfg.FUNDING_LOOKBACK_DAYS)
            self.state["funding_ok"] = funding_ok(apr, cfg.EXIT_FUNDING_APR)
            self.state["last_funding_check_ms"] = now_ms
            save_state(cfg.STATE_FILE, self.state)
            logger.info(f"funding refresh: trailing {cfg.FUNDING_LOOKBACK_DAYS:.0f}d "
                       f"APR={apr:+.1%} -> ok={self.state['funding_ok']}")
        return bool(self.state.get("funding_ok"))

    # ---- loop --------------------------------------------------------
    def run_once(self) -> None:
        if self.check_drawdown():
            return
        is_ok = self._refresh_funding_if_due()
        s = take_snapshot(self.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        actions = plan_actions(
            s, funding_is_ok=is_ok,
            deploy_fraction=cfg.DEPLOY_FRACTION,
            max_short_leverage=cfg.MAX_SHORT_LEVERAGE,
            rebalance_leverage=cfg.REBALANCE_LEVERAGE,
            min_short_leverage=cfg.MIN_SHORT_LEVERAGE,
            delta_tolerance=cfg.DELTA_TOLERANCE,
            min_order_notional=cfg.MIN_ORDER_NOTIONAL,
        )
        for a in actions:
            self._execute(a)

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("carry cycle failed")
            time.sleep(cfg.SYNC_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    engine = CarryEngine(live_trading=False if args.dry_run else None)
    if args.status:
        s = take_snapshot(engine.info, cfg.WALLET_ADDRESS, cfg.COIN, cfg.SPOT_PAIR)
        print(f"equity ${s.equity:,.2f} | spot {s.spot_coin_size} {cfg.COIN} "
             f"(${s.spot_coin_ntl:,.2f}) + ${s.spot_usdc:,.2f} USDC | "
             f"short ${s.perp_short_ntl:,.2f} @ {s.short_leverage:.2f}x | "
             f"delta ${s.delta_ntl:+.2f} | halted={engine.state.get('halted')}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
