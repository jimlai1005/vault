# Scalping Phase 0-1 Implementation Plan（sub-project H）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.
> 本 session 慣例：主對話派工、**haiku subagent 逐 task 執行**、fresh-context agent 驗收；
> 主對話不下場寫碼。派工 prompt 用 `~/.claude/rules/prompt-templates.md` 模板 2（實作），
> 把本計畫對應 task 的整段內文貼進 prompt。失敗升級路徑依 delegation.md §5。

**Goal:** 建立 scalping 研究底座（資料抓取＋幣別掃描＋回測核心），跑完 F1/F2/F3 三個
訊號家族的 walk-forward 回測，產出 phase 1 verdict（GO/NO-GO per family）。

**Architecture:** 研究腳本流（非引擎）：`scripts/scalp_lib.py`（資料層）→
`scripts/scalp_backtest_lib.py`（回測核心，有單元測試）→ `scripts/research_scalp_f*.py`
（各家族網格）→ `reports/scalp-phase1-verdict.md`。全部參數網格已預先註冊於本檔，
執行者不得擅自擴充（見 spec §6）。

**Tech Stack:** Python（repo `.venv`）、pandas、requests；資料源 Hyperliquid `/info` REST。
規格細節與 gate 定義見 `docs/superpowers/specs/2026-07-11-scalp-strategy-design.md`（下稱 spec）。

**紅線提醒：** 本 phase 全部唯讀公開資料，不碰鑰匙、不下單。任何腳本不得 import 任何
`.env.carry`/`.env.gridbot`/`.env.momentum`；`userFees` 查詢只用公開地址字串參數。

---

## Task 0: 資料目錄與 gitignore

**Files:** Modify: `.gitignore`；Create: `data/scalp/.gitkeep`

- [ ] **Step 1**: `.gitignore` 加一行 `data/scalp/*`，再加一行 `!data/scalp/.gitkeep`；建立空檔 `data/scalp/.gitkeep`。
- [ ] **Step 2**: 驗證：`git status --short` 顯示 `.gitignore` 與 `.gitkeep`，且之後放進 `data/scalp/` 的 csv 不出現在 status。
- [ ] **Step 3**: Commit：`chore(scalp): data dir scaffolding (sub-project H)`

## Task 1: `scripts/scalp_lib.py` — 資料層

**Files:** Create: `scripts/scalp_lib.py`

實作規格（完整核心程式碼，執行者照抄後補齊 import 與 docstring）：

