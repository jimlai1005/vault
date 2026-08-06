# Sub-project M Stage 1（資料層 + 偵測器 + 事件表）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建出零 look-ahead 的諧波形態偵測器，產出形態事件表與形態普查報告，並讓 M-G0（基準忠實度）與 M-G1 偵測層（無前視）兩個前置 gate 全綠。

**Architecture:** 三個模組。`m_config.py` 是唯一的凍結參數來源（其他模組一律 import，不得複製常數）；`m_data.py` 負責 PIT 幣種宇宙與 Binance K 線快取；`m_detect.py` 把 K 線轉成事件表。回測與 gate 屬 Stage 2，本計畫不碰。

**Tech Stack:** Python 3、pandas、numpy、pyarrow（parquet）、pytest。用主 repo 的 `.venv`（`.venv/bin/pytest`）。

**Spec：** [`docs/superpowers/specs/2026-08-06-harmonic-pattern-design.md`](../specs/2026-08-06-harmonic-pattern-design.md)（v3.1）。本計畫的每個判準都以 spec 為準；**任何 spec 沒寫的參數選擇都是 bug，不要自行發明——回報並停下**。

**紅線：** 本 repo 管理實盤資金。本 Stage 全部是唯讀研究，**不得** import `src/hlvault/carry|gridbot|momentum`、不得載入任何 `.env`、不得呼叫任何會下單的函式。網路呼叫只允許 Binance 公開 REST 的 K 線端點與 Hyperliquid 的 `info` 唯讀端點。測試一律離線。

---

## File Structure

| 檔案 | 責任 |
|---|---|
| `scripts/m_config.py` | **唯一的凍結參數來源**。比例表、容差、pivot 尺度、TTL、MAX_HOLD、SL 檔位表、TP 係數、時間窗、成本、SEED、試驗數、primary 設定 |
| `scripts/m_data.py` | Binance K 線分頁抓取與 parquet 快取；PIT 季度輪換幣種宇宙 |
| `scripts/m_detect.py` | pivot 偵測 → 因果式交替正規化 → XABC 候選 → 比例過濾 → PRZ → 事件表 → 去重 |
| `scripts/m_census.py` | 形態普查：跑完偵測後輸出各形態的事件數、空交集率、多形態 XABC 率 |
| `tests/test_m_config.py` | 凍結參數的不變式（表形狀、鍵集合、試驗數乘積） |
| `tests/test_m_baseline_formula.py` | **M-G0 四項斷言**（由 `scripts/m_verify_baseline.py` 改寫而來，改為 import m_config） |
| `tests/test_m_pivots.py` | pivot 偵測與因果式交替正規化 |
| `tests/test_m_patterns.py` | 比例過濾、PRZ 交集、多形態共存 |
| `tests/test_m_dedup.py` | 連通分量去重與三段 tie-break |
| `tests/test_m_nolookahead.py` | **M-G1 偵測層**截斷式斷言 |

---

## Task 1: 凍結參數模組 `m_config.py`

**Files:**
- Create: `scripts/m_config.py`
- Test: `tests/test_m_config.py`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_m_config.py`：

```python
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
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_m_config.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'm_config'`

- [ ] **Step 3: 寫 `scripts/m_config.py`**

```python
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
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_config.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/m_config.py tests/test_m_config.py
git commit -m "feat(harmonic): sub-project M 凍結參數模組 m_config"
```

---

## Task 2: M-G0 基準忠實度測試（改寫參考實作）

**Files:**
- Create: `tests/test_m_baseline_formula.py`
- Modify: `scripts/m_verify_baseline.py`（改為 import `m_config`，刪除硬編的 `SL_LEVEL_OVER_XA`）

**背景：** `scripts/m_verify_baseline.py` 已實作 M-G0 的四項斷言且實跑 `exit=0`，但它硬編了 SL 表——spec §6.2 M-G0a 要求測試必須 `import m_config`，否則改動 `m_config` 的表測試照樣綠，regression guard 形同虛設。

- [ ] **Step 1: 先跑現有腳本，確認基線是綠的**

Run: `.venv/bin/python scripts/m_verify_baseline.py`
Expected: 最後一行 `M-G0 全部斷言: PASS`，exit code 0

- [ ] **Step 2: 讓 `m_verify_baseline.py` 改吃 m_config**

把檔案開頭的常數區塊（`SL_LEVEL_OVER_XA`、`OBSERVED`、`STD_F`、`SHARK_F`、`LADDER`、`NOMINAL_AD_UPPER`）整段刪除，換成：

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import m_config as cfg

SL_LEVEL_OVER_XA = cfg.SL_LEVEL_OVER_XA
OBSERVED = cfg.OBSERVED_SL_PATTERNS
STD_F, SHARK_F = cfg.TP_FACTORS, cfg.TP_FACTORS_SHARK
LADDER = list(cfg.SL_LADDER)
NOMINAL_AD_UPPER = cfg.NOMINAL_AD_UPPER
```

`LABEL_TO_KEY`（fixture 標籤 → 形態鍵，spec §6.2）留在腳本內不動。

- [ ] **Step 3: 重跑腳本確認仍然 PASS**

Run: `.venv/bin/python scripts/m_verify_baseline.py; echo "exit=$?"`
Expected: `M-G0 全部斷言: PASS` 與 `exit=0`

- [ ] **Step 4: 寫 regression guard 測試**

建立 `tests/test_m_baseline_formula.py`：

```python
"""M-G0 基準忠實度（spec §6.2）。四項斷言 a/b/c/d。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pytest

import m_config as cfg
import m_verify_baseline as mvb


def test_verify_baseline_reads_frozen_table_from_config(monkeypatch):
    """M-G0a 的 guard 必須真的綁在 m_config 上，不能是複製的常數。"""
    assert mvb.SL_LEVEL_OVER_XA is cfg.SL_LEVEL_OVER_XA


def test_all_assertions_pass():
    """M-G0 a/b/c/d 全過（main 回傳 0）。"""
    assert mvb.main() == 0


def test_mg0a_fails_when_frozen_table_is_tampered(monkeypatch):
    """改動凍結表必須讓 M-G0a 失敗——否則 regression guard 形同虛設。"""
    tampered = dict(cfg.SL_LEVEL_OVER_XA)
    tampered["bat"] = 1.0                      # 觀測值是 1.13
    monkeypatch.setattr(mvb, "SL_LEVEL_OVER_XA", tampered)
    assert mvb.main() != 0


@pytest.mark.parametrize("label,key", list(mvb.LABEL_TO_KEY.items()))
def test_fixture_labels_map_to_known_patterns(label, key):
    assert key in cfg.PATTERNS
```

