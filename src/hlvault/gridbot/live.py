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
import time

import pandas as pd
from eth_account import Account
from hyperliquid.exchange import Exchange
from hyperliquid.info import Info

from . import config as cfg
from .allocator import allocate_capital
from .exchange_utils import (
    MAX_LEVERAGE_FALLBACK, get_account_equity, get_max_leverage, get_mid_price,
    get_sz_decimals, round_price, round_size,
)
from .resilience import ResilientExchange
from .state import default_state, load_state, save_state
from .strategy import GridConfig, desired_armed_levels, level_index, level_price
from .volatility import adaptive_step_pct, atr_pct

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gridbot")


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

    # ---- portfolio circuit breaker ----------------------------------
    def check_drawdown(self) -> bool:
        """Returns True if halted (caller must stop trading this cycle)."""
        if self.state.get("halted"):
            logger.error("HALTED — manual re-arm required (clear 'halted' in state file after review)")
            return True
        current = get_account_equity(self.info, cfg.WALLET_ADDRESS)
        peak = max(self.state.get("peak_equity", 0.0), current)
        drawdown = (peak - current) / peak if peak > 0 else 0.0
        self.state["peak_equity"] = peak
        if drawdown >= cfg.MAX_DRAWDOWN_PCT:
            logger.error(f"DRAWDOWN CIRCUIT BREAKER: {drawdown:.1%} (peak ${peak:,.2f} -> now ${current:,.2f})")
            self._flatten_everything()
            self.state["halted"] = True
            save_state(cfg.STATE_FILE, self.state)
            return True
        return False

    def _flatten_everything(self) -> None:
        """CLAUDE.md #3: only forget a level/lot once its cancel/flatten is
        CONFIRMED — a failed flatten must stay tracked (and loud) so a real
        open position is never silently dropped from state."""
        any_failed = False
        for coin, c in self.state["coins"].items():
            for lvl in list(c["armed"]):
                if self._cancel(coin, c["armed"][lvl]):
                    del c["armed"][lvl]
                else:
                    any_failed = True
            for lvl in list(c["open_lots"]):
                lot = c["open_lots"][lvl]
                cancelled = self._cancel(coin, lot["tp_oid"])
                flattened = self._market_flatten(coin, lot["size"])
                if cancelled and flattened:
                    del c["open_lots"][lvl]
                else:
                    any_failed = True
                    logger.error(f"{coin} level {lvl}: FLATTEN FAILED (cancel={cancelled} "
                                f"flatten={flattened}) — position/order still open, will retry")
        if any_failed:
            logger.error("SAFETY-CRITICAL: not everything could be flattened — manual check required")

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
        self._ensure_leverage(coin)
        c = self.state["coins"][coin]
        now_ms = int(time.time() * 1000)
        if c["stopped_until_ms"] and now_ms < c["stopped_until_ms"]:
            return
        c["stopped_until_ms"] = None

        mid = get_mid_price(self.info, coin)
        if mid <= 0:
            logger.warning(f"{coin}: no mid price, skipping this cycle")
            return
        gc = self.grid_cfg(coin)

        # stop-loss: deepest open lot's entry, per strategy.step's rationale
        if c["open_lots"]:
            bottom_level = min(int(k) for k in c["open_lots"])
            stop_px = level_price(c["anchor"], c["step_pct"], bottom_level) * (1 - cfg.STOP_BUFFER_PCT)
            if mid <= stop_px:
                logger.error(f"{coin}: STOP-LOSS triggered at {mid:.6g} <= {stop_px:.6g}")
                for lvl in list(c["armed"]):
                    if self._cancel(coin, c["armed"][lvl]):
                        del c["armed"][lvl]
                total_size = sum(lot["size"] for lot in c["open_lots"].values())
                tp_cancelled = all(self._cancel(coin, lot["tp_oid"]) for lot in c["open_lots"].values())
                flattened = self._market_flatten(coin, total_size) if total_size > 0 else True
                if tp_cancelled and flattened:
                    c["open_lots"] = {}
                    c["stopped_until_ms"] = now_ms + int(cfg.COOLDOWN_HOURS * 3600 * 1000)
                else:
                    logger.error(f"{coin}: SAFETY-CRITICAL stop-loss flatten incomplete "
                                f"(tp_cancelled={tp_cancelled} flattened={flattened}) — "
                                "keeping position tracked, will retry next cycle")
                save_state(cfg.STATE_FILE, self.state)
                return

        # reconcile against actual resting orders (exchange = source of truth)
        resting = {o["oid"]: o for o in self.info.open_orders(cfg.WALLET_ADDRESS) if o["coin"] == coin}
        for lvl, oid in list(c["armed"].items()):
            if oid not in resting:
                self._on_buy_filled(coin, int(lvl))
        for lvl, lot in list(c["open_lots"].items()):
            if lot["tp_oid"] not in resting:
                self._on_tp_filled(coin, int(lvl))

        center_k = level_index(c["anchor"], c["step_pct"], mid)
        desired = set(desired_armed_levels(center_k, gc))
        open_notional = sum(lot["entry_price"] * lot["size"] for lot in c["open_lots"].values())

        for lvl in list(c["armed"]):
            if int(lvl) not in desired:
                self._cancel(coin, c["armed"].pop(lvl))

        for lvl in desired:
            skey = str(lvl)
            if skey in c["armed"] or skey in c["open_lots"]:
                continue
            if open_notional + c["notional_per_level"] > c["max_position_notional"]:
                continue
            px = round_price(level_price(c["anchor"], c["step_pct"], lvl), self.sz_decimals(coin))
            size = round_size(c["notional_per_level"] / px, self.sz_decimals(coin))
            if size * px < cfg.MIN_ORDER_NOTIONAL:
                continue
            oid = self._place_buy(coin, px, size)
            if oid:
                c["armed"][skey] = oid

        save_state(cfg.STATE_FILE, self.state)

    def _on_buy_filled(self, coin: str, level: int) -> None:
        c = self.state["coins"][coin]
        skey = str(level)
        oid = c["armed"].pop(skey, None)
        fills = self.info.user_fills_by_time(cfg.WALLET_ADDRESS, self.state.get("last_fill_check_ms", 0))
        match = next((f for f in fills if f.get("oid") == oid), None)
        if match is None:
            logger.warning(f"{coin} level {level}: order gone but no matching fill found — treating as cancelled")
            return
        entry_price = float(match["px"])
        size = float(match["sz"])
        tp_price = round_price(level_price(c["anchor"], c["step_pct"], level + 1), self.sz_decimals(coin))
        tp_oid = self._place_tp(coin, tp_price, size, is_buy=False)
        if tp_oid:
            c["open_lots"][skey] = {"entry_price": entry_price, "size": size,
                                    "tp_price": tp_price, "tp_oid": tp_oid}
            logger.info(f"{coin}: level {level} filled @ {entry_price:.6g}, TP placed @ {tp_price:.6g}")

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

    def _cancel(self, coin: str, oid) -> bool:
        if not self.live_trading:
            logger.info(f"[DRY RUN] cancel {coin} oid={oid}")
            return True
        try:
            self.exchange.cancel(coin, oid)
            return True
        except Exception as e:
            logger.warning(f"{coin}: cancel {oid} failed: {e}")
            return False

    def _market_flatten(self, coin: str, size: float) -> bool:
        if not self.live_trading:
            logger.info(f"[DRY RUN] flatten {coin} size={size}")
            return
        try:
            self.exchange.market_close(coin, size)
        except Exception as e:
            logger.error(f"{coin}: SAFETY-CRITICAL flatten failed, manual intervention needed: {e}")

    # ---- main loop -------------------------------------------------
    def run_once(self) -> None:
        self.bootstrap_if_needed()
        if self.check_drawdown():
            return
        for coin in cfg.COIN_UNIVERSE:
            self.sync_coin(coin)
        self.state["last_fill_check_ms"] = int(time.time() * 1000)
        save_state(cfg.STATE_FILE, self.state)

    def run_forever(self) -> None:
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
        equity = get_account_equity(engine.info, cfg.WALLET_ADDRESS)
        print(f"equity: ${equity:,.2f}  halted={engine.state.get('halted')}")
        for coin, c in engine.state["coins"].items():
            print(f"  {coin}: anchor={c['anchor']:.6g} step={c['step_pct']*100:.3f}% "
                 f"armed={len(c['armed'])} open_lots={len(c['open_lots'])}")
        return
    if args.once or args.dry_run:
        engine.run_once()
    else:
        engine.run_forever()


if __name__ == "__main__":
    main()