```python
"""Shared data utilities for sub-project H (scalping research).
Source: Hyperliquid /info REST (public, read-only). candleSnapshot ~5000 bars/req."""
import time
import pandas as pd
import requests

INFO_URL = "https://api.hyperliquid.xyz/info"
SLEEP = 0.5          # pacing, well under info-endpoint rate limits
BAR_MS = 60_000
DATA_DIR = "data/scalp"

def info(payload: dict, retries: int = 5):
    for i in range(retries):
        r = requests.post(INFO_URL, json=payload, timeout=20)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** i)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"info failed after {retries} tries: {payload.get('type')}")

def get_candles(coin: str, interval: str, start_ms: int, end_ms: int) -> list:
    return info({"type": "candleSnapshot", "req": {
        "coin": coin, "interval": interval,
        "startTime": start_ms, "endTime": end_ms}})

def candles_to_df(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ("o", "h", "l", "c", "v"):
        df[col] = df[col].astype(float)
    df["t"] = df["t"].astype("int64")
    df["n"] = df["n"].astype(int)
    df = df.drop_duplicates("t").sort_values("t").reset_index(drop=True)
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df

def pull_1m_history(coin: str, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Paged pull, 5000-bar windows; jumps over empty windows (pre-listing gaps)."""
    rows, cur = [], start_ms
    while cur < end_ms:
        win_end = min(cur + 5000 * BAR_MS, end_ms)
        batch = get_candles(coin, "1m", cur, win_end)
        time.sleep(SLEEP)
        if not batch:
            cur = win_end
            continue
        rows.extend(batch)
        last_t = max(int(b["t"]) for b in batch)
        cur = max(last_t + BAR_MS, cur + BAR_MS)
    return candles_to_df(rows)

def find_earliest_1m(coin: str, floor: str = "2023-01-01") -> int | None:
    """30-day window probe; then backward refine (do not assume server returns
    range-earliest first when >5000 bars in range)."""
    cur = int(pd.Timestamp(floor, tz="UTC").timestamp() * 1000)
    now = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    while cur < now:
        batch = get_candles(coin, "1m", cur, cur + 30 * 24 * 60 * BAR_MS)
        time.sleep(SLEEP)
        if batch:
            first_t = int(batch[0]["t"])
            while True:
                probe = get_candles(coin, "1m", cur, first_t - 1)
                time.sleep(SLEEP)
                if not probe:
                    return first_t
                first_t = int(probe[0]["t"])
        cur += 30 * 24 * 60 * BAR_MS
    return None

def universe_ctxs() -> pd.DataFrame:
    """One row per perp: name, dayNtlVlm, markPx, midPx, funding, openInterest, impact_bid, impact_ask."""
    meta, ctxs = info({"type": "metaAndAssetCtxs"})
    rows = []
    for m, c in zip(meta["universe"], ctxs):
        impact = c.get("impactPxs") or [None, None]
        rows.append({"name": m["name"], "szDecimals": m["szDecimals"],
                     "dayNtlVlm": float(c["dayNtlVlm"]), "markPx": float(c["markPx"]),
                     "midPx": float(c["midPx"]) if c.get("midPx") else None,
                     "funding": float(c["funding"]), "openInterest": float(c["openInterest"]),
                     "impact_bid": float(impact[0]) if impact[0] else None,
                     "impact_ask": float(impact[1]) if impact[1] else None})
    return pd.DataFrame(rows)

def l2_spread_bps(coin: str) -> float | None:
    book = info({"type": "l2Book", "coin": coin})
    bids, asks = book["levels"][0], book["levels"][1]
    if not bids or not asks:
        return None
    bb, ba = float(bids[0]["px"]), float(asks[0]["px"])
    return (ba - bb) / ((ba + bb) / 2) * 1e4

def save_df(df: pd.DataFrame, name: str) -> str:
    path = f"{DATA_DIR}/{name}.csv.gz"
    df.to_csv(path, index=False, compression="gzip")
    return path

def load_df(name: str) -> pd.DataFrame:
    return pd.read_csv(f"{DATA_DIR}/{name}.csv.gz")
```

- [ ] **Step 1**: 照上方規格建檔（可補型別與 docstring，不得改演算法）。
- [ ] **Step 2**: 冒煙測試：`.venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import scalp_lib as s; df=s.candles_to_df(s.get_candles('BTC','1m', 1751500800000, 1751504400000)); print(len(df), df.ts.min(), df.ts.max())"`
  預期：印出約 60 筆與正確的 UTC 時間範圍。
- [ ] **Step 3**: 驗收（fresh agent）：read-back 檔案完整性＋重跑 Step 2 指令確認輸出。
- [ ] **Step 4**: Commit：`feat(scalp): data layer for HL candles/universe/l2 (sub-project H)`

## Task 2: `scripts/scalp_fee_check.py` — 費率地面真相

**Files:** Create: `scripts/scalp_fee_check.py`

規格：CLI `--user 0x...`（選填）。有 user → POST `{"type":"userFees","user":addr}`，
取 `userCrossRate`（taker）與 `userAddRate`（maker）；無 user → 印警告並使用預設
0.00045/0.00015。結果寫 `data/scalp/fees.json`：
`{"taker": <float>, "maker": <float>, "source": "userFees:<addr前6碼>|default", "ts": "<iso>"}`。
若 `userFees` 回傳結構不含上述欄位，把整包 json 印出來、以預設值落檔並在 source 標
`"endpoint-mismatch"`——**不得靜默吞掉**。

- [ ] **Step 1**: 實作。
- [ ] **Step 2**: `.venv/bin/python scripts/scalp_fee_check.py`（無參數）→ 預期印警告、產出 fees.json（default）。
- [ ] **Step 3**: 使用者提供錢包地址後重跑一次帶 `--user`（地址是公開資訊；**不讀任何 .env**）。
- [ ] **Step 4**: Commit：`feat(scalp): fee ground-truth check (sub-project H)`

## Task 3: `scripts/scalp_universe_scan.py` — 宇宙掃描（G0）

**Files:** Create: `scripts/scalp_universe_scan.py`；輸出 `reports/scalp-universe-scan.md`、`data/scalp/shortlist.json`、`data/scalp/slippage.json`

