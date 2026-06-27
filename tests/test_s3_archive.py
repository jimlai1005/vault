import gzip
import json

import lz4.frame

from hlvault.io.s3_archive import (
    S3FillSource,
    filter_fills,
    parse_records,
)


def test_parse_records_handles_lines_envelopes_and_lists():
    lines = [
        json.dumps({"user": "0xa", "coin": "BTC", "sz": "1"}),
        json.dumps({"fills": [{"user": "0xb"}, {"user": "0xc"}]}),
        json.dumps([{"user": "0xd"}]),
    ]
    blob = ("\n".join(lines)).encode()
    recs = parse_records(blob)
    assert [r["user"] for r in recs] == ["0xa", "0xb", "0xc", "0xd"]


def test_filter_fills_case_insensitive():
    recs = [{"user": "0xAbC"}, {"user": "0xZZ"}, {"address": "0xabc"}]
    out = filter_fills(recs, {"0xabc"})
    assert len(out) == 2


def test_decompress_lz4_and_gzip_paths():
    payload = json.dumps({"user": "0xa"}).encode()
    from hlvault.io.s3_archive import _decompress

    assert _decompress(lz4.frame.compress(payload)) == payload
    assert _decompress(gzip.compress(payload)) == payload
    assert _decompress(payload) == payload


class _FakeS3:
    """Mimics the boto3 S3 client surface used by S3FillSource (no network)."""

    def __init__(self, objects):
        self.objects = objects
        self.calls = []

    def list_objects_v2(self, **kw):
        self.calls.append(("list", kw))
        contents = [{"Key": k} for k in self.objects]
        return {"Contents": contents, "IsTruncated": False}

    def get_object(self, **kw):
        self.calls.append(("get", kw))
        body = lz4.frame.compress(self.objects[kw["Key"]])

        class _B:
            def read(self_inner):
                return body

        return {"Body": _B()}


def test_s3_source_uses_requester_pays_and_filters():
    blob = (
        json.dumps({"user": "0xwant", "coin": "BTC"})
        + "\n"
        + json.dumps({"user": "0xskip"})
    ).encode()
    fake = _FakeS3({"node_fills_by_block/2026/06/01.lz4": blob})
    src = S3FillSource(client=fake)
    keys = src.list_keys("node_fills_by_block/")
    out = src.fills_for(keys[0], {"0xwant"})
    assert [r["user"] for r in out] == ["0xwant"]
    # every S3 call must carry RequestPayer=requester (we pay, must authenticate)
    assert all(kw.get("RequestPayer") == "requester" for _, kw in fake.calls)
