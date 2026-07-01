from hlvault.gridbot.allocator import allocate_capital


def test_allocates_more_to_lower_volatility_coins():
    weights = allocate_capital({"A": 0.01, "B": 0.05}, total_capital=1000.0, max_alloc_pct=1.0)
    assert weights["A"] > weights["B"]
    assert abs(sum(weights.values()) - 1000.0) < 1e-6


def test_caps_any_single_coin_allocation():
    weights = allocate_capital({"A": 0.001, "B": 1.0, "C": 1.0}, total_capital=1000.0, max_alloc_pct=0.4)
    assert weights["A"] <= 400.0 + 1e-6
    assert abs(sum(weights.values()) - 1000.0) < 1e-6


def test_empty_universe_returns_empty():
    assert allocate_capital({}, total_capital=1000.0) == {}