- [ ] **Step 5: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_baseline_formula.py -q`
Expected: `8 passed`（3 個具名測試 + 5 個 parametrize case）

- [ ] **Step 6: Commit**

```bash
git add scripts/m_verify_baseline.py tests/test_m_baseline_formula.py
git commit -m "test(harmonic): M-G0 改為 import m_config，加 tamper guard"
```

---

## Task 3: K 線抓取與快取 `m_data.py`

**Files:**
- Create: `scripts/m_data.py`
- Test: `tests/test_m_data.py`

**背景：** 沿用 [`scripts/cta_proxy_pull_data.py:79`](../../../scripts/cta_proxy_pull_data.py) `pull_klines` 的分頁邏輯，但**終點必須傳入固定時間戳**——該檔的模組級 `NOW_MS = datetime.now(...)` 會讓右端點隨執行日漂移（spec §6.7、限制 M14）。

- [ ] **Step 1: 寫失敗的測試（純離線，注入假的抓取函式）**

建立 `tests/test_m_data.py`：

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd
import m_config as cfg
import m_data


def _fake_rows(start_ms, n, step_ms):
    """模仿 Binance kline 陣列：[open_time, o, h, l, c, vol, close_time, quote_vol, ...]"""
    return [[start_ms + i * step_ms, "1", "2", "0.5", "1.5", "10",
             start_ms + (i + 1) * step_ms - 1, "15", 3, "5", "7", "0"]
            for i in range(n)]


def test_pull_klines_paginates_and_respects_fixed_end(monkeypatch):
    step = 3_600_000
    start, end = cfg.FETCH_START_MS, cfg.FETCH_START_MS + step * 2500 - 1
    calls = []

    def fake_raw(symbol, interval, start_ms, end_ms, limit=1500):
        calls.append(start_ms)
        remaining = (end_ms - start_ms) // step + 1
        return _fake_rows(start_ms, min(limit, max(0, remaining)), step)

    monkeypatch.setattr(m_data, "_binance_klines_raw", fake_raw)
    df = m_data.pull_klines("BTCUSDT", "1h", start, end)

    assert len(calls) >= 2, "2500 根必須分頁"
    assert df["t"].min() == start
    assert df["t"].max() <= end, "不得抓取超過固定終點的資料"
    assert df["t"].is_monotonic_increasing and not df["t"].duplicated().any()
    assert list(df.columns) == ["t", "o", "h", "l", "c", "v", "qv"]


def test_pull_klines_never_calls_datetime_now():
    import inspect
    src = inspect.getsource(m_data)
    assert "datetime.now" not in src, "spec §6.7 禁止；右端點必須硬編"


def test_cache_roundtrip(tmp_path, monkeypatch):
    step = 3_600_000
    monkeypatch.setattr(m_data, "_binance_klines_raw",
                        lambda *a, **k: _fake_rows(cfg.FETCH_START_MS, 10, step))
    monkeypatch.setattr(m_data, "CACHE_DIR", tmp_path)
    a = m_data.load_klines("BTCUSDT", "1h", cfg.FETCH_START_MS,
                           cfg.FETCH_START_MS + step * 10 - 1)
    assert (tmp_path / "BTCUSDT_1h.parquet").exists()
    monkeypatch.setattr(m_data, "_binance_klines_raw",
                        lambda *a, **k: pytest.fail("快取命中時不得再打網路"))
    b = m_data.load_klines("BTCUSDT", "1h", cfg.FETCH_START_MS,
                           cfg.FETCH_START_MS + step * 10 - 1)
    pd.testing.assert_frame_equal(a, b)


import pytest  # noqa: E402  (fixture 用)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_m_data.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'm_data'`

- [ ] **Step 3: 實作抓取與快取層**

建立 `scripts/m_data.py`（本步只做抓取＋快取，PIT 宇宙在 Task 4）：

```python
"""Sub-project M — 資料層。spec §7。

【右端點硬編】：不得使用 datetime.now()（spec §6.7；2026-07-12 momentum 教訓：
端點差 9 天使兩年 Sharpe 從 0.57 掉到 0.18）。
"""
import pathlib
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402

BINANCE_FAPI = "https://fapi.binance.com/fapi/v1"
SLEEP = 0.25
CACHE_DIR = pathlib.Path(cfg.CACHE_DIR)
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
COLUMNS = ["t", "o", "h", "l", "c", "v", "qv"]


def _binance_klines_raw(symbol, interval, start_ms, end_ms, limit=1500):
    """單次呼叫。429/5xx 指數退避重試，語意錯誤不重試（工程原則 #2）。"""
    url = f"{BINANCE_FAPI}/klines"
    params = dict(symbol=symbol, interval=interval, startTime=int(start_ms),
                  endTime=int(end_ms), limit=limit)
    for attempt in range(5):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 418) or r.status_code >= 500:
            time.sleep(2 ** attempt)          # transient：退避重試
            continue
        raise RuntimeError(f"binance {r.status_code}: {r.text[:200]}")   # semantic：不重試
    raise RuntimeError(f"binance retries exhausted: {symbol} {interval}")


def _rows_to_df(rows):
    df = pd.DataFrame([[int(r[0]), float(r[1]), float(r[2]), float(r[3]),
                        float(r[4]), float(r[5]), float(r[7])] for r in rows],
                      columns=COLUMNS)
    return df


def pull_klines(symbol, interval, start_ms, end_ms):
    """分頁抓取 [start_ms, end_ms]。end_ms 必須由呼叫端傳入固定時間戳。"""
    step = INTERVAL_MS[interval]
    out, cursor = [], int(start_ms)
    while cursor <= end_ms:
        rows = _binance_klines_raw(symbol, interval, cursor, end_ms)
        if not rows:
            break
        df = _rows_to_df(rows)
        df = df[df["t"] <= end_ms]
        if df.empty:
            break
        out.append(df)
        last = int(df["t"].iloc[-1])
        if last < cursor:                      # 無限迴圈防護
            break
        cursor = last + step
        time.sleep(SLEEP)
    if not out:
        return pd.DataFrame(columns=COLUMNS)
    res = pd.concat(out, ignore_index=True).drop_duplicates("t").sort_values("t")
    return res.reset_index(drop=True)


def load_klines(symbol, interval, start_ms=None, end_ms=None):
    """快取優先。快取檔存在即直接讀，不打網路。"""
    start_ms = cfg.FETCH_START_MS if start_ms is None else start_ms
    end_ms = cfg.FETCH_END_MS if end_ms is None else end_ms
    path = pathlib.Path(CACHE_DIR) / f"{symbol}_{interval}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    df = pull_klines(symbol, interval, start_ms, end_ms)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_data.py -q`
Expected: `3 passed`

- [ ] **Step 5: 確認快取目錄已被 gitignore**

Run: `git check-ignore -v data/cache/harmonic_m/BTCUSDT_1h.parquet`
Expected: 命中 `.gitignore` 的 `data/cache/` 那一行。若未命中，**停下回報**，不要自行修改 `.gitignore`。

