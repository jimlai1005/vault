#!/usr/bin/env python
"""F2 research gate: walk-forward cointegration pair trading on Hyperliquid 1h perps.

Pre-declared protocol (implemented exactly, no tuning beyond the 6 configs):
  - Log close prices, hourly, inner-joined per pair. All 17*16/2 = 136 pairs.
  - Walk-forward: train window W in {60d, 90d}, rolling forward in 30d test blocks.
    Per block, ON TRAIN DATA ONLY: Engle-Granger (statsmodels coint) on log prices,
    select p < 0.05; hedge ratio beta by OLS (with intercept) of logP_a on logP_b;
    spread = logP_a - beta*logP_b; z-stats (mean/std) frozen from train.
  - On the NEXT 30d test block only: enter when |z| > z_entry (long cheap leg,
    short rich leg, equal $100 notional per leg), exit |z| < 0.5, hard stop
    |z| > 4 OR 7 days in trade. Max 5 concurrent pairs on a $1,000 book.
  - Fees: 0.045% taker per leg per side (~0.18% of one leg's notional round trip).
    Funding approximated as zero-mean (simplification, noted in report).

Point-in-time discipline: selection, beta, mu, sigma come from the train window
only and are FROZEN for the test block. No test-window statistic is used anywhere.

Implementation details (declared, not tuned):
  - Entry requires z_entry < |z| <= 4 (entering beyond the hard stop would be
    stopped out on the same bar and only burn fees).
  - When >5 pairs signal, priority = lowest train p-value (deterministic).
  - Positions are force-closed at block end (train stats expire) and when a
    leg's data ends mid-block (e.g. TON stops 2026-06-15); exit fee charged.
  - No new entries on the final bar of a block.
  - Sharpe: hourly account PnL / book, annualized via sqrt(24*365).
  - Beta must be > 0 (the long-cheap/short-rich rule is undefined for beta <= 0);
    exclusions are counted and reported.

Research-only: reads the local parquet cache, no network, no orders.
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant
from statsmodels.tsa.stattools import coint

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "candles_multi"

COINS = ["SOL", "XRP", "DOGE", "BNB", "LINK", "LTC", "AVAX", "SUI", "AAVE",
         "UNI", "CRV", "TON", "TAO", "PENDLE", "HYPE", "BTC", "ETH"]

# ---- pre-declared protocol constants (do not tune) ----
BOOK = 1_000.0            # account size, USD
LEG = 100.0               # notional per leg, USD
FEE = 0.00045             # 0.045% taker, per leg per side
MAX_CONCURRENT = 5        # max simultaneous pair trades
P_SELECT = 0.05           # Engle-Granger p-value threshold
EXIT_Z = 0.5              # take-profit: |z| reverts below this
STOP_Z = 4.0              # hard stop on z blow-out
MAX_HOLD_H = 7 * 24       # hard stop on time in trade
TEST_DAYS = 30            # walk-forward test block length
TRAIN_GRID = [60, 90]     # train window W, days
Z_ENTRY_GRID = [1.5, 2.0, 2.5]
MIN_TRAIN_COVER = 0.95    # min fraction of expected train hours per pair
HOURS_PER_YEAR = 24 * 365


def load_closes() -> pd.DataFrame:
    """Wide hourly close matrix, UTC index, one column per coin (outer join;
    pair-level inner joins happen later via dropna on the two legs)."""
    cols = {}
    for c in COINS:
        df = pd.read_parquet(CACHE / f"{c}_1h.parquet")
        s = pd.Series(df["c"].to_numpy(dtype=float),
                      index=pd.to_datetime(df["t"], unit="ms", utc=True), name=c)
        cols[c] = s[~s.index.duplicated(keep="last")]
    return pd.DataFrame(cols).sort_index()


def walk_forward_blocks(closes: pd.DataFrame, w_days: int):
    """(train_start, test_start, test_end) triples; 30d blocks, last one may be
    a partial remainder (kept if >= 7d)."""
    t0, t_last = closes.index[0], closes.index[-1]
    blocks = []
    test_start = t0 + pd.Timedelta(days=w_days)
    while test_start <= t_last:
        test_end = min(test_start + pd.Timedelta(days=TEST_DAYS),
                       t_last + pd.Timedelta(hours=1))
        if (test_end - test_start) >= pd.Timedelta(days=7):
            blocks.append((test_start - pd.Timedelta(days=w_days), test_start, test_end))
        test_start += pd.Timedelta(days=TEST_DAYS)
    return blocks


def select_pairs(closes: pd.DataFrame, train_start, test_start):
    """Engle-Granger selection + OLS hedge ratio + frozen z-stats.
    Uses TRAIN data only. Returns ({pair: params}, n_beta_excluded)."""
    expected = (test_start - train_start) / pd.Timedelta(hours=1)
    win = closes.loc[(closes.index >= train_start) & (closes.index < test_start)]
    sel, n_beta_excl = {}, 0
    for a, b in itertools.combinations(COINS, 2):
        sub = win[[a, b]].dropna()                      # inner join per pair
        if len(sub) < MIN_TRAIN_COVER * expected:
            continue
        la = np.log(sub[a].to_numpy())
        lb = np.log(sub[b].to_numpy())
        pval = coint(la, lb)[1]                         # Engle-Granger, trend='c'
        if pval >= P_SELECT:
            continue
        beta = float(OLS(la, add_constant(lb)).fit().params[1])
        if beta <= 0:
            n_beta_excl += 1
            continue
        spread = la - beta * lb
        mu, sigma = float(spread.mean()), float(spread.std(ddof=1))
        if not np.isfinite(sigma) or sigma <= 0:
            continue
        sel[(a, b)] = {"pval": pval, "beta": beta, "mu": mu, "sigma": sigma}
    return sel, n_beta_excl


def simulate(closes: pd.DataFrame, blocks, selections, z_entry: float):
    """Run the OOS test blocks for one (W, z_entry) config.
    Returns (hourly pnl Series over the full OOS span, list of closed trades)."""
    oos_index = closes.index[closes.index >= blocks[0][1]]
    pnl_by_hour: dict = {}
    trades: list[dict] = []

    for (train_start, test_start, test_end), sel in zip(blocks, selections):
        # Per-pair test-block data: inner-joined prices + FROZEN train z-score.
        pair_rows: dict = {}
        pair_last_ts: dict = {}
        for pair, p in sel.items():
            a, b = pair
            sub = closes.loc[(closes.index >= test_start) & (closes.index < test_end),
                             [a, b]].dropna()
            if sub.empty:
                continue
            z = (np.log(sub[a].to_numpy()) - p["beta"] * np.log(sub[b].to_numpy())
                 - p["mu"]) / p["sigma"]
            pair_rows[pair] = {ts: (pa, pb, zz) for ts, pa, pb, zz
                               in zip(sub.index, sub[a].to_numpy(), sub[b].to_numpy(), z)}
            pair_last_ts[pair] = sub.index[-1]

        hours = oos_index[(oos_index >= test_start) & (oos_index < test_end)]
        open_tr: dict = {}

        def close_trade(pair, tr, ts, pa, pb, reason, hp):
            fee_out = FEE * (abs(tr["ua"]) * pa + abs(tr["ub"]) * pb)
            trades.append({"pair": pair, "entry": tr["t"], "exit": ts,
                           "net": tr["val"] - tr["fee"] - fee_out, "reason": reason})
            del open_tr[pair]
            return hp - fee_out

        for i, h in enumerate(hours):
            last_hour = i == len(hours) - 1
            hp = 0.0

            # ---- mark to market + exits (before entries) ----
            for pair in list(open_tr):
                tr = open_tr[pair]
                row = pair_rows.get(pair, {}).get(h)
                if row is None:
                    # leg data gap; hold at last mark, but never carry past block
                    if last_hour:
                        hp = close_trade(pair, tr, h, tr["pa"], tr["pb"],
                                         "block_end_stale", hp)
                    continue
                pa, pb, z = row
                val = tr["ua"] * pa + tr["ub"] * pb
                hp += val - tr["val"]
                tr["val"], tr["pa"], tr["pb"] = val, pa, pb
                held_h = (h - tr["t"]) / pd.Timedelta(hours=1)
                reason = None
                if abs(z) < EXIT_Z:
                    reason = "target"
                elif abs(z) > STOP_Z:
                    reason = "z_stop"
                elif held_h >= MAX_HOLD_H:
                    reason = "time_stop"
                elif last_hour:
                    reason = "block_end"
                elif h == pair_last_ts[pair]:
                    reason = "data_end"      # e.g. TON history stops mid-block
                if reason:
                    hp = close_trade(pair, tr, h, pa, pb, reason, hp)

            # ---- entries (skip on the final bar of the block) ----
            if not last_hour and len(open_tr) < MAX_CONCURRENT:
                cands = []
                for pair, p in sel.items():
                    if pair in open_tr:
                        continue
                    row = pair_rows.get(pair, {}).get(h)
                    if row is None:
                        continue
                    pa, pb, z = row
                    if z_entry < abs(z) <= STOP_Z and h != pair_last_ts[pair]:
                        cands.append((p["pval"], pair, pa, pb, z))
                cands.sort()                       # lowest train p-value first
                for _pval, pair, pa, pb, z in cands:
                    if len(open_tr) >= MAX_CONCURRENT:
                        break
                    sa = -1.0 if z > 0 else 1.0    # z rich -> short A, long B
                    open_tr[pair] = {"t": h,
                                     "ua": sa * LEG / pa, "ub": -sa * LEG / pb,
                                     "val": 0.0, "pa": pa, "pb": pb,
                                     "fee": FEE * 2 * LEG}
                    hp -= FEE * 2 * LEG            # entry fee: 2 legs x $100

            pnl_by_hour[h] = pnl_by_hour.get(h, 0.0) + hp

    pnl = pd.Series(pnl_by_hour).reindex(oos_index, fill_value=0.0)
    return pnl, trades


def metrics(pnl: pd.Series, trades: list[dict]) -> dict:
    equity = BOOK + pnl.cumsum()
    r = pnl / BOOK
    sd = r.std(ddof=1)
    sharpe = 0.0 if (not np.isfinite(sd) or sd == 0) else \
        float(r.mean() / sd * np.sqrt(HOURS_PER_YEAR))
    mdd = float((1.0 - equity / equity.cummax()).max())
    wins = sum(1 for t in trades if t["net"] > 0)
    return {"ret": float(pnl.sum() / BOOK), "sharpe": sharpe, "mdd": mdd,
            "n_trades": len(trades),
            "win_rate": wins / len(trades) if trades else float("nan")}


def main() -> None:
    closes = load_closes()
    print(f"Data: {closes.index[0]} -> {closes.index[-1]} "
          f"({len(closes)} hourly bars, {len(COINS)} coins, "
          f"{len(COINS) * (len(COINS) - 1) // 2} pairs)")

    results = []
    final_windows = {}
    for w in TRAIN_GRID:
        blocks = walk_forward_blocks(closes, w)
        selections, beta_excl = [], 0
        for train_start, test_start, test_end in blocks:
            sel, n_excl = select_pairs(closes, train_start, test_start)
            selections.append(sel)
            beta_excl += n_excl
            print(f"W={w}d block {test_start.date()} -> {test_end.date()}: "
                  f"{len(sel)} pairs selected (train {train_start.date()} -> "
                  f"{test_start.date()})")
        if beta_excl:
            print(f"W={w}d: {beta_excl} pair-blocks excluded for beta <= 0")
        distinct = sorted({p for s in selections for p in s})
        final_windows[w] = (blocks[-1], selections[-1])
        for z_entry in Z_ENTRY_GRID:
            pnl, trades = simulate(closes, blocks, selections, z_entry)
            m = metrics(pnl, trades)
            m.update({"W": w, "z_entry": z_entry, "n_blocks": len(blocks),
                      "distinct_pairs": len(distinct),
                      "distinct_traded": len({t["pair"] for t in trades})})
            results.append(m)

    # ---- results table ----
    print("\n| W (train) | z_entry | OOS return | Sharpe (ann.) | MaxDD | trades "
          "| win rate | distinct pairs selected | distinct pairs traded |")
    print("|---|---|---|---|---|---|---|---|---|")
    for m in results:
        wr = f"{m['win_rate']:.1%}" if np.isfinite(m["win_rate"]) else "n/a"
        print(f"| {m['W']}d | {m['z_entry']} | {m['ret']:+.2%} | "
              f"{m['sharpe']:+.2f} | {m['mdd']:.2%} | {m['n_trades']} | {wr} | "
              f"{m['distinct_pairs']} | {m['distinct_traded']} |")

    # ---- final selection windows ----
    for w, ((_ts, te_s, te_e), sel) in final_windows.items():
        print(f"\nFinal selection window W={w}d (test {te_s.date()} -> "
              f"{te_e.date()}): {len(sel)} pairs")
        for (a, b), p in sorted(sel.items(), key=lambda kv: kv[1]["pval"]):
            print(f"  {a}/{b}: p={p['pval']:.4f} beta={p['beta']:.3f}")

    # ---- pre-declared gate (ALL must hold for GO) ----
    sharpes = sorted(m["sharpe"] for m in results)
    med_sharpe = float(np.median(sharpes))
    worst_mdd = max(m["mdd"] for m in results)
    min_final_pairs = min(len(sel) for _b, sel in final_windows.values())
    all_positive = all(m["ret"] > 0 for m in results)

    print("\n=== PRE-DECLARED GATE ===")
    print(f"1. median-config OOS Sharpe > 1.0 : {med_sharpe:+.2f} -> "
          f"{'PASS' if med_sharpe > 1.0 else 'FAIL'}")
    print(f"2. aggregate MDD <= 15% (worst of 6): {worst_mdd:.2%} -> "
          f"{'PASS' if worst_mdd <= 0.15 else 'FAIL'}")
    print(f"3. >= 3 distinct pairs in final selection window (min over W): "
          f"{min_final_pairs} -> {'PASS' if min_final_pairs >= 3 else 'FAIL'}")
    print(f"4. return sign positive across all 6 configs: "
          f"{'PASS' if all_positive else 'FAIL'} "
          f"({sum(m['ret'] > 0 for m in results)}/6 positive)")
    go = (med_sharpe > 1.0 and worst_mdd <= 0.15 and min_final_pairs >= 3
          and all_positive)
    print(f"\nVERDICT: {'GO' if go else 'NO-GO'}")


if __name__ == "__main__":
    main()
