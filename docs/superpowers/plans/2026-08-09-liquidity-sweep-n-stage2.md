# Sub-project N Stage 2 — 回測引擎、訂單流特徵、對照組與十道 gate

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Stage 1 的掃單事件接上訂單流確認、結構化 SL/TP、曝險對齊的匹配隨機對照組，並以 spec §8 的十道預註冊 gate 機械導出判定。

**Architecture:** 四層。**池表層**（每 symbol 一次算出所有 pivot 及其「第一次被掃穿的棒」，讓「未被掃過」成為 O(1) 查詢）→ **訂單流層**（全期逐棒 sidecar 供 CVD；事件級 `D_sweep` 從日檔 range query）→ **回測層**（進場/SL/TP/八終局，向量化掃描）→ **統計層**（事件級 E[R]、以 symbol 為叢集的自助法、十道 gate）。

**Tech Stack:** Python 3.9 / numpy / pandas / pyarrow。`.venv/bin/python`、`.venv/bin/pytest`。除 Task 7 讀本機日檔外全程零網路。

---

## 紅線（實作者必讀）

**這是預註冊研究。** spec 是 `docs/superpowers/specs/2026-08-09-liquidity-sweep-orderflow-design.md`（v1.0 + 修訂 A1/A2），**在看到任何回測結果之前已寫定**。

- **不得**因為「跑出來不好看」而調整任何門檻、定義或判準。發現 spec 有錯 → **停下來回報**。
- **不得**新增 spec 沒有的自由參數。§5 的訂單流特徵刻意只取符號、不設幅度門檻。
- **絕對不可修改**：`scripts/m_*.py`、`tests/test_m_*.py`、`data/cache/harmonic_m/*`，
  以及 Stage 1 已完成並通過 gate 的 `scripts/n_config.py`、`n_data.py`、`n_orderflow.py`、
  `n_reconcile.py`、`n_sweep.py`（**只准新增函式，不准改既有函式**）。
- 每個 Task 後確認 `.venv/bin/pytest tests/test_m_*.py -q` = **74 passed**、
  `tests/test_n_*.py` 全綠。

---

## 預先釘死的九項詮釋（承 Stage 1 的 P1–P8，續編）

| # | 議題 | 釘死的詮釋 |
|---|---|---|
| P9 | 「未被掃過」的時點 | 一律**以 `as_of`（掃單棒 j 的收盤）為準**。池 P（形成於 bar i）在 j 時未被掃過 ⟺ 其「第一次被掃穿的棒」`swept_at(P) > j`。掃單棒本身算在內。 |
| P10 | TP 池的「在進場價之外」 | 於**成交後**用實際 fill 價篩選（fill 在成交當下已知，非前視）。池集合本身仍以 `as_of` 決定。 |
| P11 | TP 無合格池 | 終局 `no_target`，`R_net = 0`，**計入分母**。不得改用固定 R:R 或最遠池代替。 |
| P12 | 棒內 SL/TP 同時觸及 | **SL 優先（悲觀）**；SL gap-through 取開盤（較差），TP 恆取 TP 價。沿用 M spec §4.5。 |
| P13 | 訂單流特徵缺值 | 該事件終局 `nodata`，`R_net = 0`，計入分母，並計入 `n_nodata` 揭露。**兩臂同規則。** |
| P14 | 對照臂的訂單流 | 對照事件在**它自己的**掃單棒上重算 `D_sweep` 與 CVD 比較——**不得沿用母事件的值**。池價位按 §7.1 的比值平移。 |
| P15 | 曝險對齊 | 每個母事件的存活對照，權重**重新正規化為合計恰好 1**。曝險比 = 對照臂加權曝險 ÷ 事件臂事件數，須 ∈ [0.95, 1.05]，否則該格**機械宣告作廢**。 |
| P16 | 主要統計量 | **每事件 E[R]**（曝險不變）。日報酬序列只用於揭露，**不得用於任何 gate 判定**。 |
| P17 | 自助法叢集 | 以 **symbol** 為叢集重抽（同幣事件相依）。`B = 10000`，種子由 `m_stats.gate_rng(gate_id)` 派生。 |

---

## File Structure

| 檔案 | 職責 |
|---|---|
| `scripts/n_sweep.py`（**追加函式，不改既有**） | `pool_table()`：每 symbol 的池表，含 `swept_at`。 |
| `scripts/n_features.py`（新） | 事件 → 訂單流特徵（`d_sweep`, `v_sweep`, `cvd_j`, `cvd_pool`, `abs_ok`, `div_ok`）。 |
| `scripts/n_backtest.py`（新） | `simulate_event()`：進場、SL、TP、八終局、R-multiple。 |
| `scripts/n_control.py`（新） | 匹配隨機對照 + 曝險對齊；`FILTER_ENTRYPOINT` 供結構性公平斷言。 |
| `scripts/n_stats.py`（新） | 事件層 E[R]、symbol 叢集自助、曝險比檢查。 |
| `scripts/n_gates.py`（新） | 十道 gate 與判定表（機械導出，無裁量）。 |
| `scripts/n_run.py`（新） | 執行入口：`{bars|events|feat|arms|gates}`。 |
| 對應 `tests/test_n_*.py` | 每個模組一支。 |

---

## Task 5: 池表（`swept_at`）

