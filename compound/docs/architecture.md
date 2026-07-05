# compound — Bitfinex USD funding optimizer: architecture

Written 2026-07-04 (overnight build). Decision doc — implementation agents follow this.

## Goal

Maximize net APR of USD lent on Bitfinex margin funding. Floor target: **12% net APR**
(after Bitfinex's ~15% fee on interest earned). Idle time is acceptable; we optimize
long-run APR, not utilization.

## Market structure observed live (2026-07-04 snapshot, see data/book_snapshot.json)

- Ticker fUSD: FRR = 0.0003715/day (≈13.6% APR), last trade 0.00015 (≈5.5% APR),
  day high 0.00037, day low 0.0000795. FRR queue ≈ $61M.
- Book bid side (borrowers): large 120-day demand at 0.000301/day (≈11% APR gross,
  $3.4M), more 120d bids layered 0.00016–0.00021.
- Book ask side (lenders): starts 0.000149 @ 2d.
- Implication: **term premium is large** (2d spot ≈5.5% vs 120d bid ≈11%). Spot-only
  lending cannot reach 12% today; term allocation + spike capture is the path.

## Unit conventions (engineering principle 1: one source, one basis)

- **All rates internally are DAILY rates as decimal fractions** (Bitfinex API native
  unit, e.g. 0.0003715). Convert to APR only at display/report edges via
  `rates.py` — the ONLY place conversion lives. APR = daily × 365 (simple) for quoting;
  compounding handled explicitly in backtest math, never implicitly.
- Net vs gross: `net = gross × (1 - fee)`; fee is config (`BFX_FEE = 0.15`, verify
  against docs/strategy-research.md when available). Reports always label net/gross.
- Equity basis for this wallet (per engineering-principles incident #3): value lives in
  exactly these buckets — funding-wallet available USD + amount on open offers +
  amount out on loans/credits (+ accrued unpaid interest if API exposes it). Each
  counted once. Reconciliation identity checked every tick against the exchange's own
  wallet balance; alert loudly on mismatch > $1.

## Layout

```
src/compound/
  config.py        # frozen dataclass; loads .env + config.json overrides
  rates.py         # daily<->APR, fee net-ting. THE only conversion site.
  bfx/
    transport.py   # HTTP + auth signing. The only module that talks to the network.
    boundary.py    # resilience boundary wrapping transport (principle 5)
    models.py      # typed views over v2 array payloads (Ticker, Book, Offer, Credit, Wallet)
    public.py      # public endpoints via boundary
    private.py     # authed endpoints via boundary
  strategy/
    base.py        # MarketState, AccountState, TargetOffer, Strategy protocol
    ladder.py      # production strategy v1 (params from backtest)
  engine/
    state.py       # fetch + reconcile account state; the identity check lives here
    reconcile.py   # target offers vs live offers -> minimal cancel/place plan
    loop.py        # tick loop; dry-run and live modes
    journal.py     # JSONL append per tick: state, decisions, fills, errors
  backtest/
    data.py        # load candles/stats CSVs
    sim.py         # fill model + portfolio simulator (term locking, compounding)
    strategies.py  # candidate strategies incl. FRR baseline
    report.py      # APR (net), utilization, lock stats, worst month, plots-as-text
scripts/
  fetch_history.py     # (built by data agent)
  run_backtest.py      # grid over strategy params -> reports/backtest_*.md
  run_engine.py        # --dry-run | --live; --once | --daemon
  status.py            # one-shot account + market snapshot for the user
tests/                 # pytest; ALL network mocked (autouse fixture blocks sockets)
```

## Resilience boundary (principle 2/3/5)

Every REST call goes through `boundary.call(spec, ...)` where spec declares:
- `kind`: read | write
- `idempotent`: bool — cancel-offer yes; place-offer NO
- `retry`: transient errors (timeouts, 5xx, connection reset, 429-with-backoff) retried
  with exp backoff ONLY if idempotent or read. Semantic errors (rejected params,
  insufficient balance, invalid key) never retried — raised as `SemanticError`.
- `critical`: bool — failures of critical writes (cancel during risk-off) alert loudly
  (journal ERROR + stderr + nonzero exit in --once mode) and are reconciled next tick.
- Place-offer failure handling: no blind retry (non-idempotent). Next tick's
  reconcile re-derives desired offers from scratch — self-healing by design.

## Engine tick (default every 5 min; config)

1. `state.py`: GET wallets, active offers, active credits/loans → AccountState;
   run identity check vs exchange wallet total.
2. `public.py`: ticker (FRR), book P0, recent trades → MarketState (+ rolling
   percentiles from journal history).
3. `strategy.decide(market, account, cfg) -> [TargetOffer(rate, period, amount)]`
   Pure function. No IO. Unit-tested heavily.
4. `reconcile.py`: diff live offers vs targets with tolerance (don't churn offers for
   <5% rate moves); emit cancels then places. Cap: ≤ N mutations/tick.
5. `journal.py`: append full snapshot + plan + results.

Dry-run mode = steps 1–3 + journal, mutations logged but not sent.

## Strategy v1 skeleton (parameters set by backtest, not by vibes)

- Split available USD into K tranches (respect 150 USD min per offer).
- Regime signal: rolling percentile of daily rate (e.g. 30d window of 1h candles) +
  distance of spot vs FRR.
- Term ladder: low regime → short periods (2d) placed near top-of-book ask to stay
  lent; high regime → escalate rate AND period (30/60/120d) to lock spikes.
  Also consider *hitting* rich long-period bids directly (taker) when bid APR net of
  fee ≥ lock threshold — observed today: 120d bid at ≈11% gross.
- Stale offers repriced after T hours unfilled.
- All thresholds in config; backtest grid decides defaults.

## Testing rules (principle 4)

- autouse fixture monkeypatches transport's session/socket — any test reaching real
  network fails the suite.
- No real .env in tests; fixtures provide fake keys.
- Backtest is deterministic (seeded) and runs offline from CSVs.

## Deployment target (phase 2, after local validation)

AWS Lightsail, systemd service, journal shipped to disk; secrets via .env outside git.
Multi-tenant phase later: strategy layer is already pure (decide() takes state, returns
targets) so per-account executors can share one strategy process.

## Coexistence & capital budget (verified live 2026-07-05)

The real account has ~4,012 USD in funding managed OUTSIDE this engine (legacy
bot/manual; observed: funding USD balance 4,340.85 vs available 328.68). Therefore:

- **Offer ownership**: the engine journals every offer id it creates and only ever
  cancels ids it owns. `cancel_all_offers` MUST NOT be used by the engine (it exists
  in private.py for completeness/manual ops only). Foreign offers and credits are
  reported in state but never mutated.
- **Capital budget**: config `capital_budget` caps total engine-managed capital
  (own open offers + own filled credits). The engine lends at most
  `min(available_balance, budget_headroom)` per tick. Scaling 328 → 250k is a config
  change gated on user review, not a code change.

## Live-test guardrails (authorized by user 2026-07-04)

- Live mutations only after: read-only reconciliation passes against real account, AND
  dry-run produces sane plans for ≥2 consecutive ticks.
- Test caps: ≤300 USD per offer, period=2d only, ≤2 concurrent offers, then scale up
  only after user reviews morning report. Caps enforced in code (config
  `live_test_mode=true`), not by operator discipline.
