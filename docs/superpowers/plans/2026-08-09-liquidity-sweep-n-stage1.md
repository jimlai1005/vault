# Sub-project N Stage 1 — 訂單流層與掃單偵測 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 sub-project N 的訂單流特徵層（逐棒 delta／CVD／事件級 `D_sweep`）與流動性掠奪事件偵測層，並通過 N-G0（跨源對帳）與 N-G1（無前視）兩道前置 gate。

**Architecture:** 兩層資料存取。**可預聚合的**（逐棒 delta、成交額、筆數）在每個 symbol-month 算一次落成小 sidecar；**不可預聚合的** `D_sweep`（依賴每個事件各自的池價位 `P`）用 `searchsorted` 對已排序的 `transact_time` 做 range query，實測 0.45 ms/事件。掃單偵測沿用 main 上已凍結的 `m_detect.find_pivots`（因果性已驗證，`confirm_t` 已是收盤時間）。

**Tech Stack:** Python 3.9 / numpy / pandas / pyarrow。`.venv/bin/python`、`.venv/bin/pytest`。資料為本機 parquet，除 Task 2 的 sidecar 建置外全程零網路。

---

## 本案定位與紅線（實作者必讀）

**這是預註冊研究。** 設計文件是 `docs/superpowers/specs/2026-08-09-liquidity-sweep-orderflow-design.md`（v1.0），**在看到任何回測結果之前已寫定**。因此：

- **不得**因為「跑出來不好看」而調整任何門檻、定義或判準。發現 spec 有錯 → **停下來回報**，由主對話決定是否修訂並在 verdict 揭露。
- **不得**用 pilot 資料（4 幣 × 6 月）選擇任何參數。pilot 的用途嚴格限定為解析正確性、對帳、無前視驗證。
- §5 的訂單流特徵**刻意無自由參數**（只取 `D_sweep` 的符號、CVD 只做比較）。**不要**「順手」加幅度門檻——每加一個都會把試驗數乘上去並抬高 `sr*`。

**絕對不可修改的檔案**（main 上已凍結、M 的可重現性基礎）：

```
scripts/m_config.py   scripts/m_data.py    scripts/m_detect.py    scripts/m_backtest.py
scripts/m_control.py  scripts/m_stats.py   scripts/m_gates.py     scripts/m_run_stage2.py
data/cache/harmonic_m/*    tests/test_m_*.py
```

本案只**新增** `scripts/n_*.py` 與 `tests/test_n_*.py`。

**每個 Task 完成後必須確認 M 的既有測試仍全綠**（`.venv/bin/pytest tests/test_m_*.py -q`，應為 74 passed）。

---

## 預先釘死的八項詮釋

實作中遇到本節已涵蓋的歧義，**照本節執行**；未涵蓋的歧義 → **停下來回報，不要自己選**。

| # | 議題 | 釘死的詮釋 |
|---|---|---|
| P1 | delta 的計價單位 | 一律 **USDT notional**（`price × quantity × sign`），使跨幣可比。不用 base 量。 |
| P2 | `sign` 的方向 | `is_buyer_maker = True` → 掛單方是買方 → **主動方是賣方** → `sign = −1`。已跨源對帳驗證（spec §3.2 事實 1）。 |
| P3 | 棒的歸屬 | 成交歸入 `bar = transact_time // BAR_MS` 的那根棒（左閉右開）。與 Binance kline 的 openTime 對齊。 |
| P4 | `D_sweep` 的價格條件 | 空方掃單取 `price ≥ P`（**含等號**）；多方取 `price ≤ P`。等號歸入「池上/池下」是保守方向（讓吸收更容易成立），一致套用於兩臂。 |
| P5 | 掃單的嚴格不等號 | `high[j] > P`（**嚴格**，等於不算掃）且 `close[j] < P`（**嚴格**，等於不算收回）。多方鏡像。 |
| P6 | 一棒掃到多個池 | 取**價格上離 `close[j]` 最近**的那個池。不挑選、不列舉。 |
| P7 | 缺 aggTrades 資料 | 該事件終局記 `nodata`、`R_net = 0`、**計入分母**，並計入 `n_dropped_nodata` 揭露。兩臂同規則。 |
| P8 | CVD 的起點 | 自該 symbol **可用 aggTrades 的最早棒**起累加。因 CVD 只做「兩個時點比大小」，起點的選擇不影響判定。起點須落檔記錄。 |

---

## File Structure

