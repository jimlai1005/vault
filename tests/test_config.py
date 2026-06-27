from hlvault.config import Settings


def test_defaults():
    s = Settings()
    assert s.universe_size == 300
    assert 6 <= s.min_history_months <= 12
    assert s.top_n == 30
    assert 0 < s.kelly_fraction <= 1
