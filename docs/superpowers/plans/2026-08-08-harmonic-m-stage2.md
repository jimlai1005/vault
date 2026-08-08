# Sub-project M Stage 2（回測層 + 對照組 + M-G2~G7 gate）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Stage 1 的事件表之上建出事件回測、匹配隨機對照組與 M-G2~G7 判定，產出 `reports/harmonic-m-verdict.md` 的全部輸入數字。

**Architecture:** 三個新模組。`m_backtest.py` 把單一事件模擬成終局與 R_net（numpy 向量化視窗掃描，無逐 bar python 迴圈）；`m_control.py` 為 primary 設定的事件生成 K=5 匹配對照並做日曆對齊；`m_gates.py` 在共用日報酬序列上算六個 gate 與判定表。另有 `m_events_grid.py` 一次性產出 4 個 TOL 檔位的事件表（M-G4 的 480 cells 需要）。

**Tech Stack:** Python 3、numpy、pandas、pyarrow。沿用主 `.venv`。統計沿用 `scripts/cta_l_stage1_gates.py`（stationary bootstrap）與 `scripts/k_gates_eval.py`（deflated_sharpe）。

**Spec:** [`2026-08-06-harmonic-pattern-design.md`](../specs/2026-08-06-harmonic-pattern-design.md)（**v3.3**）。§4.5、§5、§6 是本 Stage 的憲法；**spec 沒寫的參數選擇是 bug——回報並停下，不要發明**。

**紅線：** 全部唯讀研究。不碰 `src/hlvault/`、`deploy/`、任何 `.env*`。本 Stage **零網路**——K 線與事件表全在 `data/cache/harmonic_m/`，宇宙用 `universe_schedule.json`，**禁止重打 exchangeInfo**（spec §7.1 v3.3）。測試全離線。

**已知量級**（2026-08-08 實測）：宇宙內事件 15m 138,284 / 1h 35,833 / 4h 9,393；holdout 幣 49/97。primary（1h tol05）＋對照 K=5 ≈ 21.5 萬次模擬；全 cells ≈ 依 TOL 放寬另計。引擎以「每事件一組 numpy 切片運算」設計，禁逐 bar python 迴圈。

---

## 預先釘死的三個詮釋（spec 留白處，實作前公告）

以下三處 spec 未逐字釘死，本計畫預註冊如下、verdict 必須揭露：

1. **gap-through 的 TP 側**：spec §4.5.4 說「gap-through 取較差價」。SL 側取較差 = 跳空穿越時以**開盤價**出場（比 sl 更差）；TP 側取較差 = **恆以 tp 價**出場（跳空開在 tp 之外時不取更好的開盤價）。
2. **模式 B 的 TTL 語意**：spec §5.1「若 TTL 內不存在這樣的 pivot → no_fill」讀為「**D pivot 的 bar（idx_D）須落在 as_of 後 TTL_BARS 根內**」；其確認（idx_D + L）與進場可以晚於 TTL 窗——那正是模式 B 要量的等待代價。
3. **selected 子集的決定域**：spec §6.5 的 `selected` 在 **primary 設定（1h, tol05, 模式 A, TP1 全出）的 IS** 上決定一次，同一子集套用到全部 cells 的 selected 層。

---

## File Structure

| 檔案 | 責任 |
|---|---|
| `scripts/m_backtest.py` | bars 快取載入 → `simulate_event()`（模式 A/B × 兩出場變體 × 八終局 × 成本）→ `run_events()` 批次 → trades 表 |
| `scripts/m_stats.py` | 日報酬序列 `daily_series()`、`lower_95()`、`daily_sr()`、bootstrap 包裝（seed 派生） |
| `scripts/m_control.py` | primary 事件 → K=5 對照（決定性 RNG、δ 抽樣、比值平移、K_actual）→ 對照 trades → 日曆對齊序列 |
| `scripts/m_events_grid.py` | 4 TOL × 3 interval 事件表生成（快取命中、含 in_universe），供 M-G4 的 cells |
| `scripts/m_gates.py` | M-G2~G7、判定表、`results/m_gates_results.json` |
| `scripts/m_run_stage2.py` | 執行入口：cells 回測 → primary＋對照 → gates → 端點敏感度 |
| `tests/test_m_backtest.py` | 引擎：合成路徑逐終局、成本錨例 1.464175 / 0.7145875、fill 規則 |
| `tests/test_m_stats.py` | `lower_95` 錨例 −0.150005、r_d 聚合、sr ddof=1 |
| `tests/test_m_control.py` | 決定性、δ 範圍、比值平移、日曆對齊等長 |
| `tests/test_m_nolookahead.py` | **附加**回測層截斷斷言（spec §6.2 斷言 2） |
| `tests/test_m_gates.py` | 合成序列上的 gate 判定、判定表分支、N_OBSERVABLE assert |

---

## Task 1: 回測引擎核心（模式 A、TP1 全出、八終局）

**Files:**
- Create: `scripts/m_backtest.py`
- Test: `tests/test_m_backtest.py`

- [ ] **Step 1: 寫失敗的測試**

建立 `tests/test_m_backtest.py`：

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd
import pytest

import m_config as cfg
import m_backtest as bt

H = 3_600_000


def _bars(rows):
    """rows: list of (o, h, l, c)；t 從 0 起每根 1h。"""
    df = pd.DataFrame(rows, columns=["o", "h", "l", "c"])
    df.insert(0, "t", [i * H for i in range(len(rows))])
    df["v"] = 1.0
    df["qv"] = 1.0
    return df


def _ev(**kw):
    """最小事件。as_of = 收盤時間戳（bar0 的收盤 = H-1）→ bar1 起可交易。"""
    base = dict(event_id="E", symbol="X", interval="1h", pattern="gartley",
                direction=1, as_of=H - 1, prz_low=95.0, prz_high=100.0,
                sl=90.0, p_X=80.0, p_A=120.0, p_B=95.0, p_C=110.0)
    base.update(kw)
    return base


def test_prz_already_breached():
    # 確認棒（bar0）收盤 99 <= prz_high 100 → 不掛單
    bars = _bars([(101, 102, 98, 99)] + [(99, 100, 98, 99)] * 5)
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "prz_already_breached"
    assert r["R_net"] == 0.0
    assert r["term_t"] == H - 1                      # as_of 當日


def test_maker_fill_then_tp1():
    # bar0 收盤 105（>100 過守門）；bar1 low 觸及 100 → maker 成交；
    # bar2 high 到 tp1 → taker 出場
    ev = _ev()
    extreme = 120.0                                  # max(X,A,B,C)
    d = 100.0
    tp1 = d + cfg.TP_FACTORS[0] * (extreme - d)      # 100 + 0.382*20 = 107.64
    bars = _bars([(104, 106, 103, 105),
                  (103, 104, 99.5, 101),             # low 99.5 <= 100 → fill@100
                  (102, 108, 101, 106)])             # high 108 >= 107.64 → tp1
    r = bt.simulate_event(bars, ev)
    assert r["exit_reason"] == "tp1"
    assert r["fill"] == 100.0 and r["entry_leg"] == "maker"
    # spec §5.3：cost_abs = maker*fill + (taker+slip)*tp1
    cost = cfg.MAKER * 100.0 + (cfg.TAKER + cfg.SLIP) * tp1
    expect = (tp1 - 100.0) / 10.0 - cost / 10.0      # risk = |100-90| = 10
    assert abs(r["R_net"] - expect) < 1e-12
    assert r["term_t"] == bars["t"].iloc[2] + H - 1   # 終止 = 出場棒【收盤】時間


