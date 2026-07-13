"""Unit tests for scripts/k_vt_engine.py (sub-project K, Task 1).

All synthetic/constructed data, no network (tests/conftest.py's autouse
_no_network fixture also hard-fails any real socket use). Numbers below are
worked by hand in the module docstring / PR description; see
scripts/k_vt_engine.py's own docstring for why rc_cap/cluster_cap use exact
bisection rather than the protocol's literal one-shot formula.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from k_vt_engine import (  # noqa: E402
    LadderState,
    apply_no_add,
    causal_scores_and_cov,
    cluster_cap,
    dd_ladder_step,
    rc_cap,
    risk_contributions,
    sizing_pipeline,
    vol_scale,
)


# ---------------------------------------------------------------------------
# 1-2: rc_cap
# ---------------------------------------------------------------------------

def test_rc_cap_shrinks_60pct_asset_below_35pct_and_converges_under_10_iters():
    # 3 uncorrelated unit-variance assets, RC0=0.6, RC1=RC2=0.2 (w_i =
    # sqrt(RC_i), diag cov: RC_i = w_i^2/sum w^2). Deliberately >=3 assets:
    # with only 2, RC0+RC1==1 always, so capping RC0 to 0.35 would force
    # RC1 to 0.65 -- capping *every* asset to <=35% is only satisfiable
    # once there's enough "other" mass to absorb the released risk.
    w = np.array([np.sqrt(0.6), np.sqrt(0.2), np.sqrt(0.2)])
    cov = np.eye(3)
    rc_before = risk_contributions(w, cov)
    assert rc_before[0] == pytest.approx(0.6, abs=1e-9)

    w_capped, iters = rc_cap(w, cov, cap=0.35, max_iter=10)

    rc_after = risk_contributions(w_capped, cov)
    assert np.max(np.abs(rc_after)) <= 0.35 + 1e-9
    assert iters < 10


def test_rc_cap_is_identity_when_no_violation():
    # 4 uncorrelated equal-vol assets, equal weight -> RC_i = 0.25 each, all
    # under the 0.35 cap: rc_cap must leave w untouched.
    w = np.array([0.5, 0.5, 0.5, 0.5])
    cov = np.eye(4)
    rc = risk_contributions(w, cov)
    assert np.allclose(rc, 0.25)

    w_capped, iters = rc_cap(w, cov, cap=0.35, max_iter=10)

    assert np.allclose(w_capped, w)
    assert iters == 0


# ---- protocol §4b-5: small-N effective cap ----

def test_rc_cap_two_active_assets_uses_50pct_cap_and_does_not_zero_book():
    # N_active=2: RCs sum to 1, so the literal 35% cap is infeasible -- the
    # first draft ground the whole book to zero here (U-fixed was 100% flat
    # before HYPE listed). Effective cap = max(0.35, 1/2) = 0.5 must bind.
    w = np.array([np.sqrt(0.7), np.sqrt(0.3)])
    cov = np.eye(2)
    rc_before = risk_contributions(w, cov)
    assert rc_before[0] == pytest.approx(0.7, abs=1e-9)

    w_capped, iters = rc_cap(w, cov, cap=0.35, max_iter=10)

    rc_after = risk_contributions(w_capped, cov)
    assert np.max(np.abs(rc_after)) <= 0.5 + 1e-6   # bound by 50%, not 35%
    assert np.all(np.abs(w_capped) > 1e-6)          # NOT zeroed
    assert w_capped[0] < w[0]                        # the violator did shrink


def test_rc_cap_single_active_asset_passes_through_untouched():
    # N_active=1 (zero-weight assets don't count): its RC is identically 1,
    # no per-asset cap can be satisfied -- protocol §4b-5: the layer must
    # not act at all.
    w = np.array([0.8, 0.0, 0.0])
    cov = np.eye(3)

    w_capped, iters = rc_cap(w, cov, cap=0.35, max_iter=10)

    assert np.allclose(w_capped, w)
    assert iters == 0


def test_rc_cap_four_active_assets_keeps_35pct_cap():
    # Regression: N_active=4 -> effective cap = max(0.35, 1/4) = 0.35,
    # i.e. exactly the pre-§4b-5 behavior.
    w = np.array([np.sqrt(0.6), np.sqrt(0.2), np.sqrt(0.1), np.sqrt(0.1)])
    cov = np.eye(4)
    rc_before = risk_contributions(w, cov)
    assert rc_before[0] == pytest.approx(0.6, abs=1e-9)

    w_capped, iters = rc_cap(w, cov, cap=0.35, max_iter=10)

    rc_after = risk_contributions(w_capped, cov)
    assert np.max(np.abs(rc_after)) <= 0.35 + 1e-9
    assert iters < 10


# ---------------------------------------------------------------------------
# 3: cluster_cap
# ---------------------------------------------------------------------------

def test_cluster_cap_binds_cluster_to_75pct():
    # BTC/ETH/SOL/HYPE, uncorrelated unit variance. wBTC=wETH=wSOL=sqrt(0.3),
    # wHYPE=sqrt(0.1) -> RC_BTC=RC_ETH=RC_SOL=0.3 (sum 0.9), RC_HYPE=0.1.
    # Worked example (module docstring): the protocol's literal one-shot
    # k=sqrt(0.75/0.9)=0.9129 only reaches ~88.2% aggregate RC, still over
    # cap -- this is exactly why cluster_cap uses exact bisection.
    coins = ["BTC", "ETH", "SOL", "HYPE"]
    w = np.array([np.sqrt(0.3), np.sqrt(0.3), np.sqrt(0.3), np.sqrt(0.1)])
    cov = np.eye(4)
    rc_before = risk_contributions(w, cov)
    assert sum(abs(rc_before[:3])) == pytest.approx(0.9, abs=1e-9)

    w_capped, iters = cluster_cap(w, cov, coins, cluster_coins=("BTC", "ETH", "SOL"), cap=0.75)

    rc_after = risk_contributions(w_capped, cov)
    cluster_rc_sum = float(np.sum(np.abs(rc_after[:3])))
    assert cluster_rc_sum <= 0.75 + 1e-9
    assert iters < 5
    # a naive single-shot scale (protocol's literal formula) would leave
    # the sum well above cap -- assert we're not accidentally reproducing
    # that under-correction.
    assert cluster_rc_sum < 0.882


def test_cluster_cap_is_identity_when_no_violation_or_cluster_absent():
    coins = ["BTC", "ETH", "SOL", "HYPE"]
    # RC = [0.2, 0.2, 0.2, 0.4] (w_i = sqrt(RC_i), diag cov) -> cluster sum
    # = 0.6, comfortably under the 0.75 cap (avoids a boundary-exact 0.75
    # construction, which would be at the mercy of float rounding).
    w = np.array([np.sqrt(0.2), np.sqrt(0.2), np.sqrt(0.2), np.sqrt(0.4)])
    cov = np.eye(4)
    w_capped, iters = cluster_cap(w, cov, coins, cluster_coins=("BTC", "ETH", "SOL"), cap=0.75)
    assert np.allclose(w_capped, w)
    assert iters == 0

    # cluster entirely absent from this universe -> no-op regardless of cap
    coins2 = ["HYPE", "DOGE"]
    w2 = np.array([0.9, 0.9])
    cov2 = np.eye(2)
    w2_capped, iters2 = cluster_cap(w2, cov2, coins2, cluster_coins=("BTC", "ETH", "SOL"), cap=0.75)
    assert np.allclose(w2_capped, w2)
    assert iters2 == 0


def test_cluster_cap_inactive_when_only_cluster_assets_active():
    # protocol §4b-5: with no ACTIVE non-cluster asset (HYPE flat here), the
    # cluster's aggregate RC is identically 1 and invariant under uniform
    # scaling of the whole book, so the 75% constraint is unsolvable -- the
    # first draft's bisection "solved" it by driving the book to zero. The
    # layer must not act at all.
    coins = ["BTC", "ETH", "SOL", "HYPE"]
    w = np.array([0.5, 0.4, 0.3, 0.0])
    cov = np.eye(4)
    rc = risk_contributions(w, cov)
    assert float(np.sum(np.abs(rc[:3]))) == pytest.approx(1.0, abs=1e-9)  # >0.75 by construction

    w_capped, iters = cluster_cap(w, cov, coins, cluster_coins=("BTC", "ETH", "SOL"), cap=0.75)

    assert np.allclose(w_capped, w)  # untouched -- in particular NOT zeroed
    assert iters == 0


# ---------------------------------------------------------------------------
# 4: vol_scale
# ---------------------------------------------------------------------------

def test_vol_scale_hits_target_ex_ante_vol_exactly():
    coins_n = 3
    rng_cov = np.array([
        [0.0004, 0.0001, 0.00005],
        [0.0001, 0.0009, 0.0002],
        [0.00005, 0.0002, 0.0006],
    ])  # a plausible daily covariance matrix, not degenerate
    w = np.array([0.4, -0.3, 0.2])
    target = 0.20  # 20% annualized

    scaled = vol_scale(w, rng_cov, target_ann_vol=target, max_gross=3.0)

    ex_ante_ann_vol = float(np.sqrt(scaled @ rng_cov @ scaled * 365))
    assert ex_ante_ann_vol == pytest.approx(target, abs=1e-9)
    assert np.sum(np.abs(scaled)) < 3.0  # didn't need the gross clamp here


def test_vol_scale_clips_gross_at_max_when_target_would_exceed_it():
    # Very low vol -> the vol-target scale factor would blow gross way past
    # 3x; final gross must be clamped to max_gross exactly.
    cov = np.eye(2) * 1e-8
    w = np.array([0.5, 0.5])
    scaled = vol_scale(w, cov, target_ann_vol=0.20, max_gross=3.0)
    gross = float(np.sum(np.abs(scaled)))
    assert gross == pytest.approx(3.0, abs=1e-9)


# ---------------------------------------------------------------------------
# 5-7: drawdown ladder
# ---------------------------------------------------------------------------

def test_ladder_full_path_reduced_no_add_flat_cooldown_recovery_normal():
    state = LadderState(peak_equity=100.0)
    cell_target = 0.20

    # NORMAL -> REDUCED at dd=-11%
    state, target, no_add = dd_ladder_step(state, 89.0, cell_target)
    assert state.name == "REDUCED" and target == 0.10 and no_add is False

    # REDUCED -> NO_ADD at dd=-16%
    state, target, no_add = dd_ladder_step(state, 84.0, cell_target)
    assert state.name == "NO_ADD" and target == 0.10 and no_add is True

    # NO_ADD -> FLAT at dd=-19% (breach of flat_dd)
    state, target, no_add = dd_ladder_step(state, 81.0, cell_target)
    assert state.name == "FLAT" and target == 0.0 and no_add is False
    assert state.cooldown_remaining == 20

    # cooldown: feed 25 more days of flat (equity unchanged, no P&L since
    # exposure is 0 during FLAT) and count exactly how many are labeled FLAT
    flat_days = 1  # the trigger day itself already counted above
    for _ in range(25):
        state, target, no_add = dd_ladder_step(state, 81.0, cell_target)
        if state.name == "FLAT":
            flat_days += 1
            assert target == 0.0
        else:
            break
    assert flat_days == 20  # protocol: "冷卻 20 交易日"
    assert state.name == "RECOVERY"
    assert target == 0.10
    # RECOVERY's own exit rule (must not fall back into REDUCED/NO_ADD, and
    # must require dd > -10% specifically) is covered in its own dedicated
    # test below: test_ladder_recovery_stays_recovery_until_dd_above_10pct_then_normal.


def test_ladder_recovery_stays_recovery_until_dd_above_10pct_then_normal():
    state = LadderState(peak_equity=100.0, name="RECOVERY", cooldown_remaining=0)
    cell_target = 0.20

    # dd = -12% (inside REDUCED's normal band) -- RECOVERY must NOT be
    # reclassified as REDUCED; it stays RECOVERY per protocol wording.
    state, target, no_add = dd_ladder_step(state, 88.0, cell_target)
    assert state.name == "RECOVERY"
    assert target == 0.10

    # dd = -9% (> -10%) -> exits to NORMAL at full cell_target
    state, target, no_add = dd_ladder_step(state, 91.0, cell_target)
    assert state.name == "NORMAL"
    assert target == cell_target


def test_ladder_no_add_state_forbids_growing_any_asset_weight():
    w_yesterday = np.array([0.10, -0.20, 0.05])
    w_today_raw = np.array([0.15, -0.25, 0.03])  # first two grew, third shrank

    clamped = apply_no_add(w_today_raw, w_yesterday)

    assert clamped[0] == pytest.approx(0.10)   # clamped down to yesterday's magnitude
    assert clamped[1] == pytest.approx(-0.20)  # sign preserved, magnitude clamped
    assert clamped[2] == pytest.approx(0.03)   # already shrank -> untouched
    assert np.all(np.abs(clamped) <= np.abs(w_yesterday) + 1e-12)


def test_ladder_peak_never_resets_on_a_trough():
    state = LadderState(peak_equity=100.0)
    cell_target = 0.20

    # deep drawdown well past FLAT threshold
    state, _, _ = dd_ladder_step(state, 70.0, cell_target)
    assert state.name == "FLAT"
    assert state.peak_equity == 100.0

    # burn through the whole cooldown without ever making a new high
    for _ in range(20):
        state, target, _ = dd_ladder_step(state, 95.0, cell_target)
    # even recovering to 95 (still below the original peak of 100) must not
    # have reset/lowered the running peak
    assert state.peak_equity == 100.0
    assert state.name == "RECOVERY"  # 95 vs peak 100 -> dd=-5% > -10%...

    # a genuine new high DOES advance the peak
    state, target, _ = dd_ladder_step(state, 105.0, cell_target)
    assert state.peak_equity == 105.0
    assert state.name == "NORMAL"


# ---- protocol §4b-7b: NO_ADD empty book routes to FLAT ----

def test_no_add_empty_book_routes_to_flat_cooldown_then_recovery_rebuild():
    # Absorbing-state repro (runner dev smoke test: cell 4 frozen 375 days):
    # dd stuck in the NO_ADD band with an empty book -> equity frozen ->
    # no_add clamps |w| <= |0| forever. §4b-7b: such a day must become a
    # FLAT trigger day, run the existing 20-day cooldown into RECOVERY,
    # after which the book may rebuild.
    coins = ["A", "B"]
    cov = np.eye(2) * 1e-4
    state = LadderState(peak_equity=100.0)
    equity = 84.0                 # dd = -16% -> NO_ADD band
    prev_w = np.zeros(2)          # book already empty (signal dead zone)
    dead_signals = np.zeros(2)

    # trigger day: NO_ADD + gross==0 -> re-routed to FLAT with full cooldown
    res = sizing_pipeline(dead_signals, cov, prev_w=prev_w, ladder_state=state,
                          equity=equity, cell_target=0.20, coins=coins)
    assert res.ladder_state.name == "FLAT"
    assert res.ladder_state.cooldown_remaining == 20
    assert res.no_add is False
    assert float(np.sum(np.abs(res.w))) == 0.0
    state, prev_w = res.ladder_state, res.w

    # 19 more cooldown days: FLAT, zero exposure -- even with live signals
    # again (equity can't move; the book is flat)
    live_signals = np.array([0.5, -0.4])
    for _ in range(19):
        res = sizing_pipeline(live_signals, cov, prev_w=prev_w, ladder_state=state,
                              equity=equity, cell_target=0.20, coins=coins)
        assert res.ladder_state.name == "FLAT"
        assert float(np.sum(np.abs(res.w))) == 0.0
        state, prev_w = res.ladder_state, res.w

    # day 21 ("20 天後"): cooldown over -> RECOVERY at reduced target, and
    # the book CAN rebuild (gross > 0) -- the absorbing state is broken.
    res = sizing_pipeline(live_signals, cov, prev_w=prev_w, ladder_state=state,
                          equity=equity, cell_target=0.20, coins=coins)
    assert res.ladder_state.name == "RECOVERY"
    assert res.target_vol_used == 0.10
    assert float(np.sum(np.abs(res.w))) > 0.0


def test_no_add_with_open_book_is_not_rerouted_to_flat():
    # Regression guard for §4b-7b: NO_ADD with positions keeps its exact
    # pre-ruling semantics -- state stays NO_ADD, no_add=True, per-asset
    # magnitudes clamped to yesterday's, book NOT flattened.
    coins = ["A", "B"]
    cov = np.eye(2) * 1e-4
    state = LadderState(peak_equity=100.0)
    prev_w = np.array([0.3, -0.2])
    raw_w = np.array([0.6, -0.5])  # wants to grow -> must be clamped

    res = sizing_pipeline(raw_w, cov, prev_w=prev_w, ladder_state=state,
                          equity=84.0, cell_target=0.20, coins=coins)

    assert res.ladder_state.name == "NO_ADD"
    assert res.no_add is True
    assert float(np.sum(np.abs(res.w))) > 0.0
    assert np.all(np.abs(res.w) <= np.abs(prev_w) + 1e-12)


def test_recovery_rebreach_of_flat_threshold_retriggers_cooldown_cycle():
    # §4b-7b 循環節流: RECOVERY that breaches -18% again is a fresh FLAT
    # trigger with a fresh 20-day cooldown, cycling back to RECOVERY --
    # not a stuck state in either direction.
    state = LadderState(peak_equity=100.0, name="RECOVERY", cooldown_remaining=0)

    state, target, no_add = dd_ladder_step(state, 80.0, 0.20)  # dd = -20%
    assert state.name == "FLAT"
    assert state.cooldown_remaining == 20
    assert target == 0.0 and no_add is False

    # cooldown runs its fixed course (equity still deep under water)
    for _ in range(19):
        state, target, _ = dd_ladder_step(state, 80.0, 0.20)
        assert state.name == "FLAT" and target == 0.0
    state, target, _ = dd_ladder_step(state, 80.0, 0.20)
    assert state.name == "RECOVERY"
    assert target == 0.10


# ---------------------------------------------------------------------------
# 8: no lookahead in Sigma / signal construction
# ---------------------------------------------------------------------------
# Standard lag convention (owner-confirmed 2026-07-13): a position is decided
# at day t's close -- its inputs may use data through day t's own close --
# and earns day t+1's return. No-lookahead therefore means: the inputs that
# decided the position EARNING day t's return (i.e. the decision made at day
# t-1's close) must not see day t's data.

def test_causal_scores_and_cov_position_earning_day_t_cannot_see_day_t():
    from hlvault.momentum.signals import composite_score

    dates = pd.date_range("2024-01-01", periods=180, freq="D")
    rng = np.random.default_rng(42)
    base_returns = pd.DataFrame(
        {"A": rng.normal(0, 0.02, len(dates)), "B": rng.normal(0, 0.02, len(dates))},
        index=dates,
    )

    prev_day = dates[149]
    spike_day = dates[150]
    returns_normal = base_returns.copy()
    returns_normal.loc[spike_day, "A"] = 0.001  # ordinary small return

    returns_spiked = base_returns.copy()
    returns_spiked.loc[spike_day, "A"] = 5.0  # a wild +500% one-day spike, day-of only

    scores_normal, cov_normal = causal_scores_and_cov(returns_normal, composite_score, cov_lookback=20)
    scores_spiked, cov_spiked = causal_scores_and_cov(returns_spiked, composite_score, cov_lookback=20)

    # The decision at day t-1's close (whose position earns spike_day's
    # return) uses only rows <= t-1, which are identical across both panels:
    # its score and covariance must be unaffected by the day-t spike.
    assert scores_normal.loc[prev_day, "A"] == pytest.approx(scores_spiked.loc[prev_day, "A"])
    assert scores_normal.loc[prev_day, "B"] == pytest.approx(scores_spiked.loc[prev_day, "B"])
    assert np.allclose(cov_normal[prev_day].values, cov_spiked[prev_day].values)

    # And the day-t decision (which earns only day t+1's return) MUST see
    # day t's own close -- guards against re-introducing the extra day of
    # lag the owner ruled out (decide-at-t-close is the standard).
    assert scores_normal.loc[spike_day, "A"] != pytest.approx(scores_spiked.loc[spike_day, "A"])
    assert not np.allclose(cov_normal[spike_day].values, cov_spiked[spike_day].values)


def test_causal_cov_handles_partially_listed_universe_as_subset():
    # A coin that lists mid-panel (like HYPE) must not NaN-out the whole
    # universe's covariance: dates before it has a full lookback window get
    # a submatrix over the coins that DO have one. (An earlier draft skipped
    # any date whose FULL matrix had NaNs, which silently kept the strategy
    # flat until the youngest coin matured.)
    from hlvault.momentum.signals import composite_score

    dates = pd.date_range("2024-01-01", periods=60, freq="D")
    rng = np.random.default_rng(7)
    a = pd.Series(rng.normal(0, 0.02, len(dates)), index=dates)
    b = pd.Series(rng.normal(0, 0.02, len(dates)), index=dates)
    b.iloc[:30] = np.nan  # B "lists" on day 31
    returns = pd.DataFrame({"A": a, "B": b})

    _, cov_by_date = causal_scores_and_cov(returns, composite_score, cov_lookback=20)

    early = dates[25]  # A has a full 20d window; B not listed yet
    late = dates[55]   # B now has >= 20 days of history
    assert list(cov_by_date[early].columns) == ["A"]
    assert not cov_by_date[early].isna().any().any()
    assert list(cov_by_date[late].columns) == ["A", "B"]
    assert not cov_by_date[late].isna().any().any()
