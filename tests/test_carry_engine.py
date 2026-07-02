from dataclasses import replace

from hlvault.carry.engine import Action, plan_actions
from hlvault.carry.equity import CarrySnapshot


def snap(mid=100.0, spot_usdc=1000.0, spot_coin=0.0, short=0.0,
         margin=0.0, upnl=0.0, withdrawable=0.0):
    spot_ntl = spot_coin * mid
    short_ntl = max(short, 0.0) * mid
    perp_eq = margin + upnl + withdrawable
    lev = short_ntl / perp_eq if (short_ntl > 0 and perp_eq > 0) else 0.0
    return CarrySnapshot(mid=mid, spot_usdc=spot_usdc, spot_coin_size=spot_coin,
                         spot_coin_ntl=spot_ntl, perp_short_size=short,
                         perp_short_ntl=short_ntl, perp_margin_used=margin,
                         perp_upnl=upnl, perp_withdrawable=withdrawable,
                         equity=spot_usdc + spot_ntl + perp_eq,
                         short_leverage=lev, delta_ntl=spot_ntl - short_ntl)


CFG = dict(deploy_fraction=0.6, max_short_leverage=2.0, rebalance_leverage=2.5,
           min_short_leverage=1.2, delta_tolerance=0.02, min_order_notional=12.0)


def test_flat_and_funding_ok_enters_in_order():
    # $1000 all in spot USDC, funding positive -> move margin, buy spot, open short
    actions = plan_actions(snap(), funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["to_perp", "buy_spot", "open_short"]
    to_perp = actions[0]
    # target ntl = 0.6*1000 = 600; margin needed = 600/2.0 = 300
    assert abs(to_perp.amount - 300.0) < 1e-6
    assert abs(actions[1].size - 6.0) < 1e-6   # $600 / $100
    assert abs(actions[2].size - 6.0) < 1e-6


def test_funding_bad_unwinds_everything():
    s = snap(spot_usdc=100.0, spot_coin=6.0, short=6.0, margin=250.0,
             withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=False, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["close_short", "sell_spot", "to_spot"]
    assert abs(actions[0].size - 6.0) < 1e-6
    assert abs(actions[1].size - 6.0) < 1e-6


def test_balanced_position_produces_no_actions():
    # 6 HYPE spot vs 6 short at ~1.71x leverage, delta 0 -> hold
    s = snap(spot_usdc=50.0, spot_coin=6.0, short=6.0, margin=300.0,
             withdrawable=50.0)
    assert plan_actions(s, funding_is_ok=True, **CFG) == []


def test_pump_pushes_leverage_up_and_triggers_margin_topup():
    # price doubled: short ntl 1200, perp equity 350-600=-250+600=350... construct:
    # margin 300, upnl -600 (short lost), withdrawable 50 -> perp eq -250 (!) --
    # use milder pump: mid 140 -> short ntl 840, upnl -240, perp eq 110, lev 7.6
    s = snap(mid=140.0, spot_usdc=10.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=-240.0, withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    kinds = [a.kind for a in actions]
    assert kinds == ["sell_spot", "to_perp"]
    sell = actions[0]
    # sells enough spot so that transferring the proceeds restores <= max leverage:
    # need perp equity >= 840/2 = 420; have 110 -> shortfall 310 -> sell >= $310 of spot
    assert sell.size * 140.0 >= 310.0 - 1e-6
    # never sells more spot than needed to ALSO stay delta-neutral-ish: the
    # matching short reduction is planned next cycle by the delta guard; here
    # we only require the sale is bounded by what exists
    assert sell.size <= 6.0


def test_price_drop_pulls_excess_margin_back_and_tops_up():
    # price fell to 60: short ntl 360, upnl +240, perp eq 590, lev 0.61 < 1.2
    s = snap(mid=60.0, spot_usdc=10.0, spot_coin=6.0, short=6.0,
             margin=300.0, upnl=240.0, withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert actions and actions[0].kind == "to_spot"
    # move excess so remaining perp equity ~= 360/2 = 180: excess = 590-180 = 410
    assert abs(actions[0].amount - 410.0) < 1.0


def test_delta_drift_trims_larger_leg():
    # spot 6.5 vs short 6.0 at mid 100: delta $50 > 2% of target(600)=12
    s = snap(spot_usdc=10.0, spot_coin=6.5, short=6.0, margin=300.0,
             withdrawable=50.0)
    actions = plan_actions(s, funding_is_ok=True, **CFG)
    assert actions[0].kind == "sell_spot"
    assert abs(actions[0].size - 0.5) < 1e-6


def test_dust_actions_below_min_notional_are_suppressed():
    # tiny delta ($5 < $12 min): no action
    s = snap(spot_usdc=10.0, spot_coin=6.05, short=6.0, margin=300.0,
             withdrawable=50.0)
    assert plan_actions(s, funding_is_ok=True, **CFG) == []


def test_liquidation_defense_simulation_2x_pump():
    """Feed a synthetic pump from $100 to $200 in 5% steps; apply the
    engine's planned actions to a simulated wallet each step; assert perp
    equity never drops below HYPE maintenance margin (ntl / (2*5) = 10% ntl,
    5x max leverage) — i.e. the rebalancer acts before liquidation."""
    mid, spot_usdc, spot_coin, short = 100.0, 40.0, 6.0, 6.0
    margin, withdrawable = 300.0, 60.0
    entry = mid
    while mid < 200.0:
        mid *= 1.05
        upnl = (entry - mid) * short
        s = snap(mid=mid, spot_usdc=spot_usdc, spot_coin=spot_coin,
                 short=short, margin=margin, upnl=upnl,
                 withdrawable=withdrawable)
        perp_equity = margin + upnl + withdrawable
        maintenance = 0.10 * short * mid
        assert perp_equity > maintenance, f"liquidated at mid={mid:.1f}"
        for a in plan_actions(s, funding_is_ok=True, **CFG):
            if a.kind == "sell_spot":
                sell = min(a.size, spot_coin)
                spot_coin -= sell
                spot_usdc += sell * mid
            elif a.kind == "to_perp":
                amt = min(a.amount, spot_usdc)
                spot_usdc -= amt
                withdrawable += amt
            elif a.kind == "close_short":
                # realize upnl on the closed fraction into margin pool
                frac = min(a.size, short) / short if short else 0.0
                withdrawable += upnl * frac
                short -= min(a.size, short)
                entry = mid  # remaining position re-marked for sim simplicity
            # buy_spot / open_short / to_spot not expected during a pump