**Files:** Modify `scripts/n_sweep.py`（**只追加**）；Test `tests/test_n_pools.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_n_pools.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_sweep as sw

BAR = 3_600_000


def bars(rows):
    a = np.array(rows, dtype=float)
    return pd.DataFrame({"t": np.arange(len(rows), dtype=np.int64) * BAR,
                         "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]})


def test_swept_at_is_first_bar_trading_through():
    """pivot high 於 idx=2（L=2）；idx=6 首次 high>pool -> swept_at=6。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 3 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4
    pt = sw.pool_table(bars(rows), L=2)
    hi = pt[(pt["kind"] == "high") & (pt["idx"] == 2)]
    assert len(hi) == 1
    assert int(hi.iloc[0]["swept_at"]) == 6


def test_swept_at_is_n_when_never_swept():
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 6
    pt = sw.pool_table(bars(rows), L=2)
    hi = pt[(pt["kind"] == "high") & (pt["idx"] == 2)]
    assert int(hi.iloc[0]["swept_at"]) == len(rows)


def test_swept_at_uses_strict_inequality():
    """等於池價不算掃穿（與 is_sweep 的嚴格不等號一致，P5）。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] \
        + [(9, 12.0, 8.5, 9)] + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 5
    pt = sw.pool_table(bars(rows), L=2)
    hi = pt[(pt["kind"] == "high") & (pt["idx"] == 2)]
    assert int(hi.iloc[0]["swept_at"]) == 4          # idx=3 的 12.0 不算


def test_low_pool_mirrors():
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 9.5, 6.0, 9)] + [(9, 9.5, 8.5, 9)] * 3 \
        + [(9, 9.5, 5.5, 9)] + [(9, 9.5, 8.5, 9)] * 4
    pt = sw.pool_table(bars(rows), L=2)
    lo = pt[(pt["kind"] == "low") & (pt["idx"] == 2)]
    assert int(lo.iloc[0]["swept_at"]) == 6


def test_pool_table_has_confirm_t_and_is_sorted():
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 6.0, 9)] \
        + [(9, 9.5, 8.5, 9)] * 6
    pt = sw.pool_table(bars(rows), L=2)
    assert set(["idx", "kind", "price", "t", "confirm_t", "swept_at"]) <= set(pt.columns)
    assert pt["confirm_t"].is_monotonic_increasing


@pytest.mark.parametrize("k", [9, 11])
def test_pool_table_no_lookahead_for_confirmed_pools(k):
    """截斷不得改變已確認池的 price/confirm_t（swept_at 會因未來未知而不同，
    故只比對前兩者——swept_at 的 PIT 正確性由 selectable_pools 的 as_of 過濾保證）。"""
    rows = [(9, 9.5, 8.5, 9)] * 2 + [(9, 12.0, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 4 \
        + [(9, 12.5, 8.5, 9)] + [(9, 9.5, 8.5, 9)] * 6
    b = bars(rows)
    full = sw.pool_table(b, L=2).set_index(["idx", "kind"])
    tr = sw.pool_table(b.iloc[:k].copy(), L=2).set_index(["idx", "kind"])
    for idx, r in tr.iterrows():
        assert idx in full.index
        assert full.loc[idx, "price"] == pytest.approx(r["price"])
        assert full.loc[idx, "confirm_t"] == r["confirm_t"]


def test_selectable_pools_filters_by_as_of_and_unswept():
    """P9：as_of 時已確認、且 swept_at > j 才算可用。"""
    pt = pd.DataFrame({
        "idx": [1, 2, 3], "kind": ["low"] * 3, "price": [10.0, 9.0, 8.0],
        "t": [0, BAR, 2 * BAR], "confirm_t": [3 * BAR - 1, 4 * BAR - 1, 9 * BAR - 1],
        "swept_at": [5, 99, 99]})
    out = sw.selectable_pools(pt, kind="low", as_of=5 * BAR - 1, j=6, n_last=10)
    assert out["idx"].tolist() == [2]      # idx1 已被掃(5<=6)、idx3 尚未確認


def test_selectable_pools_keeps_only_last_n():
    pt = pd.DataFrame({
        "idx": list(range(10)), "kind": ["low"] * 10,
        "price": [float(i) for i in range(10)],
        "t": [i * BAR for i in range(10)],
        "confirm_t": [(i + 1) * BAR - 1 for i in range(10)],
        "swept_at": [99] * 10})
    out = sw.selectable_pools(pt, kind="low", as_of=100 * BAR, j=50, n_last=3)
    assert out["idx"].tolist() == [7, 8, 9]
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_pools.py -v --basetemp=/tmp/nt5`
Expected: FAIL — `AttributeError: module 'n_sweep' has no attribute 'pool_table'`

- [ ] **Step 3: 追加到 `scripts/n_sweep.py` 末尾（不改動任何既有函式）**

```python


# ═══ Stage 2 追加（spec §6.3 的 TP 池選擇）═══════════════════════════════
# 既有函式（is_unswept / is_sweep / pick_pool / build_events）已通過 N-G1，
# 一律不改動。以下為新增。

def pool_table(bars_df, L):
    """每 symbol 的池表：所有 pivot ＋ 其【第一次被掃穿的棒】。

    swept_at 讓「未被掃過」成為 O(1) 查詢（否則每事件每池都要掃一次區間）。
    掃穿判定用嚴格不等號，與 is_sweep 一致（P5）：
      pivot high 被掃穿 ⟺ ∃k > idx，high[k] > price
      pivot low  被掃穿 ⟺ ∃k > idx，low[k]  < price
    從未被掃穿 → swept_at = len(bars)（哨兵值，永遠大於任何 j）。

    回傳依 confirm_t 排序的 DataFrame(idx, kind, price, t, confirm_t, swept_at)。
    """
    df = bars_df.reset_index(drop=True)
    hi = df["h"].to_numpy(dtype=float)
    lo = df["l"].to_numpy(dtype=float)
    n = len(df)
    rows = []
    for p in det.find_pivots(df, L):
        price = float(p.price)
        if p.kind == "high":
            m = hi[p.idx + 1:] > price
        else:
            m = lo[p.idx + 1:] < price
        swept = p.idx + 1 + int(np.argmax(m)) if m.any() else n
        rows.append(dict(idx=int(p.idx), kind=p.kind, price=price,
                         t=int(p.t), confirm_t=int(p.confirm_t),
                         swept_at=int(swept)))
    cols = ["idx", "kind", "price", "t", "confirm_t", "swept_at"]
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values("confirm_t", kind="stable").reset_index(drop=True)


def selectable_pools(pool_tbl, kind, as_of, j, n_last):
    """P9：as_of 時【已確認】且【尚未被掃過】的同側池，取最近 n_last 個。

    swept_at > j 才算未被掃過——掃單棒 j 本身算在內。
    """
    m = ((pool_tbl["kind"] == kind)
         & (pool_tbl["confirm_t"] <= int(as_of))
         & (pool_tbl["swept_at"] > int(j)))
    out = pool_tbl[m]
    return out.tail(int(n_last)).reset_index(drop=True)
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_pools.py -v --basetemp=/tmp/nt5`
Expected: PASS（9 passed）