流程（依 spec §5）：
1. `universe_ctxs()` 過濾 `dayNtlVlm >= 20e6` → candidates（印出名單與家數）。
2. 每個 candidate：`find_earliest_1m` → `depth_days`。
3. spread 取樣：對 candidates 迴圈取 `l2_spread_bps`，每輪之間 `time.sleep(30)`，
   共 240 輪（約 2 小時）；CLI `--quick` 改 20 輪（煙測用）。每幣記 `spread_med_bps`。
4. 拉近 30 天 1m K 線（`pull_1m_history`），算：`range_med_bps`（單根 (h-l)/c 中位數）、
   `p90_range5_bps`（rolling 5 根窗的 (max(h)-min(l))/c 的 P90）。
5. 成本：讀 `fees.json`；`slip_bps = max(spread_med/2, impact_spread/2) + 0.5`，其中
   `impact_spread = (impact_ask-impact_bid)/mid*1e4`；`rt_cost_bps = 2*taker_bps + 2*slip_bps`。
   `ratio = p90_range5_bps / rt_cost_bps`。每幣滑價寫入 `slippage.json`。
6. shortlist：`ratio >= 3 AND spread_med <= 5 AND depth_days >= 180`，按 ratio 取前 8。
   產出 markdown 表（全 candidates 各欄位）＋ G0 判定行（≥4 幣過 → PASS）。

- [ ] **Step 1**: 實作。
- [ ] **Step 2**: `.venv/bin/python scripts/scalp_universe_scan.py --quick` → 預期產出三個輸出檔、表格完整、G0 行存在。
- [ ] **Step 3**: 正式跑（不帶 --quick，wall-clock ~2h，可背景跑）。
- [ ] **Step 4**: 驗收（fresh agent）：讀 `reports/scalp-universe-scan.md`，逐欄檢查無 NaN 佔位、
  ratio 計算可由同列數字重現、shortlist.json 與表格一致。
- [ ] **Step 5**: Commit：`feat(scalp): universe scan + G0 gate (sub-project H)`

## Task 4: `scripts/scalp_pull_history.py` — 全量 1m 歷史

**Files:** Create: `scripts/scalp_pull_history.py`；輸出 `data/scalp/<COIN>_1m.csv.gz`

規格：讀 `shortlist.json`，每幣 `find_earliest_1m` → `pull_1m_history(earliest, now)` →
完整性檢查：`gaps = 相鄰 t 差 > 60_000ms 的清單`，印出 gap 數與最大 gap；
`save_df(df, f"{coin}_1m")`。每幣印 `coin, bars, first_ts, last_ts, gap_count`。
5m 資料不另外抓——回測需要時由 1m 本地 resample。

- [ ] **Step 1**: 實作。
- [ ] **Step 2**: `.venv/bin/python scripts/scalp_pull_history.py`（每幣 ~1-3 分鐘）。
  預期：每幣一行摘要；任何幣 gap_count > 50 要在輸出標 WARN（不中斷）。
- [ ] **Step 3**: 驗收（fresh agent）：對每個輸出檔 `load_df` 抽查——筆數與摘要一致、
  t 嚴格遞增、無重複、價格欄無 0/NaN。
- [ ] **Step 4**: Commit：`feat(scalp): 1m history puller (sub-project H)`（資料檔不進 git）

## Task 5: `scripts/scalp_backtest_lib.py` — 回測核心（有單元測試）

**Files:** Create: `scripts/scalp_backtest_lib.py`；Test: `tests/test_scalp_backtest.py`

核心規格（誠信規範 spec §6 的機械落實）：

