"""plan_actions tests for the TRANSFER-FREE carry engine: agent/API keys
cannot usdClassTransfer (user-signed, master-key-only — observed live
2026-07-03), so every rebalance must be expressed as spot/perp orders and
delta neutrality is preserved by moving both legs together."""
from hlvault.carry.engine import Action, plan_actions
from hlvault.carry.equity import CarrySnapshot


def snap(mid=100.0, spot_usdc=1000.0, spot_coin=0.0, short=0.0,
         margin=0.0, upnl=0.0, withdrawable=0.0):
    spot_ntl = spot_coin * mid
    short_ntl = max(short, 0.0) * mid
    # perp_eq = margin + withdrawable, NOT + upnl: on the real API,
    # `withdrawable` already has unrealized pnl baked in (see equity.py).
    # `upnl` is still threaded through and stored on the snapshot (tests use
    # it to derive a `withdrawable` that already reflects a pnl move), but it
    # must never be added a second time here.
    perp_eq = margin + withdrawable
    lev = short_ntl / perp_eq if (short_ntl > 0 and perp_eq > 0) else 0.0
    return CarrySnapshot(mid=mid, spot_usdc=spot_usdc, spot_coin_size=spot_coin,
                         spot_coin_ntl=spot_ntl, perp_short_size=short,
                         perp_short_ntl=short_ntl, perp_margin_used=margin,
                         perp_upnl=upnl, perp_withdrawable=withdrawable,
                         equity=spot_usdc + spot_ntl + perp_eq,
                         short_leverage=lev, delta_ntl=spot_ntl - short_ntl)


CFG = dict(deploy_fraction=0.6, max_short_leverage=2.0, rebalance_leverage=2.5,
           min_short_leverage=1.2, delta_tolerance=0.02, min_order_notional=12.0)


# ---- entry (priority 5) -----------------------------------------------

