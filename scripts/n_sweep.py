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
