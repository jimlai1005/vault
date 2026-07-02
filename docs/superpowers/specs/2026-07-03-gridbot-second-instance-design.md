# Sub-project D — Gridbot Multi-Instance + Second Deployment

**Date:** 2026-07-03
**Status:** Design approved (decision delegated to Claude as project decider)
**Depends on:** `reports/strategy-direction-2026-07-03.md` (why this direction)

## Executive summary

Make `hlvault.gridbot` instance-aware (parametrized env file + state file),
then deploy a **second live instance** on the idle ex-momentum wallet
(`$1,000` USDC) trading a **backtest-selected coin set disjoint from
instance 1's HYPE/BTC/ETH**. Same engine, same risk policy (20% MDD halt,
per-coin stop-loss + cooldown), more markets, more capital working.

## Goals / Non-goals

**Goals**
- One gridbot codebase, N independent live instances: per-instance env file,
  state file, and log identity. Zero behavior change for instance 1 beyond a
  restart.
- Structural fix for the env-collision bug class already hit by momentum:
  gridbot's config switches from `load_dotenv()` (writes shared `os.environ`)
  to `dotenv_values()` (isolated dict) — same fix momentum's config received
  in commit `d33a991`, applied to gridbot.
- Data-driven coin selection for instance 2 with an explicit go/no-go:
  candidates are liquid HL perps excluding HYPE/BTC/ETH; each is run through
  the existing `hlvault.gridbot.backtest` on up to 2 years of hourly candles
  with the same vol-adaptive sizing the live engine uses; select the top ≤3 by
  Sharpe among those with **positive net PnL and backtest MDD within the 20%
  budget**. If fewer than 2 coins qualify → do not deploy; write the verdict
  and stop (same anti-p-hacking stance as sub-projects A/C — no threshold
  tuning until something passes).
- One-time funding move: the wallet's $1,000 sits in the perp account;
  gridbot's (deliberately, post-incident) equity basis is spot USDC +
  position economics. A small deploy-time script transfers perp → spot via
  the SDK's class-transfer call, check-before-transfer (idempotent by
  construction: skip if spot already funded).

**Non-goals**
- No strategy-logic changes to the grid mechanic itself (spacing, TP pairing,
  stop-loss, allocator all untouched).
- No changes to `hlvault.momentum` (stays dormant) beyond none at all.
- No new alerting infra (instance 2 reuses the Telegram notifier config in
  its own env file; gridbot itself doesn't gain Telegram in this sub-project
  — its existing local logging + halt-flag behavior is unchanged).

## Design

### 1. Instance parametrization (`hlvault/gridbot/config.py`)

- Env file path: `GRIDBOT_ENV_FILE` process environment variable, default
  `.env.gridbot` (backward compatible — instance 1 needs no env change).
- Config reads via `dotenv_values(path)` into a private dict (mirroring
  momentum's config), never touching `os.environ`. `WALLET_PRIVATE_KEY` /
  `WALLET_ADDRESS` move to the same isolated-dict read.
- `INSTANCE` name derives from the env file stem (`.env.gridbot` → `gridbot`,
  `.env.gridbot2` → `gridbot2`); `STATE_FILE` becomes
  `data/cache/{INSTANCE}_state.json`. Instance 1's existing
  `gridbot_state.json` filename is preserved by that rule automatically.
- Logger name / log lines pick up the instance name for disambiguation.

### 2. Coin selection driver (`scripts/select_gridbot2_coins.py`)

- Candidates (liquid HL perps, ex-instance-1): SOL, XRP, DOGE, BNB, LINK,
  LTC, AVAX, SUI, AAVE, UNI, CRV, TON, TAO, PENDLE.
- For each: fetch up to 730 days of 1h candles (`hlvault.prices.get_candles`),
  compute the same vol-adaptive step (`volatility.adaptive_step_pct`) and
  per-coin budget the live engine would use, run
  `hlvault.gridbot.backtest.run_backtest`, record net PnL, Sharpe, MDD,
  stop-outs.
- Verdict: top ≤3 by Sharpe among {PnL > 0, MDD within −20% of allocated
  budget}; ≥2 required to deploy. Report written to
  `reports/gridbot2-coin-selection.md` (committed).

### 3. Funding transfer script (`scripts/fund_gridbot2_spot.py`)

- Reads instance-2 env file; checks spot USDC balance; if below target and
  perp withdrawable covers it, calls the SDK's `usd_class_transfer` for the
  shortfall; re-reads and prints both balances. Refuses to run if
  `LIVE_TRADING` is not set in the env file (sanity that the right file is
  being pointed at). Manual-run, one-time.

### 4. Instance 2 config + launch

- `.env.gridbot2` (gitignored — add to `.gitignore`): ex-momentum wallet
  creds, `ALLOCATED_CAPITAL=1000`, `MAX_DRAWDOWN_PCT=0.20`, `LIVE_TRADING`
  false until dry-run passes, `COIN_UNIVERSE` = selected coins.
- Local launch (matching how instance 1 actually runs today, a background
  `python -m hlvault.gridbot.live` process): same command with
  `GRIDBOT_ENV_FILE=.env.gridbot2`. `deploy/hl-gridbot2.service` +
  `deploy/setup-gridbot2.sh` mirrored from instance 1's for future server
  use (sets `Environment=GRIDBOT_ENV_FILE=...`).
- Rollout order: land code → run tests → **restart instance 1** (state file
  + exchange reconciliation make this safe; verify `--status` after) → run
  coin selection → if GO: fund spot, dry-run instance 2, flip live.

## Testing

- Existing gridbot tests must pass unchanged (instance 1 default path).
- New: config honors `GRIDBOT_ENV_FILE` (monkeypatched env var + tmp env
  file → correct values, correct derived `STATE_FILE` name); both gridbot
  and momentum configs importable in one process with both real env files
  present, no cross-contamination (regression for the `d33a991` bug class).
- No test touches network/real env files (existing autouse fixture).

## Risks

- **2-day live sample is short.** Mitigated by the mechanic's independent
  10-month/$585k evidence and by unchanged hard risk controls; instance 2
  adds market diversification rather than concentration.
- **Grid bleeds in sustained crashes.** Unchanged stop-loss + cooldown +
  portfolio breaker; coin selection filters out chronic downtrenders by
  requiring positive backtest PnL including their crash windows.
- **Restarting instance 1.** State persists to JSON and open orders/lots are
  reconciled against the exchange each cycle; a brief stop is routine.