def test_entry_sizes_both_legs_within_both_sides():
    # spot 685 / perp 315 at mid 100: equity 1000, target 600.
    # affordable = min(600, spot cash 685, perp capacity 315*2=630) = 600.
    actions = plan_actions(snap(spot_usdc=685.0, withdrawable=315.0),
                           funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["buy_spot", "open_short"]
    assert abs(actions[0].size - 6.0) < 1e-9   # $600 / $100
    assert abs(actions[1].size - 6.0) < 1e-9   # legs always equal

def test_entry_clamped_by_spot_cash():
    # equity 1000 but only $350 spot cash: both legs must shrink to $350 —
    # a $600 short against a $350 buy would be one cycle of unhedged exposure
    actions = plan_actions(snap(spot_usdc=350.0, withdrawable=650.0),
                           funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["buy_spot", "open_short"]
    assert abs(actions[0].size - 3.5) < 1e-9   # min(600, 350, 1300) = 350
    assert abs(actions[0].size - actions[1].size) < 1e-12

def test_entry_clamped_by_perp_margin_capacity():
    # only $100 on the perp side: max short = 100*2 = $200 binds both legs
    actions = plan_actions(snap(spot_usdc=900.0, withdrawable=100.0),
                           funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["buy_spot", "open_short"]
    assert abs(actions[0].size - 2.0) < 1e-9   # min(600, 900, 200) = 200
    assert abs(actions[0].size - actions[1].size) < 1e-12

def test_entry_blocked_when_perp_has_no_margin():
    # All cash sits on spot; no transfer can be planned (agent-key limit) so
    # the engine must return [] — live.py surfaces this with an operator
    # alert (manual master-key transfer is the only fix).
    assert plan_actions(snap(spot_usdc=1000.0), funding_is_ok=True, **CFG) == []
    # dust margin (capacity 5*2=10 < $12 min notional) is still blocked
    assert plan_actions(snap(spot_usdc=1000.0, withdrawable=5.0),
                        funding_is_ok=True, **CFG) == []


# ---- funding gate (priority 1) ----------------------------------------

def test_funding_bad_unwinds_with_orders_only():
    s = snap(spot_usdc=100.0, spot_coin=6.0, short=6.0, margin=250.0,
             withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=False, **CFG)
    kinds = [a.kind for a in actions]
    # close the liquidation-risk leg FIRST; no to_spot consolidation — the
    # stranded perp margin is unreachable (and harmless) without a transfer
    assert kinds == ["close_short", "sell_spot"]
    assert abs(actions[0].size - 6.0) < 1e-9
    assert abs(actions[1].size - 6.0) < 1e-9

def test_funding_bad_while_flat_does_nothing():
    assert plan_actions(snap(), funding_is_ok=False, **CFG) == []


# ---- steady state ------------------------------------------------------

def test_balanced_position_produces_no_actions():
    # 6 HYPE spot vs 6 short at ~1.71x leverage, delta 0 -> hold
    s = snap(spot_usdc=50.0, spot_coin=6.0, short=6.0, margin=300.0,
             withdrawable=50.0)
    assert plan_actions(s, funding_is_ok=True, **CFG) == []


# ---- liquidation defense: paired unwind (priority 2) -------------------

def test_pump_triggers_paired_unwind():
    # The hand-trace: entered 6/6 at mid 100 with perp side margin 300 +
    # withdrawable 15 = 315; pump to 130 costs the short (130-100)*6=180,
    # which (correctly) reduces withdrawable by 180 -- it already reflects
    # upnl, it isn't added on top. New withdrawable = 15-180 = -165.
    # short ntl 780, perp equity 300+(-165)=135, lev 5.78 > 2.5.
    # delta_ntl slice = 780 - max(135,0)*2 = 510 -> close 510/130 = 3.923...
    s = snap(mid=130.0, spot_usdc=10.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=-180.0, withdrawable=-165.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    # close_short FIRST — it's the leg at liquidation risk
    assert kinds == ["close_short", "sell_spot"]
    assert abs(actions[0].size - 510.0 / 130.0) < 1e-9
    assert abs(actions[1].size - 510.0 / 130.0) < 1e-9  # matched slice: delta kept
    # the slice restores exactly max leverage: (780-510)/135 = 2.0
    perp_eq = 300.0 + (-165.0)
    assert abs((s.perp_short_ntl - actions[0].size * s.mid) / perp_eq - 2.0) < 1e-9

def test_paired_unwind_sells_only_what_spot_holds():
    # spot has less than the slice: sell what exists; the delta guard trims
    # the residual short next cycle. Same perp state as the test above.
    s = snap(mid=130.0, spot_usdc=10.0, spot_coin=2.0, short=6.0,
             margin=300.0, upnl=-180.0, withdrawable=-165.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert [a.kind for a in actions] == ["close_short", "sell_spot"]
    assert abs(actions[0].size - 510.0 / 130.0) < 1e-9
    assert abs(actions[1].size - 2.0) < 1e-9

def test_underwater_short_closes_everything():
    # Regression (adversarial review): perp equity <= 0 makes short_leverage
    # read as 0.0 (equity.py guard), which used to sail past the
    # `> rebalance_leverage` trigger — the engine planned NOTHING while the
    # short was deepest underwater. The raw-fields check must fire instead.
    # With max(perp_equity, 0) the slice is the FULL short — close it all.
    # withdrawable already reflects the -480 loss (it's not added again):
    # margin 300 + withdrawable -430 = perp eq -130.
    s = snap(mid=180.0, spot_usdc=10.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=-480.0, withdrawable=-430.0)  # perp eq = -130
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert actions, "engine must not go silent on an underwater short"
    assert [a.kind for a in actions] == ["close_short", "sell_spot"]
    # exactly the live position — max(perp_eq, 0) means the plan can never
    # exceed it (live.py's clamp stays as defense-in-depth only)
    assert abs(actions[0].size - 6.0) < 1e-9
    assert abs(actions[1].size - 6.0) < 1e-9

def test_underwater_short_with_no_spot_left_closes_short_only():
    s = snap(mid=180.0, spot_usdc=5.0, spot_coin=0.0, short=6.0,
             margin=300.0, upnl=-480.0, withdrawable=-430.0)  # perp eq = -130
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert [a.kind for a in actions] == ["close_short"]
    assert abs(actions[0].size - 6.0) < 1e-9


# ---- grow-back (priority 3) --------------------------------------------

def test_low_leverage_grows_both_legs_from_spot_cash():
    # price fell to 60: the short GAINS (upnl +240), already folded into
    # withdrawable (50+240=290, not added again). short ntl 360,
    # perp eq 300+290=590, lev 0.61 < 1.2. Idle perp margin can't be
    # recycled (no transfers) — instead grow both legs toward target with
    # spot cash: min(690-360, cash 200, 590*2-360=820) = 200
    s = snap(mid=60.0, spot_usdc=200.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=240.0, withdrawable=290.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["buy_spot", "open_short"]
    assert abs(actions[0].size - 200.0 / 60.0) < 1e-9
    assert abs(actions[0].size - actions[1].size) < 1e-12

def test_low_leverage_growth_bounded_by_perp_headroom():
    # perp eq 60+250=310, ntl 360 -> lev 1.16 < 1.2; headroom 310*2-360 = 260
    # binds (target gap 642-360=282 and cash 400 are both larger)
    s = snap(mid=60.0, spot_usdc=400.0, spot_coin=6.0, short=6.0,
             margin=60.0, upnl=240.0, withdrawable=250.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert [a.kind for a in actions] == ["buy_spot", "open_short"]
    assert abs(actions[0].size - 260.0 / 60.0) < 1e-9

def test_low_leverage_without_cash_holds():
    # lev 0.61 but only $10 spot cash (< min notional): nothing affordable to
    # grow -> no action at all; the idle perp margin is a harmless buffer
    s = snap(mid=60.0, spot_usdc=10.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=240.0, withdrawable=290.0)
    assert plan_actions(s, funding_is_ok=True, **CFG) == []


# ---- delta guard (priority 4) ------------------------------------------

def test_delta_drift_trims_heavier_spot_leg():
    # spot 6.5 vs short 6.0 at mid 100: delta $50 > tolerance
    s = snap(spot_usdc=10.0, spot_coin=6.5, short=6.0, margin=300.0,
             withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert actions[0].kind == "sell_spot"
    assert abs(actions[0].size - 0.5) < 1e-9

def test_delta_drift_trims_heavier_short_leg():
    s = snap(spot_usdc=10.0, spot_coin=5.5, short=6.0, margin=300.0,
             withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert [a.kind for a in actions] == ["close_short"]
    assert abs(actions[0].size - 0.5) < 1e-9

def test_dust_actions_below_min_notional_are_suppressed():
    # tiny delta ($5 < $12 min): no action
    s = snap(spot_usdc=10.0, spot_coin=6.05, short=6.0, margin=300.0,
             withdrawable=50.0)
    assert plan_actions(s, funding_is_ok=True, **CFG) == []


# ---- structural guarantees ---------------------------------------------

def test_transfer_kinds_are_never_planned():
    # Structural guarantee of the transfer-free redesign (agent keys cannot
    # usdClassTransfer): sweep a coarse grid of wallet states; the planned
    # vocabulary must only ever contain executable order kinds.
    allowed = {"buy_spot", "sell_spot", "open_short", "close_short"}
    for mid in (0.5, 100.0, 180.0):
        for spot_usdc in (0.0, 10.0, 1000.0):
            for spot_coin in (0.0, 6.0):
                for short in (0.0, 6.0):
                    for upnl in (-480.0, 0.0, 240.0):
                        for funding in (True, False):
                            s = snap(mid=mid, spot_usdc=spot_usdc,
                                     spot_coin=spot_coin, short=short,
                                     margin=300.0 if short else 0.0,
                                     upnl=upnl if short else 0.0,
                                     withdrawable=50.0)
                            for a in plan_actions(s, funding_is_ok=funding, **CFG):
                                assert a.kind in allowed
                                assert a.size > 0


def test_liquidation_defense_simulation_2x_pump():
    """Feed a synthetic pump from $100 to $200 in 5% steps; apply the
    engine's planned PAIRED UNWIND to a simulated wallet each step; assert
    perp equity never drops below HYPE maintenance margin (ntl / (2*5) = 10%
    ntl, 5x max leverage) — i.e. the rebalancer acts before liquidation.

    `withdrawable` is mark-to-market EVERY step (matching the real API,
    where it always reflects current unrealized pnl, not just realized pnl
    at the last close) -- `base_withdrawable` tracks the realized-to-date
    component, and `withdrawable = base_withdrawable + upnl` is what's fed
    to the snapshot/engine each step. perp_equity is therefore
    margin + withdrawable (no separate +upnl -- it's already folded in),
    matching the fixed formula in equity.py/engine.py."""
    mid, spot_usdc, spot_coin, short = 100.0, 40.0, 6.0, 6.0
    margin, base_withdrawable = 300.0, 60.0
    entry = mid
    while mid < 200.0:
        mid *= 1.05
        upnl = (entry - mid) * short
        withdrawable = base_withdrawable + upnl
        s = snap(mid=mid, spot_usdc=spot_usdc, spot_coin=spot_coin,
                 short=short, margin=margin, upnl=upnl,
                 withdrawable=withdrawable)
        perp_equity = margin + withdrawable
        maintenance = 0.10 * short * mid
        assert perp_equity > maintenance, f"liquidated at mid={mid:.1f}"
        actions = plan_actions(s, funding_is_ok=True, **CFG)
        kinds = [a.kind for a in actions]
        if "close_short" in kinds and "sell_spot" in kinds:
            # the liquidation-risk leg must be handled first
            assert kinds.index("close_short") < kinds.index("sell_spot")
        for a in actions:
            assert a.kind in ("close_short", "sell_spot"), \
                f"unexpected {a.kind} during a pump"
            if a.kind == "close_short":
                assert a.size <= short + 1e-9  # never plans an oversized close
                closed = min(a.size, short)
                base_withdrawable += upnl  # realize + re-mark: perp equity conserved
                short -= closed
                entry = mid
                upnl = 0.0
            elif a.kind == "sell_spot":
                sell = min(a.size, spot_coin)
                spot_coin -= sell
                spot_usdc += sell * mid
    assert short > 0, "defense should trim the short, not flatten it"
