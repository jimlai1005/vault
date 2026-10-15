import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import m_config as mcfg
import n_config as cfg


def test_inherits_m_frozen_time_window():
    """時間切點沿用 M，以利對照；且一律硬編（spec §3.5，禁 datetime.now）。"""
    assert cfg.EVENT_START_MS == mcfg.EVENT_START_MS
    assert cfg.IS_END_MS == mcfg.IS_END_MS
    assert cfg.OOS_START_MS == mcfg.OOS_START_MS
    assert cfg.EVENT_END_MS == mcfg.EVENT_END_MS


def test_costs_match_repo_convention():
    assert cfg.TAKER == mcfg.TAKER and cfg.SLIP == mcfg.SLIP
    assert cfg.STRESS_MULT == 1.5


def test_frozen_design_constants():
    assert cfg.PIVOT_L == 10
    assert cfg.N_POOLS == 20
    assert cfg.MAX_HOLD_BARS == 100
    assert cfg.CONTROL_K == 5


def test_derived_constants_have_documented_derivation():
    """SL 緩衝 = 1x round-trip taker；風險守門 = 2x。由成本常數導出。"""
    rt = 2 * (cfg.TAKER + cfg.SLIP)
    assert abs(cfg.SL_BUFFER - rt) < 1e-12
    assert abs(cfg.MIN_RISK_FRAC - 2 * rt) < 1e-12
    assert abs(cfg.SL_BUFFER - 0.0011) < 1e-12
    assert abs(cfg.MIN_RISK_FRAC - 0.0022) < 1e-12


def test_trial_count_selfconsistent():
    """spec §9 + 修訂 A3：6 臂 x 2 interval x 2 L x 2 TP 規則 = 48；宣告 56。"""
    assert cfg.N_OBSERVABLE_TRIALS == 48
    assert cfg.N_TRIALS_DECLARED == 56
    assert len(cfg.ARMS) == 6
    # A3 只【追加】強化臂，原臂與 primary 一律不動
    assert "sweep+ABS" in cfg.ARMS and "sweep+ABSs" in cfg.ARMS
    assert cfg.PRIMARY["arm"] == "sweep+ABS"


def test_exposure_band_is_preregistered():
    """spec §7.3：曝險比落在 [0.95, 1.05] 之外的格機械宣告作廢。"""
    assert cfg.EXPOSURE_BAND == (0.95, 1.05)


def test_primary_cell_fully_frozen():
    p = cfg.PRIMARY
    assert p == {"interval": "1h", "pivot_l": 10, "arm": "sweep+ABS",
                 "tp_rule": "nearest_unswept"}


def test_cache_dirs_distinct_from_m():
    assert cfg.CACHE_DIR_N != mcfg.CACHE_DIR
    assert cfg.CACHE_DIR_TRADES != mcfg.CACHE_DIR
