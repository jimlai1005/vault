#!/usr/bin/env python3
"""Phase-split backtest: run the winning ladder3 config per halving-cycle phase.

Config = winner from scripts/run_backtest.py:
  make_ladder3(short=[(0.3,2),(0.6,1)], term=[(0.5,3),(0.8,2)],
               spike_aprs=[0.2,0.4,0.8], spike_weight_each=1.0, lock30_apr=0.07)
Data: data.hourly_bars_dual() (1h p2 + daily p30, 2021 -> now).
Each phase segment (>=120 days) is simulated independently with fresh capital
(sim has no per-window attribution). BASE fill regime, fee 15%, $10k.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from compound.backtest import data, sim, strategies

HALVINGS = [date(2016, 7, 9), date(2020, 5, 11), date(2024, 4, 20)]
PHASES = [("H+0-6m", 0, 6), ("H+6-12m", 6, 12), ("H+12-18m", 12, 18),
          ("H+18-30m", 18, 30), ("H+30-48m", 30, 999)]
MONTH_DAYS = 30.4375


def phase_of(d: date):
    last = None
    for h in HALVINGS:
        if d >= h:
            last = h
    m = (d - last).days / MONTH_DAYS
    for name, lo, hi in PHASES:
        if lo <= m < hi:
            return last.year, name
    return last.year, PHASES[-1][0]


def main():
    bars = data.hourly_bars_dual()
    strat = strategies.make_ladder3(
        short=[(0.3, 2), (0.6, 1)], term=[(0.5, 3), (0.8, 2)],
        spike_aprs=[0.2, 0.4, 0.8], spike_weight_each=1.0,
        lock30_apr=0.07, name="winner")

    # contiguous phase segments
    segs = []
    for b in bars:
        d = datetime.fromtimestamp(b.mts / 1000, tz=timezone.utc).date()
        key = phase_of(d)
        if segs and segs[-1][0] == key:
            segs[-1][1].append(b)
        else:
            segs.append([key, [b]])

    print("| cycle | phase | span | days | net APR | util | fills |")
    print("|---|---|---|---|---|---|---|")
    for (cyc, ph), seg in segs:
        days = len(seg) / 24.0
        d0 = datetime.fromtimestamp(seg[0].mts / 1000, tz=timezone.utc).date()
        d1 = datetime.fromtimestamp(seg[-1].mts / 1000, tz=timezone.utc).date()
        if days < 120:
            print("| %d | %s | %s..%s | %.0f | (skipped <120d) | | |" % (cyc, ph, d0, d1, days))
            continue
        r = sim.run(seg, strat, sim.BASE, capital=10_000.0, rebalance_every=4)
        print("| %d | %s | %s..%s | %.0f | %.2f%% | %.0f%% | %d |"
              % (cyc, ph, d0, d1, days, r.net_apr * 100, r.utilization * 100, r.fills))

    # cross-check: one continuous run, yearly split
    full = sim.run(bars, strat, sim.BASE, capital=10_000.0, rebalance_every=4)
    print("\ncontinuous full run: net APR %.2f%%, yearly %s"
          % (full.net_apr * 100,
             {y: round(v * 100, 1) for y, v in full.yearly_apr.items()}))


if __name__ == "__main__":
    main()