- [ ] **Step 5: 確認既有測試未受影響並 commit**

```bash
.venv/bin/pytest tests/test_n_*.py -q --basetemp=/tmp/nt5b     # 應全綠
.venv/bin/pytest tests/test_m_*.py -q --basetemp=/tmp/nt5c     # 應 74 passed
git add scripts/n_sweep.py tests/test_n_pools.py
git commit -m "feat(sweep-n): 池表與 TP 池選擇（swept_at O(1) 查詢）

只追加 pool_table/selectable_pools，既有已過 N-G1 的函式一律不動。
掃穿判定沿用嚴格不等號；未被掃過以 swept_at > j 判定（掃單棒本身算在內）。"
```

---

## Task 6: 訂單流特徵（ABS / DIV）

**Files:** Create `scripts/n_features.py`；Test `tests/test_n_features.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_n_features.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_features as nf


def test_abs_ok_bearish_requires_positive_sweep_delta():
    """spec §5.2：空方掃單，池上方是【主動買】被吸收 -> D_sweep > 0。"""
    assert nf.abs_ok(d_sweep=100.0, direction=-1) is True
    assert nf.abs_ok(d_sweep=-100.0, direction=-1) is False
    assert nf.abs_ok(d_sweep=0.0, direction=-1) is False


def test_abs_ok_bullish_mirrors():
    assert nf.abs_ok(d_sweep=-100.0, direction=+1) is True
    assert nf.abs_ok(d_sweep=100.0, direction=+1) is False


def test_abs_ok_nan_rejects():
    assert nf.abs_ok(d_sweep=float("nan"), direction=-1) is False


def test_div_ok_bearish_requires_cvd_not_higher():
    """spec §5.3：價格創了比池更高的高點，但 CVD 沒有同步創高。"""
    assert nf.div_ok(cvd_j=50.0, cvd_pool=100.0, direction=-1) is True
    assert nf.div_ok(cvd_j=100.0, cvd_pool=100.0, direction=-1) is True   # <= 含等號
    assert nf.div_ok(cvd_j=150.0, cvd_pool=100.0, direction=-1) is False


def test_div_ok_bullish_mirrors():
    assert nf.div_ok(cvd_j=150.0, cvd_pool=100.0, direction=+1) is True
    assert nf.div_ok(cvd_j=50.0, cvd_pool=100.0, direction=+1) is False


def test_div_ok_nan_rejects():
    assert nf.div_ok(cvd_j=float("nan"), cvd_pool=1.0, direction=-1) is False
    assert nf.div_ok(cvd_j=1.0, cvd_pool=float("nan"), direction=-1) is False


def test_arm_pass_composes_flags():
    """spec §9 的四臂。"""
    f = dict(abs_ok=True, div_ok=False)
    assert nf.arm_pass("sweep_only", f) is True
    assert nf.arm_pass("sweep+ABS", f) is True
    assert nf.arm_pass("sweep+DIV", f) is False
    assert nf.arm_pass("sweep+ABS+DIV", f) is False
    f2 = dict(abs_ok=True, div_ok=True)
    assert nf.arm_pass("sweep+ABS+DIV", f2) is True


def test_arm_pass_rejects_unknown_arm():
    with pytest.raises(KeyError):
        nf.arm_pass("sweep+MAGIC", dict(abs_ok=True, div_ok=True))


def test_cvd_at_returns_nan_outside_range():
    bars = pd.DataFrame({"t": [0, 3600000], "cvd": [1.0, 2.0]})
    assert nf.cvd_at(bars, 0) == 1.0
    assert nf.cvd_at(bars, 3600000) == 2.0
    assert np.isnan(nf.cvd_at(bars, 7200000))
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_features.py -v --basetemp=/tmp/nt6`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_features'`

- [ ] **Step 3: 實作**

