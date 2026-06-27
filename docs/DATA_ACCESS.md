# Data access — how the go/no-go backtest gets its history

The analytic pipeline is complete and tested. The only thing it needs to run a
real out-of-sample verdict is **6–12 months of fill history** for the candidate
traders. We chose the **official Hyperliquid S3 archive** as the source.

## What you need to provide (one-time)

The archive bucket `s3://hl-mainnet-node-data/` is **requester-pays** — AWS bills
*your* account for the GET/egress, so the reader must authenticate as you.

Provide AWS credentials in any standard way the SDK picks up automatically:

```bash
# option 1: env vars (simplest for a one-off run)
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-1   # or your region

# option 2: a named profile
aws configure         # then: export AWS_PROFILE=yourprofile
```

A read-only IAM user with `s3:GetObject` + `s3:ListBucket` (and the implicit
requester-pays acknowledgement) is sufficient. **No write permissions needed.**

## Cost control (already built in)

`node_fills_by_block` is the whole-exchange firehose. To avoid pulling hundreds
of GB we **pre-screen** the 39.5k-row leaderboard down to a few hundred
candidates first (`hlvault.prescreen`), using the per-address allTime ROI /
volume already in the leaderboard payload, then deep-pull only those. Expected
egress is single-digit dollars. Pulled objects are cached to parquet so re-runs
are free.

## What happens once credentials are present

1. Pre-screen leaderboard → candidate set.
2. `S3FillSource.list_keys` confirms the live key layout/compression.
3. Deep-pull + cache fills for candidates; reconstruct equity curves.
4. Sample-length gate → metrics → alpha/beta → selection → HRP weights.
5. Walk-forward OOS backtest → `reports/oos-verdict.md` with **GO / NO-GO**.

Step 5 is the gate: sub-project B (the live multi-trader vault execution engine)
proceeds only on a GO.
