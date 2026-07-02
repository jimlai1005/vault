"""Live momentum engine — independent of gridbot, its own wallet/capital.
The drawdown circuit breaker is checked every cycle (SYNC_INTERVAL_SECONDS);
the momentum signal itself only recomputes/rebalances every
REBALANCE_INTERVAL_HOURS, since it's built from daily candles and rebalancing
more often would just churn on noise.

Market-order payload shape: the installed hyperliquid-python-sdk's
Exchange.order() takes a required, non-Optional `limit_px: float` and an
`order_type: OrderType` that (in this SDK version) only supports
`{"limit": {...}}` shapes — there is no `{"market": {...}}` order type.
The SDK's own market_open()/market_close() helpers implement "market order"
as an aggressive IoC limit order: they compute a slippage-adjusted price via
_slippage_price() (mid price nudged by +/-slippage, rounded to the venue's
sig-fig/decimal rules) and then call order(..., order_type={"limit": {"tif":
"Ioc"}}). gridbot never needed this because it only ever places resting
limit orders (tif=Alo/Gtc); this is the first market-order call site in the
repo. _place_order reproduces that same aggressive-IoC-limit shape directly
(rather than calling market_open, which ResilientExchange does not wrap and
which re-derives is_buy/size from the live position instead of accepting
the already-computed reconciliation order from risk.compute_order)."""
from __future__ import annotations

import argparse
import logging
import time

import pandas as pd
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from hlvault.gridbot.exchange_utils import get_account_equity, get_mid_price
from hlvault.gridbot.resilience import ResilientExchange
from hlvault.notify.telegram import send_alert
from hlvault.prices import get_candles

from . import config as cfg
from . import risk, signals
from .state import load_state, save_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("momentum")

CANDLE_LOOKBACK_DAYS = 200  # enough for the 120d lookback plus a buffer
ORDER_SLIPPAGE = 0.05  # matches hyperliquid.exchange.Exchange.DEFAULT_SLIPPAGE


