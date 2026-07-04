"""Signal-reproduction (parity) test — closes the spec's go-live gate item
(docs/superpowers/specs/2026-07-04-cta-live-engine-design.md, "Go-live gate"):
given fixed OI/LSR/kline fixtures, the LIVE signal path (hlvault.cta.signals)
must produce numerically identical per-bar output to the BACKTEST
(scripts/research_cta_positioning_phase2b.py) for the same closed bar. If the
two drift (EMA adjust flag, ATR alpha, percentile inclusivity, shift
semantics), the forward test stops being evidence about the backtested
strategy — hence full-series, every-bar comparison, no sampling.

The backtest module is imported directly (its signal functions are module
level and import-safe: main() is __main__-guarded, nothing at import time does
IO), so BOTH sides of every comparison are the real shipped code — no
re-implementation that could mask drift.

Alignment contract (forming-bar semantics):
  * backtest: indicators are computed on bar t-1 and shifted one bar to act at
    bar t — shifted_signals(...).iloc[t] holds the signal KNOWN at t-1 close.
  * live: the engine receives a frame whose final row is the still-forming
    bar t, drops it (live.py: closed = frame.iloc[:-1]) and compute_signals
    evaluates the last CLOSED row t-1.
  Therefore compute_signals(bars.iloc[:t+1].iloc[:-1]) must equal
  shifted_signals(...).iloc[t] for every t >= 1 (t=0 has no live counterpart:
  the backtest row 0 is pure shift fill-values and the live engine never acts
  with zero closed bars).

Drift-injection audit (verified by temporarily mutating signals.py and
watching this file go red — see the F1 commit): ATR alpha, percentile
inclusivity (<= vs <), fuel lookback off-by-one, crowd min_periods and
slow-EMA adjust=True are all caught. Honest limitation: adjust=True on the
FAST EMA is NOT detectable at trend-flag level — its numeric effect decays as
(1-2/21)^t, so after the 50-bar warmup mask no flag flips in any realistic
fixture. It is also immaterial to live decisions: the engine always evaluates
the LAST bar of a ~650-bar frame, where the adjust difference has attenuated
to ~1e-27 of the initial transient (slow EMA: ~1e-11). The near-tie fixture
below exists to catch the slow-EMA variant, which is the detectable one.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hlvault.cta import config as cfg
from hlvault.cta import signals

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "research_cta_positioning_phase2b",
    _ROOT / "scripts" / "research_cta_positioning_phase2b.py")
p2b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2b)

# Deployed config (4h-p10-fuel24, short-only live) expressed in bars. The
# backtest side uses p2b's OWN constants; the live side receives these as
# explicit arguments the same way live.py derives them — so a drift in either
# module's constants or math breaks parity here.
TF = "4h"
BPD = p2b.TFS[TF]["bars_per_day"]                        # 6
PCTILE = 10                                              # from p2b.PCTILES
FUEL_LB_H = 24                                           # from p2b.FUEL_LOOKBACKS
FUEL_LB_BARS = max(1, round(FUEL_LB_H / 24 * BPD))       # 6 — live.py's formula
CROWD_WINDOW_BARS = p2b.CROWD_WINDOW_DAYS * BPD          # 540
CROWD_WARMUP_BARS = p2b.CROWD_WARMUP_DAYS * BPD          # 180
TREND_WARMUP = p2b.TREND_WARMUP_BARS                     # 50
EMA_FAST, EMA_SLOW = 20, 50   # hardcoded inside p2b.raw_indicators
ATR_PERIOD = 14               # hardcoded inside p2b.raw_indicators (alpha=1/14)
ATOL = 1e-9
N_BARS = 720                  # >= 700: covers trend warmup (50), crowd warmup
                              # (180) and a FULL crowd window (540) with margin


# ---------------------------------------------------------------- fixtures
def _ohlc_frame(close: np.ndarray, long_pct: np.ndarray, oi: np.ndarray,
                rng: np.random.Generator) -> pd.DataFrame:
    n = len(close)
    idx = pd.date_range("2025-01-01", periods=n, freq="4h")
    opn = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0.0, 0.002, n))
    return pd.DataFrame({
        "open": opn,
        "high": np.maximum(opn, close) * (1 + spread),
        "low": np.minimum(opn, close) * (1 - spread),
        "close": close,
        "oi_level": oi,
        "long_pct": long_pct,
    }, index=idx)


def _frame_downtrend_crowded_long() -> pd.DataFrame:
    """Clear downtrend + retail piling in long (rising long-%) + rising OI:
    must generate real SHORT signals."""
    rng = np.random.default_rng(101)
    close = 100.0 * np.cumprod(1 + rng.normal(-0.004, 0.004, N_BARS))
    long_pct = np.clip(np.linspace(40, 75, N_BARS) + rng.normal(0, 1.5, N_BARS), 0, 100)
    oi = 1000.0 * np.cumprod(1 + rng.normal(0.002, 0.003, N_BARS))
    return _ohlc_frame(close, long_pct, oi, rng)


def _frame_uptrend_crowded_short() -> pd.DataFrame:
    """Clear uptrend + retail piling in short (falling long-%) + rising OI:
    must generate real LONG signals."""
    rng = np.random.default_rng(202)
    close = 100.0 * np.cumprod(1 + rng.normal(0.004, 0.004, N_BARS))
    long_pct = np.clip(np.linspace(75, 40, N_BARS) + rng.normal(0, 1.5, N_BARS), 0, 100)
    oi = 1000.0 * np.cumprod(1 + rng.normal(0.002, 0.003, N_BARS))
    return _ohlc_frame(close, long_pct, oi, rng)


def _frame_chop_no_signal() -> pd.DataFrame:
    """Rangebound chop, mid-range crowding noise, driftless OI: mostly flat
    decisions (regime coverage for the no-trade paths)."""
    rng = np.random.default_rng(303)
    t = np.arange(N_BARS)
    close = 100.0 * (1 + 0.01 * np.sin(2 * np.pi * t / 60) + rng.normal(0, 0.002, N_BARS))
    long_pct = np.clip(55 + rng.normal(0, 3.0, N_BARS), 0, 100)
    oi = 1000.0 * np.cumprod(1 + rng.normal(0.0, 0.003, N_BARS))
    return _ohlc_frame(close, long_pct, oi, rng)


def _frame_ema_near_tie() -> pd.DataFrame:
    """EMA-sensitivity canary: flat price + small additive noise keeps the
    EMA20/EMA50 gap hovering around zero, so the trend flags flip constantly
    and even a tiny numeric perturbation of either EMA (e.g. adjust=True on
    the slow EMA) flips flags at some bars — sharpening the trend-flag parity
    that the strongly-trending fixtures cannot discriminate."""
    rng = np.random.default_rng(11)
    close = 100.0 + rng.normal(0, 0.05, N_BARS)
    long_pct = np.clip(55 + rng.normal(0, 3.0, N_BARS), 0, 100)
    oi = 1000.0 * np.cumprod(1 + rng.normal(0.0, 0.003, N_BARS))
    return _ohlc_frame(close, long_pct, oi, rng)


# ---------------------------------------------------------------- helpers
def _assert_series_close_or_both_nan(live: np.ndarray, bt: np.ndarray, what: str) -> None:
    live, bt = np.asarray(live, dtype=float), np.asarray(bt, dtype=float)
    both_nan = np.isnan(live) & np.isnan(bt)
    same_num = np.isclose(live, bt, rtol=0.0, atol=ATOL, equal_nan=False)
    ok = both_nan | same_num
    if not ok.all():
        i = int(np.argmin(ok))
        raise AssertionError(
            f"{what} diverges first at bar {i}: live={live[i]!r} backtest={bt[i]!r} "
            f"(diff={live[i] - bt[i]!r}); {int((~ok).sum())} bars differ in total")


def _bt_side(row: pd.Series, side: str) -> str:
    """The backtest's entry condition (simulate(): want_s / want_l) restated
    as a side string for a given side switch."""
    want_s = side in ("short", "both") and bool(row["trend_dn"] and row["crowd_long"] and row["fuel_ok"])
    want_l = side in ("long", "both") and bool(row["trend_up"] and row["crowd_short"] and row["fuel_ok"])
    if want_s:
        return "short"
    if want_l:
        return "long"
    return "flat"


def _run_parity(bars: pd.DataFrame) -> list[str]:
    """Assert full parity on one fixture; returns the per-bar both-sides
    decision list (for the anti-vacuity checks)."""
    raw = p2b.raw_indicators(bars, TF)
    shifted = p2b.shifted_signals(raw, PCTILE, FUEL_LB_H)

    # Anti-vacuity: the crowding percentile must actually engage after warmup,
    # otherwise every crowd flag is trivially False and the test proves nothing.
    assert raw["lpct_raw"].iloc[CROWD_WARMUP_BARS:].notna().all()

    # -- full-series numeric parity of the raw indicator series (unshifted,
    # same rows both sides) --
    live_trend = signals.ema_trend(bars["close"], EMA_FAST, EMA_SLOW, TREND_WARMUP)
    assert (live_trend["trend_up"].to_numpy() == raw["trend_up_raw"].to_numpy()).all(), "trend_up series"
    assert (live_trend["trend_dn"].to_numpy() == raw["trend_dn_raw"].to_numpy()).all(), "trend_dn series"
    live_pct_full = signals.crowd_percentile(bars["long_pct"], CROWD_WINDOW_BARS, CROWD_WARMUP_BARS)
    _assert_series_close_or_both_nan(live_pct_full.to_numpy(), raw["lpct_raw"].to_numpy(),
                                     "crowd percentile (full series)")
    live_atr_full = signals.atr(bars, ATR_PERIOD, TREND_WARMUP)
    _assert_series_close_or_both_nan(live_atr_full.to_numpy(), raw["atr_raw"].to_numpy(),
                                     "ATR (full series)")

    # -- per-bar, full-sequence: the live engine's exact call shape (drop the
    # forming bar, evaluate the last CLOSED bar) vs the backtest's shifted
    # act-at-bar-t signals --
    decisions: list[str] = []
    for t in range(1, len(bars)):
        frame_seen_live = bars.iloc[:t + 1]      # last row = still-forming bar t
        closed = frame_seen_live.iloc[:-1]       # live.py's forming-bar drop
        sig = signals.compute_signals(
            closed, ema_fast=EMA_FAST, ema_slow=EMA_SLOW,
            trend_warmup_bars=TREND_WARMUP, crowd_pctile=float(PCTILE),
            crowd_window_bars=CROWD_WINDOW_BARS, crowd_warmup_bars=CROWD_WARMUP_BARS,
            fuel_lookback_bars=FUEL_LB_BARS, atr_period=ATR_PERIOD)
        row = shifted.iloc[t]
        loc = f"bar {t} ({shifted.index[t]})"

        assert sig["trend_up"] == bool(row["trend_up"]), f"trend_up @ {loc}"
        assert sig["trend_dn"] == bool(row["trend_dn"]), f"trend_dn @ {loc}"
        assert sig["crowd_long"] == bool(row["crowd_long"]), f"crowd_long @ {loc}"
        assert sig["crowd_short"] == bool(row["crowd_short"]), f"crowd_short @ {loc}"
        assert sig["fuel"] == bool(row["fuel_ok"]), f"fuel @ {loc}"

        # crowd percentile on the truncated (closed-bars-only) frame — the
        # number the live crowd flags are derived from — vs the backtest's
        # unshifted percentile at t-1 (== shifted value acting at t)
        pct_live = signals.crowd_percentile(
            closed["long_pct"], CROWD_WINDOW_BARS, CROWD_WARMUP_BARS).iloc[-1]
        pct_bt = raw["lpct_raw"].iloc[t - 1]
        if np.isnan(pct_bt):
            assert np.isnan(pct_live), f"crowd pct NaN mismatch @ {loc}"
        else:
            assert abs(pct_live - pct_bt) <= ATOL, \
                f"crowd pct @ {loc}: live={pct_live!r} backtest={pct_bt!r}"

        atr_bt = row["atr"]
        if np.isnan(atr_bt):
            assert np.isnan(sig["atr"]), f"ATR NaN mismatch @ {loc}"
        else:
            assert abs(sig["atr"] - atr_bt) <= ATOL, \
                f"ATR @ {loc}: live={sig['atr']!r} backtest={atr_bt!r}"

        # final decision parity, for the deployed short-only switch AND the
        # full both-sides logic
        live_both = signals.decide(sig["trend_up"], sig["trend_dn"], sig["crowd_long"],
                                   sig["crowd_short"], sig["fuel"],
                                   enable_long=True, enable_short=True)
        assert live_both == _bt_side(row, "both"), f"decision(both) @ {loc}"
        live_short_only = signals.decide(sig["trend_up"], sig["trend_dn"], sig["crowd_long"],
                                         sig["crowd_short"], sig["fuel"],
                                         enable_long=False, enable_short=True)
        assert live_short_only == _bt_side(row, "short"), f"decision(short-only) @ {loc}"
        decisions.append(live_both)
    return decisions


# ---------------------------------------------------------------- tests
def test_parity_downtrend_crowded_long_generates_shorts():
    decisions = _run_parity(_frame_downtrend_crowded_long())
    assert "short" in decisions      # anti-vacuity: the short regime really fires


def test_parity_uptrend_crowded_short_generates_longs():
    decisions = _run_parity(_frame_uptrend_crowded_short())
    assert "long" in decisions       # anti-vacuity: the long regime really fires


def test_parity_chop_is_mostly_flat():
    decisions = _run_parity(_frame_chop_no_signal())
    assert decisions.count("flat") >= 0.8 * len(decisions)


def test_parity_ema_near_tie_canary():
    _run_parity(_frame_ema_near_tie())


def test_live_config_matches_backtested_config():
    """Parity above proves the MATH matches; this proves the deployed
    PARAMETERS still point at the backtested config (4h-p10-fuel24). It reads
    hlvault.cta.config as loaded (i.e. .env.cta overrides included) on
    purpose: overriding a signal parameter would silently turn the forward
    test into evidence about an UN-backtested strategy, and this gate must
    scream when that happens."""
    assert cfg.TIMEFRAME == TF
    assert cfg.BARS_PER_DAY == BPD
    assert cfg.EMA_FAST == EMA_FAST
    assert cfg.EMA_SLOW == EMA_SLOW
    assert cfg.TREND_WARMUP_BARS == TREND_WARMUP
    assert cfg.CROWD_PCTILE == PCTILE and PCTILE in p2b.PCTILES
    assert cfg.CROWD_WINDOW_DAYS == p2b.CROWD_WINDOW_DAYS
    assert cfg.CROWD_WARMUP_DAYS == p2b.CROWD_WARMUP_DAYS
    assert cfg.FUEL_LOOKBACK_HOURS == FUEL_LB_H and FUEL_LB_H in p2b.FUEL_LOOKBACKS
    assert cfg.ATR_PERIOD == ATR_PERIOD
    assert cfg.STOP_ATR_MULT == p2b.STOP_ATR_MULT
    assert cfg.MAX_HOLD_DAYS == p2b.MAX_HOLD.days