| 檔案 | 職責 |
|---|---|
| `scripts/n_config.py`（新） | spec §3–§9 的凍結常數。單一參數來源，其他模組一律 import，不得複製。 |
| `scripts/n_data.py`（**已存在**） | aggTrades 下載、checksum、header sniff、`signed_qty`／`trade_count`。**本 Stage 不修改**。 |
| `scripts/n_orderflow.py`（新） | 逐棒聚合（delta／notional／n_trades／CVD）落 sidecar；事件級 `D_sweep` range query。 |
| `scripts/n_sweep.py`（新） | 流動性池、未被掃過判定、掃單事件表組裝。 |
| `scripts/n_reconcile.py`（新） | **N-G0**：aggTrades 主動買量 vs kline `takerBuyVolume` 逐棒對帳。 |
| `tests/test_n_config.py`（新） | 凍結參數自洽。 |
| `tests/test_n_orderflow.py`（新） | 聚合正確性、`D_sweep` 只計池上方、缺值處理、**截斷式無前視**。 |
| `tests/test_n_sweep.py`（新） | 掃單定義邊界（等號不算）、未被掃過、同棒多池取最近。 |
| `tests/test_n_reconcile.py`（新） | 對帳函式（用合成資料，零網路）。 |

---

## Task 1: N 凍結參數

**Files:** Create `scripts/n_config.py`；Test `tests/test_n_config.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_n_config.py
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
    """spec §9：4 臂 x 2 interval x 2 L x 2 TP 規則 = 32；宣告 40。"""
    assert cfg.N_OBSERVABLE_TRIALS == 32
    assert cfg.N_TRIALS_DECLARED == 40
    assert len(cfg.ARMS) == 4


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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_config'`

- [ ] **Step 3: 實作**

```python
# scripts/n_config.py
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
ARMS = ("sweep_only", "sweep+ABS", "sweep+DIV", "sweep+ABS+DIV")
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
N_TRIALS_DECLARED   = N_OBSERVABLE_TRIALS + 8

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

assert N_OBSERVABLE_TRIALS == 32
assert N_TRIALS_DECLARED == 40
assert abs(SL_BUFFER - 0.0011) < 1e-12
assert abs(MIN_RISK_FRAC - 0.0022) < 1e-12
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_config.py -v`
Expected: PASS（8 passed）

- [ ] **Step 5: 確認 M 未受影響並 commit**

```bash
.venv/bin/pytest tests/test_m_config.py -q
git add scripts/n_config.py tests/test_n_config.py
git commit -m "feat(sweep-n): 凍結 N 的預註冊參數

時間切點與成本沿用 M；SL 緩衝(0.0011)與風險守門(0.0022)由 round-trip
taker 導出而非調校；試驗數 32 可觀察 + 8 揭露 = 40（spec §9）。"
```

---

## Task 2: 訂單流層（逐棒聚合 + 事件級 D_sweep + CVD）

**Files:** Create `scripts/n_orderflow.py`；Test `tests/test_n_orderflow.py`

**架構**（實測依據：BTC 最大月 5,772 萬列，載入 3.2s、聚合 5.9s、事件查詢 0.45 ms）：
- `build_bars()`：每 symbol-month 聚合一次 → `bars_{SYMBOL}_{interval}.parquet`（小檔）
- `sweep_delta()`：對已排序的 `transact_time` 做 `searchsorted` range query，現算

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_n_orderflow.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_orderflow as of

BAR = 3_600_000


def trades(rows):
    """rows: (transact_time, price, quantity, is_buyer_maker)"""
    a = pd.DataFrame(rows, columns=["transact_time", "price", "quantity",
                                    "is_buyer_maker"])
    a["agg_trade_id"] = np.arange(len(a))
    a["first_trade_id"] = np.arange(len(a))
    a["last_trade_id"] = np.arange(len(a))
    return a[["agg_trade_id", "price", "quantity", "first_trade_id",
              "last_trade_id", "transact_time", "is_buyer_maker"]]


def test_bar_aggregation_delta_sign():
    """P2：is_buyer_maker=True -> 主動方是賣方 -> delta 為負。"""
    df = trades([(0, 10.0, 3.0, False),      # 主動買 30
                 (1, 10.0, 1.0, True)])      # 主動賣 10
    b = of.build_bars(df, BAR)
    assert len(b) == 1
    assert b["delta"].iloc[0] == pytest.approx(20.0)
    assert b["notional"].iloc[0] == pytest.approx(40.0)


def test_bar_aggregation_uses_notional_not_base():
    """P1：一律 USDT notional，不是 base 量。"""
    df = trades([(0, 100.0, 2.0, False)])
    assert of.build_bars(df, BAR)["notional"].iloc[0] == pytest.approx(200.0)


def test_bar_assignment_is_left_closed():
    """P3：bar = transact_time // BAR_MS，左閉右開。"""
    df = trades([(BAR - 1, 10.0, 1.0, False), (BAR, 10.0, 1.0, False)])
    b = of.build_bars(df, BAR)
    assert list(b["t"]) == [0, BAR]


