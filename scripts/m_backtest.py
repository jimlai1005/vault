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