def test_gap_fill_is_taker_and_bar_participates_in_exit():
    # bar1 開盤 97 <= 100（跳空進 PRZ 但 > sl 90）→ taker 成交@97；
    # 同一根 low 89 <= 90 → 同棒 SL（悲觀，M10）
    bars = _bars([(104, 106, 103, 105),
                  (97, 98, 89, 95)])
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "sl"
    assert r["fill"] == 97.0 and r["entry_leg"] == "taker"
    # SL gap-through：開盤 97 > sl → 出在 sl=90
    cost = (cfg.TAKER + cfg.SLIP) * 97.0 + (cfg.TAKER + cfg.SLIP) * 90.0
    expect = (90.0 - 97.0) / 7.0 - cost / 7.0        # risk = |97-90| = 7
    assert abs(r["R_net"] - expect) < 1e-12


def test_invalidated_by_gap():
    # bar1 開盤 89 <= sl 90 → 作廢不進場
    bars = _bars([(104, 106, 103, 105), (89, 95, 88, 94)])
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "invalidated_by_gap"
    assert r["R_net"] == 0.0
    assert r["term_t"] == bars["t"].iloc[1] + H - 1   # 終止 = 跳空棒【收盤】時間


def test_no_fill_after_ttl():
    rows = [(104, 106, 103, 105)] + [(103, 104, 101, 102)] * (cfg.TTL_BARS + 3)
    bars = _bars(rows)
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "no_fill"
    assert r["R_net"] == 0.0
    # 終止日 = TTL 最後一根的收盤
    assert r["term_t"] == bars["t"].iloc[cfg.TTL_BARS] + H - 1


def test_time_stop_exits_at_close():
    rows = [(104, 106, 103, 105), (103, 104, 99.5, 101)]      # bar1 fill@100
    rows += [(101, 102, 100.5, 101.5)] * (cfg.MAX_HOLD_BARS + 5)
    bars = _bars(rows)
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "time_stop"
    j = 1 + cfg.MAX_HOLD_BARS - 1                    # fill 棒起算第 100 根
    assert r["exit_px"] == bars["c"].iloc[j]
    assert r["term_t"] == bars["t"].iloc[j] + H - 1


def test_censored_marks_to_market():
    rows = [(104, 106, 103, 105), (103, 104, 99.5, 101), (101, 103, 100.5, 102.5)]
    bars = _bars(rows)                               # 資料在持倉中結束
    r = bt.simulate_event(bars, _ev())
    assert r["exit_reason"] == "censored"
    assert r["exit_px"] == 102.5                     # 最後收盤 mark-to-market
    assert r["term_t"] == bars["t"].iloc[2] + H - 1


def test_bearish_mirror():
    # bearish：direction=-1，trigger = prz_low，SL 在上方
    ev = _ev(direction=-1, prz_low=100.0, prz_high=105.0, sl=110.0,
             p_X=120.0, p_A=80.0, p_B=105.0, p_C=90.0)
    extreme = 80.0                                   # min(X,A,B,C)
    d = 100.0
    tp1 = d - cfg.TP_FACTORS[0] * (d - extreme)      # 100 - 0.382*20 = 92.36
    bars = _bars([(97, 98, 95, 96),                  # 收盤 96 < trigger 100 → 過守門
                  (98, 100.5, 97, 99),               # high 100.5 >= 100 → fill@100
                  (99, 100, 92, 93)])                # low 92 <= 92.36 → tp1
    r = bt.simulate_event(bars, ev)
    assert r["exit_reason"] == "tp1"
    cost = cfg.MAKER * 100.0 + (cfg.TAKER + cfg.SLIP) * tp1
    expect = (100.0 - tp1) / 10.0 - cost / 10.0
    assert abs(r["R_net"] - expect) < 1e-12


def test_anchor_single_leg():
    """spec §5.3 數值錨例：entry=100, sl=98, exit=103 → R_net = 1.464175。"""
    r = bt.r_net_single(entry=100.0, sl=98.0, exit_px=103.0, direction=1,
                        entry_leg="maker")
    assert abs(r - 1.464175) < 1e-9


def test_stress_multiplier():
    """M-G7：fee×1.5、slip×1.5。"""
    r = bt.r_net_single(entry=100.0, sl=98.0, exit_px=103.0, direction=1,
                        entry_leg="maker", stress=cfg.STRESS_MULT)
    cost = 1.5 * (cfg.MAKER * 100.0 + (cfg.TAKER + cfg.SLIP) * 103.0)
    assert abs(r - ((103.0 - 100.0) / 2.0 - cost / 2.0)) < 1e-12
```

- [ ] **Step 2: 跑 `.venv/bin/pytest tests/test_m_backtest.py -q`**，確認 `ModuleNotFoundError: No module named 'm_backtest'`。

- [ ] **Step 3: 實作 `scripts/m_backtest.py`**

```python
"""Sub-project M — 事件回測引擎。spec §4.5、§5。

【向量化契約】每個事件的成交偵測與出場掃描都是 numpy 切片運算，
禁止逐 bar 的 python 迴圈（15m 有 13.8 萬宇宙內事件）。
【八終局】tp1/tp2/sl/time_stop/no_fill/invalidated_by_gap/
prz_already_breached/censored——互斥且窮盡，全部有 term_t，不丟任何樣本。
"""
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402

_BARS_CACHE = {}


def load_bars(symbol, interval):
    """把 K 線載成 numpy dict（每 (symbol, interval) 只讀一次 parquet）。"""
    key = (symbol, interval)
    if key not in _BARS_CACHE:
        df = pd.read_parquet(
            pathlib.Path(cfg.CACHE_DIR) / f"{symbol}_{interval}.parquet")
        _BARS_CACHE[key] = {c: df[c].to_numpy() for c in ("t", "o", "h", "l", "c")}
    return _BARS_CACHE[key]


def _fees(entry_leg, stress=1.0):
    fee_in = cfg.MAKER if entry_leg == "maker" else (cfg.TAKER + cfg.SLIP)
    fee_out = cfg.TAKER + cfg.SLIP
    return fee_in * stress, fee_out * stress


def r_net_single(entry, sl, exit_px, direction, entry_leg, stress=1.0):
    """spec §5.3。錨例：maker 進場 100/sl 98/出 103 → 1.464175。"""
    risk = abs(entry - sl)
    fee_in, fee_out = _fees(entry_leg, stress)
    gross = direction * (exit_px - entry) / risk
    cost = (fee_in * entry + fee_out * exit_px) / risk
    return gross - cost