def test_trade_count_uses_id_range_not_row_count():
    """P：aggTrades 的行數不是成交筆數。"""
    df = trades([(0, 10.0, 1.0, False)])
    df.loc[0, "first_trade_id"] = 100
    df.loc[0, "last_trade_id"] = 109
    assert of.build_bars(df, BAR)["n_trades"].iloc[0] == 10


def test_cvd_is_cumulative_and_starts_at_first_bar():
    df = trades([(0, 10.0, 1.0, False), (BAR, 10.0, 3.0, True)])
    b = of.build_bars(df, BAR)
    assert list(b["cvd"]) == pytest.approx([10.0, -20.0])


def test_sweep_delta_counts_only_at_or_above_pool_for_bearish():
    """P4：空方掃單取 price >= P（含等號）。"""
    df = trades([(0, 9.0, 1.0, False),    # 池下，不算
                 (1, 10.0, 2.0, False),   # 等於池 -> 算（+20）
                 (2, 11.0, 1.0, True)])   # 池上主動賣 -> 算（-11）
    idx = of.build_index(df, BAR)
    d, v = of.sweep_delta(df, idx, bar_t=0, pool=10.0, direction=-1)
    assert d == pytest.approx(20.0 - 11.0)
    assert v == pytest.approx(20.0 + 11.0)


def test_sweep_delta_mirrors_for_bullish():
    df = trades([(0, 11.0, 1.0, False),   # 池上，不算
                 (1, 10.0, 2.0, True),    # 等於池 -> 算（-20）
                 (2, 9.0, 1.0, False)])   # 池下主動買 -> 算（+9）
    idx = of.build_index(df, BAR)
    d, v = of.sweep_delta(df, idx, bar_t=0, pool=10.0, direction=+1)
    assert d == pytest.approx(-20.0 + 9.0)


def test_sweep_delta_empty_bar_returns_nan():
    df = trades([(0, 10.0, 1.0, False)])
    idx = of.build_index(df, BAR)
    d, v = of.sweep_delta(df, idx, bar_t=5 * BAR, pool=10.0, direction=-1)
    assert np.isnan(d) and np.isnan(v)


def test_build_index_requires_sorted_time():
    df = trades([(BAR, 10.0, 1.0, False), (0, 10.0, 1.0, False)])
    with pytest.raises(ValueError):
        of.build_index(df, BAR)


@pytest.mark.parametrize("k", [3, 5, 8])
def test_no_lookahead_truncation(k):
    """截斷式斷言：只餵前 k 根棒的成交，第 k-1 根的聚合值必須不變。"""
    rows = [(i * BAR + 1, 10.0 + i, 1.0 + i, i % 2 == 0) for i in range(10)]
    full = of.build_bars(trades(rows), BAR)
    trunc = of.build_bars(trades(rows[:k]), BAR)
    for col in ("delta", "notional", "n_trades", "cvd"):
        assert trunc[col].iloc[-1] == pytest.approx(full[col].iloc[k - 1])
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_orderflow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_orderflow'`

- [ ] **Step 3: 實作**