```python
# scripts/n_features.py
"""Sub-project N — 訂單流確認特徵。spec §5。

【全部無自由參數】——ABS 只取 D_sweep 的符號、DIV 只做兩個 CVD 值的比較。
幅度門檻會推高試驗數且（依 M 的教訓）買到的是勝率不是期望值，故一律不設。
|D_sweep| 與 D_sweep/V_sweep 的分布只落檔揭露。

缺值一律判否（P13），兩臂同規則。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
import n_orderflow as of  # noqa: E402

ARM_REQUIRES = {
    "sweep_only": (),
    "sweep+ABS": ("abs_ok",),
    "sweep+DIV": ("div_ok",),
    "sweep+ABS+DIV": ("abs_ok", "div_ok"),
}


def abs_ok(d_sweep, direction):
    """spec §5.2：掃單腿的主動流方向與交易方向【相反】＝被吸收。

    空方掃單（direction=-1，做空）：池上方是主動【買】被吸收 → D_sweep > 0
    多方掃單（direction=+1，做多）：池下方是主動【賣】被吸收 → D_sweep < 0
    """
    d = float(d_sweep)
    if not np.isfinite(d):
        return False
    return bool(d > 0 if direction == -1 else d < 0)


def div_ok(cvd_j, cvd_pool, direction):
    """spec §5.3：價格創了比池更極端的值，但累積 delta 沒有同步跟上。

    空方掃單：CVD_j <= CVD_pool（價更高但買盤沒更強）
    多方掃單：CVD_j >= CVD_pool
    """
    a, b = float(cvd_j), float(cvd_pool)
    if not (np.isfinite(a) and np.isfinite(b)):
        return False
    return bool(a <= b if direction == -1 else a >= b)


def arm_pass(arm, flags):
    """該臂要求的旗標是否全部成立。未知臂別 -> KeyError（不得靜默放行）。"""
    req = ARM_REQUIRES[arm]
    return all(bool(flags[k]) for k in req) if req else True


def cvd_at(bars_of, t):
    """逐棒訂單流表在時點 t 的 CVD；查無該棒 -> NaN。"""
    m = bars_of["t"].to_numpy() == int(t)
    if not m.any():
        return float("nan")
    return float(bars_of["cvd"].to_numpy()[m][0])


def attach(events, bars_of, trades_by_day, bar_ms):
    """事件表 → 加上 d_sweep / v_sweep / cvd_j / cvd_pool / abs_ok / div_ok。

    trades_by_day：dict(day 'YYYY-MM-DD' -> (trades_df, index))，
    由呼叫端依事件涉及的日期預先載入（避免重複讀檔）。
    缺資料的事件 -> d_sweep = NaN，下游記 nodata（P13）。
    """
    out = events.copy()
    ds, vs = [], []
    for e in out.to_dict("records"):
        day = pd.Timestamp(int(e["t_j"]), unit="ms", tz="UTC").strftime("%Y-%m-%d")
        pair = trades_by_day.get(day)
        if pair is None:
            ds.append(float("nan"))
            vs.append(float("nan"))
            continue
        tr, idx = pair
        d, v = of.sweep_delta(tr, idx, int(e["t_j"]), float(e["pool"]),
                              int(e["direction"]))
        ds.append(d)
        vs.append(v)
    out["d_sweep"] = ds
    out["v_sweep"] = vs
    out["cvd_j"] = [cvd_at(bars_of, t) for t in out["t_j"]]
    out["cvd_pool"] = [cvd_at(bars_of, t) for t in out["pool_t"]]
    out["abs_ok"] = [abs_ok(d, s) for d, s in zip(out["d_sweep"], out["direction"])]
    out["div_ok"] = [div_ok(a, b, s) for a, b, s
                     in zip(out["cvd_j"], out["cvd_pool"], out["direction"])]
    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_features.py -v --basetemp=/tmp/nt6`
Expected: PASS（10 passed）

- [ ] **Step 5: Commit**

```bash
.venv/bin/pytest tests/test_m_*.py -q --basetemp=/tmp/nt6b
git add scripts/n_features.py tests/test_n_features.py
git commit -m "feat(sweep-n): 訂單流確認特徵 ABS/DIV（無自由參數）

ABS 只取 D_sweep 符號、DIV 只比兩個 CVD 值，皆不設幅度門檻——
門檻會推高試驗數且依 M 的教訓買到的是勝率不是期望值。缺值一律判否。"
```

---

## Task 7: 回測引擎

