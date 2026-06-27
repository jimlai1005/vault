"""Requester-pays S3 reader for the official Hyperliquid fills archive
(s3://hl-mainnet-node-data/node_fills_by_block). All GETs pass RequestPayer
='requester' (the caller's AWS account is billed). Records are filtered to the
target address set while streaming so we never materialize the firehose.

The exact on-disk key layout + compression are confirmed on first authenticated
access via `list_keys`; `parse_records`, `filter_fills`, and `_decompress` are
pure and fully unit-tested, so only the listing/decoding glue (which key prefix,
which compression) depends on seeing the live bucket."""
from __future__ import annotations

import gzip
import json
from typing import Iterable

from .source import SemanticError, TransientError, resilient_read

BUCKET = "hl-mainnet-node-data"
FILLS_PREFIX = "node_fills_by_block/"


def _decompress(blob: bytes) -> bytes:
    """Archive objects may be lz4-framed, gzip, or plain newline JSON."""
    if blob[:4] == b"\x04\x22\x4d\x18":  # lz4 frame magic
        import lz4.frame

        return lz4.frame.decompress(blob)
    if blob[:2] == b"\x1f\x8b":  # gzip magic
        return gzip.decompress(blob)
    return blob


def parse_records(decompressed: bytes) -> list[dict]:
    """Parse newline-delimited JSON blocks from node_fills_by_block.

    Real format: each line is a block envelope
        {"local_time","block_time","block_number","events": [[addr, fill], ...]}
    where each event is a 2-element [address, fill_dict] pair. We flatten to a
    list of fill dicts with the address injected as `user`. Older/alternate
    layouts ({"fills":[...]} or bare list/dict lines) are handled defensively."""
    out: list[dict] = []
    for line in decompressed.splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if isinstance(obj, dict) and "events" in obj:
            for ev in obj["events"] or []:
                if isinstance(ev, list) and len(ev) == 2 and isinstance(ev[1], dict):
                    addr, fill = ev
                    rec = dict(fill)
                    rec["user"] = addr
                    out.append(rec)
        elif isinstance(obj, dict) and "fills" in obj:
            out.extend(obj["fills"])
        elif isinstance(obj, list):
            out.extend(obj)
        else:
            out.append(obj)
    return out


def _addr(rec: dict) -> str | None:
    return rec.get("user") or rec.get("address") or rec.get("ethAddress")


def filter_fills(records: Iterable[dict], addresses: set[str]) -> list[dict]:
    """Keep only fills belonging to the target address set (lowercased match)."""
    want = {a.lower() for a in addresses}
    out = []
    for rec in records:
        a = _addr(rec)
        if a is not None and a.lower() in want:
            out.append(rec)
    return out


class S3FillSource:
    def __init__(self, client=None):
        if client is None:
            import boto3

            client = boto3.client("s3")
        self._s3 = client

    def list_keys(self, prefix: str) -> list[str]:
        def call():
            keys: list[str] = []
            token = None
            while True:
                kw = {"Bucket": BUCKET, "Prefix": prefix, "RequestPayer": "requester"}
                if token:
                    kw["ContinuationToken"] = token
                try:
                    resp = self._s3.list_objects_v2(**kw)
                except Exception as e:  # noqa: BLE001 — classify below
                    raise _classify(e)
                keys.extend(o["Key"] for o in resp.get("Contents", []))
                if not resp.get("IsTruncated"):
                    break
                token = resp.get("NextContinuationToken")
            return keys

        return resilient_read(call)

    def get_object(self, key: str) -> bytes:
        def call():
            try:
                resp = self._s3.get_object(
                    Bucket=BUCKET, Key=key, RequestPayer="requester"
                )
            except Exception as e:  # noqa: BLE001
                raise _classify(e)
            return _decompress(resp["Body"].read())

        return resilient_read(call)

    def fills_for(self, key: str, addresses: set[str]) -> list[dict]:
        records = parse_records(self.get_object(key))
        return filter_fills(records, addresses)


def _classify(exc: Exception) -> Exception:
    """Map a botocore exception to the resilience boundary's taxonomy."""
    name = type(exc).__name__
    msg = str(exc)
    transient = ("Throttl", "SlowDown", "RequestTimeout", "5", "ConnectionError")
    if any(t in name or t in msg for t in transient):
        return TransientError(msg)
    return SemanticError(msg)