```python
# scripts/n_orderflow.py
"""Sub-project N — 訂單流特徵層。spec §5。

兩層存取（實測：BTC 最大月 5,772 萬列，載入 3.2s、聚合 5.9s、事件查詢 0.45ms）：
  · 可預聚合的（delta / notional / n_trades / cvd）→ build_bars()，每 symbol-month
    算一次落 sidecar。
  · 不可預聚合的 D_sweep（依賴每事件各自的池價位 P）→ sweep_delta()，用
    searchsorted 對已排序的 transact_time 做 range query，現算。

全部計價一律 USDT notional（P1），符號約定見 n_data.signed_qty（P2）。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
import n_data as nd  # noqa: E402

CACHE_N = pathlib.Path(cfg.CACHE_DIR_N)


def build_bars(df, bar_ms):
    """aggTrades DataFrame → 逐棒聚合表（t, delta, notional, n_trades, cvd）。

    delta / notional 一律 USDT notional（P1）；bar = transact_time // bar_ms（P3）；
    n_trades 由 last_trade_id - first_trade_id + 1 還原（aggTrades 行數 != 筆數）。
    cvd 自本表第一根棒起累加（P8）。
    """
    if len(df) == 0:
        return pd.DataFrame(columns=["t", "delta", "notional", "n_trades", "cvd"])
    px = df["price"].to_numpy(dtype=float)
    q = df["quantity"].to_numpy(dtype=float)
    sgn = 1.0 - 2.0 * df["is_buyer_maker"].to_numpy()      # True -> -1（P2）
    t = df["transact_time"].to_numpy(dtype=np.int64)
    g = pd.DataFrame({
        "t": (t // int(bar_ms)) * int(bar_ms),
        "delta": q * px * sgn,
        "notional": q * px,
        "n_trades": nd.trade_count(df),
    }).groupby("t", sort=True).sum().reset_index()
    g["cvd"] = g["delta"].cumsum()
    return g


def build_index(df, bar_ms):
    """棒邊界索引，供 sweep_delta 做 O(log n) range query。

    回傳 dict(bar_t -> (start, end))；要求 transact_time 已排序（實測 Binance
    的 dump 已排序，但不假設——不符即拋錯，不靜默排序）。
    """
    t = df["transact_time"].to_numpy(dtype=np.int64)
    if len(t) > 1 and not bool((np.diff(t) >= 0).all()):
        raise ValueError("transact_time 未排序；searchsorted 前提不成立")
    if len(t) == 0:
        return {}
    b0 = int(t[0]) // int(bar_ms)
    b1 = int(t[-1]) // int(bar_ms)
    edges = (np.arange(b0, b1 + 2, dtype=np.int64)) * int(bar_ms)
    pos = np.searchsorted(t, edges, side="left")
    return {int(edges[i]): (int(pos[i]), int(pos[i + 1]))
            for i in range(len(edges) - 1)}


def sweep_delta(df, index, bar_t, pool, direction):
    """單一事件的 (D_sweep, V_sweep)。spec §5.1。

    direction = -1（空方掃單，池為 pivot high）→ 只計 price >= pool（P4）
    direction = +1（多方掃單，池為 pivot low） → 只計 price <= pool
    棒內無成交 → (nan, nan)，呼叫端據此記 nodata（P7）。
    """
    rng = index.get(int(bar_t))
    if rng is None or rng[1] <= rng[0]:
        return float("nan"), float("nan")
    a, b = rng
    px = df["price"].to_numpy(dtype=float)[a:b]
    q = df["quantity"].to_numpy(dtype=float)[a:b]
    sgn = 1.0 - 2.0 * df["is_buyer_maker"].to_numpy()[a:b]
    m = (px >= float(pool)) if direction == -1 else (px <= float(pool))
    if not m.any():
        return 0.0, 0.0
    notional = q[m] * px[m]
    return float((notional * sgn[m]).sum()), float(notional.sum())


def bars_path(symbol, interval):
    return CACHE_N / f"bars_{symbol}_{interval}.parquet"


def load_bars_of(symbol, interval):
    """已落檔的逐棒訂單流表。"""
    return pd.read_parquet(bars_path(symbol, interval))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_orderflow.py -v`
Expected: PASS（12 passed，含 3 個 parametrize 的無前視斷言）

- [ ] **Step 5: 在真實 pilot 資料上抽驗（實跑）**

```bash
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "scripts")
import n_data as nd, n_orderflow as of, n_config as cfg
df = nd.load_month("GALAUSDT", 2023, 3)
b = of.build_bars(df, cfg.BAR_MS["1h"])
print("棒數:", len(b), "| 應為該月小時數 744")
print(b.head(3).to_string(index=False))
idx = of.build_index(df, cfg.BAR_MS["1h"])
print("索引棒數:", len(idx))
import numpy as np
t0 = int(b["t"].iloc[100])
d, v = of.sweep_delta(df, idx, t0, float(df["price"].median()), -1)
print(f"抽驗 sweep_delta: D={d:,.0f} V={v:,.0f}  |D|<=V: {abs(d) <= v + 1e-6}")
PY
```

Expected: 棒數 744；`|D| <= V` 為 True（帶號和的絕對值不可能超過總量——這是恆等式檢查）。

- [ ] **Step 6: Commit**

```bash
.venv/bin/pytest tests/test_m_*.py -q
git add scripts/n_orderflow.py tests/test_n_orderflow.py
git commit -m "feat(sweep-n): 訂單流特徵層（逐棒 delta/CVD + 事件級 D_sweep）

可預聚合的逐棒量落 sidecar；D_sweep 依賴每事件各自的池價位故用
searchsorted range query 現算（實測 0.45ms/事件）。build_index 不假設
輸入已排序——不符即拋錯，不靜默排序。含截斷式無前視斷言。"
```

---

## Task 3: N-G0 跨源對帳

**Files:** Create `scripts/n_reconcile.py`；Test `tests/test_n_reconcile.py`

spec §8 的 N-G0：抽樣 ≥ 200 個 symbol-hour，aggTrades 主動買量與 kline `takerBuyVolume` 相對誤差 < 1e-9。**不過即全案作廢。**