- [ ] **Step 6: Commit**

```bash
git add scripts/m_data.py tests/test_m_data.py
git commit -m "feat(harmonic): sub-project M K 線抓取與 parquet 快取層"
```

---

## Task 4: PIT 幣種宇宙

**Files:**
- Modify: `scripts/m_data.py`（附加 `build_pit_universe_m`）
- Modify: `tests/test_m_data.py`（附加測試）

**背景：** spec §7.1 明訂**複製 [`scripts/k_data_layer.py:157`](../../../scripts/k_data_layer.py) 的邏輯但不呼叫該函式**——它的門檻硬編（`min_volume=100e6`、`[:8]`）、季度迴圈止於 2026-Q1、且讀 `data/k_framework/klines/*_1d.csv.gz`。動手前先讀該函式一遍，確認邏輯理解正確。

- [ ] **Step 1: 寫失敗的測試**

在 `tests/test_m_data.py` 附加：

```python
def test_pit_universe_uses_only_prior_data(monkeypatch, tmp_path):
    """季度 Q 的幣單只能由 Q 開始【之前】的資料決定（spec §7.1）。"""
    step = cfg.INTERVAL_MS["1d"] if hasattr(cfg, "INTERVAL_MS") else 86_400_000
    q_start = m_data.quarter_start_ms(2021, 1)

    seen_max_t = []

    def fake_load(symbol, interval, start_ms=None, end_ms=None):
        assert interval == "1d"
        n = 400
        df = pd.DataFrame({
            "t": [q_start - (n - i) * step for i in range(n)],
            "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1.0,
            "qv": 1e8 if symbol == "AAAUSDT" else 1e6,     # BBB 流動性不足
        })
        # 塞入未來資料：若被使用，seen_max_t 會超過 q_start
        future = df.copy()
        future["t"] = future["t"] + n * step
        future["qv"] = 1e12
        out = pd.concat([df, future], ignore_index=True)
        seen_max_t.append(out["t"].max())
        return out

    monkeypatch.setattr(m_data, "load_klines", fake_load)
    uni = m_data.build_pit_universe_m(["AAAUSDT", "BBBUSDT"], quarters=[(2021, 1)])

    assert uni[(2021, 1)] == ["AAAUSDT"], "只有流動性達標的幣入選"
    assert max(seen_max_t) > q_start, "測試本身要餵入未來資料才有意義"


def test_pit_universe_quarters_extend_to_2026q2():
    qs = m_data.quarters(cfg.UNIVERSE_FIRST_QUARTER, cfg.UNIVERSE_LAST_QUARTER)
    assert qs[0] == (2020, 3)
    assert qs[-1] == (2026, 2), "OOS 尾端三個月必須有幣單（spec §7.1）"
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_m_data.py -q -k pit`
Expected: FAIL，`AttributeError: module 'm_data' has no attribute 'quarter_start_ms'`

- [ ] **Step 3: 實作 PIT 宇宙**

在 `scripts/m_data.py` 附加：

```python
def quarter_start_ms(year, q):
    month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
    from datetime import datetime, timezone
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def quarters(first, last):
    out, cur = [], first
    while cur <= last:
        out.append(cur)
        cur = (cur[0] + 1, 1) if cur[1] == 4 else (cur[0], cur[1] + 1)
    return out


def build_pit_universe_m(symbols, quarters=None):
    """Point-in-time 季度輪換幣種宇宙（spec §7.1）。

    複製 k_data_layer.build_pit_universe 的邏輯，但門檻參數化、季度延伸至
    2026-Q2、1d 資料由本模組自行抓取。

    每季只用【季度開始前】的資料：trailing 90 日中位 quote volume >= $50M
    且上市 >= 180 天，取 top 30。
    """
    qs = quarters if quarters is not None else globals()["quarters"](
        cfg.UNIVERSE_FIRST_QUARTER, cfg.UNIVERSE_LAST_QUARTER)
    day = 86_400_000
    universe = {}
    for (y, q) in qs:
        cutoff = quarter_start_ms(y, q)
        rows = []
        for sym in symbols:
            df = load_klines(sym, "1d")
            df = df[df["t"] < cutoff]                        # ← PIT 的核心：只看過去
            if df.empty:
                continue
            listed_days = (cutoff - int(df["t"].min())) / day
            if listed_days < cfg.UNIVERSE_MIN_LISTED_DAYS:
                continue
            trailing = df[df["t"] >= cutoff - 90 * day]
            if trailing.empty:
                continue
            med_qv = float(trailing["qv"].median())
            if med_qv < cfg.UNIVERSE_MIN_QUOTE_VOL:
                continue
            rows.append((sym, med_qv))
        rows.sort(key=lambda r: -r[1])
        universe[(y, q)] = [s for s, _ in rows[:cfg.UNIVERSE_TOP_N]]
    return universe
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_data.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/m_data.py tests/test_m_data.py
git commit -m "feat(harmonic): PIT 季度輪換幣種宇宙（門檻參數化、延伸至 2026-Q2）"
```

---

## Task 5: Pivot 偵測與因果式交替正規化

**Files:**
- Create: `scripts/m_detect.py`
- Test: `tests/test_m_pivots.py`

