import json

import pytest

from compound.bfx import models
from compound.config import Config
from compound.engine import reconcile
from compound.engine.journal import Journal
from compound.engine.loop import Engine
from compound.strategy import ladder
from compound.strategy.base import AccountState, MarketState, TargetOffer


def offer(oid, rate, period, amount):
    return models.FundingOffer(
        id=oid, symbol="fUSD", created_ms=0, updated_ms=0, amount=amount,
        amount_orig=amount, type="LIMIT", flags=None, status="ACTIVE",
        rate=rate, period=period, hidden=0, renew=0)


CFG_LIVE_TEST = Config(api_key="k", api_secret="s", capital_budget=328.0)
CFG_FULL = Config(api_key="k", api_secret="s", capital_budget=10_000.0,
                  live_test_mode=False)


def acct(available=328.67, own=None, committed=0.0):
    return AccountState(available=available, own_offers=own or [],
                        foreign_offers=[], own_committed=committed,
                        wallet_total=4340.85)


def market(last=0.00015, highs2=None, highs30=None):
    return MarketState(frr=0.00037, last=last, best_ask=0.00015,
                       best_bid=0.0003, highs2=highs2 or [0.0001 + i * 1e-6 for i in range(720)],
                       highs30=highs30 or [0.0002 + i * 1e-6 for i in range(30)])


# ---- strategy ----

def test_live_probe_two_offers_capped():
    t = ladder.decide(market(), acct(), CFG_LIVE_TEST)
    assert len(t) == 2
    assert all(o.period == 2 for o in t)
    assert all(150 <= o.amount <= 300 for o in t)
    assert sum(o.amount for o in t) <= 328.67 + 1e-9
    assert t[1].rate >= t[0].rate   # manage probe quotes above fill probe


def test_budget_headroom_respected():
    # 200 already committed of 328 budget -> headroom 128 < min_offer -> nothing
    t = ladder.decide(market(), acct(committed=200.0), CFG_LIVE_TEST)
    assert t == []


def test_full_strategy_shape():
    t = ladder.decide(market(), acct(available=10_000.0), CFG_FULL)
    periods = sorted({o.period for o in t})
    assert periods == [2, 30, 120]
    spike = [o for o in t if o.period == 120]
    assert {round(o.rate * 365, 2) for o in spike} == {0.20, 0.40, 0.80}
    assert sum(o.amount for o in t) <= 10_000.0 + 1e-6


def test_term_floor_applies():
    m = market(highs30=[0.00005] * 30)   # 30d market dead at ~1.8% APR
    t = ladder.decide(m, acct(available=10_000.0), CFG_FULL)
    term = [o for o in t if o.period == 30]
    assert all(o.rate >= 0.07 / 365 - 1e-12 for o in term)


# ---- reconcile ----

def test_plan_keeps_matching_offer():
    own = [offer(1, 0.000150, 2, 164.0)]
    targets = [TargetOffer(rate=0.000152, period=2, amount=164.0, tag="probe")]
    p = reconcile.plan(targets, own, acct(own=own), CFG_LIVE_TEST)
    assert p.cancels == [] and p.places == []


def test_plan_replaces_stale_offer():
    own = [offer(1, 0.000150, 2, 164.0)]
    targets = [TargetOffer(rate=0.000200, period=2, amount=164.0, tag="probe")]
    p = reconcile.plan(targets, own, acct(own=own), CFG_LIVE_TEST)
    assert [o.id for o in p.cancels] == [1]
    assert len(p.places) == 1


def test_live_guardrails_clamp_period_and_amount():
    targets = [TargetOffer(rate=0.0003, period=120, amount=5000.0, tag="spike")]
    p = reconcile.plan(targets, [], acct(available=5000.0), CFG_LIVE_TEST)
    assert len(p.places) == 1
    assert p.places[0].period == 2
    assert p.places[0].amount == 300.0


def test_budget_cap_blocks_overplacement():
    targets = [TargetOffer(rate=0.0003, period=2, amount=300.0, tag="a"),
               TargetOffer(rate=0.0004, period=2, amount=300.0, tag="b")]
    a = acct(available=1000.0, committed=100.0)   # budget 328 - 100 = 228 left
    p = reconcile.plan(targets, [], a, CFG_LIVE_TEST)
    assert len(p.places) == 0 or sum(t.amount for t in p.places) <= 228 + 1e-9
    assert any(r == "budget" for r, _ in p.skipped)