- [ ] **Step 1: 寫失敗測試（純合成，零網路）**

```python
# tests/test_n_reconcile.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_reconcile as rec

BAR = 3_600_000


def mk_trades(rows):
    a = pd.DataFrame(rows, columns=["transact_time", "price", "quantity",
                                    "is_buyer_maker"])
    a["agg_trade_id"] = np.arange(len(a))
    a["first_trade_id"] = np.arange(len(a))
    a["last_trade_id"] = np.arange(len(a))
    return a


def test_taker_buy_base_matches_when_consistent():
    """主動買量 = is_buyer_maker 為 False 的 quantity 總和（base 量，非 notional）。"""
    tr = mk_trades([(0, 10.0, 3.0, False), (1, 10.0, 5.0, True),
                    (BAR, 10.0, 2.0, False)])
    tbv = pd.DataFrame({"t": [0, BAR], "tbv": [3.0, 2.0]})
    out = rec.reconcile(tr, tbv, BAR)
    assert out["n_bars"] == 2
    assert out["max_rel_err"] == pytest.approx(0.0)
    assert out["pass"] is True


def test_detects_mismatch():
    tr = mk_trades([(0, 10.0, 3.0, False)])
    tbv = pd.DataFrame({"t": [0], "tbv": [4.0]})
    out = rec.reconcile(tr, tbv, BAR)
    assert out["pass"] is False
    assert out["max_rel_err"] > 0.1


def test_only_compares_overlapping_bars():
    """kline 有、aggTrades 沒有的棒不列入比較（避免月界假警報）。"""
    tr = mk_trades([(0, 10.0, 3.0, False)])
    tbv = pd.DataFrame({"t": [0, BAR, 2 * BAR], "tbv": [3.0, 9.9, 9.9]})
    out = rec.reconcile(tr, tbv, BAR)
    assert out["n_bars"] == 1 and out["pass"] is True


def test_zero_volume_bar_uses_absolute_tolerance():
    """兩邊皆為 0 的棒不得因除以 0 而判失敗。"""
    tr = mk_trades([(0, 10.0, 0.0, False)])
    tbv = pd.DataFrame({"t": [0], "tbv": [0.0]})
    assert rec.reconcile(tr, tbv, BAR)["pass"] is True
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_reconcile'`

- [ ] **Step 3: 實作**

```python
# scripts/n_reconcile.py
"""Sub-project N — N-G0 跨源對帳。spec §8。

aggTrades 重建的「主動買量」必須與 Binance kline 的 takerBuyVolume 逐棒相符。
這是動用 aggTrades 前的唯一保險：符號約定錯了、棒歸屬錯了、或解析錯位，
都會在這裡爆掉。不過即全案作廢（spec §8.1）。

注意：kline 的 takerBuyVolume 是【base 量】，不是 notional——此處刻意用
base 量比對，才能與 Binance 的定義對齊（與 §5 特徵用 notional 是兩回事）。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402

REL_TOL = 1e-9
ABS_TOL = 1e-6


def taker_buy_base_by_bar(trades, bar_ms):
    """aggTrades → 每棒的主動買【base 量】。is_buyer_maker=False 才是主動買。"""
    m = ~trades["is_buyer_maker"].to_numpy()
    t = trades["transact_time"].to_numpy(dtype=np.int64)
    return (pd.DataFrame({"t": (t[m] // int(bar_ms)) * int(bar_ms),
                          "tbv_agg": trades["quantity"].to_numpy(dtype=float)[m]})
            .groupby("t", sort=True).sum().reset_index())


def reconcile(trades, kline_taker, bar_ms):
    """回傳 dict(n_bars, max_rel_err, worst_t, pass)。只比對兩邊都有的棒。"""
    a = taker_buy_base_by_bar(trades, bar_ms)
    b = kline_taker.rename(columns={"tbv": "tbv_kline"})[["t", "tbv_kline"]]
    j = a.merge(b, on="t", how="inner")
    if len(j) == 0:
        return {"n_bars": 0, "max_rel_err": float("nan"),
                "worst_t": None, "pass": False}
    x = j["tbv_agg"].to_numpy(dtype=float)
    y = j["tbv_kline"].to_numpy(dtype=float)
    denom = np.maximum(np.abs(y), ABS_TOL)
    rel = np.abs(x - y) / denom
    rel = np.where((np.abs(x) <= ABS_TOL) & (np.abs(y) <= ABS_TOL), 0.0, rel)
    k = int(np.argmax(rel))
    return {"n_bars": int(len(j)), "max_rel_err": float(rel[k]),
            "worst_t": int(j["t"].iloc[k]), "pass": bool(rel.max() <= REL_TOL)}
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_reconcile.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 在真實 pilot 資料上執行 N-G0（實跑，這是 gate）**

```bash
.venv/bin/python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "scripts")
import n_config as cfg, n_data as nd, n_reconcile as rec
sys.path.insert(0, "scripts")
import m2_data  # 若不存在則改用下方 fallback
PY
```

> **注意**：kline 的 taker sidecar（`{SYM}_1h_taker.parquet`）是 M2 分支的產物，
> **本分支可能沒有**。若 `data/cache/harmonic_m/{SYM}_1h_taker.parquet` 不存在，
> 停下來回報——N-G0 需要它，主對話會決定是補抓還是改用 aggTrades 自我一致性檢查。
> **不要自己改對帳判準去繞過。**

```bash
ls data/cache/harmonic_m/GALAUSDT_1h_taker.parquet && \
.venv/bin/python - <<'PY'
import json, pathlib, sys
sys.path.insert(0, "scripts")
import pandas as pd, n_config as cfg, n_data as nd, n_reconcile as rec
out = {}
for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "GALAUSDT"):
    tk = pd.read_parquet(f"data/cache/harmonic_m/{sym}_1h_taker.parquet")
    tr = nd.load_month(sym, 2023, 3)
    out[sym] = rec.reconcile(tr, tk, cfg.BAR_MS["1h"])
    print(sym, out[sym], flush=True)
