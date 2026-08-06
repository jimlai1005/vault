"""Sub-project M — 凍結參數。

spec: docs/superpowers/specs/2026-08-06-harmonic-pattern-design.md (v3.1)

【本檔在第一次跑回測後不得修改】。任何改動都必須在 verdict 揭露並重新宣告
N_TRIALS_DECLARED（spec §6.7）。其他模組一律 import 本檔，不得複製常數。
"""
from datetime import datetime, timezone

# ── 形態集合（spec §4.2；5-0 已剔除，見裁決表）────────────────────────────
PATTERNS = ("gartley", "bat", "alt_bat", "butterfly",
            "crab", "deep_crab", "shark", "cypher")

# 四欄主表：(AB/XA, BC/AB, CD/BC, AD/XA)。單點目標寫成 (v, v) 由容差層展開；
# None = 該形態無此約束。cypher 不走本表。
HARMONIC_RATIOS = {
    "gartley":   ((0.618, 0.618), (0.382, 0.886), (1.13,  1.618), (0.786, 0.786)),
    "bat":       ((0.382, 0.500), (0.382, 0.886), (1.618, 2.618), (0.886, 0.886)),
    "alt_bat":   ((0.382, 0.382), (0.382, 0.886), (2.0,   3.618), (1.13,  1.13)),
    "butterfly": ((0.786, 0.786), (0.382, 0.886), (1.618, 2.618), (1.27,  1.27)),
    "crab":      ((0.382, 0.618), (0.382, 0.886), (2.24,  3.618), (1.618, 1.618)),
    "deep_crab": ((0.886, 0.886), (0.382, 0.886), (2.24,  3.618), (1.618, 1.618)),
    "shark":     (None,           (1.13,  1.618), (1.618, 2.24),  (0.886, 1.13)),
}

# Cypher 用自己的基準（BC 對 XA、D 對 XC）。塞進上表必錯（spec §4.2）。
CYPHER_RATIOS = {
    "ab_over_xa": (0.382, 0.618),
    "xc_over_xa": (1.272, 1.414),
    "cd_over_xc": (0.786, 0.786),
}

# 各形態的名目 AD/XA 上界，供 SL fallback 規則使用（cypher 為推導值）
NOMINAL_AD_UPPER = {
    "gartley": 0.786, "bat": 0.886, "alt_bat": 1.13, "butterfly": 1.27,
    "crab": 1.618, "deep_crab": 1.618, "shark": 1.13, "cypher": 0.728,
}

# ── SL 形態常數檔位（spec §4.5.2）────────────────────────────────────────
# 5 個來自 fixture 觀測，3 個由 fallback 規則推導。
SL_LEVEL_OVER_XA = {
    "cypher": 1.0, "bat": 1.13, "shark": 1.272, "butterfly": 1.618, "deep_crab": 2.0,
    "gartley": 1.0, "alt_bat": 1.272, "crab": 2.0,
}
OBSERVED_SL_PATTERNS = frozenset({"cypher", "bat", "shark", "butterfly", "deep_crab"})
SL_LADDER = (1.0, 1.13, 1.272, 1.618, 2.0)

# ── TP 係數（spec §4.5.3）────────────────────────────────────────────────
TP_FACTORS = (0.382, 0.618)
TP_FACTORS_SHARK = (0.500, 0.886)

# ── 容差（spec §4.4）─────────────────────────────────────────────────────
TOL = 0.05
TOL_AD_XA = 0.03
TOL_GRID = (0.03, 0.05, 0.08, 0.10)
TOL_AD_RATIO = 0.6                      # TOL_AD_XA = TOL_AD_RATIO * TOL

# ── 偵測與回測（spec §4.1、§4.5）─────────────────────────────────────────
PIVOT_LENGTHS = (5, 10, 20, 40)
INTERVALS = ("15m", "1h", "4h")
TTL_BARS = 30
MAX_HOLD_BARS = 100

# ── 時間窗（spec §6.7：兩端都硬編，禁 datetime.now()）────────────────────
def _ms(s: str) -> int:
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)

FETCH_START_MS = _ms("2020-01-01T00:00:00")     # PIT 篩選需要 trailing 窗
EVENT_START_MS = _ms("2020-07-01T00:00:00")     # 事件與統計的起點
IS_END_MS      = _ms("2023-12-31T23:59:59")
OOS_START_MS   = IS_END_MS + 1
EVENT_END_MS   = _ms("2026-06-30T23:59:59")
FETCH_END_MS   = EVENT_END_MS

# ── 幣種宇宙（spec §7.1）─────────────────────────────────────────────────
UNIVERSE_MIN_QUOTE_VOL = 50e6
UNIVERSE_MIN_LISTED_DAYS = 180
UNIVERSE_TOP_N = 30
UNIVERSE_FIRST_QUARTER = (2020, 3)
UNIVERSE_LAST_QUARTER = (2026, 2)

# ── 成本（spec §5.2；沿用 repo 慣例，不自編）─────────────────────────────
TAKER = 0.00045          # scripts/scalp_fee_check.py:18
MAKER = 0.00015          # scripts/scalp_fee_check.py:19
SLIP = 0.0001            # scripts/cta_l_stage1.py:68，僅 taker 腿支付
STRESS_MULT = 1.5
RISK_PER_TRADE = 0.01

# ── 統計（spec §6.1、§6.4）───────────────────────────────────────────────
SEED = 20260806
BOOTSTRAP_B = 10000
BOOTSTRAP_EXPECTED_BLOCK = 20
CONTROL_K = 5
CONTROL_DELTA_MIN = TTL_BARS + MAX_HOLD_BARS + 1     # 131
CONTROL_DELTA_MAX = 300
N_OBSERVABLE_TRIALS = (len(PATTERNS) + 2) * 4 * 3 * 2 * 2      # 480
N_TRIALS_DECLARED = N_OBSERVABLE_TRIALS + 2 + 2 + 2 + 1        # 487

# ── primary 設定（spec §6.3：完整凍結，無留白）───────────────────────────
PRIMARY = {
    "interval": "1h",
    "tol": 0.05,
    "entry_mode": "A",
    "exit_variant": "tp1_full",
    "pattern_layer": "merged",
}

# ── 快取路徑 ─────────────────────────────────────────────────────────────
CACHE_DIR = "data/cache/harmonic_m"

assert set(SL_LEVEL_OVER_XA) == set(PATTERNS)
assert set(HARMONIC_RATIOS) == set(PATTERNS) - {"cypher"}
assert N_TRIALS_DECLARED == 487
