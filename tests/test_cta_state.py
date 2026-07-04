from hlvault.cta.state import default_state, load_state, save_state


def test_default_state_shape():
    assert default_state() == {
        "halted": False,
        "peak_equity": 0.0,
        "_alerted_this_halt": False,
        "_flatten_complete": False,
        "last_rebalance_ms": 0,
        "entries": {},
    }


def test_load_missing_file_returns_default(tmp_path):
    assert load_state(tmp_path / "nope.json") == default_state()


def test_save_then_load_roundtrip(tmp_path):
    p = tmp_path / "s.json"
    s = default_state()
    s["peak_equity"] = 1234.5
    s["entries"] = {"BTC": {"dir": -1, "entry_px": 65000.0, "stop": 68000.0,
                            "entry_ms": 1720000000000}}
    save_state(p, s)
    assert load_state(p) == s