n = sum(v["n_bars"] for v in out.values())
ok = all(v["pass"] for v in out.values())
print(f"N-G0: 對帳 {n} 個 symbol-hour（需 >= 200），全通過 = {ok}")
pathlib.Path(cfg.CACHE_DIR_N).mkdir(parents=True, exist_ok=True)
pathlib.Path(cfg.CACHE_DIR_N, "g0_reconcile.json").write_text(
    json.dumps(out, indent=1))
PY
```

Expected: 每個 symbol 的 `max_rel_err` 為 0.0（或 < 1e-9）、`pass: True`，
合計 `n_bars >= 200`，最後印出 `全通過 = True`。

**任一 symbol 不過 → 停下來回報 BLOCKED，不要繼續 Task 4。**

- [ ] **Step 6: Commit**

```bash
git add scripts/n_reconcile.py tests/test_n_reconcile.py
git commit -m "feat(sweep-n): N-G0 跨源對帳（aggTrades vs kline takerBuyVolume）

用 base 量比對以對齊 Binance 的定義；只比兩邊都有的棒（避免月界假警報）；
兩邊皆 0 的棒改用絕對容差。不過即全案作廢（spec §8.1）。"
```

---

## Task 4: 掃單事件偵測

**Files:** Create `scripts/n_sweep.py`；Test `tests/test_n_sweep.py`

沿用 main 上已凍結的 `m_detect.find_pivots(df, L)`——回傳 `list[Pivot]`，
欄位 `idx, kind("high"|"low"), price, t, confirm_idx, confirm_t`，
其中 **`confirm_t` 已是收盤時間**（`t + bar_ms − 1`），可直接與 `as_of` 比較。

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_n_sweep.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_sweep as sw

BAR = 3_600_000


def bars(rows):
    """rows: (o, h, l, c)。t 由 0 起每根 BAR。"""
    a = np.array(rows, dtype=float)
    return pd.DataFrame({"t": np.arange(len(rows), dtype=np.int64) * BAR,
                         "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]})


def test_unswept_true_until_exceeded():
    h = np.array([10.0, 9.0, 9.5, 9.9])
    assert sw.is_unswept(h, pool=10.0, i=0, j=4, kind="high") is True
    h2 = np.array([10.0, 9.0, 10.1, 9.9])
    assert sw.is_unswept(h2, pool=10.0, i=0, j=4, kind="high") is False


def test_unswept_excludes_forming_bar_itself():
    """池所在那根棒不算把自己掃掉。"""
    h = np.array([10.0, 9.0])
    assert sw.is_unswept(h, pool=10.0, i=0, j=2, kind="high") is True


def test_sweep_requires_strict_penetration_and_strict_reclaim():
    """P5：high[j] > P 嚴格；close[j] < P 嚴格。等號一律不算。"""
    assert sw.is_sweep(high=10.1, low=9.0, close=9.9, pool=10.0, direction=-1) is True
    assert sw.is_sweep(high=10.0, low=9.0, close=9.9, pool=10.0, direction=-1) is False
    assert sw.is_sweep(high=10.1, low=9.0, close=10.0, pool=10.0, direction=-1) is False


def test_sweep_mirrors_for_bullish():
    assert sw.is_sweep(high=11.0, low=9.9, close=10.1, pool=10.0, direction=+1) is True
    assert sw.is_sweep(high=11.0, low=10.0, close=10.1, pool=10.0, direction=+1) is False
    assert sw.is_sweep(high=11.0, low=9.9, close=10.0, pool=10.0, direction=+1) is False


def test_pick_nearest_pool_to_close():
    """P6：一棒掃到多個池時取價格上離 close 最近的。"""
    assert sw.pick_pool([10.0, 10.5, 11.0], close=9.8) == 10.0
    assert sw.pick_pool([10.0, 10.5, 11.0], close=10.9) == 11.0


def test_build_events_finds_bearish_sweep():
    """pivot high 於 idx=2（L=2 -> confirm 於 idx=4），idx=7 掃它。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 5
    ev = sw.build_events(bars(rows), symbol="X", interval="1h", L=2)
    assert len(ev) >= 1
    e = ev[ev["j"] == 7].iloc[0]
    assert e["direction"] == -1
    assert e["pool"] == pytest.approx(12.0)
    assert e["as_of"] == 7 * BAR + BAR - 1


def test_build_events_respects_pool_confirmation_time():
    """未確認的 pivot 不得使用：L=2 的 pivot 要到 idx+2 收盤才確認。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 12.5, 8.5, 9)] \
        + [(9, 9.5, 8.5, 9)] * 6
    ev = sw.build_events(bars(rows), symbol="X", interval="1h", L=2)
    assert (ev["j"] > 4).all() if len(ev) else True


@pytest.mark.parametrize("k", [9, 11, 13])
def test_no_lookahead_truncation(k):
    """N-G1：只餵前 k 根，前 k 根內偵測到的事件必須與全量一致。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 6
    b = bars(rows)
    full = sw.build_events(b, "X", "1h", L=2)
    trunc = sw.build_events(b.iloc[:k].copy(), "X", "1h", L=2)
    keep = full[full["j"] < k - 2]          # 尾端 L 根的 pivot 尚未確認，不比較
    for _, r in keep.iterrows():
        m = trunc[trunc["j"] == r["j"]]
        assert len(m) == 1, f"截斷後遺失事件 j={r['j']}"
        assert m.iloc[0]["pool"] == pytest.approx(r["pool"])
        assert m.iloc[0]["direction"] == r["direction"]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_sweep.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_sweep'`