def test_concurrency_cap():
    targets = [TargetOffer(rate=0.0003, period=2, amount=150.0, tag=str(i))
               for i in range(4)]
    p = reconcile.plan(targets, [], acct(available=10_000.0),
                       Config(api_key="k", api_secret="s", capital_budget=10_000.0))
    assert len(p.places) <= 2


def test_mutation_cap():
    cfg = Config(api_key="k", api_secret="s", capital_budget=100_000.0,
                 live_test_mode=False, max_mutations_per_tick=3)
    own = [offer(i, 0.001, 2, 200.0) for i in range(5)]
    targets = [TargetOffer(rate=0.0003, period=2, amount=200.0, tag=str(i))
               for i in range(5)]
    p = reconcile.plan(targets, own, acct(available=100_000.0, own=own), cfg)
    assert len(p.cancels) + len(p.places) <= 3


# ---- journal ----

def test_journal_ownership_roundtrip(tmp_path):
    j = Journal(tmp_path)
    j.record_placed(offer(42, 0.0003, 2, 164.0))
    assert 42 in j.owned_ids
    j2 = Journal(tmp_path)   # reload from disk
    assert 42 in j2.owned_ids
    j2.record_canceled(42)
    assert 42 not in Journal(tmp_path).owned_ids


def test_journal_fill_attribution_and_committed(tmp_path):
    j = Journal(tmp_path)
    j.record_placed(offer(7, 0.0003, 2, 164.0))
    info = j.record_filled(7)
    assert info["amount"] == 164.0
    assert j.committed_amount() == pytest.approx(164.0)
    assert 7 not in j.owned_ids


# ---- engine tick ----

class FakePriv:
    def __init__(self, offers=None):
        self.offers = offers or []
        self.canceled = []
        self.submitted = []
        self._next_id = 1000

    def get_wallets(self):
        return [models.Wallet("funding", "USD", 4340.85, 0.0, 328.67)]

    def get_funding_offers(self, symbol):
        return list(self.offers)

    def get_funding_credits(self, symbol):
        return []

    def get_funding_loans(self, symbol):
        # foreign lent capital: balance - available - open offers
        lent = 4340.85 - 328.67 - sum(o.amount or 0 for o in self.offers)
        return [models.FundingLoan(
            id=1, symbol="fUSD", side=1, created_ms=0, updated_ms=0,
            amount=lent, flags=None, status="ACTIVE", rate_type="FIXED",
            rate=0.0002, period=30, opened_ms=0, last_payout_ms=0,
            notify=0, hidden=0, renew=0, no_close=0)]

    def submit_offer(self, symbol, amount, rate, period, hidden=False):
        self._next_id += 1
        off = offer(self._next_id, rate, period, amount)
        self.submitted.append(off)
        self.offers.append(off)
        return off

    def cancel_offer(self, offer_id):
        self.canceled.append(offer_id)
        self.offers = [o for o in self.offers if o.id != offer_id]
        return None


class FakePub:
    def get_ticker(self, symbol="fUSD"):
        return models.FundingTicker.from_array(
            [0.00037, 0.0003, 120, 1e6, 0.00015, 2, 1e6, 0, 0, 0.00015,
             1e8, 0.0004, 0.0001, None, None, 6e7, 0])

    def get_book(self, symbol="fUSD", precision="P0", length=100):
        return [models.BookEntry.from_array([0.0003, 120, 1, -1e6]),
                models.BookEntry.from_array([0.00015, 2, 1, 1e6])]

    def get_candles(self, key, **kw):
        import time as _time
        now_ms = int(_time.time() * 1000)
        highs = [0.0001 + i * 1e-6 for i in range(720)]
        return [models.Candle.from_array(
                    [now_ms - (720 - i) * 3600 * 1000, h, h, h, h, 1e6])
                for i, h in enumerate(highs)]


def test_dry_run_makes_no_mutations(tmp_path, fake_config):
    priv = FakePriv()
    eng = Engine(fake_config, FakePub(), priv, Journal(tmp_path), dry_run=True)
    p = eng.tick()
    assert len(p.places) == 2          # live probe plan exists...
    assert priv.submitted == []        # ...but nothing was sent
    assert priv.canceled == []