def r_net_batch(entry, sl, exit1, exit2, direction, entry_leg, stress=1.0):
    """spec §4.5.4。錨例：100/98/101/102 maker → 0.7145875。
    fee_in 全額收一次；各出場腿按半額收。"""
    risk = abs(entry - sl)
    fee_in, fee_out = _fees(entry_leg, stress)
    gross = 0.5 * direction * (exit1 - entry) / risk \
        + 0.5 * direction * (exit2 - entry) / risk
    cost = (fee_in * entry + 0.5 * fee_out * exit1 + 0.5 * fee_out * exit2) / risk
    return gross - cost


def _first_true(mask):
    """mask 中第一個 True 的索引；全 False 回 -1。"""
    idx = int(np.argmax(mask))
    return idx if mask[idx] else -1


def _scan_exit(b, s, j0, j1, sl, tp):
    """[j0, j1) 內找第一個 SL/TP 命中。回 (bar_idx, reason, exit_px)；無 → (-1,,)。
    棒內優先序 SL → TP（悲觀）；SL gap-through 取開盤（較差）、TP 恆取 tp。"""
    lo, hi, op = b["l"][j0:j1], b["h"][j0:j1], b["o"][j0:j1]
    sl_hit = (lo <= sl) if s == 1 else (hi >= sl)
    tp_hit = (hi >= tp) if s == 1 else (lo <= tp)
    any_hit = sl_hit | tp_hit
    k = _first_true(any_hit)
    if k < 0:
        return -1, "", 0.0
    if sl_hit[k]:                                     # SL 優先（悲觀）
        gap = (op[k] <= sl) if s == 1 else (op[k] >= sl)
        return j0 + k, "sl", float(op[k]) if gap else float(sl)
    return j0 + k, "tp", float(tp)


def simulate_event(bars_df, ev, exit_variant="tp1_full", mode="A",
                   stress=1.0, pivots=None):
    """單一事件 → dict(exit_reason, R_net, fill, entry_leg, exit_px, term_t)。

    bars_df：DataFrame（測試用）或 load_bars 的 numpy dict。
    模式 B 需傳 pivots（該 symbol/interval/L 的 find_pivots 結果）。
    """
    b = bars_df if isinstance(bars_df, dict) else \
        {c: bars_df[c].to_numpy() for c in ("t", "o", "h", "l", "c")}
    t = b["t"]
    n = len(t)
    bar_ms = int(t[1] - t[0]) if n > 1 else 1
    s = int(ev["direction"])
    trigger = float(ev["prz_high"] if s == 1 else ev["prz_low"])
    sl = float(ev["sl"])

    def close_t(j):
        return int(t[j]) + bar_ms - 1

    # 確認棒 = 收盤時間 == as_of 的那根
    i0 = int(np.searchsorted(t, ev["as_of"], side="right"))   # 第一根可交易 bar
    ic = i0 - 1
    if ic < 0 or i0 >= n:
        return dict(exit_reason="no_fill", R_net=0.0, fill=np.nan,
                    entry_leg="", exit_px=np.nan,
                    term_t=int(ev["as_of"]))
    # 前置守門（spec §4.5.1）
    if s * (b["c"][ic] - trigger) <= 0:
        return dict(exit_reason="prz_already_breached", R_net=0.0, fill=np.nan,
                    entry_leg="", exit_px=np.nan, term_t=int(ev["as_of"]))

    # ── 成交（模式 A：PRZ 限價；模式 B：D 確認後市價）───────────────────
    if mode == "A":
        j1 = min(i0 + cfg.TTL_BARS, n)
        op, lo, hi = b["o"][i0:j1], b["l"][i0:j1], b["h"][i0:j1]
        gap = (op <= trigger) if s == 1 else (op >= trigger)
        touch = (lo <= trigger) if s == 1 else (hi >= trigger)
        k = _first_true(gap | touch)
        if k < 0:
            return dict(exit_reason="no_fill", R_net=0.0, fill=np.nan,
                        entry_leg="", exit_px=np.nan, term_t=close_t(j1 - 1))
        jf = i0 + k
        if gap[k]:
            if (s == 1 and b["o"][jf] <= sl) or (s == -1 and b["o"][jf] >= sl):
                return dict(exit_reason="invalidated_by_gap", R_net=0.0,
                            fill=np.nan, entry_leg="", exit_px=np.nan,
                            term_t=close_t(jf))
            fill, entry_leg = float(b["o"][jf]), "taker"
        else:
            fill, entry_leg = trigger, "maker"
    else:                                             # 模式 B
        want_kind = "low" if s == 1 else "high"
        prz_lo, prz_hi = float(ev["prz_low"]), float(ev["prz_high"])
        idx_c = int(np.searchsorted(t, ev["t_C"]))
        ttl_end_idx = i0 + cfg.TTL_BARS               # D 的 bar 須在 TTL 窗內（預釘 2）
        cand = [p for p in (pivots or [])
                if p.idx > idx_c and p.kind == want_kind
                and prz_lo <= p.price <= prz_hi and p.idx < ttl_end_idx]
        if not cand:
            return dict(exit_reason="no_fill", R_net=0.0, fill=np.nan,
                        entry_leg="", exit_px=np.nan,
                        term_t=close_t(min(ttl_end_idx, n) - 1))
        d_piv = cand[0]                               # 第一個，不挑選
        je = int(np.searchsorted(t, d_piv.confirm_t, side="right"))
        if je >= n:
            return dict(exit_reason="no_fill", R_net=0.0, fill=np.nan,
                        entry_leg="", exit_px=np.nan, term_t=close_t(n - 1))
        jf, fill, entry_leg = je, float(b["o"][je]), "taker"

    # ── 出場（自 fill 棒起，MAX_HOLD 根）────────────────────────────────
    extreme = max(ev["p_X"], ev["p_A"], ev["p_B"], ev["p_C"]) if s == 1 \
        else min(ev["p_X"], ev["p_A"], ev["p_B"], ev["p_C"])
    d_px = fill
    leg = abs(extreme - d_px)
    f1, f2 = (cfg.TP_FACTORS_SHARK if ev["pattern"] == "shark"
              else cfg.TP_FACTORS)
    tp1 = d_px + s * f1 * leg
    tp2 = d_px + s * f2 * leg
    j_end = min(jf + cfg.MAX_HOLD_BARS, n)

    if exit_variant == "tp1_full":
        jx, reason, px = _scan_exit(b, s, jf, j_end, sl, tp1)
        if jx >= 0:
            rn = r_net_single(fill, sl, px, s, entry_leg, stress)
            return dict(exit_reason="tp1" if reason == "tp" else "sl",
                        R_net=rn, fill=fill, entry_leg=entry_leg,
                        exit_px=px, term_t=close_t(jx))
        j_last = j_end - 1
        px = float(b["c"][j_last])
        reason = "time_stop" if j_end == jf + cfg.MAX_HOLD_BARS else "censored"
        rn = r_net_single(fill, sl, px, s, entry_leg, stress)
        return dict(exit_reason=reason, R_net=rn, fill=fill,
                    entry_leg=entry_leg, exit_px=px, term_t=close_t(j_last))

    # 分批變體（spec §4.5.4）：leg1 tp1；tp1 觸及後 SL 移損益兩平，leg2 掃 tp2
    fee_in, fee_out = _fees(entry_leg, stress)
    jx, reason, px1 = _scan_exit(b, s, jf, j_end, sl, tp1)
    if jx < 0 or reason == "sl":                      # tp1 未觸及 → 退化為單腿
        if jx >= 0:                                   # sl
            rn = r_net_single(fill, sl, px1, s, entry_leg, stress)
            return dict(exit_reason="sl", R_net=rn, fill=fill,
                        entry_leg=entry_leg, exit_px=px1, term_t=close_t(jx))
        j_last = j_end - 1
        px = float(b["c"][j_last])
        reason = "time_stop" if j_end == jf + cfg.MAX_HOLD_BARS else "censored"
        rn = r_net_single(fill, sl, px, s, entry_leg, stress)
        return dict(exit_reason=reason, R_net=rn, fill=fill,
                    entry_leg=entry_leg, exit_px=px, term_t=close_t(j_last))
    breakeven = fill * (1 + s * (fee_in + fee_out))
    jx2, reason2, px2 = _scan_exit(b, s, jx, j_end, breakeven, tp2)
    if jx2 < 0:
        j_last = j_end - 1
        px2 = float(b["c"][j_last])
        reason2 = "time_stop" if j_end == jf + cfg.MAX_HOLD_BARS else "censored"
        jx2 = j_last
    rn = r_net_batch(fill, sl, px1, px2, s, entry_leg, stress)
    return dict(exit_reason=f"tp1+{'tp2' if reason2 == 'tp' else reason2}",
                R_net=rn, fill=fill, entry_leg=entry_leg, exit_px=px2,
                term_t=close_t(jx2))