**背景：** spec §4.1.1 是整份 spec 最容易寫錯的一段。v2 的規則引入 look-ahead 而 mutation test 抓不到。**動手前把 spec §4.1 與 §4.1.1 讀完整**。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_m_pivots.py`：

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd
import m_detect


def _bars(highs, lows):
    n = len(highs)
    return pd.DataFrame({"t": [i * 3_600_000 for i in range(n)],
                         "o": lows, "h": highs, "l": lows, "c": highs,
                         "v": [1.0] * n, "qv": [1.0] * n})


def test_pivot_needs_full_window_on_both_sides():
    # L=2：索引 0,1 與 n-2,n-1 不得成為 pivot（spec §4.1 邊界）
    highs = [1, 2, 9, 2, 1, 2, 1]
    df = _bars(highs, [-h for h in highs])
    piv = m_detect.find_pivots(df, L=2)
    assert all(2 <= p.idx <= len(df) - 3 for p in piv)
    assert any(p.idx == 2 and p.kind == "high" for p in piv)


def test_pivot_confirm_time_is_L_bars_later():
    highs = [1, 2, 9, 2, 1, 2, 1]
    df = _bars(highs, [-h for h in highs])
    p = [x for x in m_detect.find_pivots(df, L=2) if x.idx == 2][0]
    assert p.confirm_idx == 4
    assert p.confirm_t == int(df["t"].iloc[4])


def test_ties_resolve_to_earliest_bar():
    highs = [1, 5, 2, 5, 1, 0, 1]        # 索引 1 與 3 同高
    df = _bars(highs, [-h for h in highs])
    piv = [p for p in m_detect.find_pivots(df, L=1) if p.kind == "high"]
    assert min(p.idx for p in piv) == 1


def test_closed_run_takes_extreme_open_run_takes_running_extreme():
    """spec §4.1.1：X/A/B 用【已封閉段】的極值，C 用【as_of 當下】的 running extreme。"""
    # 兩個連續 pivot high（索引 2 與 6，之間無 pivot low），再一個 pivot low（索引 9）
    highs = [0, 1, 5, 1, 0, 1, 8, 1, 0, 0, 1, 0]
    lows = [0, 0, 0, 0, 1, 0, 0, 0, 1, -5, 0, 0]
    df = _bars(highs, lows)
    seq_open = m_detect.normalize_alternating(df, L=1, as_of_idx=7)
    seq_closed = m_detect.normalize_alternating(df, L=1, as_of_idx=11)

    # as_of 在索引 7：該 high 段尚未封閉，running extreme 是 5（索引 2）
    open_highs = [p for p in seq_open if p.kind == "high"]
    assert open_highs[-1].idx == 2
    # as_of 在索引 11：段已封閉（索引 9 出現 pivot low），極值改為 8（索引 6）
    closed_highs = [p for p in seq_closed if p.kind == "high" and p.idx <= 6]
    assert closed_highs[-1].idx == 6


def test_sequence_strictly_alternates():
    highs = [0, 1, 5, 1, 0, 1, 8, 1, 0, 0, 1, 0]
    lows = [0, 0, 0, 0, 1, 0, 0, 0, 1, -5, 0, 0]
    seq = m_detect.normalize_alternating(_bars(highs, lows), L=1, as_of_idx=11)
    kinds = [p.kind for p in seq]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_m_pivots.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'm_detect'`

- [ ] **Step 3: 實作 pivot 與因果式正規化**

建立 `scripts/m_detect.py`：

```python
"""Sub-project M — 偵測器。spec §4。

【因果性】本模組的每一個輸出都只能由 close_time <= as_of 的 K 線算出。
spec §4.1.1 的合併規則是最容易寫錯的一段：v2 的版本因為需要知道「同型段何時
結束」而引入 look-ahead，且 M-G1 的斷言方向錯誤而抓不到。
"""
import pathlib
import sys
from dataclasses import dataclass

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402


@dataclass(frozen=True)
class Pivot:
    idx: int
    kind: str          # "high" | "low"
    price: float
    t: int
    confirm_idx: int
    confirm_t: int


def find_pivots(df, L):
    """spec §4.1：high[i] == max(high[i-L..i+L])，平手取最早；頭尾 L 根不判定。"""
    highs, lows, ts = df["h"].values, df["l"].values, df["t"].values
    n = len(df)
    out = []
    for i in range(L, n - L):
        win_h = highs[i - L:i + L + 1]
        if highs[i] == win_h.max() and highs[i] > highs[i - L:i].max(initial=float("-inf")):
            out.append(Pivot(i, "high", float(highs[i]), int(ts[i]),
                             i + L, int(ts[i + L])))
        win_l = lows[i - L:i + L + 1]
        if lows[i] == win_l.min() and lows[i] < lows[i - L:i].min(initial=float("inf")):
            out.append(Pivot(i, "low", float(lows[i]), int(ts[i]),
                             i + L, int(ts[i + L])))
    return sorted(out, key=lambda p: (p.idx, p.kind))


def normalize_alternating(df, L, as_of_idx):
    """spec §4.1.1 因果式合併。

    只使用 confirm_idx <= as_of_idx 的 pivot（在 as_of 當下已確認者）。
    連續同型段：【已封閉】者取極值（封閉 = 其後已出現異型 pivot）；
    【未封閉】的最後一段取截至 as_of 為止的 running extreme。
    兩者在本實作中是同一段程式——因為只掃描已確認的 pivot，未封閉段自然
    只看得到 as_of 之前的成員。
    """
    piv = [p for p in find_pivots(df, L) if p.confirm_idx <= as_of_idx]
    seq = []
    for p in piv:
        if seq and seq[-1].kind == p.kind:
            prev = seq[-1]
            better = (p.price > prev.price) if p.kind == "high" else (p.price < prev.price)
            if better:
                seq[-1] = p                       # 同段內取較極端者
            # 價格平手或較差 → 保留較早者（spec §4.1.1）
        else:
            seq.append(p)
    return seq
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_pivots.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/m_detect.py tests/test_m_pivots.py
git commit -m "feat(harmonic): 因果式 pivot 偵測與交替序列正規化"
```

---

## Task 6: 形態候選、比例過濾與 PRZ

**Files:**
- Modify: `scripts/m_detect.py`
- Test: `tests/test_m_patterns.py`