**Files:** Create `scripts/n_backtest.py`；Test `tests/test_n_backtest.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_n_backtest.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_backtest as bt
import n_config as cfg

BAR = 3_600_000


def mk(rows):
    a = np.array(rows, dtype=float)
    return dict(t=np.arange(len(rows), dtype=np.int64) * BAR,
                o=a[:, 0], h=a[:, 1], l=a[:, 2], c=a[:, 3])


def ev(**kw):
    """預設：空方掃單（做空），掃單棒 j=1，針尖 110，pool 100。"""
    base = dict(event_id="e1", symbol="X", interval="1h", j=1,
                t_j=BAR, as_of=2 * BAR - 1, direction=-1, pool=100.0,
                sweep_high=110.0, sweep_low=95.0, close_j=98.0)
    base.update(kw)
    return base


POOLS_LOW = pd.DataFrame({"idx": [0], "kind": ["low"], "price": [80.0],
                          "t": [0], "confirm_t": [BAR - 1], "swept_at": [99]})


def test_sl_is_outside_wick_tip_by_frozen_buffer():
    """spec §6.2：做空 SL = 針尖 x (1 + 0.0011)。"""
    assert bt.stop_price(110.0, -1) == pytest.approx(110.0 * (1 + cfg.SL_BUFFER))
    assert bt.stop_price(90.0, +1) == pytest.approx(90.0 * (1 - cfg.SL_BUFFER))


def test_entry_is_next_bar_open():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 60, 62)]
              + [(62, 63, 61, 62)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["fill"] == pytest.approx(97.0)
    assert r["entry_leg"] == "taker"


def test_tp_is_nearest_unswept_opposite_pool():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 79, 82)]
              + [(82, 83, 81, 82)] * 30)
    pools = pd.DataFrame({"idx": [0, 0], "kind": ["low", "low"],
                          "price": [80.0, 60.0], "t": [0, 0],
                          "confirm_t": [BAR - 1, BAR - 1], "swept_at": [99, 99]})
    r = bt.simulate_event(bars, ev(), pools)
    assert r["exit_reason"] == "tp"
    assert r["exit_px"] == pytest.approx(80.0)      # 取較近的 80，非 60


def test_no_target_when_no_pool_beyond_entry():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 96, 97)]
              + [(97, 98, 96, 97)] * 30)
    pools = pd.DataFrame({"idx": [0], "kind": ["low"], "price": [99.0],
                          "t": [0], "confirm_t": [BAR - 1], "swept_at": [99]})
    r = bt.simulate_event(bars, ev(), pools)   # 池 99 高於 fill 97 -> 做空無效
    assert r["exit_reason"] == "no_target"
    assert r["R_net"] == 0.0


def test_risk_too_small_terminal():
    """fill 貼著 SL（<0.22%）-> risk_too_small，R=0，計入分母。"""
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98),
               (110.0, 111, 109, 110)] + [(110, 111, 109, 110)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "risk_too_small"
    assert r["R_net"] == 0.0


def test_invalidated_by_gap_when_open_beyond_sl():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (120, 121, 119, 120)]
              + [(120, 121, 119, 120)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "invalidated_by_gap"
    assert r["R_net"] == 0.0


def test_sl_priority_within_bar_is_pessimistic():
    """同棒同時觸及 SL 與 TP -> 記 SL（P12）。"""
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 111, 79, 90)]
              + [(90, 91, 89, 90)] * 30)
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "sl"


def test_time_stop_after_max_hold():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98)]
              + [(97, 98, 96, 97)] * (cfg.MAX_HOLD_BARS + 5))
    r = bt.simulate_event(bars, ev(), POOLS_LOW)
    assert r["exit_reason"] == "time_stop"


def test_nodata_when_orderflow_missing():
    bars = mk([(100, 101, 99, 100), (105, 110, 95, 98), (97, 98, 79, 82)]
              + [(82, 83, 81, 82)] * 30)
    r = bt.simulate_event(bars, ev(d_sweep=float("nan")), POOLS_LOW,
                          require_orderflow=True)
    assert r["exit_reason"] == "nodata"
    assert r["R_net"] == 0.0


def test_r_net_anchor_matches_m():
    """沿用 m_backtest.r_net_single，錨例不得變（spec §6.6）。"""
    assert abs(bt.r_net(100, 98, 103, 1) - 0.9925) < 1e-3


def test_bullish_mirror_end_to_end():
    """多方掃單：針尖在下，SL 在針尖下方，TP 取上方最近未掃池。"""
    bars = mk([(100, 101, 99, 100), (95, 105, 90, 102), (103, 121, 102, 120)]
              + [(120, 121, 119, 120)] * 30)
    pools_hi = pd.DataFrame({"idx": [0], "kind": ["high"], "price": [120.0],
                             "t": [0], "confirm_t": [BAR - 1], "swept_at": [99]})
    r = bt.simulate_event(bars, ev(direction=1, pool=100.0, sweep_low=90.0,
                                   sweep_high=105.0, close_j=102.0), pools_hi)
    assert r["fill"] == pytest.approx(103.0)
    assert r["exit_reason"] == "tp"
    assert r["exit_px"] == pytest.approx(120.0)
    assert r["R_net"] > 0
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_backtest.py -v --basetemp=/tmp/nt7`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_backtest'`

- [ ] **Step 3: 實作**

```python
# scripts/n_backtest.py
"""Sub-project N — 回測引擎。spec §6。

進場：掃單棒 j 收盤後，於 bar j+1 開盤市價（taker）。不模擬 Stop 單——
      1h K 線無棒內路徑，假設「觸發價即成交價」是樂觀偏差且無法驗證。
停損：針尖外側，緩衝 SL_BUFFER = 1x round-trip taker（由成本常數導出）。
停利：對側【未被掃過】的最近池；無合格池 -> no_target（P11）。
終局（互斥窮盡，皆有 term_t）：
  tp / sl / time_stop / censored / no_target / risk_too_small /
  invalidated_by_gap / nodata
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
import n_sweep as sw  # noqa: E402
from m_backtest import _first_true, r_net_single  # noqa: E402


def stop_price(tip, direction):
    """SL 置於針尖外側。做空(-1) 針尖是 high；做多(+1) 針尖是 low。"""
    b = cfg.SL_BUFFER
    return float(tip) * (1.0 + b) if direction == -1 else float(tip) * (1.0 - b)


def r_net(entry, sl, exit_px, direction, stress=1.0):
    """兩腿皆 taker（spec §6.6）。沿用 M 的記帳，錨例不變。"""
    return r_net_single(entry, sl, exit_px, direction, "taker", stress)


def pick_tp(pools_side, fill, direction):
    """對側未被掃過的池中，取【在進場價之外且最接近】的一個（P10）。

    做空(-1)：取低於 fill 的最高者；做多(+1)：取高於 fill 的最低者。
    無合格者 -> NaN。
    """
    if pools_side is None or len(pools_side) == 0:
        return float("nan")
    p = pools_side["price"].to_numpy(dtype=float)
    p = p[p < float(fill)] if direction == -1 else p[p > float(fill)]
    if p.size == 0:
        return float("nan")
    return float(p.max() if direction == -1 else p.min())


def _scan_exit(b, s, j0, j1, sl, tp):
    """[j0, j1) 內第一個 SL/TP 命中。棒內 SL 優先（悲觀，P12）；
    SL gap-through 取開盤（較差），TP 恆取 tp。回 (idx, reason, px)。"""
    lo, hi, op = b["l"][j0:j1], b["h"][j0:j1], b["o"][j0:j1]
    sl_hit = (hi >= sl) if s == -1 else (lo <= sl)
    tp_hit = (lo <= tp) if s == -1 else (hi >= tp)
    k = _first_true(sl_hit | tp_hit)
    if k < 0:
        return -1, "", 0.0
    if sl_hit[k]:
        gap = (op[k] >= sl) if s == -1 else (op[k] <= sl)
        return j0 + k, "sl", float(op[k]) if gap else float(sl)
    return j0 + k, "tp", float(tp)


def _term(reason, term_t, **kw):
    d = dict(exit_reason=reason, R_net=0.0, fill=np.nan, entry_leg="",
             exit_px=np.nan, sl=np.nan, tp=np.nan, term_t=int(term_t))
    d.update(kw)
    return d


def simulate_event(bars, e, pool_tbl, stress=1.0, require_orderflow=False):
    """單一掃單事件 → 終局 dict。

    pool_tbl：該 symbol 的池表（n_sweep.pool_table）或已篩好的對側池子集。
    require_orderflow=True 時，e['d_sweep'] 為 NaN 即記 nodata（P13）。
    """
    t = bars["t"]
    n = len(t)
    bar_ms = int(t[1] - t[0]) if n > 1 else 1
    s = int(e["direction"])
    j = int(e["j"])

    def close_t(k):
        return int(t[k]) + bar_ms - 1

    if require_orderflow and not np.isfinite(float(e.get("d_sweep", np.nan))):
        return _term("nodata", e["as_of"])

    jf = j + 1                                   # 成交棒 = 掃單棒的下一根
    if jf >= n:
        return _term("censored", close_t(n - 1))
    fill = float(bars["o"][jf])
    tip = float(e["sweep_high"]) if s == -1 else float(e["sweep_low"])
    sl = stop_price(tip, s)

    if (s == -1 and fill >= sl) or (s == 1 and fill <= sl):
        return _term("invalidated_by_gap", close_t(jf))
    if abs(fill - sl) / abs(fill) < cfg.MIN_RISK_FRAC:
        return _term("risk_too_small", close_t(jf))

    side = "low" if s == -1 else "high"
    pools_side = sw.selectable_pools(pool_tbl, side, int(e["as_of"]), j,
                                     cfg.N_POOLS) \
        if "kind" in getattr(pool_tbl, "columns", []) else pool_tbl
    tp = pick_tp(pools_side, fill, s)
    if not np.isfinite(tp):
        return _term("no_target", close_t(jf), fill=fill, sl=sl)

    j_end = min(jf + cfg.MAX_HOLD_BARS, n)
    jx, reason, px = _scan_exit(bars, s, jf, j_end, sl, tp)
    if jx >= 0:
        return dict(exit_reason=reason, R_net=r_net(fill, sl, px, s, stress),
                    fill=fill, entry_leg="taker", exit_px=px, sl=sl, tp=tp,
                    term_t=close_t(jx))
    j_last = j_end - 1
    px = float(bars["c"][j_last])
    reason = "time_stop" if j_end == jf + cfg.MAX_HOLD_BARS else "censored"
    return dict(exit_reason=reason, R_net=r_net(fill, sl, px, s, stress),
                fill=fill, entry_leg="taker", exit_px=px, sl=sl, tp=tp,
                term_t=close_t(j_last))
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_backtest.py -v --basetemp=/tmp/nt7`
Expected: PASS（11 passed）。
**任何一條失敗一律回報 BLOCKED——不准改測試的 K 線數字或放寬判定。**