def run_events(events, mode="A", exit_variant="tp1_full", stress=1.0,
               pivots_by_key=None):
    """事件表 → trades DataFrame。events 必須已過 in_universe 過濾。"""
    out = []
    for (sym, iv), grp in events.groupby(["symbol", "interval"], sort=False):
        b = load_bars(sym, iv)
        for ev in grp.to_dict("records"):
            piv = None
            if mode == "B":
                piv = pivots_by_key[(sym, iv, int(ev["pivot_length"]))]
            r = simulate_event(b, ev, exit_variant=exit_variant, mode=mode,
                               stress=stress, pivots=piv)
            r.update(event_id=ev["event_id"], symbol=sym, interval=iv,
                     pattern=ev["pattern"], as_of=int(ev["as_of"]))
            out.append(r)
    return pd.DataFrame(out)
```

- [ ] **Step 4: 跑 `.venv/bin/pytest tests/test_m_backtest.py -q`**
Expected: `10 passed`
<!-- 2026-08-08 errata：兩個 term_t 斷言原誤寫開盤時間（與其他四個測試及 F3 的收盤語意矛盾），Task 1 BLOCKED 後修正；「11 passed」為計數錯誤，實為 10 個測試。 -->

- [ ] **Step 5: Commit**

```bash
git add scripts/m_backtest.py tests/test_m_backtest.py
git commit -m "feat(harmonic): Stage 2 回測引擎 — 模式 A、八終局、成本錨例"
```

---

## Task 2: 分批變體與模式 B 的測試

**Files:**
- Modify: `tests/test_m_backtest.py`（附加）

- [ ] **Step 1: 附加測試**

```python
def test_anchor_batch():
    """spec §4.5.4 錨例：100/98/101/102 → 0.7145875；誤讀版 0.7183375 必須被拒。"""
    r = bt.r_net_batch(entry=100.0, sl=98.0, exit1=101.0, exit2=102.0,
                       direction=1, entry_leg="maker")
    assert abs(r - 0.7145875) < 1e-9
    assert abs(r - 0.7183375) > 1e-4


def test_batch_full_path_tp1_then_tp2():
    ev = _ev()
    d, extreme = 100.0, 120.0
    tp1 = d + 0.382 * 20                              # 107.64
    tp2 = d + 0.618 * 20                              # 112.36
    bars = _bars([(104, 106, 103, 105),
                  (103, 104, 99.5, 101),              # fill@100 maker
                  (102, 108, 101, 106),               # tp1 觸及（leg1 出）
                  (106, 113, 105, 112)])              # tp2 觸及（leg2 出）
    r = bt.simulate_event(bars, ev, exit_variant="batch")
    assert r["exit_reason"] == "tp1+tp2"
    expect = bt.r_net_batch(100.0, 90.0, tp1, tp2, 1, "maker")
    assert abs(r["R_net"] - expect) < 1e-12


def test_batch_breakeven_after_tp1():
    ev = _ev()
    tp1 = 107.64
    fee_in, fee_out = cfg.MAKER, cfg.TAKER + cfg.SLIP
    be = 100.0 * (1 + fee_in + fee_out)               # 100.07
    bars = _bars([(104, 106, 103, 105),
                  (103, 104, 99.5, 101),              # fill@100
                  (102, 108, 101, 106),               # tp1 → SL 移 be
                  (105, 106, 100.0, 104)])            # low 100.0 <= be → leg2 出 be
    r = bt.simulate_event(bars, ev, exit_variant="batch")
    assert r["exit_reason"] == "tp1+sl"
    expect = bt.r_net_batch(100.0, 90.0, tp1, be, 1, "maker")
    assert abs(r["R_net"] - expect) < 1e-9


def test_mode_b_enters_after_d_confirmation():
    """模式 B：C 之後第一個方向正確且落在 PRZ 內的 pivot，確認後下一根開盤進場。"""
    import m_detect
    # zigzag：C 之後價格跌入 PRZ 形成 pivot low@6（95–100 內），L=1 → 確認@7，bar8 開盤進場
    path = [105.0, 110.0, 104.0, 108.0, 103.0, 101.0, 97.0, 102.0, 104.0, 106.0,
            108.0, 110.0]
    bars = _bars([(p, p + 0.5, p - 0.5, p) for p in path])
    piv = m_detect.find_pivots(bars, 1)
    ev = _ev(as_of=bars["t"].iloc[4] + H - 1, t_C=bars["t"].iloc[3],
             pivot_length=1, prz_low=95.0, prz_high=100.0)
    r = bt.simulate_event(bars, ev, mode="B", pivots=piv)
    assert r["entry_leg"] == "taker"
    assert r["fill"] == bars["o"].iloc[8]             # pivot@6 確認@7 → bar8 開盤