- [ ] **Step 3: 實作**

```python
# scripts/n_sweep.py
"""Sub-project N — 流動性掠奪事件偵測。spec §4。

沿用 main 上已凍結的 m_detect.find_pivots（因果性已驗證，confirm_t 已是收盤時間）。
本模組不重新實作 pivot。

事件定義（spec §4.3，無自由參數）：
  空方掃單（做空）：∃ 未被掃過的 pivot high P，confirm_t(P) <= close_t(j-1)
                    且 high[j] > P（嚴格）且 close[j] < P（嚴格）
  多方掃單（做多）：鏡像
  as_of = close_t(j)；最早可成交時點為 bar j+1 的開盤。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_detect as det  # noqa: E402


def is_unswept(extremes, pool, i, j, kind):
    """池 P（形成於 bar i）在 bar j 之前是否未被掃過。spec §4.2。

    extremes：kind="high" 傳 high 陣列、"low" 傳 low 陣列。
    區間為 (i, j) 開區間——池所在那根不算把自己掃掉。
    """
    seg = np.asarray(extremes, dtype=float)[i + 1:j]
    if seg.size == 0:
        return True
    return bool((seg <= pool).all() if kind == "high" else (seg >= pool).all())


def is_sweep(high, low, close, pool, direction):
    """單棒是否構成掃單。P5：兩個條件皆為嚴格不等號。"""
    if direction == -1:
        return bool(high > pool and close < pool)
    return bool(low < pool and close > pool)


def pick_pool(pools, close):
    """P6：一棒掃到多個池時，取價格上離 close 最近的那個。"""
    p = np.asarray(pools, dtype=float)
    return float(p[int(np.argmin(np.abs(p - float(close))))])


def build_events(bars_df, symbol, interval, L):
    """K 線 → 掃單事件表。

    欄位：event_id, symbol, interval, j, t_j, as_of, direction, pool,
          pool_idx, pool_t, sweep_high, sweep_low, close_j, penetration
    penetration = |針尖 − 池| / 池，供強制揭露用（不參與判定）。
    """
    df = bars_df.reset_index(drop=True)
    t = df["t"].to_numpy(dtype=np.int64)
    hi = df["h"].to_numpy(dtype=float)
    lo = df["l"].to_numpy(dtype=float)
    cl = df["c"].to_numpy(dtype=float)
    n = len(df)
    bar_ms = int(t[1] - t[0]) if n > 1 else 1
    close_t = t + bar_ms - 1

    pivs = det.find_pivots(df, L)
    highs = [(p.idx, float(p.price), int(p.confirm_t)) for p in pivs
             if p.kind == "high"]
    lows = [(p.idx, float(p.price), int(p.confirm_t)) for p in pivs
            if p.kind == "low"]

    rows = []
    for j in range(n):
        prev_close_t = int(close_t[j - 1]) if j > 0 else -1
        for kind, pool_list, direction, ext in (
                ("high", highs, -1, hi), ("low", lows, +1, lo)):
            cands = [(i, price) for (i, price, ct) in pool_list
                     if ct <= prev_close_t and i < j
                     and is_sweep(hi[j], lo[j], cl[j], price, direction)
                     and is_unswept(ext, price, i, j, kind)]
            if not cands:
                continue
            pool = pick_pool([p for _, p in cands], cl[j])
            pool_idx = [i for i, p in cands if p == pool][0]
            tip = hi[j] if direction == -1 else lo[j]
            rows.append(dict(
                event_id=f"{symbol}|{interval}|{L}|{int(t[j])}|{direction}",
                symbol=symbol, interval=interval, j=j, t_j=int(t[j]),
                as_of=int(close_t[j]), direction=direction, pool=pool,
                pool_idx=int(pool_idx), pool_t=int(t[pool_idx]),
                sweep_high=float(hi[j]), sweep_low=float(lo[j]),
                close_j=float(cl[j]),
                penetration=abs(tip - pool) / abs(pool) if pool else np.nan))
    cols = ["event_id", "symbol", "interval", "j", "t_j", "as_of", "direction",
            "pool", "pool_idx", "pool_t", "sweep_high", "sweep_low",
            "close_j", "penetration"]
    return pd.DataFrame(rows, columns=cols)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_sweep.py -v`
