import pytest

from hlvault.io.source import SemanticError, TransientError, resilient_read


def test_retries_transient_then_succeeds():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("timeout")
        return "ok"

    assert resilient_read(fn, max_attempts=5, base_delay=0) == "ok"
    assert calls["n"] == 3


def test_semantic_not_retried():
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        raise SemanticError("bad address")

    with pytest.raises(SemanticError):
        resilient_read(fn, max_attempts=5, base_delay=0)
    assert calls["n"] == 1