def test_mode_b_no_qualifying_pivot_is_no_fill():
    import m_detect
    path = [105.0, 110.0, 104.0, 108.0, 107.0, 108.5, 107.5, 109.0, 108.0, 110.0]
    bars = _bars([(p, p + 0.5, p - 0.5, p) for p in path])   # 從未進 PRZ
    piv = m_detect.find_pivots(bars, 1)
    ev = _ev(as_of=bars["t"].iloc[4] + H - 1, t_C=bars["t"].iloc[3],
             pivot_length=1, prz_low=95.0, prz_high=100.0)
    r = bt.simulate_event(bars, ev, mode="B", pivots=piv)
    assert r["exit_reason"] == "no_fill"
```

- [ ] **Step 2: 跑 `.venv/bin/pytest tests/test_m_backtest.py -q`**
Expected: `15 passed`。<!-- errata：Task 1 實為 10 測試，+5 = 15 -->**若模式 B 測試失敗，先手算 fixture 的 pivot 結構再判斷是 fixture 還是引擎的問題，BLOCKED 回報，不要改引擎邏輯。**

- [ ] **Step 3: Commit**

```bash
git add tests/test_m_backtest.py
git commit -m "test(harmonic): 分批變體錨例與模式 B 進場測試"
```

---

## Task 3: 統計層 `m_stats.py`

**Files:**
- Create: `scripts/m_stats.py`
- Test: `tests/test_m_stats.py`

- [ ] **Step 1: 寫失敗的測試**

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd

import m_config as cfg
import m_stats as ms

DAY = 86_400_000


def test_lower_95_anchor():
    """spec §6.1 錨例。"""
    boot = np.arange(10000) / 10000 - 0.2
    assert abs(ms.percentile_lower_95(boot) - (-0.150005)) < 1e-9


def test_daily_series_aggregation():
    """r_d = 0.01 × Σ R_net（同終止日），無事件日補 0，範圍連續。"""
    trades = pd.DataFrame({
        "R_net": [1.0, -0.5, 2.0, 0.0],
        "term_t": [0 * DAY + 5, 0 * DAY + 9, 2 * DAY + 1, 2 * DAY + 2],
        "weight": [1.0, 1.0, 1.0, 1.0]})
    s = ms.daily_series(trades)
    assert list(s.values) == [0.01 * 0.5, 0.0, 0.01 * 2.0]   # 三天連續，中間補 0
    assert len(s) == 3


def test_daily_sr_uses_ddof1():
    r = pd.Series([0.01, -0.02, 0.03, 0.0])
    assert abs(ms.daily_sr(r) - r.mean() / r.std(ddof=1)) < 1e-12


def test_bootstrap_deterministic_per_gate():
    rng_a = ms.gate_rng("M-G2")
    rng_b = ms.gate_rng("M-G2")
    rng_c = ms.gate_rng("M-G3")
    a, b, c = (r.integers(0, 1000, 5).tolist() for r in (rng_a, rng_b, rng_c))
    assert a == b and a != c


def test_lower95_of_mean_smoke():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(0.5, 1.0, 800))
    lo = ms.lower_95_of_mean(x, gate_id="TEST", B=500)
    assert 0.3 < lo < 0.5                             # 均值 0.5 的下界應在其下不遠處
```

- [ ] **Step 2: 確認失敗**（ModuleNotFoundError）

- [ ] **Step 3: 實作 `scripts/m_stats.py`**

```python
"""Sub-project M — 統計層。spec §6.1。

M-G2/G3/G4 全在同一條日報酬序列上計算；Sharpe 一律未年化日 SR（ddof=1）；
lower_95 = percentile method 單尾第 5 百分位。
"""
import hashlib
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cta_l_stage1_gates import stationary_bootstrap_indices  # noqa: E402

DAY_MS = 86_400_000


def percentile_lower_95(boot):
    """spec §6.1：numpy.percentile(boot, 5.0)。錨例 −0.150005。"""
    return float(np.percentile(np.asarray(boot), 5.0))


def daily_sr(r):
    r = pd.Series(r).dropna()
    sd = r.std(ddof=1)
    return float(r.mean() / sd) if sd > 0 else 0.0


def daily_series(trades, weight_col="weight"):
    """trades(R_net, term_t[, weight]) → 連續 UTC 日曆日的 r_d Series。

    r_d = RISK_PER_TRADE × Σ weight·R_net（term_t 所屬日）；無事件日 r_d = 0。
    """
    t = trades.copy()
    if weight_col not in t:
        t[weight_col] = 1.0
    t["day"] = (t["term_t"] // DAY_MS).astype(int)
    g = (t["R_net"] * t[weight_col]).groupby(t["day"]).sum() * cfg.RISK_PER_TRADE
    full = pd.RangeIndex(int(g.index.min()), int(g.index.max()) + 1)
    return g.reindex(full, fill_value=0.0)


def gate_rng(gate_id):
    """spec §6.1：每 gate 以 (SEED, gate_id) 派生子種子，可複現且互不干擾。"""
    h = int(hashlib.sha256(f"{cfg.SEED}:{gate_id}".encode()).hexdigest(), 16)
    return np.random.default_rng([cfg.SEED, h % (2 ** 32)])


def _boot_stat(values, stat_fn, gate_id, B):
    v = np.asarray(values, dtype=float)
    n = len(v)
    rng = gate_rng(gate_id)
    seed = int(rng.integers(0, 2 ** 31 - 1))
    idx = stationary_bootstrap_indices(n, B, cfg.BOOTSTRAP_EXPECTED_BLOCK,
                                       seed=seed)
    return np.array([stat_fn(v[row]) for row in idx])


def lower_95_of_mean(series, gate_id, B=None):
    B = cfg.BOOTSTRAP_B if B is None else B
    boot = _boot_stat(np.asarray(series, dtype=float), np.mean, gate_id, B)
    return percentile_lower_95(boot)


def lower_95_of_paired_diff(series_a, series_b, gate_id, B=None):
    """配對 stationary bootstrap：兩序列等長、逐日對齊，同一組索引重抽。"""
    a = np.asarray(series_a, dtype=float)
    b = np.asarray(series_b, dtype=float)
    assert len(a) == len(b), "配對 bootstrap 要求等長對齊序列（spec §5.4）"
    B = cfg.BOOTSTRAP_B if B is None else B
    boot = _boot_stat(a - b, np.mean, gate_id, B)
    return percentile_lower_95(boot)
```

**注意**：`stationary_bootstrap_indices` 的實際簽名以 [`scripts/cta_l_stage1_gates.py:148`](../../../scripts/cta_l_stage1_gates.py) 為準——實作前先開檔核對參數名（`n, B, expected_block, seed`）與回傳形狀（若回傳的是生成器或 (B, n) 陣列，照實際調整 `_boot_stat` 的迭代方式）。**若簽名不符，照實際簽名改 `_boot_stat`，並在回報中註明**。

- [ ] **Step 4: 跑 `.venv/bin/pytest tests/test_m_stats.py -q`** Expected: `5 passed`
- [ ] **Step 5: Commit** `git add scripts/m_stats.py tests/test_m_stats.py && git commit -m "feat(harmonic): 統計層 — 日報酬序列、lower_95、gate 種子派生"`

---

## Task 4: 對照組 `m_control.py`