**背景：** 讀 spec §4.2（比例表與逐形態的過濾規則）、§4.3（PRZ 與缺約束處理）、§4.5.2（SL 不吃 D）。**注意三個特例**：Shark 無 `AB/XA`；Cypher 不套 `BC/AB`、PRZ 由 `CD/XC` 單獨決定；同一組 XABC 可同時滿足多個形態，這是預期行為。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_m_patterns.py`：

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import m_config as cfg
import m_detect


def _xabc(x, a, b, c):
    """回傳 (價格四元組, direction)。bullish: x 低 a 高 b 低 c 高。"""
    return dict(p_X=x, p_A=a, p_B=b, p_C=c, direction=1)


def test_perfect_gartley_passes_filters():
    # AB/XA = 0.618, BC/AB = 0.5（在 0.382-0.886 內）
    xa = 100.0
    x, a = 0.0, 100.0
    b = a - 0.618 * xa                       # 38.2
    c = b + 0.5 * (a - b)                    # 69.1
    assert m_detect.passes_prefilters("gartley", _xabc(x, a, b, c), cfg.TOL)


def test_ad_xa_off_by_20pct_produces_no_prz():
    xa = 100.0
    x, a = 0.0, 100.0
    b, c = a - 0.618 * xa, a - 0.618 * xa + 0.5 * 0.618 * xa
    prz = m_detect.compute_prz("gartley", _xabc(x, a, b, c), cfg.TOL, cfg.TOL_AD_XA)
    lo, hi = prz
    d_correct = a - 0.786 * xa               # 21.4
    d_off = a - 0.786 * 1.2 * xa             # 偏 20%
    assert lo <= d_correct <= hi
    assert not (lo <= d_off <= hi)


def test_shark_skips_ab_xa_filter():
    """spec §4.2：Shark 的 AB/XA 為 None。"""
    assert cfg.HARMONIC_RATIOS["shark"][0] is None
    # 一個 AB/XA 極端的 XABC，只要 BC/AB 合格就該通過
    x, a = 0.0, 100.0
    b = a - 0.95 * 100.0                     # AB/XA = 0.95，對任何有約束的形態都不合格
    c = b + 1.3 * (a - b)                    # BC/AB = 1.3，在 1.13-1.618 內
    assert m_detect.passes_prefilters("shark", _xabc(x, a, b, c), cfg.TOL)


def test_cypher_uses_xc_not_bc_ab():
    """spec §4.2：Cypher 不套 BC/AB，改用 XC/XA；PRZ 由 CD/XC 決定。"""
    x, a = 0.0, 100.0
    b = a - 0.5 * 100.0                      # AB/XA = 0.5，在 0.382-0.618 內
    c = x + 1.30 * 100.0                     # XC/XA = 1.30，在 1.272-1.414 內
    d = _xabc(x, a, b, c)
    assert m_detect.passes_prefilters("cypher", d, cfg.TOL)
    lo, hi = m_detect.compute_prz("cypher", d, cfg.TOL, cfg.TOL_AD_XA)
    expected_d = c - 0.786 * (c - x)
    assert lo <= expected_d <= hi


def test_empty_intersection_returns_none():
    """AD/XA 與 CD/BC 的區間不相交 → 候選作廢（spec §4.3）。"""
    x, a = 0.0, 100.0
    b = a - 0.886 * 100.0                    # deep_crab 的 AB/XA
    c = b + 0.4 * (a - b)                    # BC 很短 → CD/BC 推出的 D 區遠離 AD/XA 的 D 區
    assert m_detect.compute_prz("deep_crab", _xabc(x, a, b, c), cfg.TOL, cfg.TOL_AD_XA) is None


def test_one_xabc_can_satisfy_multiple_patterns():
    """spec §4.2 末段：as_of 前只有兩軸可驗，Bat 與 Crab 的前置過濾完全重疊。"""
    x, a = 0.0, 100.0
    b = a - 0.45 * 100.0                     # 同時落在 bat(0.382-0.50) 與 crab(0.382-0.618)
    c = b + 0.5 * (a - b)                    # BC/AB = 0.5，兩者都合格
    d = _xabc(x, a, b, c)
    hits = [p for p in ("bat", "crab") if m_detect.passes_prefilters(p, d, cfg.TOL)]
    assert hits == ["bat", "crab"]


def test_sl_does_not_depend_on_fill():
    """spec §4.5.2：SL 由 X/A 與形態常數唯一決定。"""
    x, a = 0.0, 100.0
    sl = m_detect.compute_sl("bat", _xabc(x, a, 50.0, 70.0))
    assert sl == a - cfg.SL_LEVEL_OVER_XA["bat"] * (a - x)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_m_patterns.py -q`
Expected: FAIL，`AttributeError: module 'm_detect' has no attribute 'passes_prefilters'`

- [ ] **Step 3: 實作過濾、PRZ 與 SL**

在 `scripts/m_detect.py` 附加：

```python
def _band(target, tol):
    """spec §4.4：單點目標加對稱百分比帶；區間目標原樣使用。"""
    lo, hi = target
    if lo == hi:
        return lo * (1 - tol), hi * (1 + tol)
    return lo, hi


def _in_band(value, target, tol):
    lo, hi = _band(target, tol)
    return lo <= value <= hi


def passes_prefilters(pattern, pts, tol):
    """spec §4.3：as_of 前即可檢驗的過濾條件（只涉及 X/A/B/C）。"""
    xa = abs(pts["p_A"] - pts["p_X"])
    ab = abs(pts["p_A"] - pts["p_B"])
    bc = abs(pts["p_C"] - pts["p_B"])
    if xa == 0 or ab == 0:
        return False
    if pattern == "cypher":
        xc = abs(pts["p_C"] - pts["p_X"])
        return (_in_band(ab / xa, cfg.CYPHER_RATIOS["ab_over_xa"], tol)
                and _in_band(xc / xa, cfg.CYPHER_RATIOS["xc_over_xa"], tol))
    ab_xa, bc_ab, _, _ = cfg.HARMONIC_RATIOS[pattern]
    if ab_xa is not None and not _in_band(ab / xa, ab_xa, tol):
        return False
    return _in_band(bc / ab, bc_ab, tol)


def compute_prz(pattern, pts, tol, tol_ad):
    """spec §4.3：回傳 (prz_low, prz_high)；交集為空回傳 None。"""
    s = pts["direction"]                       # +1 bullish, -1 bearish
    xa = abs(pts["p_A"] - pts["p_X"])
    bc = abs(pts["p_C"] - pts["p_B"])
    intervals = []
    if pattern == "cypher":
        xc = abs(pts["p_C"] - pts["p_X"])
        lo, hi = _band(cfg.CYPHER_RATIOS["cd_over_xc"], tol_ad)
        intervals.append(sorted((pts["p_C"] - s * hi * xc, pts["p_C"] - s * lo * xc)))
    else:
        _, _, cd_bc, ad_xa = cfg.HARMONIC_RATIOS[pattern]
        if ad_xa is not None:
            lo, hi = _band(ad_xa, tol_ad)
            intervals.append(sorted((pts["p_A"] - s * hi * xa, pts["p_A"] - s * lo * xa)))
        if cd_bc is not None:
            lo, hi = _band(cd_bc, tol)
            intervals.append(sorted((pts["p_C"] - s * hi * bc, pts["p_C"] - s * lo * bc)))
    if not intervals:
        raise AssertionError(f"{pattern} 無任何 PRZ 約束——spec §4.3 禁止此情況")
    lo = max(i[0] for i in intervals)
    hi = min(i[1] for i in intervals)
    return None if lo > hi else (lo, hi)


def compute_sl(pattern, pts):
    """spec §4.5.2：SL 由 X/A 與形態常數唯一決定，【不吃 D】。"""
    s = pts["direction"]
    return pts["p_A"] - s * cfg.SL_LEVEL_OVER_XA[pattern] * abs(pts["p_A"] - pts["p_X"])
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_patterns.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/m_detect.py tests/test_m_patterns.py
git commit -m "feat(harmonic): 形態前置過濾、PRZ 交集與形態常數止損"
```

---

## Task 7: 事件表組裝與去重

**Files:**
- Modify: `scripts/m_detect.py`
- Test: `tests/test_m_dedup.py`