- [ ] **Step 5: Commit**

```bash
.venv/bin/pytest tests/test_m_*.py -q --basetemp=/tmp/nt7b
git add scripts/n_backtest.py tests/test_n_backtest.py
git commit -m "feat(sweep-n): 回測引擎（針尖外 SL / 對側未掃池 TP / 八終局）

進場恆為次棒開盤 taker；SL 緩衝與風險守門皆由凍結成本常數導出；
TP 取對側未被掃過且在進場價之外的最近池，無合格者記 no_target（R=0
計入分母，不得改用固定 R:R 代替）。棒內 SL 優先（悲觀）。"
```

---

## Task 8: 對照組與曝險對齊

**Files:** Create `scripts/n_control.py`、`scripts/n_stats.py`；Test `tests/test_n_control.py`

- [ ] **Step 1: 寫失敗測試**

```python
# tests/test_n_control.py
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_control as nc
import n_features as nf
import n_stats as ns


def test_control_arm_uses_identical_filter_function_object():
    """結構性公平保證：兩臂共用同一個函式物件，不是兩份平行實作。"""
    assert nc.FILTER_ENTRYPOINT is nf.arm_pass


def test_weights_renormalize_to_one_per_parent():
    """P15：每個母事件的存活對照，權重合計恰為 1。"""
    ct = pd.DataFrame({"parent_id": ["a", "a", "a", "b", "b"],
                       "R_net": [1.0, 2.0, 3.0, 4.0, 5.0]})
    out = nc.renormalize_weights(ct)
    s = out.groupby("parent_id")["weight"].sum()
    assert s.min() == pytest.approx(1.0) and s.max() == pytest.approx(1.0)


def test_weights_handle_single_survivor():
    ct = pd.DataFrame({"parent_id": ["a"], "R_net": [1.0]})
    assert nc.renormalize_weights(ct)["weight"].iloc[0] == pytest.approx(1.0)


def test_exposure_ratio_and_band():
    """P15：曝險比 = 對照加權曝險 / 事件臂事件數，出帶即作廢。"""
    assert ns.exposure_ratio(n_events=100, ctl_weight_sum=100.0) == pytest.approx(1.0)
    assert ns.exposure_ok(1.00) is True
    assert ns.exposure_ok(0.94) is False
    assert ns.exposure_ok(1.06) is False


def test_event_level_mean_is_exposure_invariant():
    """P16：對照臂複製一份（曝險加倍）不改變每事件 E[R]。"""
    ct = pd.DataFrame({"parent_id": ["a", "a"], "R_net": [1.0, 3.0]})
    ct = nc.renormalize_weights(ct)
    m1 = ns.weighted_event_mean(ct)
    ct2 = pd.concat([ct, ct], ignore_index=True)
    ct2 = nc.renormalize_weights(ct2)
    assert ns.weighted_event_mean(ct2) == pytest.approx(m1)


def test_cluster_bootstrap_is_deterministic():
    df = pd.DataFrame({"symbol": ["A"] * 5 + ["B"] * 5,
                       "R_net": list(range(10)), "weight": [1.0] * 10})
    a = ns.cluster_boot_lower95(df, df, "T1", B=200)
    b = ns.cluster_boot_lower95(df, df, "T1", B=200)
    assert a == pytest.approx(b)


def test_cluster_bootstrap_zero_diff_for_identical_arms():
    df = pd.DataFrame({"symbol": ["A"] * 5 + ["B"] * 5,
                       "R_net": list(range(10)), "weight": [1.0] * 10})
    assert ns.cluster_boot_lower95(df, df, "T2", B=200) == pytest.approx(0.0)


def test_control_delta_range_matches_spec():
    import n_config as cfg
    assert cfg.CONTROL_DELTA_MIN == cfg.MAX_HOLD_BARS + 1
    assert cfg.CONTROL_DELTA_MAX == 300
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_control.py -v --basetemp=/tmp/nt8`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_control'`

