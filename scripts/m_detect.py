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
import pandas as pd


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
    # 強制 float：int64 輸入會讓 .max(initial=-inf) 拋 OverflowError
    highs = df["h"].values.astype(float)
    lows = df["l"].values.astype(float)
    ts = df["t"].values
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
        # 效能：同一 L 內 confirm_idx = idx + L，故 piv_all 的 (idx, kind) 排序
        # 即 confirm 排序；normalize 的摺疊只動 seq[-1]（取極值）或 append，
        # 因此「as_of = p_c.confirm_idx 的序列」可由前綴增量延伸——每個 L 只需
        # 一次 find_pivots 與一趟線性掃描，語意與逐 pivot 重算完全等價
        # （等價性由 tests/test_m_patterns.py::test_incremental_equals_reference 檢定）。
        seq = []
        i, n_piv = 0, len(piv_all)
        while i < n_piv:
            j = i                                   # 同一 idx（同一 confirm）的群組一起入列
            while j < n_piv and piv_all[j].idx == piv_all[i].idx:
                p = piv_all[j]
                if seq and seq[-1].kind == p.kind:
                    prev = seq[-1]
                    better = (p.price > prev.price) if p.kind == "high" \
                        else (p.price < prev.price)
                    if better:
                        seq[-1] = p
                else:
                    seq.append(p)
                j += 1
            group, i = piv_all[i:j], j
            for p_c in group:
                if len(seq) < 4 or seq[-1].idx != p_c.idx:
                    continue
                x, a, b, c = seq[-4:]
                direction = 1 if x.kind == "low" else -1
                if [x.kind, a.kind, b.kind, c.kind] not in (
                        ["low", "high", "low", "high"],
                        ["high", "low", "high", "low"]):
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
                        event_id=(f"{symbol}_{interval}_{direction}_{L}_"
                                  f"{c.t}_{pattern}"),
                        xabc_group_id=gid, symbol=symbol, interval=interval,
                        pattern=pattern, direction=direction, pivot_length=L,
                        t_X=x.t, t_A=a.t, t_B=b.t, t_C=c.t,
                        p_X=x.price, p_A=a.price, p_B=b.price, p_C=c.price,
                        as_of=c.confirm_t,
                        ratio_ab_xa=ab / xa,
                        ratio_bc_ab=abs(c.price - b.price) / ab,
                        ratio_xc_xa=abs(c.price - x.price) / xa,
                        prz_low=prz_lo, prz_high=prz_hi, sl=sl,
                        tp1_planned=d_trigger + direction * f1 * leg,
                        tp2_planned=d_trigger + direction * f2 * leg,
                        dedup_merged=0, tol_used=tol))
    ev = pd.DataFrame(rows)
    if ev.empty or not do_dedup:
        return ev
    return dedup(ev)