**背景：** 讀 spec §3.2（事件表 schema）與 §4.6（連通分量去重 + 三段 tie-break）。v2 的規則不具傳遞性且「L 最小 ⟺ as_of 最早」是假恆等式。

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_m_dedup.py`：

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd
import m_detect


def _ev(eid, tx, ta, tb, tc, as_of, L, pattern="bat"):
    return dict(event_id=eid, symbol="BTCUSDT", interval="1h", pattern=pattern,
                direction=1, pivot_length=L, t_X=tx, t_A=ta, t_B=tb, t_C=tc,
                as_of=as_of, dedup_merged=0)


def test_connected_components_merge_transitively():
    """e1~e2、e2~e3 但 e1≁e3（只差 2 個時間戳）→ 三者仍應併為一列。"""
    e1 = _ev("e1", 1, 2, 3, 4, as_of=100, L=5)
    e2 = _ev("e2", 1, 2, 3, 9, as_of=110, L=10)     # 與 e1 差 t_C
    e3 = _ev("e3", 1, 2, 8, 9, as_of=120, L=20)     # 與 e2 差 t_B；與 e1 差兩個
    out = m_detect.dedup(pd.DataFrame([e1, e2, e3]))
    assert len(out) == 1
    assert out.iloc[0]["event_id"] == "e1"          # as_of 最小
    assert out.iloc[0]["dedup_merged"] == 2


def test_tiebreak_prefers_smallest_as_of_then_L_then_id():
    a = _ev("zzz", 1, 2, 3, 4, as_of=100, L=20)
    b = _ev("aaa", 1, 2, 3, 4, as_of=100, L=20)     # as_of 與 L 皆同 → 字典序
    c = _ev("mmm", 1, 2, 3, 4, as_of=100, L=5)      # L 較小
    d = _ev("nnn", 1, 2, 3, 4, as_of=90, L=40)      # as_of 最小 → 勝出
    out = m_detect.dedup(pd.DataFrame([a, b, c, d]))
    assert len(out) == 1 and out.iloc[0]["event_id"] == "nnn"

    out2 = m_detect.dedup(pd.DataFrame([a, b, c]))
    assert out2.iloc[0]["event_id"] == "mmm"        # L 最小

    out3 = m_detect.dedup(pd.DataFrame([a, b]))
    assert out3.iloc[0]["event_id"] == "aaa"        # 字典序


def test_different_patterns_never_merge():
    """spec §4.2 末段：不跨形態合併。"""
    a = _ev("a", 1, 2, 3, 4, as_of=100, L=5, pattern="bat")
    b = _ev("b", 1, 2, 3, 4, as_of=100, L=5, pattern="crab")
    out = m_detect.dedup(pd.DataFrame([a, b]))
    assert len(out) == 2


def test_unrelated_events_survive():
    a = _ev("a", 1, 2, 3, 4, as_of=100, L=5)
    b = _ev("b", 50, 60, 70, 80, as_of=200, L=5)
    assert len(m_detect.dedup(pd.DataFrame([a, b]))) == 2
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_m_dedup.py -q`
Expected: FAIL，`AttributeError: module 'm_detect' has no attribute 'dedup'`

- [ ] **Step 3: 實作去重**

在 `scripts/m_detect.py` 附加：

```python
def dedup(events):
    """spec §4.6：連通分量分組 + 三段 tie-break。

    相鄰關係不具傳遞性，故必須取【連通分量】（transitive closure），
    不能取 clique。tie-break：as_of 最小 → pivot_length 最小 → event_id 字典序。
    """
    if events.empty:
        return events.copy()
    keep_rows = []
    for _, grp in events.groupby(["symbol", "interval", "pattern", "direction"],
                                 sort=False):
        rows = grp.to_dict("records")
        parent = list(range(len(rows)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(i, j):
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[max(ri, rj)] = min(ri, rj)

        keys = ("t_X", "t_A", "t_B", "t_C")
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                same = sum(rows[i][k] == rows[j][k] for k in keys)
                if same >= 3:
                    union(i, j)

        comps = {}
        for i in range(len(rows)):
            comps.setdefault(find(i), []).append(rows[i])
        for members in comps.values():
            best = min(members, key=lambda r: (r["as_of"], r["pivot_length"],
                                               r["event_id"]))
            best = dict(best)
            best["dedup_merged"] = len(members) - 1
            keep_rows.append(best)
    out = pd.DataFrame(keep_rows)
    return out.sort_values("event_id").reset_index(drop=True)
```

同時在檔案開頭補 `import pandas as pd`。

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_dedup.py -q`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/m_detect.py tests/test_m_dedup.py
git commit -m "feat(harmonic): 事件表連通分量去重與三段 tie-break"
```

---

## Task 8: 事件表產生器（`build_events`）

**Files:**
- Modify: `scripts/m_detect.py`
- Test: `tests/test_m_patterns.py`（附加）

- [ ] **Step 1: 寫失敗的測試**

在 `tests/test_m_patterns.py` 附加：

```python
import pandas as pd


def _synthetic_gartley_bars():
    """構造一段一定會產生 bullish Gartley 候選的合成 K 線。"""
    xa = 100.0
    x, a = 100.0, 200.0
    b = a - 0.618 * xa
    c = b + 0.5 * (a - b)
    pivots = [(0, x, "low"), (12, a, "high"), (24, b, "low"), (36, c, "high")]
    n = 60
    highs = [150.0] * n
    lows = [150.0] * n
    for idx, price, kind in pivots:
        for k in range(max(0, idx - 4), min(n, idx + 5)):
            if kind == "high":
                highs[k] = min(highs[k], price - 5)
                lows[k] = min(lows[k], price - 20)
            else:
                lows[k] = max(lows[k], price + 5)
                highs[k] = max(highs[k], price + 20)
        highs[idx] = price if kind == "high" else highs[idx]
        lows[idx] = price if kind == "low" else lows[idx]
    return pd.DataFrame({"t": [i * 3_600_000 for i in range(n)],
                         "o": lows, "h": highs, "l": lows, "c": highs,
                         "v": [1.0] * n, "qv": [1.0] * n})


def test_build_events_emits_required_schema():
    df = _synthetic_gartley_bars()
    ev = m_detect.build_events(df, symbol="BTCUSDT", interval="1h")
    required = {"event_id", "xabc_group_id", "symbol", "interval", "pattern",
                "direction", "pivot_length", "t_X", "t_A", "t_B", "t_C",
                "p_X", "p_A", "p_B", "p_C", "as_of", "ratio_ab_xa",
                "ratio_bc_ab", "ratio_xc_xa", "prz_low", "prz_high", "sl",
                "tp1_planned", "tp2_planned", "dedup_merged", "tol_used"}
    assert required.issubset(set(ev.columns))


def test_every_event_as_of_is_after_its_C_confirm():
    df = _synthetic_gartley_bars()
    ev = m_detect.build_events(df, symbol="BTCUSDT", interval="1h")
    if ev.empty:
        import pytest
        pytest.skip("合成資料未產生事件——調整 fixture 而非放寬斷言")
    assert (ev["as_of"] > ev["t_C"]).all()
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_m_patterns.py -q -k build_events`
Expected: FAIL，`AttributeError: module 'm_detect' has no attribute 'build_events'`

- [ ] **Step 3: 實作 `build_events`**

在 `scripts/m_detect.py` 附加：

