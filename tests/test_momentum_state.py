from hlvault.momentum.state import default_state, load_state, save_state


def test_default_state_shape():
    s = default_state()
    assert s == {"halted": False, "peak_equity": 0.0, "last_rebalance_ms": 0,
                "_alerted_this_halt": False, "_flatten_complete": False}


def test_load_missing_file_returns_default(tmp_path):
    s = load_state(tmp_path / "nope.json")
    assert s == default_state()


def test_save_then_load_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    s = default_state()
    s["peak_equity"] = 1234.5
    save_state(path, s)
    assert load_state(path) == s