**Files:**
- Create: `scripts/m_control.py`
- Test: `tests/test_m_control.py`

- [ ] **Step 1: 寫失敗的測試**

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd

import m_config as cfg
import m_control as mc

H = 3_600_000


def _ev(eid="E1", as_of=1000 * H - 1):
    return dict(event_id=eid, symbol="X", interval="1h", pattern="bat",
                direction=1, as_of=as_of, prz_low=95.0, prz_high=100.0,
                sl=90.0, p_X=80.0, p_A=120.0, p_B=95.0, p_C=110.0)


def _bars(n=2000, seed=5):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.004, n)))
    return pd.DataFrame({"t": [i * H for i in range(n)], "o": close,
                         "h": close * 1.003, "l": close * 0.997, "c": close,
                         "v": 1.0, "qv": 1.0})


def test_deterministic_and_delta_range():
    bars = _bars()
    c1 = mc.make_controls(_ev(), bars)
    c2 = mc.make_controls(_ev(), bars)
    assert [x["delta_bars"] for x in c1] == [x["delta_bars"] for x in c2]
    for x in c1:
        assert cfg.CONTROL_DELTA_MIN <= x["delta_bars"] <= cfg.CONTROL_DELTA_MAX


def test_ratio_shift_preserved():
    bars = _bars()
    ev = _ev()
    ctrls = mc.make_controls(ev, bars)
    t = bars["t"].to_numpy()
    for x in ctrls:
        ic = int(np.searchsorted(t, x["as_of"], side="right")) - 1
        anchor = bars["c"].iloc[ic]
        ic0 = int(np.searchsorted(t, ev["as_of"], side="right")) - 1
        anchor0 = bars["c"].iloc[ic0]
        assert abs(x["prz_high"] / anchor - ev["prz_high"] / anchor0) < 1e-9
        assert abs(x["sl"] / anchor - ev["sl"] / anchor0) < 1e-9


def test_out_of_range_reduces_k_actual():
    bars = _bars(n=1200)                              # 尾端不夠 δ+曝險窗 → 部分捨棄
    ev = _ev(as_of=1150 * H - 1)
    ctrls = mc.make_controls(ev, bars)
    assert len(ctrls) < cfg.CONTROL_K
    for x in ctrls:
        assert x["weight"] == 1.0 / len(ctrls)        # 1/K_actual（spec §5.4）


def test_calendar_alignment_maps_back():
    """對照的日曆對齊：mapped_term_t = term_t − δ·bar_ms（spec §5.4）。"""
    x = dict(delta_bars=150, term_t=500 * H - 1)
    assert mc.mapped_term_t(x, bar_ms=H) == 500 * H - 1 - 150 * H
```

- [ ] **Step 2: 確認失敗**

- [ ] **Step 3: 實作 `scripts/m_control.py`**

```python
"""Sub-project M — 匹配隨機對照組。spec §5.4。

只為通過前置守門的事件生成；δ 只取正向 {131..300}；比值平移不重算；
每事件 RNG 由 (SEED, event_id) 決定性派生（與處理順序無關）。
"""
import hashlib
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg  # noqa: E402


def _event_rng(event_id):
    h = int(hashlib.sha256(f"{cfg.SEED}:{event_id}".encode()).hexdigest(), 16)
    return np.random.default_rng([cfg.SEED, h % (2 ** 32)])


def make_controls(ev, bars_df):
    """單一（已通過守門的）事件 → 至多 K 個對照事件 dict。

    對照欄位與原事件同 schema，另加 delta_bars 與 weight = 1/K_actual。
    窗口超界重抽最多 10 次；仍失敗則捨棄該對照。
    """
    t = bars_df["t"].to_numpy() if not isinstance(bars_df, dict) else bars_df["t"]
    c = bars_df["c"].to_numpy() if not isinstance(bars_df, dict) else bars_df["c"]
    n = len(t)
    bar_ms = int(t[1] - t[0])
    ic0 = int(np.searchsorted(t, ev["as_of"], side="right")) - 1
    anchor0 = float(c[ic0])
    need = cfg.TTL_BARS + cfg.MAX_HOLD_BARS           # 曝險窗
    rng = _event_rng(ev["event_id"])
    out = []
    for k in range(cfg.CONTROL_K):
        ok = False
        for _ in range(10):
            delta = int(rng.integers(cfg.CONTROL_DELTA_MIN,
                                     cfg.CONTROL_DELTA_MAX + 1))
            ic = ic0 + delta
            if ic + 1 + need < n:                     # 完整曝險窗在資料內
                ok = True
                break
        if not ok:
            continue
        anchor = float(c[ic])
        scale = anchor / anchor0
        out.append(dict(
            event_id=f"{ev['event_id']}__ctrl{k}",
            symbol=ev["symbol"], interval=ev["interval"],
            pattern=ev["pattern"], direction=ev["direction"],
            as_of=int(t[ic]) + bar_ms - 1,
            prz_low=ev["prz_low"] * scale, prz_high=ev["prz_high"] * scale,
            sl=ev["sl"] * scale,
            p_X=ev["p_X"] * scale, p_A=ev["p_A"] * scale,
            p_B=ev["p_B"] * scale, p_C=ev["p_C"] * scale,
            delta_bars=delta))
    for x in out:
        x["weight"] = 1.0 / len(out)
    return out


def mapped_term_t(ctrl_trade, bar_ms):
    """spec §5.4 日曆對齊：對照的日報酬記在 term_t − δ·bar_ms。"""
    return int(ctrl_trade["term_t"]) - int(ctrl_trade["delta_bars"]) * bar_ms
```

- [ ] **Step 4: 跑 `.venv/bin/pytest tests/test_m_control.py -q`** Expected: `4 passed`
- [ ] **Step 5: Commit** `git add scripts/m_control.py tests/test_m_control.py && git commit -m "feat(harmonic): 匹配隨機對照組 — 決定性 δ、比值平移、日曆對齊"`

---

## Task 5: M-G1 回測層截斷斷言（spec §6.2 斷言 2）

**Files:**
- Modify: `tests/test_m_nolookahead.py`（附加）

- [ ] **Step 1: 附加測試**

```python
def test_backtest_truncation_only_settled_trades(  # spec §6.2 斷言 2
):
    """對 term_date <= T（完整跑的值）的交易，截斷重跑後逐欄相同。"""
    import m_backtest as bt

    df = _random_walk_bars(n=900, seed=13)
    ev_tbl = m_detect.build_events(df, "BTCUSDT", "1h", do_dedup=True)
    assert len(ev_tbl) > 0
    full = bt.run_events(ev_tbl.assign(in_universe=True))
    cut = int(len(df) * 0.6)
    T = int(df["t"].iloc[cut]) + 3_600_000 - 1

    df_tr = df.iloc[:cut + 1].reset_index(drop=True)
    ev_tr = m_detect.build_events(df_tr, "BTCUSDT", "1h", do_dedup=True)
    # 只比 as_of <= T 的事件（偵測層已由斷言 1 保證一致）
    trunc = bt.run_events(ev_tr[ev_tr["as_of"] <= T])

    full_settled = full[(full["as_of"] <= T) & (full["term_t"] <= T)] \
        .sort_values("event_id").reset_index(drop=True)
    tr_sub = trunc[trunc["event_id"].isin(full_settled["event_id"])] \
        .sort_values("event_id").reset_index(drop=True)
    assert len(tr_sub) == len(full_settled)
    for col in ("exit_reason", "R_net", "fill", "exit_px", "term_t"):
        pd.testing.assert_series_equal(full_settled[col], tr_sub[col],
                                       check_exact=False, rtol=1e-12)