```python
def _extreme(pts):
    prices = [pts["p_X"], pts["p_A"], pts["p_B"], pts["p_C"]]
    return max(prices) if pts["direction"] == 1 else min(prices)


def build_events(df, symbol, interval, tol=None, tol_ad=None, lengths=None,
                 do_dedup=True):
    """spec §4：K 線 → 事件表。

    do_dedup=False 供 M-G1 的偵測層斷言使用（spec §6.2：截斷斷言必須在去重前評估）。
    """
    tol = cfg.TOL if tol is None else tol
    tol_ad = cfg.TOL_AD_XA if tol_ad is None else tol_ad
    lengths = cfg.PIVOT_LENGTHS if lengths is None else lengths
    rows = []
    for L in lengths:
        piv_all = find_pivots(df, L)
        for p_c in piv_all:
            seq = normalize_alternating(df, L, as_of_idx=p_c.confirm_idx)
            if len(seq) < 4 or seq[-1].idx != p_c.idx:
                continue
            x, a, b, c = seq[-4:]
            direction = 1 if x.kind == "low" else -1
            if [x.kind, a.kind, b.kind, c.kind] not in (
                    ["low", "high", "low", "high"], ["high", "low", "high", "low"]):
                continue
            pts = dict(p_X=x.price, p_A=a.price, p_B=b.price, p_C=c.price,
                       direction=direction)
            xa = abs(pts["p_A"] - pts["p_X"])
            ab = abs(pts["p_A"] - pts["p_B"])
            if xa == 0 or ab == 0:
                continue
            for pattern in cfg.PATTERNS:
                if not passes_prefilters(pattern, pts, tol):
                    continue
                prz = compute_prz(pattern, pts, tol, tol_ad)
                if prz is None:
                    continue
                prz_lo, prz_hi = prz
                sl = compute_sl(pattern, pts)
                d_trigger = prz_hi if direction == 1 else prz_lo
                leg = abs(_extreme(pts) - d_trigger)
                f1, f2 = (cfg.TP_FACTORS_SHARK if pattern == "shark"
                          else cfg.TP_FACTORS)
                gid = (f"{symbol}_{interval}_{direction}_{L}_"
                       f"{x.t}_{a.t}_{b.t}_{c.t}")
                rows.append(dict(
                    event_id=f"{symbol}_{interval}_{direction}_{L}_{c.t}_{pattern}",
                    xabc_group_id=gid, symbol=symbol, interval=interval,
                    pattern=pattern, direction=direction, pivot_length=L,
                    t_X=x.t, t_A=a.t, t_B=b.t, t_C=c.t,
                    p_X=x.price, p_A=a.price, p_B=b.price, p_C=c.price,
                    as_of=c.confirm_t,
                    ratio_ab_xa=ab / xa, ratio_bc_ab=abs(c.price - b.price) / ab,
                    ratio_xc_xa=abs(c.price - x.price) / xa,
                    prz_low=prz_lo, prz_high=prz_hi, sl=sl,
                    tp1_planned=d_trigger + direction * f1 * leg,
                    tp2_planned=d_trigger + direction * f2 * leg,
                    dedup_merged=0, tol_used=tol))
    ev = pd.DataFrame(rows)
    if ev.empty or not do_dedup:
        return ev
    return dedup(ev)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_m_patterns.py -q`
Expected: `9 passed`

- [ ] **Step 5: 跑全部既有測試，確認沒有回歸**

Run: `.venv/bin/pytest tests/test_m_config.py tests/test_m_baseline_formula.py tests/test_m_pivots.py tests/test_m_patterns.py tests/test_m_dedup.py tests/test_m_data.py -q`
Expected: 全綠

- [ ] **Step 6: Commit**

```bash
git add scripts/m_detect.py tests/test_m_patterns.py
git commit -m "feat(harmonic): 事件表產生器 build_events"
```

---

## Task 9: M-G1 偵測層無前視測試

**Files:**
- Create: `tests/test_m_nolookahead.py`

**背景：** 讀 spec §6.2 的 M-G1 全文。**兩個陷阱**：(a) 斷言必須在**去重前**評估——去重的連通分量會因截斷而裂開，使事件「憑空出現」，那是去重的預期行為不是 look-ahead；(b) 斷言必須雙向——不得有事件消失，**也不得有事件出現**。

- [ ] **Step 1: 寫測試**

建立 `tests/test_m_nolookahead.py`：

```python
"""M-G1 偵測層：截斷式無前視斷言（spec §6.2）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd
import pytest

import m_detect


def _random_walk_bars(n=1200, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    high = close * (1 + rng.uniform(0, 0.004, n))
    low = close * (1 - rng.uniform(0, 0.004, n))
    return pd.DataFrame({"t": [i * 3_600_000 for i in range(n)],
                         "o": close, "h": high, "l": low, "c": close,
                         "v": 1.0, "qv": 1.0})


@pytest.mark.parametrize("frac", [0.25, 0.50, 0.75])
def test_truncation_changes_nothing_at_or_before_T(frac):
    df = _random_walk_bars()
    cut = int(len(df) * frac)
    T = int(df["t"].iloc[cut])

    full = m_detect.build_events(df, "BTCUSDT", "1h", do_dedup=False)
    trunc = m_detect.build_events(df.iloc[:cut + 1].reset_index(drop=True),
                                  "BTCUSDT", "1h", do_dedup=False)

    full_le = full[full["as_of"] <= T].sort_values("event_id").reset_index(drop=True)
    trunc_le = trunc[trunc["as_of"] <= T].sort_values("event_id").reset_index(drop=True)

    missing = set(full_le["event_id"]) - set(trunc_le["event_id"])
    appeared = set(trunc_le["event_id"]) - set(full_le["event_id"])
    assert not missing, f"截斷後消失的事件（look-ahead）：{sorted(missing)[:5]}"
    assert not appeared, f"截斷後憑空出現的事件（look-ahead）：{sorted(appeared)[:5]}"

    pd.testing.assert_frame_equal(full_le, trunc_le, check_exact=False, rtol=1e-12)


def test_events_exist_in_fixture():
    """避免上面的斷言在零事件時空轉。"""
    ev = m_detect.build_events(_random_walk_bars(), "BTCUSDT", "1h", do_dedup=False)
    assert len(ev) > 0, "隨機遊走未產生任何事件——先檢查偵測器而非放寬測試"
```

- [ ] **Step 2: 跑測試**

Run: `.venv/bin/pytest tests/test_m_nolookahead.py -q`
Expected: `4 passed`

**若失敗：** 這代表偵測器真的有 look-ahead。**不要放寬斷言**（spec §6.2 的斷言本身已經是正確版本）。回頭檢查 `normalize_alternating` 是否使用了 `confirm_idx > as_of_idx` 的 pivot，或 `build_events` 是否在 `p_c` 之外的地方讀到未來的 bar。

- [ ] **Step 3: Commit**