```python
"""Backtest core for sub-project H. Signals on CLOSED bars only; fills at next bar open."""
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass
class Trade:
    coin: str; side: int; entry_i: int; exit_i: int
    entry_px: float; exit_px: float; gross_bps: float; net_bps: float; exit_reason: str

def prep(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ret"] = np.log(out["c"] / out["c"].shift(1))
    out["sigma"] = out["ret"].ewm(span=240, min_periods=240).std()
    vmean = out["v"].rolling(240).mean(); vstd = out["v"].rolling(240).std()
    out["vol_z"] = (out["v"] - vmean) / vstd
    tr = np.maximum(out["h"] - out["l"],
         np.maximum((out["h"] - out["c"].shift(1)).abs(), (out["l"] - out["c"].shift(1)).abs()))
    out["atr14"] = tr.rolling(14).mean()
    return out

def simulate(df, sig, hold_bars, stop_atr_mult, fee_bps, slip_bps,
             coin="", target_px=None, stop_px=None) -> list:
    """sig[i] in {+1,-1,0} decided at bar i close -> entry at open[i+1] +/- slip.
    Exit priority inside a bar: STOP first (pessimistic), then TARGET, else time-stop
    exits at open[entry_i + hold_bars]. target_px/stop_px: optional arrays (F2 style);
    when None, stop = entry -/+ stop_atr_mult * atr14[i]."""
    trades, i, n = [], 0, len(df)
    o, h, l, atr = df["o"].values, df["h"].values, df["l"].values, df["atr14"].values
    sig = np.asarray(sig)
    while i < n - 2:
        s = sig[i]
        if s == 0 or np.isnan(atr[i]):
            i += 1; continue
        e_i = i + 1
        e_px = o[e_i] * (1 + s * slip_bps / 1e4)
        stop = stop_px[i] if stop_px is not None else e_px - s * stop_atr_mult * atr[i]
        tgt = target_px[i] if target_px is not None else None
        exit_i, exit_px, reason = None, None, None
        last = min(e_i + hold_bars, n - 1)
        for j in range(e_i, last + 1):
            if s == 1 and l[j] <= stop:   # gap-through: fill at the worse of stop/open
                exit_i, exit_px, reason = j, min(stop, o[j]), "stop"; break
            if s == -1 and h[j] >= stop:
                exit_i, exit_px, reason = j, max(stop, o[j]), "stop"; break
            if tgt is not None and ((s == 1 and h[j] >= tgt) or (s == -1 and l[j] <= tgt)):
                exit_i, exit_px, reason = j, tgt, "target"; break
        if exit_i is None:
            exit_i, exit_px, reason = last, o[last], "time"
        exit_px = exit_px * (1 - s * slip_bps / 1e4)
        gross = s * (exit_px / e_px - 1) * 1e4 + 2 * slip_bps  # gross excludes slip
        net = s * (exit_px / e_px - 1) * 1e4 - 2 * fee_bps
        trades.append(Trade(coin, int(s), e_i, exit_i, e_px, exit_px, gross, net, reason))
        i = exit_i + 1   # one position per coin, no overlap
    return trades

def metrics(trades, df=None) -> dict:
    if not trades:
        return {"n": 0}
    net = np.array([t.net_bps for t in trades])
    wins, losses = net[net > 0], net[net <= 0]
    pf = wins.sum() / max(1e-9, -losses.sum()) if len(losses) else float("inf")
    eq = net.cumsum(); mdd = float((eq - np.maximum.accumulate(eq)).min())
    t_stat = float(net.mean() / (net.std(ddof=1) + 1e-12) * np.sqrt(len(net)))
    out = {"n": len(net), "pf": round(float(pf), 3), "win": round(float((net > 0).mean()), 3),
           "avg_net_bps": round(float(net.mean()), 2), "mdd_bps": round(mdd, 1),
           "t_stat": round(t_stat, 2)}
    if df is not None:
        mon = pd.Series(net, index=df["ts"].iloc[[t.entry_i for t in trades]].values)
        by_m = mon.groupby(pd.Series(mon.index).dt.to_period("M").values).sum()
        out["months_pos"] = f"{int((by_m > 0).sum())}/{len(by_m)}"
    return out

def walk_forward(df, configs, run_fn, train_days=60, test_days=30):
    """run_fn(df_slice, config) -> trades. Select best config on train (by pf, n>=20),
    apply to test; concatenate OOS trades. Returns (oos_trades, picks)."""
    ts = df["ts"]; start, end = ts.iloc[0], ts.iloc[-1]
    oos, picks, cur = [], [], start + pd.Timedelta(days=train_days)
    while cur + pd.Timedelta(days=test_days) <= end:
        tr_df = df[(ts >= cur - pd.Timedelta(days=train_days)) & (ts < cur)].reset_index(drop=True)
        te_df = df[(ts >= cur) & (ts < cur + pd.Timedelta(days=test_days))].reset_index(drop=True)
        scored = []
        for cfg in configs:
            m = metrics(run_fn(tr_df, cfg))
            if m.get("n", 0) >= 20:
                scored.append((m["pf"], cfg))
        if scored:
            best = max(scored, key=lambda x: x[0])[1]
            oos.extend(run_fn(te_df, best)); picks.append((str(cur.date()), best))
        cur += pd.Timedelta(days=test_days)
    return oos, picks
```

