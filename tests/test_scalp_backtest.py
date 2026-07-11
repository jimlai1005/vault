"""Unit tests for scalp_backtest_lib.py core integrity.
Synthetic bar data only; no network access."""
import sys
sys.path.insert(0, "scripts")

import numpy as np
import pandas as pd
import pytest

from scalp_backtest_lib import Trade, prep, simulate, metrics


@pytest.fixture
def simple_bars():
    """Synthetic bars: flat market at price 100, no volatility."""
    return pd.DataFrame({
        "t": range(1000, 1000 + 100),  # 100 bars
        "o": [100.0] * 100,
        "h": [100.0] * 100,
        "l": [100.0] * 100,
        "c": [100.0] * 100,
        "v": [1000.0] * 100,
        "n": [100] * 100,
        "ts": pd.date_range("2025-01-01", periods=100, freq="1min", tz="UTC"),
    })


@pytest.fixture
def volatile_bars():
    """Synthetic bars with realistic vol & ATR for cost testing."""
    n = 250
    np.random.seed(42)
    rets = np.random.normal(0, 0.001, n)
    prices = 100.0 * np.exp(np.cumsum(rets))
    return pd.DataFrame({
        "t": range(1000, 1000 + n),
        "o": prices * (1 + np.random.uniform(-0.001, 0.001, n)),
        "h": prices * (1 + np.abs(np.random.uniform(0, 0.002, n))),
        "l": prices * (1 - np.abs(np.random.uniform(0, 0.002, n))),
        "c": prices,
        "v": np.full(n, 1000.0),
        "n": np.full(n, 100),
        "ts": pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC"),
    })


@pytest.fixture
def prepped_volatile(volatile_bars):
    """Volatile bars after prep (sigma, ATR14, etc)."""
    return prep(volatile_bars)


def test_no_lookahead(simple_bars):
    """Sig[i] at bar i -> entry at open[i+1] +/- slip.
    Verify entry_px = open[i+1] * (1 + side*slip_bps/1e4)."""
    df = prep(simple_bars)
    slip_bps = 1.0

    # Signal at bar 20 (after atr14 is valid)
    sig = np.zeros(len(df))
    sig[20] = 1  # long signal at bar 20

    trades = simulate(
        df, sig, hold_bars=5, stop_atr_mult=1.0, fee_bps=0.5, slip_bps=slip_bps,
        coin="TEST", target_px=None, stop_px=None
    )

    assert len(trades) == 1
    t = trades[0]
    expected_entry_px = df.loc[21, "o"] * (1 + slip_bps / 1e4)
    assert abs(t.entry_px - expected_entry_px) < 1e-9
    assert t.entry_i == 21


def test_costs_applied(simple_bars):
    """Net PnL = Gross - 2*fee - 2*slip (entry slip + exit slip).
    Use flat market to isolate cost calculation."""
    df = prep(simple_bars)
    fee_bps = 2.0
    slip_bps = 1.0

    # Signal at bar 20; hold 5 bars (exits at bar 25)
    sig = np.zeros(len(df))
    sig[20] = 1  # long signal

    # Set stop price far below market to avoid triggering during hold period
    stop_px = np.full(len(df), np.nan)
    stop_px[20] = 50.0  # Far below entry

    trades = simulate(
        df, sig, hold_bars=5, stop_atr_mult=1.0, fee_bps=fee_bps, slip_bps=slip_bps,
        coin="TEST", target_px=None, stop_px=stop_px
    )

    assert len(trades) == 1
    t = trades[0]
    # Flat market: all PnL comes from costs (slip on entry + exit, plus fees)
    # net_bps = -2*slip - 2*fee (both hurt a long position in flat market)
    expected_net_bps = -2 * slip_bps - 2 * fee_bps
    assert abs(t.net_bps - expected_net_bps) < 1e-3, f"Expected {expected_net_bps}, got {t.net_bps}"