class MomentumEngine:
    def __init__(self, live_trading: bool | None = None):
        if not cfg.WALLET_PRIVATE_KEY or not cfg.WALLET_ADDRESS:
            raise RuntimeError("WALLET_PRIVATE_KEY / WALLET_ADDRESS not set in .env.momentum")
        self.live_trading = cfg.LIVE_TRADING if live_trading is None else live_trading
        account = Account.from_key(cfg.WALLET_PRIVATE_KEY)
        self.info = Info(cfg.HL_API_URL, skip_ws=True)
        raw_exchange = Exchange(account, cfg.HL_API_URL, account_address=cfg.WALLET_ADDRESS)
        self.exchange = ResilientExchange(raw_exchange)
        self.state = load_state(cfg.STATE_FILE)

    def bootstrap_if_needed(self) -> None:
        if self.state.get("peak_equity", 0.0) > 0:
            return
        equity = get_account_equity(self.info, cfg.WALLET_ADDRESS)
        self.state["peak_equity"] = equity
        save_state(cfg.STATE_FILE, self.state)
        logger.info(f"bootstrap: starting equity ${equity:,.2f}")

    def check_drawdown(self) -> bool:
        halted, self.state = risk.check_drawdown(
            self.info, cfg.WALLET_ADDRESS, self.state, cfg.MAX_DRAWDOWN_PCT
        )
        if not halted:
            save_state(cfg.STATE_FILE, self.state)
            return False
        # Persist the halt BEFORE attempting to flatten (risk.check_drawdown's
        # documented caller obligation): a crash mid-flatten must not lose the
        # halt flag and cause a restart to skip re-checking drawdown.
        save_state(cfg.STATE_FILE, self.state)
        if not self.state.get("_alerted_this_halt"):
            send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                      "MOMENTUM DRAWDOWN CIRCUIT BREAKER TRIPPED — flattening and halting.")
            self._flatten_everything()
            self.state["_alerted_this_halt"] = True
            save_state(cfg.STATE_FILE, self.state)
        return True

    def _flatten_everything(self) -> None:
        """Deliberately NOT gated by self.live_trading (unlike gridbot's
        _market_flatten). This only runs once the drawdown circuit breaker
        has already tripped on real, already-open positions — those
        positions are real regardless of whether this process was started
        with --dry-run, so a "dry run" flag must never suppress the one
        action that gets real risk off the table (CLAUDE.md #3: a
        safety-critical action must never be silently skipped)."""
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        any_failed = False
        for p in user_state.get("assetPositions", []):
            pos = p["position"]
            size = float(pos["szi"])
            coin = pos["coin"]
            if abs(size) < 1e-9:
                continue
            try:
                self.exchange.market_close(coin, abs(size))
            except Exception as e:
                any_failed = True
                logger.error(f"SAFETY-CRITICAL: flatten failed for {coin}: {e}")
        if any_failed:
            logger.error("SAFETY-CRITICAL: not everything could be flattened — manual check required")

    def _place_order(self, coin: str, order: dict) -> None:
        if not self.live_trading:
            logger.info(f"[DRY RUN] {coin} order={order}")
            return
        try:
            mid = get_mid_price(self.info, coin)
            is_buy = order["is_buy"]
            # Aggressive IoC limit at mid +/- slippage — the same "market
            # order" shape hyperliquid.exchange.Exchange.market_open/
            # market_close use internally (see module docstring).
            limit_px = mid * (1 + ORDER_SLIPPAGE) if is_buy else mid * (1 - ORDER_SLIPPAGE)
            self.exchange.order(coin, is_buy, order["size"], limit_px,
                                order_type={"limit": {"tif": "Ioc"}},
                                reduce_only=order["reduce_only"])
            logger.info(f"{coin}: placed {order}")
        except Exception as e:
            logger.error(f"{coin}: order failed: {e}")

    def maybe_rebalance(self) -> None:
        now_ms = int(time.time() * 1000)
        interval_ms = int(cfg.REBALANCE_INTERVAL_HOURS * 3600 * 1000)
        if now_ms - self.state.get("last_rebalance_ms", 0) < interval_ms:
            return

        equity = get_account_equity(self.info, cfg.WALLET_ADDRESS)
        end = now_ms
        start = end - CANDLE_LOOKBACK_DAYS * 86400 * 1000
        vol_by_coin, scores = {}, {}
        for coin in cfg.COIN_UNIVERSE:
            candles = get_candles(coin, "1d", start, end)
            if len(candles) < 30:
                logger.warning(f"{coin}: not enough candle history, skipping this rebalance")
                continue
            rets = signals.daily_log_returns(candles.set_index("day")["c"])
            vol = rets.tail(cfg.VOL_LOOKBACK_DAYS).std(ddof=1)
            if pd.isna(vol) or vol <= 0:
                continue
            score_series = signals.composite_score(rets)
            if score_series.dropna().empty:
                continue
            vol_by_coin[coin] = float(vol)
            scores[coin] = float(score_series.dropna().iloc[-1])

        if not vol_by_coin:
            logger.warning("momentum: no coins with enough data this cycle, skipping rebalance")
            return

        budgets = risk.risk_budget_per_coin(vol_by_coin, equity, cfg.MAX_COIN_ALLOCATION_PCT)
        user_state = self.info.user_state(cfg.WALLET_ADDRESS)
        current_by_coin = {
            p["position"]["coin"]: float(p["position"]["szi"])
            for p in user_state.get("assetPositions", [])
        }

        for coin in vol_by_coin:
            sig = signals.score_to_position(scores[coin], cfg.ENTRY_THRESHOLD)
            target_notional = risk.target_position_notional(sig, budgets.get(coin, 0.0), cfg.LEVERAGE)
            price = get_mid_price(self.info, coin)
            if price <= 0:
                continue
            order = risk.compute_order(current_by_coin.get(coin, 0.0), target_notional,
                                       price, cfg.MIN_ORDER_NOTIONAL)
            if order is not None:
                self._place_order(coin, order)

        self.state["last_rebalance_ms"] = now_ms
        self.state["_alerted_this_halt"] = False
        save_state(cfg.STATE_FILE, self.state)

    def run_once(self) -> None:
        self.bootstrap_if_needed()
        if self.check_drawdown():
            return
        self.maybe_rebalance()

    def run_forever(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                logger.exception("momentum cycle failed")
            time.sleep(cfg.SYNC_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    engine = MomentumEngine(live_trading=False if args.dry_run else None)
    if args.status:
        equity = get_account_equity(engine.info, cfg.WALLET_ADDRESS)
        print(f"equity: ${equity:,.2f}  halted={engine.state.get('halted')} "
             f"peak={engine.state.get('peak_equity')}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