Expected: PASS（10 passed，含 3 個 parametrize 的無前視斷言）

- [ ] **Step 5: 在真實資料上抽驗事件率（實跑）**

```bash
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "scripts")
import pandas as pd, n_config as cfg, n_sweep as sw, m_backtest as bt
b = bt.load_bars("BTCUSDT", "1h")
df = pd.DataFrame({k: b[k] for k in ("t", "o", "h", "l", "c")})
ev = sw.build_events(df, "BTCUSDT", "1h", cfg.PIVOT_L)
print(f"BTCUSDT 1h 全期: {len(df):,} 根棒 -> {len(ev):,} 個掃單事件 "
      f"（{len(ev)/len(df):.2%}）")
print("方向分布:", ev["direction"].value_counts().to_dict())
print("穿刺幅度分位:", ev["penetration"].describe(
    percentiles=[.1, .5, .9]).round(6).to_dict())
PY
```

Expected: 事件率落在合理範圍（若 > 20% 或 < 0.1%，停下來回報——可能是定義實作錯誤）。
**穿刺幅度分布只做揭露，不得據此加門檻**（spec §4.3）。

- [ ] **Step 6: Commit**

```bash
.venv/bin/pytest tests/test_m_*.py -q
git add scripts/n_sweep.py tests/test_n_sweep.py
git commit -m "feat(sweep-n): 流動性掠奪事件偵測

沿用 m_detect.find_pivots（因果性已驗證）。掃單的兩個條件皆為嚴格不等號；
池須於 j-1 收盤前確認；一棒多池取離 close 最近者。穿刺幅度只落檔揭露、
不設門檻（spec §4.3：門檻是自由旋鈕）。含 N-G1 截斷式斷言。"
```

---

## Stage 1 驗收（主對話親跑，不採信 subagent 回報）

```bash
# 1. N 的新測試全綠
.venv/bin/pytest tests/test_n_*.py -q

# 2. M 的既有測試全綠（凍結產物未受污染）
.venv/bin/pytest tests/test_m_*.py -q          # Expected: 74 passed

# 3. M 的凍結檔零改動
git diff --stat main -- scripts/m_*.py tests/test_m_*.py
# Expected：空輸出

# 4. N-G0 通過且對帳棒數 >= 200
python -c "import json;d=json.load(open('data/cache/sweep_n/g0_reconcile.json'));\
print({k:(v['n_bars'],v['max_rel_err'],v['pass']) for k,v in d.items()});\
print('N-G0 PASS =', all(v['pass'] for v in d.values()), \
'| 總棒數 =', sum(v['n_bars'] for v in d.values()))"
```

**Stage 1 完成的判準**：上列四項全部有輸出證據，且 N-G0 為 PASS。
Stage 2（回測引擎、對照組、gate 引擎）另立計畫。