def test_stop_before_target_same_bar(prepped_volatile):
    """When STOP and TARGET both hit in same bar, exit reason is 'stop'."""
    df = prepped_volatile

    # Pick a bar with meaningful ATR
    i_entry = 50
    entry_px = df.loc[i_entry + 1, "o"]
    atr14 = df.loc[i_entry, "atr14"]

    # Set target above, stop below (on long)
    target_px = np.full(len(df), np.nan)
    stop_px = np.full(len(df), np.nan)
    target_px[i_entry] = entry_px * 1.002  # target +0.2%
    stop_px[i_entry] = entry_px * 0.998    # stop -0.2%

    # Create bar at i_entry+1 that hits BOTH (stop & target)
    sig = np.zeros(len(df))
    sig[i_entry] = 1  # long signal

    # Inject high/low that trigger both
    df_test = df.copy()
    df_test.loc[i_entry + 1, "h"] = entry_px * 1.005  # hits target
    df_test.loc[i_entry + 1, "l"] = entry_px * 0.995  # hits stop

    trades = simulate(
        df_test, sig, hold_bars=20, stop_atr_mult=2.0, fee_bps=1.0, slip_bps=0.5,
        coin="TEST", target_px=target_px, stop_px=stop_px
    )

    assert len(trades) >= 1
    t = trades[0]
    assert t.exit_reason == "stop", f"Expected 'stop', got '{t.exit_reason}'"


def test_no_overlap(simple_bars):
    """Same coin: exit_i < next entry_i (no overlapping positions)."""
    df = prep(simple_bars)

    # Two long signals with gap
    sig = np.array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0] + [0] * (len(df) - 10))

    trades = simulate(
        df, sig, hold_bars=3, stop_atr_mult=1.0, fee_bps=1.0, slip_bps=0.5,
        coin="TEST", target_px=None, stop_px=None
    )

    if len(trades) >= 2:
        # Check no overlap
        for i in range(len(trades) - 1):
            assert trades[i].exit_i < trades[i + 1].entry_i, \
                f"Trade {i} exits at {trades[i].exit_i}, trade {i+1} enters at {trades[i+1].entry_i}"


def test_gap_through_stop(prepped_volatile):
    """Open gaps through stop -> fill at worse of stop/open.
    Long: if open < stop, fill at min(stop, open)."""
    df = prepped_volatile

    i_entry = 50
    entry_px = df.loc[i_entry + 1, "o"]

    sig = np.zeros(len(df))
    sig[i_entry] = 1  # long

    # Set stop below entry
    stop_px = np.full(len(df), np.nan)
    stop_px[i_entry] = entry_px * 0.99  # stop at 99% of entry

    df_test = df.copy()
    # Next bar opens below stop (gap down)
    df_test.loc[i_entry + 1, "o"] = entry_px * 0.98  # opens below stop
    df_test.loc[i_entry + 1, "h"] = entry_px * 0.985
    df_test.loc[i_entry + 1, "l"] = entry_px * 0.97  # stays below

    trades = simulate(
        df_test, sig, hold_bars=10, stop_atr_mult=2.0, fee_bps=1.0, slip_bps=0.5,
        coin="TEST", target_px=None, stop_px=stop_px
    )

    assert len(trades) >= 1
    t = trades[0]
    assert t.exit_reason == "stop"
    # Exit price should be min(stop, open) before slippage
    expected_exit = min(stop_px[i_entry], df_test.loc[i_entry + 1, "o"])
    # With slip applied on exit (subtract for long): exit_px = expected_exit * (1 - slip)
    expected_exit_with_slip = expected_exit * (1 - 0.5 / 1e4)
    assert abs(t.exit_px - expected_exit_with_slip) < 1e-4


