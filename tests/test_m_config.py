import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import m_config as cfg


def test_pattern_set_is_eight_and_excludes_five_zero():
    # spec §4.2 裁決表：5-0 已剔除
    assert len(cfg.PATTERNS) == 8
    assert "five_zero" not in cfg.PATTERNS
    assert set(cfg.PATTERNS) == {
        "gartley", "bat", "alt_bat", "butterfly",
        "crab", "deep_crab", "shark", "cypher",
    }


def test_ratio_tables_cover_every_pattern_exactly_once():
    # cypher 走自己的表，其餘 7 種走四欄主表（spec §4.2）
    assert set(cfg.HARMONIC_RATIOS) == set(cfg.PATTERNS) - {"cypher"}
    assert set(cfg.CYPHER_RATIOS) == {"ab_over_xa", "xc_over_xa", "cd_over_xc"}
    for key, row in cfg.HARMONIC_RATIOS.items():
        assert len(row) == 4, key
    # spec §4.2：Shark 無 AB/XA 約束
    assert cfg.HARMONIC_RATIOS["shark"][0] is None


def test_sl_level_table_covers_every_pattern():
    assert set(cfg.SL_LEVEL_OVER_XA) == set(cfg.PATTERNS)
    assert cfg.OBSERVED_SL_PATTERNS == {"cypher", "bat", "shark", "butterfly", "deep_crab"}


def test_trial_counts():
    # spec §6.4：(8 形態 + 合併層 + selected 層) x 4 x 3 x 2 x 2
    assert cfg.N_OBSERVABLE_TRIALS == (len(cfg.PATTERNS) + 2) * 4 * 3 * 2 * 2 == 480
    assert cfg.N_TRIALS_DECLARED == 487


def test_windows_are_hardcoded_timestamps():
    # spec §6.7：兩端都硬編，禁 datetime.now()
    assert cfg.FETCH_START_MS < cfg.EVENT_START_MS < cfg.IS_END_MS < cfg.EVENT_END_MS
    assert cfg.OOS_START_MS == cfg.IS_END_MS + 1


def test_primary_is_fully_specified():
    # spec §6.3：interval 是 v2 遺漏的維度
    assert cfg.PRIMARY == {
        "interval": "1h", "tol": 0.05, "entry_mode": "A",
        "exit_variant": "tp1_full", "pattern_layer": "merged",
    }


def test_costs_match_repo_convention():
    assert (cfg.TAKER, cfg.MAKER, cfg.SLIP) == (0.00045, 0.00015, 0.0001)
    assert cfg.STRESS_MULT == 1.5