- [ ] **Step 3: 實作**

```python
# scripts/n_stats.py
"""Sub-project N — 事件層統計。spec §7.3、§7.4。

主要統計量是【每事件 E[R]】而非日報酬均值（P16）——日報酬與交易頻率相依，
跨格比較無效。M2 的 B5 事故即源於此：對照臂曝險達事件臂的 1.19~7.52 倍時，
兩臂皆負 EV 的逐日配對差會機械性轉正。

自助法以 symbol 為叢集重抽（P17），尊重同幣事件的相依性。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
from m_stats import gate_rng  # noqa: E402


def exposure_ratio(n_events, ctl_weight_sum):
    return float(ctl_weight_sum) / max(float(n_events), 1e-12)


def exposure_ok(ratio):
    lo, hi = cfg.EXPOSURE_BAND
    return bool(lo <= float(ratio) <= hi)


def weighted_event_mean(df):
    """加權每事件 E[R]。無 weight 欄視為每列權重 1。"""
    if len(df) == 0:
        return float("nan")
    w = df["weight"].to_numpy(dtype=float) if "weight" in df else np.ones(len(df))
    r = df["R_net"].to_numpy(dtype=float)
    return float((r * w).sum() / max(w.sum(), 1e-12))


def _cluster_stats(df):
    """依 symbol 聚合出 (Σ w·R, Σ w)，供叢集自助法用。"""
    w = df["weight"].to_numpy(dtype=float) if "weight" in df else np.ones(len(df))
    g = pd.DataFrame({"symbol": df["symbol"].to_numpy(),
                      "wr": df["R_net"].to_numpy(dtype=float) * w,
                      "w": w}).groupby("symbol", sort=True).sum()
    return g


def cluster_boot_lower95(arm_a, arm_b, gate_id, B=None):
    """lower_95 of (E[R]_a − E[R]_b)，以 symbol 為叢集重抽。

    arm_b 傳 None 時退化為單臂的 lower_95(E[R])。
    """
    B = cfg.BOOTSTRAP_B if B is None else B
    ga = _cluster_stats(arm_a)
    gb = _cluster_stats(arm_b) if arm_b is not None else None
    syms = sorted(set(ga.index) | (set(gb.index) if gb is not None else set()))
    a_wr = np.array([float(ga["wr"].get(s, 0.0)) for s in syms])
    a_w = np.array([float(ga["w"].get(s, 0.0)) for s in syms])
    if gb is not None:
        b_wr = np.array([float(gb["wr"].get(s, 0.0)) for s in syms])
        b_w = np.array([float(gb["w"].get(s, 0.0)) for s in syms])

    def stat(ix):
        a = a_wr[ix].sum() / max(a_w[ix].sum(), 1e-12)
        if gb is None:
            return a
        return a - b_wr[ix].sum() / max(b_w[ix].sum(), 1e-12)

    rng = gate_rng(gate_id)
    n = len(syms)
    boot = np.array([stat(rng.integers(0, n, n)) for _ in range(int(B))])
    return float(np.percentile(boot, 5.0))
```

```python
# scripts/n_control.py
"""Sub-project N — 匹配隨機對照組與曝險對齊。spec §7。

對照事件在【它自己的】掃單棒上重算訂單流特徵（P14），不沿用母事件的值。
兩臂共用同一個過濾器入口（FILTER_ENTRYPOINT），由測試斷言——公平性是
結構保證，不靠實作者記得。
"""
import hashlib
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import n_config as cfg  # noqa: E402
import n_features as nf  # noqa: E402

FILTER_ENTRYPOINT = nf.arm_pass


def event_rng(event_id):
    h = int(hashlib.sha256(f"{cfg.SEED}:{event_id}".encode()).hexdigest(), 16)
    return np.random.default_rng([cfg.SEED, h % (2 ** 32)])


def make_controls(e, bars, n_bars):
    """單一事件 → 至多 K 個位移對照。價位按 close 比值平移（spec §7.1）。"""
    c = bars["c"]
    j0 = int(e["j"])
    anchor0 = float(c[j0])
    rng = event_rng(e["event_id"])
    out = []
    for k in range(cfg.CONTROL_K):
        placed = False
        for _ in range(10):
            delta = int(rng.integers(cfg.CONTROL_DELTA_MIN,
                                     cfg.CONTROL_DELTA_MAX + 1))
            j = j0 + delta
            if j + 1 + cfg.MAX_HOLD_BARS < n_bars:
                placed = True
                break
        if not placed:
            continue
        scale = float(c[j]) / anchor0
        bar_ms = int(bars["t"][1] - bars["t"][0])
        out.append(dict(
            event_id=f"{e['event_id']}__ctrl{k}", parent_id=e["event_id"],
            symbol=e["symbol"], interval=e["interval"], j=j,
            t_j=int(bars["t"][j]), as_of=int(bars["t"][j]) + bar_ms - 1,
            direction=int(e["direction"]), pool=float(e["pool"]) * scale,
            pool_t=int(bars["t"][j]) - (int(e["t_j"]) - int(e["pool_t"])),
            sweep_high=float(e["sweep_high"]) * scale,
            sweep_low=float(e["sweep_low"]) * scale,
            close_j=float(c[j]), delta_bars=delta))
    return out


def renormalize_weights(ct):
    """P15：每個母事件的存活對照，權重合計恰為 1。

    【必須在過濾之後重算】——沿用生成時的 1/K 會讓被過濾掉的名額憑空消失，
    使對照臂權重總和 < 1、系統性低估對照臂（方向恰好有利事件臂）。
    """
    out = ct.copy()
    out["weight"] = 1.0 / out.groupby("parent_id")["R_net"].transform("size")
    return out
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_control.py -v --basetemp=/tmp/nt8`
Expected: PASS（8 passed）