def test_maker_entry_strict_l_less_l(simple_bars):
    """Maker entry: fills only when l[j] < L (strict), at price L. No slip on entry."""
    from scalp_backtest_lib import simulate_maker

    df = prep(simple_bars)
    fee_maker_bps = 1.5
    fee_taker_bps = 4.5
    slip_bps = 1.0

    i_signal = 20
    limit_px = np.full(len(df), np.nan)
    limit_px[i_signal] = 100.0  # Limit at 100 (same as market)

    sig = np.zeros(len(df))
    sig[i_signal] = 1  # Long signal

    df_test = df.copy()
    # Bar i_signal+1: l = 100.0 exactly -> should NOT fill (not < L)
    df_test.loc[i_signal + 1, "l"] = 100.0
    df_test.loc[i_signal + 1, "h"] = 100.1

    trades = simulate_maker(
        df_test, sig, limit_px, None, None,
        fee_maker_bps=fee_maker_bps, fee_taker_bps=fee_taker_bps, slip_bps=slip_bps,
        entry_ttl=3, hold_bars=60, coin="TEST"
    )
    assert len(trades) == 0, "Should not fill when l == L (not strict <)"

    # Now bar i_signal+1: l = 99.9 < 100.0 -> should fill at L=100.0
    df_test.loc[i_signal + 1, "l"] = 99.9
    trades = simulate_maker(
        df_test, sig, limit_px, None, None,
        fee_maker_bps=fee_maker_bps, fee_taker_bps=fee_taker_bps, slip_bps=slip_bps,
        entry_ttl=3, hold_bars=60, coin="TEST"
    )
    assert len(trades) >= 1
    t = trades[0]
    assert t.entry_px == 100.0, f"Entry should be at limit L=100.0, got {t.entry_px}"
    # Entry should have 0 slip (maker entry)
    assert t.entry_i == i_signal + 1


def test_maker_no_fill_in_entry_ttl(simple_bars):
    """Maker entry: TTL=3 bars; if not filled in bars [i+1, i+3], cancel (no trade)."""
    from scalp_backtest_lib import simulate_maker

    df = prep(simple_bars)
    fee_maker_bps = 1.5
    fee_taker_bps = 4.5
    slip_bps = 1.0

    i_signal = 20
    limit_px = np.full(len(df), np.nan)
    limit_px[i_signal] = 99.0  # Aggressive limit (below market)

    sig = np.zeros(len(df))
    sig[i_signal] = 1  # Long signal

    df_test = df.copy()
    # Bars i+1 to i+3: all have l >= 99.0 -> no fill
    for j in range(i_signal + 1, i_signal + 4):
        df_test.loc[j, "l"] = 99.5  # Low > limit

    trades = simulate_maker(
        df_test, sig, limit_px, None, None,
        fee_maker_bps=fee_maker_bps, fee_taker_bps=fee_taker_bps, slip_bps=slip_bps,
        entry_ttl=3, hold_bars=60, coin="TEST"
    )
    assert len(trades) == 0, "Should cancel after 3-bar TTL with no fill"


