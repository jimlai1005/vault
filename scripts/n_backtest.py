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