- [ ] **Step 5: Commit**

```bash
.venv/bin/pytest tests/test_m_*.py -q --basetemp=/tmp/nt8b
git add scripts/n_control.py scripts/n_stats.py tests/test_n_control.py
git commit -m "feat(sweep-n): 對照組、曝險對齊與事件層叢集自助

M2 的 B5 曝險失配事故事前內建防護：主要統計量為每事件 E[R]（曝險不變），
權重於過濾後重新正規化為每母事件合計 1，曝險比須落在 [0.95,1.05]。
兩臂共用同一過濾器函式物件，由測試斷言。"
```

---

## Task 9: 十道 gate 與執行入口

**Files:** Create `scripts/n_gates.py`、`scripts/n_run.py`；Test `tests/test_n_gates.py`

- [ ] **Step 1: 寫失敗測試（判定表機械性）**

```python
# tests/test_n_gates.py
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
import n_gates as ng


def base(**kw):
    d = dict(G0=True, G1=True, G1b=True, G2=True, G3=True, G4=True,
             G5=True, G6=True, G7=True, G8=True)
    d.update(kw)
    return d


def test_all_pass_is_go():
    assert ng.verdict(base()) == "GO"


def test_g8_fail_is_go_with_mechanism_unsupported():
    assert ng.verdict(base(G8=False)) == "GO（機制未獲支持）"


def test_g0_or_g1_fail_voids_everything():
    assert ng.verdict(base(G0=False)) == "作廢"
    assert ng.verdict(base(G1=False)) == "作廢"


def test_exposure_fail_voids_cell():
    assert ng.verdict(base(G1b=False)) == "作廢"


def test_g2_fail_is_nogo_regardless_of_g3():
    assert ng.verdict(base(G2=False, G3=True)) == "NO-GO"
    assert ng.verdict(base(G2=False, G3=False)) == "NO-GO"


def test_g3_fail_is_nogo():
    assert ng.verdict(base(G3=False)) == "NO-GO"


def test_any_of_g4_g5_g7_fail_is_nogo():
    for k in ("G4", "G5", "G7"):
        assert ng.verdict(base(**{k: False})) == "NO-GO"


def test_g6_fail_is_nogo():
    assert ng.verdict(base(G6=False)) == "NO-GO"


def test_verdict_requires_all_keys():
    import pytest
    with pytest.raises(KeyError):
        ng.verdict({"G2": True})
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_n_gates.py -v --basetemp=/tmp/nt9`
Expected: FAIL — `ModuleNotFoundError: No module named 'n_gates'`

- [ ] **Step 3: 實作 `scripts/n_gates.py`**

```python
# scripts/n_gates.py
"""Sub-project N — 十道 gate 的判定表。spec §8.1。

【機械導出，無裁量】。任何需要「判斷一下」的地方都是設計錯誤——
若判定表無法涵蓋某個結果組合，停下來修 spec，不要在此加特例。
"""
GATE_KEYS = ("G0", "G1", "G1b", "G2", "G3", "G4", "G5", "G6", "G7", "G8")


def verdict(g):
    """spec §8.1 判定表。缺任何一把鑰匙 -> KeyError（不得靜默預設 True）。"""
    v = {k: bool(g[k]) for k in GATE_KEYS}
    if not (v["G0"] and v["G1"]):
        return "作廢"
    if not v["G1b"]:
        return "作廢"
    if not v["G2"]:
        return "NO-GO"
    if not v["G3"]:
        return "NO-GO"
    if not (v["G4"] and v["G5"] and v["G6"] and v["G7"]):
        return "NO-GO"
    return "GO" if v["G8"] else "GO（機制未獲支持）"
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_n_gates.py -v --basetemp=/tmp/nt9`
Expected: PASS（9 passed）

- [ ] **Step 5: 實作 `scripts/n_run.py`（執行入口，無單元測試——由實跑驗收）**

> 本步驟的程式碼較長且需與真實資料互動。**由主對話撰寫並實跑**，
> subagent 執行到 Step 4 即停，回報後等待指示。

- [ ] **Step 6: Commit（只 commit gate 判定表）**

```bash
.venv/bin/pytest tests/test_m_*.py -q --basetemp=/tmp/nt9b
git add scripts/n_gates.py tests/test_n_gates.py
git commit -m "feat(sweep-n): 十道 gate 的判定表（機械導出，無裁量）

G0/G1 或曝險 G1b 不過即作廢；G2 不過即 NO-GO（不論 G3）；
全過但 G8（吸收的邊際貢獻）不過 -> GO（機制未獲支持），
verdict 須揭露 edge 來自 sweep 結構而非訂單流。"
```

---

## Stage 2 驗收（主對話親跑）

```bash
.venv/bin/pytest tests/test_n_*.py -q          # N 全部測試
.venv/bin/pytest tests/test_m_*.py -q          # Expected: 74 passed
git diff --stat main -- scripts/m_*.py tests/test_m_*.py    # Expected: 空
git diff --stat HEAD~5 -- scripts/n_config.py scripts/n_data.py \
    scripts/n_orderflow.py scripts/n_reconcile.py           # Expected: 空（Stage 1 凍結）
```

Stage 3（實跑四臂、十道 gate、verdict）另立。
