"""Resumable extractor for the Hyperliquid node_fills_by_block archive.

Downloads each hourly firehose file (requester-pays), filters to the
pre-screened candidate addresses, and appends their fills to per-day parquet
shards under data/cache/fills/. A checkpoint file records completed keys so the
job is safely resumable after interruption (the firehose is ~165GB / ~3h).

Usage:
    python scripts/pull_archive.py --start 20250727 --end 20260627 --keep 300

Requires AWS credentials in the environment (requester-pays bills the caller).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import boto3
import lz4.frame
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from hlvault.io.s3_archive import BUCKET, filter_fills, parse_records  # noqa: E402
from hlvault.ingest import fills_to_frame  # noqa: E402
from hlvault.prescreen import prescreen  # noqa: E402

CACHE = Path("data/cache/fills")
CKPT = Path("data/cache/_pulled_keys.txt")


def daterange(start: str, end: str):
    d = dt.datetime.strptime(start, "%Y%m%d").date()
    e = dt.datetime.strptime(end, "%Y%m%d").date()
    while d <= e:
        yield d
        d += dt.timedelta(days=1)


def load_candidates(keep: int) -> set[str]:
    lb = json.load(open("/tmp/hl_lb2.json"))["leaderboardRows"]
    return {a.lower() for a in prescreen(lb, keep=keep)}


def done_keys() -> set[str]:
    return set(CKPT.read_text().splitlines()) if CKPT.exists() else set()


def mark_done(key: str) -> None:
    CKPT.parent.mkdir(parents=True, exist_ok=True)
    with open(CKPT, "a") as f:
        f.write(key + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--keep", type=int, default=300)
    args = ap.parse_args()

    cands = load_candidates(args.keep)
    print(f"candidates: {len(cands)}", flush=True)
    s3 = boto3.client("s3")
    done = done_keys()
    CACHE.mkdir(parents=True, exist_ok=True)

    total_fills = 0
    for d in daterange(args.start, args.end):
        day = d.strftime("%Y%m%d")
        day_rows: list[dict] = []
        for hour in range(24):
            key = f"node_fills_by_block/hourly/{day}/{hour}.lz4"
            if key in done:
                continue
            try:
                raw = s3.get_object(Bucket=BUCKET, Key=key, RequestPayer="requester")[
                    "Body"
                ].read()
            except s3.exceptions.NoSuchKey:
                mark_done(key)
                continue
            except Exception as e:  # noqa: BLE001
                print(f"  skip {key}: {type(e).__name__} {e}", flush=True)
                continue
            recs = parse_records(lz4.frame.decompress(raw))
            day_rows.extend(filter_fills(recs, cands))
            mark_done(key)
        if day_rows:
            df = fills_to_frame(day_rows)
            df["user"] = [r.get("user") for r in day_rows]
            out = CACHE / f"{day}.parquet"
            if out.exists():
                df = pd.concat([pd.read_parquet(out), df], ignore_index=True)
            df.to_parquet(out)
            total_fills += len(day_rows)
            print(f"{day}: +{len(day_rows)} candidate fills "
                  f"(cum {total_fills})", flush=True)
    print(f"DONE. total candidate fills: {total_fills}", flush=True)


if __name__ == "__main__":
    main()