單元測試（無網路、純合成 bar；repo 測試紅線適用）：
1. `test_no_lookahead`：訊號在 bar i，斷言 `entry_px == open[i+1]*(1+slip)`。
2. `test_costs_applied`：淨損益 = 毛損益 − 2×fee − 2×slip（用零波動合成 bar 驗證到 1e-9）。
3. `test_stop_before_target_same_bar`：同一 bar 同時觸及 stop 與 target 時，出場是 stop。
4. `test_no_overlap`：同幣同時間最多一倉（exit_i < 下一筆 entry_i）。
5. `test_gap_through_stop`：開盤即跳空穿越停損時，成交價是 open（更差者），不是停損價。

- [ ] **Step 1**: 先寫四個測試（紅燈）：`.venv/bin/pytest tests/test_scalp_backtest.py -v` 預期 FAIL（module 不存在）。
- [ ] **Step 2**: 照規格實作 lib。
- [ ] **Step 3**: `.venv/bin/pytest tests/test_scalp_backtest.py -v` 預期 4 passed，貼輸出。
- [ ] **Step 4**: 驗收（fresh agent）：只給測試檔與 lib，檢查測試是否真的測到規格
  （特別是 lookahead 與 stop 優先序），並重跑 pytest。
- [ ] **Step 5**: Commit：`feat(scalp): backtest core with integrity tests (sub-project H)`

## Task 6: `scripts/research_scalp_f1_burst.py` — F1 突發動能延續

**Files:** Create: `scripts/research_scalp_f1_burst.py`；輸出 `reports/scalp-f1-burst-results.md`、`data/scalp/f1_trades.csv`

**預先註冊網格（不得擴充）**：`Z ∈ {3,4,5}`、`V ∈ {2,3}`、`hold ∈ {5,15,30}` bars、
stop 固定 1.5×ATR14 → 18 configs。訊號：
`sig[i] = sign(ret[i]) if (abs(ret[i]/sigma[i]) >= Z and vol_z[i] >= V) else 0`。
每幣讀 `<COIN>_1m.csv.gz` → `prep` → `walk_forward`（train 60d/test 30d）→
pooled OOS metrics（全幣 OOS trades 串接）＋逐幣 metrics。
費率讀 `fees.json`、滑價讀 `slippage.json`。**敏感度**：fee 與 slip ×1.5 重跑 pooled。
報告含：pooled 表、逐幣表、敏感度表、每 walk-forward 窗被選中的 config 清單、
G1 逐條 PASS/FAIL 行。**G1 門檻（照抄，與 spec §7 同源）**：pooled OOS 淨 PF ≥ 1.3、
交易數 ≥ 300、≥60% 月度切片為正、equity MDD ≤ 15%（以每筆 $1,000 名目的 equity 曲線
換算 %）、OOS t-stat ≥ 2.0、成本×1.5 下 PF ≥ 1.15。

- [ ] **Step 1**: 實作。
- [ ] **Step 2**: `.venv/bin/python scripts/research_scalp_f1_burst.py` 跑通，產出兩個輸出檔。
- [ ] **Step 3**: 驗收（fresh agent）：報告數字與 f1_trades.csv 重算一致（抽 pooled PF 與 n）；
  G1 各條判定與數字相符。
- [ ] **Step 4**: Commit：`feat(scalp): F1 burst-continuation walk-forward (sub-project H)`

## Task 7: `scripts/research_scalp_f2_fade.py` — F2 過度延伸回歸

**Files:** Create: `scripts/research_scalp_f2_fade.py`；輸出 `reports/scalp-f2-fade-results.md`、`data/scalp/f2_trades.csv`

**預先註冊網格**：`W ∈ {15,30,60}`、`K ∈ {3,4,5}` → 9 configs；出場固定：
target = 延伸段 38.2% 回撤、stop = 極值外 0.5×ATR14、time-stop 60 bars。訊號（fade dump 方向，fade pump 對稱）：
```python
cum = np.log(df.c / df.c.shift(W))
ext_z = cum / (df.sigma * np.sqrt(W))
wick_lo = (df.c - df.l) / (df.h - df.l + 1e-12)
long_sig = (ext_z <= -K) & (df.vol_z >= 3) & (wick_lo >= 0.3)
# long: extreme = rolling W 窗最低價；target = extreme + 0.382*(窗起點 c - extreme)
# stop = extreme - 0.5*atr14；用 simulate 的 target_px/stop_px 陣列傳入
```
其餘流程、敏感度、報告結構與 Task 6 完全相同（walk-forward train 60d/test 30d、
費率讀 `fees.json`、滑價讀 `slippage.json`、敏感度 fee/slip ×1.5 重跑 pooled）。
**G1 門檻（照抄，與 spec §7 同源）**：pooled OOS 淨 PF ≥ 1.3、交易數 ≥ 300、
≥60% 月度切片為正、equity MDD ≤ 15%、OOS t-stat ≥ 2.0、成本×1.5 下 PF ≥ 1.15。
報告額外加：exit_reason 分布（target/stop/time 占比）與 MAE 註記——
stop 占比 > 50% 即在報告標註「發散主導」。

