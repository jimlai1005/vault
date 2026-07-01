import pytest

from hlvault.gridbot.strategy import (
    GridConfig, init_state, step, level_price, level_index, desired_armed_levels,
)


def make_cfg(**overrides):
    base = dict(
        coin="TEST", step_pct=0.01, num_levels=3, notional_per_level=100.0,
        max_position_notional=1000.0, stop_buffer_pct=0.05, cooldown_candles=2,
        fee_rate=0.0,
    )
    base.update(overrides)
    return GridConfig(**base)


def test_level_price_and_index_are_inverse():
    anchor = 100.0
    for k in (-5, -1, 0, 3, 10):
        px = level_price(anchor, 0.01, k)
        assert level_index(anchor, 0.01, px) == k


def test_initial_arm_window_is_below_price():
    cfg = make_cfg()
    state = init_state(100.0)
    state, events = step(state, {"h": 100.0, "l": 100.0, "c": 100.0}, cfg)
    assert not events
    center_k = level_index(state.anchor, cfg.step_pct, 100.0)
    assert set(state.armed) == set(desired_armed_levels(center_k, cfg))
    assert all(level_price(state.anchor, cfg.step_pct, k) < 100.0 for k in state.armed)


def test_dip_fills_a_level_then_bounce_closes_it_profitably():
    cfg = make_cfg()
    state = init_state(100.0)
    state, _ = step(state, {"h": 100.0, "l": 100.0, "c": 100.0}, cfg)
    lvl = max(state.armed)  # nearest rung below price
    fill_px = level_price(state.anchor, cfg.step_pct, lvl)

    state, events = step(state, {"h": 100.0, "l": fill_px - 0.001, "c": fill_px}, cfg)
    fills = [e for e in events if e.kind == "fill"]
    assert len(fills) == 1 and fills[0].level == lvl
    assert lvl in state.open_lots

    tp_px = level_price(state.anchor, cfg.step_pct, lvl + 1)
    state, events = step(state, {"h": tp_px + 0.001, "l": tp_px, "c": tp_px}, cfg)
    tps = [e for e in events if e.kind == "tp"]
    assert len(tps) == 1
    assert tps[0].pnl > 0
    assert lvl not in state.open_lots


def test_position_cap_skips_further_fills():
    cfg = make_cfg(num_levels=5, notional_per_level=400.0, max_position_notional=1000.0)
    state = init_state(100.0)
    state, _ = step(state, {"h": 100.0, "l": 100.0, "c": 100.0}, cfg)
    # crash straight through every armed level in one candle
    state, events = step(state, {"h": 100.0, "l": 50.0, "c": 50.0}, cfg)
    fills = [e for e in events if e.kind == "fill"]
    total_notional = sum(f.price * f.size for f in fills)
    assert total_notional <= cfg.max_position_notional + 1e-6
    assert len(fills) < 5  # capped before exhausting all 5 armed rungs


def test_stop_loss_flattens_and_starts_cooldown():
    cfg = make_cfg(stop_buffer_pct=0.02, cooldown_candles=3)
    state = init_state(100.0)
    state, _ = step(state, {"h": 100.0, "l": 100.0, "c": 100.0}, cfg)
    lvl = max(state.armed)
    fill_px = level_price(state.anchor, cfg.step_pct, lvl)
    state, _ = step(state, {"h": 100.0, "l": fill_px - 0.001, "c": fill_px}, cfg)
    assert state.open_lots

    crash_px = fill_px * (1 - cfg.stop_buffer_pct) - 0.01
    state, events = step(state, {"h": fill_px, "l": crash_px, "c": crash_px}, cfg)
    stops = [e for e in events if e.kind == "stop"]
    assert len(stops) == 1
    assert not state.open_lots
    assert not state.armed
    assert state.stopped_for == cfg.cooldown_candles


def test_cooldown_blocks_rearming_until_it_expires():
    cfg = make_cfg(stop_buffer_pct=0.02, cooldown_candles=2)
    state = init_state(100.0)
    state, _ = step(state, {"h": 100.0, "l": 100.0, "c": 100.0}, cfg)
    lvl = max(state.armed)
    fill_px = level_price(state.anchor, cfg.step_pct, lvl)
    state, _ = step(state, {"h": 100.0, "l": fill_px - 0.001, "c": fill_px}, cfg)
    crash_px = fill_px * (1 - cfg.stop_buffer_pct) - 0.01
    state, _ = step(state, {"h": fill_px, "l": crash_px, "c": crash_px}, cfg)

    state, _ = step(state, {"h": crash_px, "l": crash_px, "c": crash_px}, cfg)
    assert not state.armed and state.stopped_for == 1
    state, _ = step(state, {"h": crash_px, "l": crash_px, "c": crash_px}, cfg)
    assert state.stopped_for == 0
    assert state.armed  # re-armed once cooldown expired


def test_uptrend_trails_the_window_upward():
    cfg = make_cfg()
    state = init_state(100.0)
    state, _ = step(state, {"h": 100.0, "l": 100.0, "c": 100.0}, cfg)
    state, _ = step(state, {"h": 200.0, "l": 100.0, "c": 200.0}, cfg)
    center_k = level_index(state.anchor, cfg.step_pct, 200.0)
    assert max(state.armed) < center_k
    assert all(level_price(state.anchor, cfg.step_pct, k) < 200.0 for k in state.armed)