```bash
git add tests/test_m_nolookahead.py
git commit -m "test(harmonic): M-G1 偵測層截斷式無前視斷言"
```

---

## Task 10: 形態普查

**Files:**
- Create: `scripts/m_census.py`
- Create: `reports/m-pattern-census.md`（由腳本產生）

**背景：** 這是 Stage 1 的交付物，也是 Stage 2 設計的輸入。spec §4.3 要求空交集比例逐形態揭露、§4.2 末段要求多形態 XABC 率揭露。

- [ ] **Step 1: 寫腳本**

建立 `scripts/m_census.py`：

```python
"""Sub-project M — 形態普查（Stage 1 交付物）。

輸出各形態的事件數（去重前後）、空交集率、多形態 XABC 率，逐 interval 分列。
這些數字是 Stage 2 回測層的設計輸入，也是 spec §4.3／§4.2 要求的強制揭露。

用法：.venv/bin/python scripts/m_census.py
"""
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg      # noqa: E402
import m_data               # noqa: E402
import m_detect             # noqa: E402

OUT = pathlib.Path("reports/m-pattern-census.md")


def census():
    candidates = m_data.binance_universe_symbols()
    universe = m_data.build_pit_universe_m(candidates)
    symbols = sorted({s for syms in universe.values() for s in syms})
    lines = ["# Sub-project M — 形態普查（Stage 1）", "",
             f"幣種數：{len(symbols)}｜pivot 尺度：{cfg.PIVOT_LENGTHS}｜"
             f"容差：TOL={cfg.TOL} / TOL_AD_XA={cfg.TOL_AD_XA}", ""]
    for interval in cfg.INTERVALS:
        frames = []
        for sym in symbols:
            df = m_data.load_klines(sym, interval)
            if df.empty:
                continue
            df = df[(df["t"] >= cfg.FETCH_START_MS) & (df["t"] <= cfg.FETCH_END_MS)]
            raw = m_detect.build_events(df, sym, interval, do_dedup=False)
            if not raw.empty:
                frames.append(raw)
        if not frames:
            lines += [f"## {interval}", "", "無事件。", ""]
            continue
        raw = pd.concat(frames, ignore_index=True)
        raw = raw[(raw["as_of"] >= cfg.EVENT_START_MS)
                  & (raw["as_of"] <= cfg.EVENT_END_MS)]
        ded = m_detect.dedup(raw)
        multi = (ded.groupby("xabc_group_id")["pattern"].nunique() > 1)
        lines += [f"## {interval}", "",
                  f"去重前 {len(raw)}｜去重後 {len(ded)}｜"
                  f"多形態 XABC 佔比 {multi.mean():.1%}", "",
                  "| 形態 | 去重前 | 去重後 | IS | OOS |", "|---|---|---|---|---|"]
        for p in cfg.PATTERNS:
            sub = ded[ded["pattern"] == p]
            n_is = int((sub["as_of"] <= cfg.IS_END_MS).sum())
            lines.append(f"| {p} | {int((raw['pattern'] == p).sum())} | "
                         f"{len(sub)} | {n_is} | {len(sub) - n_is} |")
        lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    census()
```

**注意：** `m_data.binance_universe_symbols()` 尚未實作——它應回傳 Binance USDT 永續的全部 symbol（供 PIT 篩選的候選池）。在 `m_data.py` 補上：

```python
def binance_universe_symbols():
    """Binance USDT 永續的全部 symbol（PIT 篩選的候選池）。"""
    r = requests.get(f"{BINANCE_FAPI}/exchangeInfo", timeout=30)
    r.raise_for_status()
    return sorted(s["symbol"] for s in r.json()["symbols"]
                  if s.get("quoteAsset") == "USDT"
                  and s.get("contractType") == "PERPETUAL")
```

- [ ] **Step 2: 先小規模試跑（只抓 BTC/ETH、只跑 4h）**

在 python REPL 或臨時腳本中：

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'scripts')
import m_data, m_detect
df = m_data.load_klines('BTCUSDT', '4h')
print('bars:', len(df))
ev = m_detect.build_events(df, 'BTCUSDT', '4h')
print('events:', len(ev))
print(ev.groupby('pattern').size())
"
```

Expected: 印出 bar 數（應為數千）與各形態事件數。**這一步會真的打網路抓 Binance 公開 K 線，屬唯讀，不碰任何錢包。**

- [ ] **Step 3: 檢查數量級是否合理**

判準（這是 Stage 2 設計的關鍵輸入，不是 gate）：
- BTC 4h 六年約 13,000 根 bar，四個 pivot 尺度合計預期產生**數十到數百**個事件
- 若某形態是 **0**：檢查該形態的比例表與 PRZ 交集邏輯（原版腳本的 Gartley 只有 3 筆、Alt Bat 是 0，那是它的 bug，我們不該複製）
- 若總數 **> 50,000**：容差或候選規則可能過寬，回頭核對 §4.4

**把觀察到的數字記下來，回報給主對話——不要自行調整 spec 的凍結參數。**

- [ ] **Step 4: 跑完整普查**

Run: `.venv/bin/python scripts/m_census.py`
Expected: 產生 `reports/m-pattern-census.md`

**注意：** 這一步會抓 30 幣 × 4 個 interval × 6 年的 K 線，耗時可能達數十分鐘。用 `run_in_background` 執行並定期檢查。

- [ ] **Step 5: Commit**

```bash
git add scripts/m_census.py scripts/m_data.py reports/m-pattern-census.md
git commit -m "feat(harmonic): 形態普查腳本與 Stage 1 普查報告"
```

---

## Stage 1 完成判準

全部滿足才算完成（spec §6.2 的兩個前置 gate + 交付物）：

- [ ] `.venv/bin/pytest tests/test_m_*.py -q` 全綠，且**貼出輸出**
- [ ] `.venv/bin/python scripts/m_verify_baseline.py` → `M-G0 全部斷言: PASS`，exit 0（**M-G0**）
- [ ] `tests/test_m_nolookahead.py` 全綠（**M-G1 偵測層**）
- [ ] `reports/m-pattern-census.md` 存在且逐形態、逐 interval 有數字
- [ ] `git status` 乾淨
- [ ] 回報普查的實際數字，以及任何「spec 沒寫到、實作時必須決定」的地方——**那些是 spec 缺陷，要回填 spec 而不是默默決定**

## Stage 2 預告（本計畫不含）

`m_backtest.py`（PRZ 掛單模擬、八種終局、R-multiple、日報酬序列）、`m_control.py`（匹配隨機對照組、日曆對齊）、`m_gates.py`（M-G2~M-G7 與判定表）、`reports/harmonic-m-verdict.md`。Stage 2 的計畫在 Stage 1 的普查數字出來後再寫——因為事件數量級會決定回測層要不要分批處理、以及某些形態是否樣本不足而只能併入總體判定。