def test_maker_vs_taker_fees(simple_bars):
    """Registered F2b cost contract (exact formulas):
    - taker exit (stop/time): net = side*(exit/entry-1)*1e4 - 1.5 - 4.5 - 1*slip
    - maker exit (target):    net = side*(exit/entry-1)*1e4 - 1.5 - 1.5 (ZERO slip)
    Slip is paid ONLY on the taker exit leg, once. Maker legs pay no slip."""
    from scalp_backtest_lib import simulate_maker

    df = prep(simple_bars)
    fee_maker_bps = 1.5
    fee_taker_bps = 4.5
    slip_bps = 0.5

    # --- Case 1: time-stop (taker) exit; flat market ---
    i_signal = 20
    limit_px = np.full(len(df), np.nan)
    limit_px[i_signal] = 100.0

    sig = np.zeros(len(df))
    sig[i_signal] = 1

    df_test = df.copy()
    df_test.loc[i_signal + 1, "l"] = 99.9  # fill at L=100.0

    trades = simulate_maker(
        df_test, sig, limit_px, None, None,
        fee_maker_bps=fee_maker_bps, fee_taker_bps=fee_taker_bps, slip_bps=slip_bps,
        entry_ttl=3, hold_bars=10, coin="TEST"
    )
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "time"
    raw = t.side * (t.exit_px / t.entry_px - 1) * 1e4
    expected_net = raw - fee_maker_bps - fee_taker_bps - slip_bps  # raw - 6.0 - slip
    assert abs(t.net_bps - expected_net) < 1e-9, \
        f"Taker exit: expected net {expected_net}, got {t.net_bps}"
    # Flat market sanity: raw = 0 -> net = -6.5 exactly
    assert abs(t.net_bps - (-6.5)) < 1e-9

    # --- Case 2: target (maker) exit: net = raw - 3.0, zero slip on both legs ---
    i_signal2 = 40
    limit_px2 = np.full(len(df), np.nan)
    limit_px2[i_signal2] = 100.0

    target_px = np.full(len(df), np.nan)
    target_px[i_signal2] = 100.5

    stop_px = np.full(len(df), np.nan)
    stop_px[i_signal2] = 90.0  # far away, never hit

    sig2 = np.zeros(len(df))
    sig2[i_signal2] = 1

    df_test2 = df.copy()
    df_test2.loc[i_signal2 + 1, "l"] = 99.9    # fill at L=100.0 on entry bar
    df_test2.loc[i_signal2 + 2, "h"] = 100.6   # h > T (strict) on bar after entry

    trades2 = simulate_maker(
        df_test2, sig2, limit_px2, target_px, stop_px,
        fee_maker_bps=fee_maker_bps, fee_taker_bps=fee_taker_bps, slip_bps=slip_bps,
        entry_ttl=3, hold_bars=60, coin="TEST"
    )
    assert len(trades2) == 1
    t2 = trades2[0]
    assert t2.exit_reason == "target"
    assert t2.exit_px == target_px[i_signal2], \
        f"Target fills at T exactly (zero slip), got {t2.exit_px}"
    raw2 = t2.side * (t2.exit_px / t2.entry_px - 1) * 1e4
    expected_net2 = raw2 - 2 * fee_maker_bps  # raw - 3.0, no slip
    assert abs(t2.net_bps - expected_net2) < 1e-9, \
        f"Maker target exit: expected net {expected_net2}, got {t2.net_bps}"
    # raw = 50 bps (100 -> 100.5) -> net = 47.0 exactly
    assert abs(t2.net_bps - 47.0) < 1e-9


def test_maker_target_from_next_bar(prepped_volatile):
    """Maker target only valid from bar after entry (not entry bar itself)."""
    from scalp_backtest_lib import simulate_maker

    df = prepped_volatile
    fee_maker_bps = 1.5
    fee_taker_bps = 4.5
    slip_bps = 0.5

    i_signal = 50
    entry_px = df.loc[i_signal + 1, "o"]
    atr = df.loc[i_signal, "atr14"]

    # Set limit and target close together
    limit_px = np.full(len(df), np.nan)
    limit_px[i_signal] = entry_px * 0.99  # Entry limit

    target_px = np.full(len(df), np.nan)
    target_px[i_signal] = entry_px * 1.01  # Target 1% above entry

    sig = np.zeros(len(df))
    sig[i_signal] = 1

    df_test = df.copy()
    # Entry at bar i+1
    df_test.loc[i_signal + 1, "l"] = limit_px[i_signal] - 0.1  # Fill at limit

    # Entry bar (i+1) also has high > target -> should NOT exit (target only from next bar)
    df_test.loc[i_signal + 1, "h"] = target_px[i_signal] + 0.5

    # Stop far away
    stop_px = np.full(len(df), np.nan)
    stop_px[i_signal] = entry_px * 0.90

    trades = simulate_maker(
        df_test, sig, limit_px, target_px, stop_px,
        fee_maker_bps=fee_maker_bps, fee_taker_bps=fee_taker_bps, slip_bps=slip_bps,
        entry_ttl=3, hold_bars=60, coin="TEST"
    )

    assert len(trades) >= 1
    t = trades[0]
    # Target should NOT be hit on entry bar (i+1), should exit later on time or target after
    # We check that it's not a "target" exit on the entry bar itself
    assert t.exit_i > i_signal + 1 or t.exit_reason != "target", \
        f"Target should not be valid on entry bar; exit at {t.exit_i}, reason {t.exit_reason}"
