"""Sub-project N — 凍結參數。

spec: docs/superpowers/specs/2026-08-09-liquidity-sweep-orderflow-design.md (v1.0)

【本檔在第一次跑回測後不得修改】。任何改動都必須在 verdict 揭露並重新宣告
N_TRIALS_DECLARED（spec §9）。其他模組一律 import 本檔，不得複製常數。

本案是【預註冊】研究：所有門檻在看到結果前寫定。pilot 資料不得用於選參數。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as mcfg  # noqa: E402

# ── 時間窗（沿用 M 的切點以利對照；spec §3.5，硬編、禁 datetime.now）──────
EVENT_START_MS = mcfg.EVENT_START_MS
IS_END_MS      = mcfg.IS_END_MS
OOS_START_MS   = mcfg.OOS_START_MS
EVENT_END_MS   = mcfg.EVENT_END_MS

# ── 成本（沿用 repo 慣例，不自編；spec §6.6）──────────────────────────────
TAKER       = mcfg.TAKER          # 0.00045
SLIP        = mcfg.SLIP           # 0.0001
STRESS_MULT = 1.5

# ── 由成本導出的兩個距離常數（spec §6.2、§6.4）────────────────────────────
# round-trip taker = 2 x (TAKER + SLIP) = 0.0011
ROUND_TRIP    = 2 * (TAKER + SLIP)
SL_BUFFER     = 1.0 * ROUND_TRIP   # 0.0011：SL 置於針尖外緣，緩衝不小於單趟往返成本
MIN_RISK_FRAC = 2.0 * ROUND_TRIP   # 0.0022：低於 1x 時成本即吃掉 1R，2x 留最小餘裕

# ── 偵測與回測（spec §4、§6）──────────────────────────────────────────────
PIVOT_L        = 10          # primary；20 為宣告的消融檔位
PIVOT_L_GRID   = (10, 20)
INTERVALS      = ("1h", "15m")
BAR_MS         = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
N_POOLS        = 20          # TP 搜尋窗：最近 N 個已確認的對側池
MAX_HOLD_BARS  = 100

# ── 進場臂（spec §5、§9）──────────────────────────────────────────────────
# 修訂 A3（2026-08-09）：原 ABS 幾乎恆真（pilot 覆蓋率 96.5%），追加無自由
# 參數的強化臂 ABSs（池上方主動買 + 整棒淨流為賣 = 真有大單吸收）。
# 原臂保留不動，primary 維持 sweep+ABS。詳見 spec §5.2.1。
ARMS = ("sweep_only", "sweep+ABS", "sweep+ABSs",
        "sweep+DIV", "sweep+ABS+DIV", "sweep+ABSs+DIV")
TP_RULES = ("nearest_unswept", "nearest_unswept_rr1")

# ── 統計（spec §7）────────────────────────────────────────────────────────
SEED           = mcfg.SEED        # 20260806，跨子專案沿用同一根種子
BOOTSTRAP_B    = 10000
CONTROL_K      = 5
CONTROL_DELTA_MIN = MAX_HOLD_BARS + 1
CONTROL_DELTA_MAX = 300
EXPOSURE_BAND  = (0.95, 1.05)     # spec §7.3：出帶即機械宣告該格作廢

# ── 試驗數（spec §9）──────────────────────────────────────────────────────
N_OBSERVABLE_TRIALS = len(ARMS) * len(INTERVALS) * len(PIVOT_L_GRID) * len(TP_RULES)
N_TRIALS_DECLARED   = N_OBSERVABLE_TRIALS + 8   # A3 後：48 + 8 = 56

# ── primary cell（完整凍結，無留白；spec §9）──────────────────────────────
PRIMARY = {
    "interval": "1h",
    "pivot_l": 10,
    "arm": "sweep+ABS",
    "tp_rule": "nearest_unswept",
}

# ── 路徑 ──────────────────────────────────────────────────────────────────
CACHE_DIR_N      = "data/cache/sweep_n"        # 事件表、特徵、gate 輸出
CACHE_DIR_TRADES = "data/cache/orderflow_n"    # aggTrades 原始（n_data.py 寫入）
CACHE_DIR_KLINE  = mcfg.CACHE_DIR              # 沿用 M 的 K 線快取（唯讀）

assert N_OBSERVABLE_TRIALS == 48
assert N_TRIALS_DECLARED == 56
assert abs(SL_BUFFER - 0.0011) < 1e-12
assert abs(MIN_RISK_FRAC - 0.0022) < 1e-12