def test_live_tick_places_and_records_ownership(tmp_path, fake_config):
    priv = FakePriv()
    j = Journal(tmp_path)
    eng = Engine(fake_config, FakePub(), priv, j, dry_run=False)
    eng.tick()
    assert len(priv.submitted) == 2
    assert all(o.id in j.owned_ids for o in priv.submitted)
    assert all(o.period == 2 for o in priv.submitted)
    assert all((o.amount_orig or o.amount) <= 300.0 for o in priv.submitted)


def test_live_tick_never_touches_foreign_offers(tmp_path, fake_config):
    foreign = offer(555, 0.0009, 2, 500.0)   # someone else's offer
    priv = FakePriv(offers=[foreign])
    j = Journal(tmp_path)
    eng = Engine(fake_config, FakePub(), priv, j, dry_run=False)
    eng.tick()
    assert 555 not in priv.canceled
    # second tick with same state: probes exist and match, still hands off
    eng.tick()
    assert 555 not in priv.canceled


def test_partial_fill_cancel_keeps_committed(tmp_path):
    j = Journal(tmp_path)
    j.record_placed(offer(9, 0.0003, 2, 300.0))
    # canceled after 120 of 300 filled: 120 must remain committed
    j.record_canceled(9, filled_amount=120.0)
    assert 9 not in j.owned_ids
    assert j.committed_amount() == pytest.approx(120.0)


def test_fully_deployed_book_no_churn():
    # All capital on our own offers, available ~0: strategy must still emit
    # the full desired set and reconcile must keep matching offers.
    highs = [0.0001 + i * 1e-6 for i in range(720)]
    q30, q90 = highs[int(0.3 * 719)], highs[int(0.9 * 719)]
    own = [offer(1, q30, 2, 164.0), offer(2, q90, 2, 164.0)]
    a = acct(available=0.68, own=own)
    m = market(last=0.00013, highs2=highs)
    targets = ladder.decide(m, a, CFG_LIVE_TEST)
    assert len(targets) == 2, "deployed capital must still produce targets"
    p = reconcile.plan(targets, own, a, CFG_LIVE_TEST)
    assert p.cancels == [] and p.places == []


def test_cancel_and_replace_funded_by_freed_cash():
    # available 0, one stale offer: replacement is funded by the cancel.
    own = [offer(1, 0.00099, 2, 300.0)]
    a = acct(available=0.0, own=own)
    targets = [TargetOffer(rate=0.0003, period=2, amount=300.0, tag="new")]
    p = reconcile.plan(targets, own, a, CFG_LIVE_TEST)
    assert [o.id for o in p.cancels] == [1]
    assert len(p.places) == 1


def test_repaid_fill_released_from_budget(tmp_path):
    j = Journal(tmp_path)
    j.record_placed(offer(11, 0.000156, 2, 164.0))
    j.record_filled(11)
    # age the fill past the grace period
    j._state["fills"][0]["filled_ts"] -= 3600
    j._persist()
    # no matching live credit/loan -> repaid -> released
    assert j.reconcile_fills([]) == 1
    assert j.committed_amount() == 0.0


def test_live_fill_still_counts(tmp_path):
    j = Journal(tmp_path)
    j.record_placed(offer(12, 0.00025, 2, 164.0))
    j.record_filled(12)
    j._state["fills"][0]["filled_ts"] -= 3600
    j._persist()
    live = [models.FundingLoan(
        id=77, symbol="fUSD", side=1, created_ms=0, updated_ms=0, amount=164.0,
        flags=None, status="ACTIVE", rate_type="FIXED", rate=0.00025, period=2,
        opened_ms=0, last_payout_ms=0, notify=0, hidden=0, renew=0, no_close=0)]
    assert j.reconcile_fills(live) == 0
    assert j.committed_amount() == pytest.approx(164.0)


def test_fresh_fill_kept_during_grace(tmp_path):
    j = Journal(tmp_path)
    j.record_placed(offer(13, 0.0003, 2, 164.0))
    j.record_filled(13)   # filled_ts = now
    assert j.reconcile_fills([]) == 0   # inside grace period, kept
    assert j.committed_amount() == pytest.approx(164.0)