```

**注意**：`run_events` 需要 `load_bars` 讀 parquet——本測試餵的是合成 DataFrame。實作時把 `run_events` 拆出一個 `run_events_on_bars(events, bars_df, ...)` 供測試直接注入 bars（`run_events` 內部呼叫它），**不要在測試裡 monkeypatch 快取**。這是介面調整，允許實作者在 Task 1 的 `run_events` 上做此重構（回報時註明）。

- [ ] **Step 2: 跑 `.venv/bin/pytest tests/test_m_nolookahead.py -q`** Expected: `5 passed`（原 4＋新 1）。**失敗 = 回測層有 look-ahead，BLOCKED 回報，禁止放寬。**
- [ ] **Step 3: Commit** `git add tests/test_m_nolookahead.py scripts/m_backtest.py && git commit -m "test(harmonic): M-G1 回測層截斷斷言（term_date <= T）"`

---

## Task 6: TOL 網格事件表 `m_events_grid.py`

**Files:**
- Create: `scripts/m_events_grid.py`

- [ ] **Step 1: 寫腳本**

```python
"""Sub-project M — TOL 網格事件表（M-G4 的 480 cells 需要）。

對 TOL_GRID 的每個檔位重跑偵測（TOL_AD_XA = 0.6×TOL，spec §4.4），
寫 events_{interval}_tol{NN}.parquet（含 in_universe）。K 線快取命中，零網路。
tol05 的輸出應與 Stage 1 census 的 events_{interval}.parquet 逐列一致（sanity）。

用法：.venv/bin/python scripts/m_events_grid.py
"""
import json
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg      # noqa: E402
import m_census             # noqa: E402
import m_data               # noqa: E402
import m_detect             # noqa: E402

CACHE = pathlib.Path(cfg.CACHE_DIR)


def main():
    universe = {tuple(map(int, k.replace("-Q", " ").split())): set(v)
                for k, v in json.load(open(CACHE / "universe_schedule.json")).items()}
    symbols = sorted({s for v in universe.values() for s in v})
    for tol in cfg.TOL_GRID:
        tol_ad = round(cfg.TOL_AD_RATIO * tol, 6)
        tag = f"tol{int(round(tol * 100)):02d}"
        for interval in cfg.INTERVALS:
            out = CACHE / f"events_{interval}_{tag}.parquet"
            if out.exists():
                print(f"skip {out.name}（已存在）")
                continue
            frames = []
            for sym in symbols:
                df = m_data.load_klines(sym, interval)
                if df.empty:
                    continue
                raw = m_detect.build_events(df, sym, interval,
                                            tol=tol, tol_ad=tol_ad,
                                            do_dedup=False)
                if not raw.empty:
                    frames.append(raw)
            raw = pd.concat(frames, ignore_index=True)
            raw = raw[(raw["as_of"] >= cfg.EVENT_START_MS)
                      & (raw["as_of"] <= cfg.EVENT_END_MS)]
            ded = m_detect.dedup(raw)
            ded["in_universe"] = [
                r.symbol in universe.get(m_census.quarter_of_ms(r.as_of), set())
                for r in ded.itertuples()]
            ded.to_parquet(out, index=False)
            print(f"{out.name}: 去重後 {len(ded)}，宇宙內 {int(ded['in_universe'].sum())}")
    # sanity：tol05 vs census 輸出
    for interval in cfg.INTERVALS:
        a = pd.read_parquet(CACHE / f"events_{interval}_tol05.parquet")
        b = pd.read_parquet(CACHE / f"events_{interval}.parquet")
        assert len(a) == len(b), (interval, len(a), len(b))
    print("sanity: tol05 ≡ census 輸出")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 背景執行**（純計算，預估 30-60 分鐘）

```bash
nohup .venv/bin/python scripts/m_events_grid.py > /private/tmp/claude-501/-Users-jim-projects-vault/0d897fdf-f466-41ac-a40a-70ea2da0a8c0/scratchpad/grid.log 2>&1 &
```

完成後檢查 log 末行有 `sanity: tol05 ≡ census 輸出`，且 12 個 parquet（4 TOL × 3 interval）都存在。

- [ ] **Step 3: Commit** `git add scripts/m_events_grid.py && git commit -m "feat(harmonic): TOL 網格事件表生成（M-G4 cells 輸入）"`

---

## Task 7: Gate 引擎 `m_gates.py`

**Files:**
- Create: `scripts/m_gates.py`
- Test: `tests/test_m_gates.py`

- [ ] **Step 1: 寫失敗的測試**

```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))

import numpy as np
import pandas as pd

import m_config as cfg
import m_gates as mg


def test_verdict_table_branches():
    """spec §6.6 判定表：逐分支窮盡。"""
    g = dict(G2=True, G3=True, G4=True, G5=True, G6=True, G7=True)
    assert mg.verdict(g) == "GO"
    assert mg.verdict({**g, "G3": False}) == "NO-GO"
    assert mg.verdict({**g, "G4": False}) == "NO-GO（多重檢定未通過）"
    assert mg.verdict({**g, "G5": False}) == "NO-GO（過擬合）"
    assert mg.verdict({**g, "G6": False}) == "NO-GO（過擬合）"
    assert mg.verdict({**g, "G7": False}) == "NO-GO（成本邊際）"
    assert mg.verdict({**g, "G2": False}) == "NO-GO"


def test_is_oos_assignment_by_as_of():
    """spec §6.5：歸屬鍵 = as_of；跨界事件屬 IS。"""
    tr = pd.DataFrame({"as_of": [cfg.IS_END_MS - 1, cfg.IS_END_MS + 1],
                       "term_t": [cfg.OOS_START_MS + 5, cfg.OOS_START_MS + 5],
                       "R_net": [1.0, 1.0]})
    assert list(mg.split_is_oos(tr)["is_is"]) == [True, False]


def test_holdout_hash():
    """spec §6.5：sha256(symbol) % 2 == 1 為 holdout，UTF-8。"""
    import hashlib
    for s in ("BTCUSDT", "1000PEPEUSDT"):
        expect = int(hashlib.sha256(s.encode("utf-8")).hexdigest(), 16) % 2 == 1
        assert mg.is_holdout(s) == expect


def test_n_observable_assert():
    """M-G4 的 sr_list 長度必須恰為 480，否則 raise。"""
    import pytest
    with pytest.raises(AssertionError):
        mg.check_sr_list([0.01] * 479)
    mg.check_sr_list([0.01] * 480)
```