- [ ] **Step 1**: 實作。
- [ ] **Step 2**: 跑通、產出輸出檔。
- [ ] **Step 3**: 驗收（fresh agent）：同 Task 6 標準＋exit_reason 占比可由 csv 重算。
- [ ] **Step 4**: Commit：`feat(scalp): F2 overshoot-fade walk-forward (sub-project H)`

## Task 8: `scripts/research_scalp_f3_session.py` — F3 時段效應統計

**Files:** Create: `scripts/research_scalp_f3_session.py`；輸出 `reports/scalp-f3-session-stats.md`

先統計、後規則（spec §4 F3）。本 task **只做統計**，不做策略回測：
1. 每幣：UTC hour × weekday 的平均淨漂移（bps/小時）、實現波動、成交量占比熱圖（markdown 表）。
2. funding 邊界效應：每小時整點前後 ±5 分鐘的平均報酬 vs 全樣本基線。
3. 前後半段穩定性：資料窗對半切，熱點（|漂移| 前 3 名的 hour×dow 格）在兩半是否同號。
4. 報告結尾列出「值得規則化的候選窗口 ≤ 2 個」與各自兩半段數字；若無穩定熱點，明寫。

- [ ] **Step 1**: 實作。
- [ ] **Step 2**: 跑通、產出報告。
- [ ] **Step 3**: 驗收（fresh agent）：抽 2 個格子的數字由原始資料重算一致。
- [ ] **Step 4**: Commit：`feat(scalp): F3 session-effect stats (sub-project H)`

## Task 9: `reports/scalp-phase1-verdict.md` — Phase 1 綜合判定

**Files:** Create: `reports/scalp-phase1-verdict.md`

這是判斷題，不派 haiku：主對話綜合 Task 6-8 結果，逐條對照 spec §7 G1，
每個家族給 GO / regime-conditional GO / NO-GO。**必附**：資料窗 regime 標註、
反面證據（哪些幣/月份失效）、多重檢定聲明（每家族 config 數、是否事後擴充）。
依 delegation.md §6：**另派一個 opus agent 只拿數字表獨立判定**，兩判不一致呈使用者。
F3 若有穩定熱點，在此決定是否加開一個規則化回測 task（事後新增要在 verdict 註明）。

- [ ] **Step 1**: 主對話撰寫 verdict 草稿。
- [ ] **Step 2**: 派 opus 第二意見 agent（只給數字表與 gate 定義，不給草稿結論）。
- [ ] **Step 3**: 合併判定；不一致處呈使用者裁決。
- [ ] **Step 4**: Commit：`docs(scalp): phase 1 verdict (sub-project H)`

---

## Phase 2/3 預告（G1 通過後才開工，屆時各寫自己的 plan）

- **Phase 2（F4 跨幣錯位）**：F4a 單腿 lead-lag 優先（BTC/ETH 1m 大動作 → 落後 alt 的
  跟隨漂移）、F4b beta 對沖雙腿；gate G2（雙倍成本、對單幣家族的增益證明）；
  必報 MAE 分布與 time-stop 占比（直面 pair-trading NO-GO 的發散失敗模式）。
- **Phase 3（引擎與部署）**：`src/hlvault/scalp/` 仿 `cta/` 結構（config env 隔離、
  ResilientExchange、notify、dry-run 模式）→ `deploy/setup-scalp.sh` + `hl-scalp.service`
  → paper 2-4 週 → G3 → **上實盤前必問**。

## 執行成本與時程估計

- Phase 0：Task 0-4，約半天（spread 取樣 2h wall-clock 可背景跑）。
- Phase 1：Task 5-9，約 1-2 天（回測腳本各自獨立，Task 6-8 可平行派工）。
- API 用量：全部公開 info endpoint，0.5s pacing，無鑰匙、無下單。