- [ ] **Step 2: 確認失敗**

- [ ] **Step 3: 實作 `scripts/m_gates.py`**

```python
"""Sub-project M — M-G2~G7 與判定表。spec §6.3~§6.7。

任何 gate 失敗都不得由作者裁量覆蓋（spec §6.6）。
"""
import hashlib
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_config as cfg      # noqa: E402
import m_stats as ms        # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from k_gates_eval import deflated_sharpe  # noqa: E402


def split_is_oos(trades):
    t = trades.copy()
    t["is_is"] = t["as_of"] <= cfg.IS_END_MS
    return t


def is_holdout(symbol):
    return int(hashlib.sha256(symbol.encode("utf-8")).hexdigest(), 16) % 2 == 1


def check_sr_list(sr_list):
    assert len(sr_list) == cfg.N_OBSERVABLE_TRIALS == 480, (
        f"sr_list={len(sr_list)}，spec §6.3 要求恰為 480")


def gate_g2(series):
    return ms.lower_95_of_mean(series, gate_id="M-G2")


def gate_g3(series_pattern, series_control):
    return ms.lower_95_of_paired_diff(series_pattern, series_control,
                                      gate_id="M-G3")


def gate_g4(sr_list, primary_oos_series):
    check_sr_list(sr_list)
    res = deflated_sharpe(sr_list, pd.Series(primary_oos_series),
                          n_trials_declared=cfg.N_TRIALS_DECLARED)
    return res


def verdict(g):
    """spec §6.6 判定表。g = dict(G2..G7 -> bool)。"""
    if not g["G2"]:
        return "NO-GO"
    if not g["G3"]:
        return "NO-GO"
    if not g["G4"]:
        return "NO-GO（多重檢定未通過）"
    if not (g["G5"] and g["G6"]):
        return "NO-GO（過擬合）"
    if not g["G7"]:
        return "NO-GO（成本邊際）"
    return "GO"
```

**注意**：`k_gates_eval.py` 的 `deflated_sharpe` import 會連帶載入該模組的其他相依——實作前先確認 `import k_gates_eval` 在本 repo 的 `scripts/` 路徑下可獨立載入（它內部 import 的 `daily_sr` 來自 `research_k_vt_v1`）。**若載入失敗（相依斷裂），把 `deflated_sharpe` 的函式體（`scripts/k_gates_eval.py:90-114`）逐字複製到 `m_gates.py` 並註明出處與「逐字複製、未改動」，BLOCKED 升級不需要**——這是 spec 已認可的既有公式重用。

- [ ] **Step 4: 跑 `.venv/bin/pytest tests/test_m_gates.py -q`** Expected: `4 passed`
- [ ] **Step 5: Commit** `git add scripts/m_gates.py tests/test_m_gates.py && git commit -m "feat(harmonic): gate 引擎 — M-G2~G7 與判定表"`

---

## Task 8: 執行入口 `m_run_stage2.py`（主對話親自執行）

**本 task 由主對話執行，不派 haiku**——涉及長時運算的分段判斷與中間結果審視。

- [ ] **Step 1: 寫 `scripts/m_run_stage2.py`**（結構如下，主對話撰寫）：
  1. **cells 回測**：對 480 cells（10 層 × 4 TOL × 3 interval × 2 模式 × 2 出場）各算 OOS 未年化日 Sharpe。同一 (tol, interval, 模式, 出場) 只跑一次全事件回測，pattern 層與合併層、selected 層由 trades 子集聚合。
  2. **primary＋對照**：primary 設定（1h tol05 A tp1_full 合併層）的宇宙內事件 → trades；通過守門者生成 K=5 對照 → 對照 trades → 日曆對齊序列。
  3. **selected 子集**：primary IS 上依 spec §6.5 公式決定（n≥30 且 lower_95>0），落檔揭露。
  4. **六 gate**：M-G2/G3（全期）、M-G4（OOS，sr_list=480 cells）、M-G5（OOS）、M-G6（holdout 全期）、M-G7（stress 全期）。
  5. **兩組消融切片**（spec §6.4，計入 N_TRIALS 的 +2）：在 primary 事件表上
     (i) 只留 `|ratio_ad_xa − 名目值|/名目值 <= 0.03` 的事件；
     (ii) D 落在 X 之外（alt_bat/butterfly/crab/deep_crab/shark）vs 之內
     （gartley/bat/cypher）兩組——各自回測出 OOS Sharpe 與 E[R_net]，揭露用。
  6. **端點敏感度**：IS/OOS 分界 ±7 天重算 M-G5 的 OOS 序列 lower_95，「變號=翻盤」。
  7. 全部結果 → `data/cache/harmonic_m/gates_results.json` ＋ console 摘要。
- [ ] **Step 2: 分段執行與審視**（cells → primary → gates），每段親跑親驗。
- [ ] **Step 3: Commit 腳本與結果摘要。**

---

## Task 9: verdict 報告 `reports/harmonic-m-verdict.md`（主對話撰寫）

**強制內容清單**（spec 各節的揭露義務，寫報告時逐條打勾）：
- [ ] 判定表結果與六 gate 數字（含每個 lower_95、psr）
- [ ] 先驗聲明：「基於成分證偽的高信心先驗」vs「本實測」的區分（spec §1.2）
- [ ] 容差證偽訊號 4×2 表與 Spearman 旗標（spec §4.4）
- [ ] 八終局分布、censored 佔比（>5% 須附排除敏感度）、`prz_already_breached` 率
- [ ] 宇宙內/外事件數、去重前後、多形態 XABC 佔比、對照捨棄數
- [ ] selected 子集內容與（a）全形態 vs（b）子集的 OOS 對照（判定以 a 為準）
- [ ] 模式 A vs B 的差距（等待確認的代價）
- [ ] spec §10 全部 14 條限制逐條回應＋本計畫「預先釘死的三個詮釋」揭露
- [ ] M-G0 的 6/6 與「5 個形態觀測、3 個 fallback」的錨點強度聲明
- [ ] 端點敏感度結果

---

## Task 10: Final review（opus）＋完成判準

- [ ] fresh-context opus 對 Stage 2 全部產出審查（含 gates_results.json 與 verdict 數字對帳、對照組實際分布抽查）
- [ ] 主對話親跑：全測試綠、M-G0/M-G1（含回測層）、gate 數字重現
- [ ] verdict 若為 GO：加跑第二意見（獨立 agent 重做判定，spec 慣例）；GO/NO-GO 與全部證據呈 owner

---

## Stage 2 完成判準

- [ ] `.venv/bin/pytest tests/test_m_*.py -q` 全綠（預估 ~60 tests）
- [ ] M-G1 回測層截斷斷言綠
- [ ] 480 cells 的 sr_list 長度 assert 通過
- [ ] `gates_results.json` 存在且 verdict 由判定表機械導出
- [ ] `reports/harmonic-m-verdict.md` 強制內容清單逐條有落
- [ ] final review 無 BLOCKER
- [ ] git 乾淨
