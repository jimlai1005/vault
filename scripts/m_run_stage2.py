"""Sub-project M — Stage 2 執行入口。spec §6、計畫 Task 8。

分段執行、各段產物落檔可續跑：
  primary  : primary trades（併 sl/direction/ratio_ad_xa 欄）＋ K=5 對照 trades
  cells    : 480 cells 的 OOS 未年化日 Sharpe → cells_sharpe.json
  gates    : M-G2~G7 ＋ selected ＋ 消融 ＋ 端點敏感度 → gates_results.json
  all      : primary → cells → gates

用法：.venv/bin/python scripts/m_run_stage2.py {primary|cells|gates|all}
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_backtest as bt     # noqa: E402
import m_config as cfg      # noqa: E402
import m_control as mc      # noqa: E402
import m_detect             # noqa: E402
import m_gates as mg        # noqa: E402
import m_stats as ms        # noqa: E402

CACHE = pathlib.Path(cfg.CACHE_DIR)
DAY_MS = 86_400_000
BAR_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
_PIVOT_CACHE = {}


def _tol_tag(tol):
    return f"tol{int(round(tol * 100)):02d}"


def _load_events(interval, tol):
    df = pd.read_parquet(CACHE / f"events_{interval}_{_tol_tag(tol)}.parquet")
    return df[df["in_universe"]].reset_index(drop=True)


def _pivots_for(symbol, interval, lengths):
    out = {}
    for L in lengths:
        key = (symbol, interval, int(L))
        if key not in _PIVOT_CACHE:
            bars = pd.DataFrame(dict(bt.load_bars(symbol, interval)))
            _PIVOT_CACHE[key] = m_detect.find_pivots(bars, int(L))
        out[key] = _PIVOT_CACHE[key]
    return out


def _run(events, mode, exit_variant, stress=1.0):
    frames = []
    for (sym, iv), grp in events.groupby(["symbol", "interval"], sort=False):
        piv = None
        if mode == "B":
            piv = _pivots_for(sym, iv, grp["pivot_length"].unique())
        b = bt.load_bars(sym, iv)
        frames.append(bt.run_events_on_bars(grp, b, mode=mode,
                                            exit_variant=exit_variant,
                                            stress=stress, pivots_by_key=piv))
    return pd.concat(frames, ignore_index=True)


# ── primary ──────────────────────────────────────────────────────────────────

def stage_primary():
    p = cfg.PRIMARY
    ev = _load_events(p["interval"], p["tol"])
    tr = _run(ev, p["entry_mode"], p["exit_variant"])
    # 併入 gate/消融所需欄位（同源：同一張事件表）
    tr = tr.merge(ev[["event_id", "direction", "sl", "ratio_ad_xa"]],
                  on="event_id", how="left", validate="1:1")
    tr.to_parquet(CACHE / "primary_trades.parquet", index=False)
    print(f"primary: {len(tr)} trades，終局分布：")
    print(tr["exit_reason"].value_counts().to_string(), flush=True)

    ok_ids = set(tr.loc[tr["exit_reason"] != "prz_already_breached", "event_id"])
    ev_ok = ev[ev["event_id"].isin(ok_ids)]
    bar_ms = BAR_MS[p["interval"]]
    ctrl_rows, dropped = [], 0
    for (sym, iv), grp in ev_ok.groupby(["symbol", "interval"], sort=False):
        b = bt.load_bars(sym, iv)
        bars_df = pd.DataFrame(dict(b))
        for e in grp.to_dict("records"):
            ctrls = mc.make_controls(e, bars_df)
            dropped += cfg.CONTROL_K - len(ctrls)
            for c in ctrls:
                r = bt.simulate_event(b, c, exit_variant=p["exit_variant"],
                                      mode="A")
                r.update(event_id=c["event_id"], symbol=sym, interval=iv,
                         pattern=c["pattern"], as_of=int(c["as_of"]),
                         weight=c["weight"], delta_bars=c["delta_bars"])
                r["mapped_term_t"] = mc.mapped_term_t(
                    dict(term_t=r["term_t"], delta_bars=c["delta_bars"]), bar_ms)
                ctrl_rows.append(r)
    ct = pd.DataFrame(ctrl_rows)
    ct.to_parquet(CACHE / "control_trades.parquet", index=False)
    n_breach_ctrl = int((ct["exit_reason"] == "prz_already_breached").sum())
    print(f"controls: {len(ct)} trades（捨棄 {dropped} 名額；"
          f"對照 breached {n_breach_ctrl}）", flush=True)


# ── selected（spec §6.5，在 primary IS 上決定一次）──────────────────────────

def compute_selected(tr):
    is_tr = tr[tr["as_of"] <= cfg.IS_END_MS]
    sel = []
    for pat in cfg.PATTERNS:
        sub = is_tr[is_tr["pattern"] == pat]
        if len(sub) < 30:
            continue
        lo = ms.lower_95_of_mean(ms.daily_series(sub), f"SEL-{pat}")
        if lo > 0:
            sel.append(pat)
    return sel


# ── cells ────────────────────────────────────────────────────────────────────

def _layer_series(trades, layer, selected):
    if layer == "merged":
        sub = trades
    elif layer == "selected":
        sub = trades[trades["pattern"].isin(selected)]
    else:
        sub = trades[trades["pattern"] == layer]
    return None if sub.empty else ms.daily_series(sub)


def stage_cells(selected):
    layers = list(cfg.PATTERNS) + ["merged", "selected"]
    cells = {}
    for tol in cfg.TOL_GRID:
        for interval in cfg.INTERVALS:
            ev = _load_events(interval, tol)
            for mode in ("A", "B"):
                for exit_variant in ("tp1_full", "batch"):
                    tr = _run(ev, mode, exit_variant)
                    oos = tr[tr["as_of"] > cfg.IS_END_MS]
                    for layer in layers:
                        s = _layer_series(oos, layer, selected)
                        cells["|".join([_tol_tag(tol), interval, mode,
                                        exit_variant, layer])] = \
                            ms.daily_sr(s) if s is not None else 0.0
                    print(f"  cell {_tol_tag(tol)}/{interval}/{mode}/"
                          f"{exit_variant}: {len(tr)} trades", flush=True)
    assert len(cells) == cfg.N_OBSERVABLE_TRIALS == 480, len(cells)
    (CACHE / "cells_sharpe.json").write_text(json.dumps(cells, indent=1))
    print(f"cells_sharpe.json: {len(cells)} cells")


# ── gates ────────────────────────────────────────────────────────────────────

def _series_pair(tr, ct):
    """M-G3 兩臂：pattern 臂（非 breached）與對照臂（mapped 日曆），共同範圍補 0
    ——r_d 本義即「當日無事件終止 = 0」（spec §6.1），非 union 補零 hack。"""
    pat = tr[tr["exit_reason"] != "prz_already_breached"]
    s_pat = ms.daily_series(pat)
    ct2 = ct.rename(columns={"term_t": "orig_term_t", "mapped_term_t": "term_t"})
    s_ctl = ms.daily_series(ct2, weight_col="weight")
    lo = min(s_pat.index.min(), s_ctl.index.min())
    hi = max(s_pat.index.max(), s_ctl.index.max())
    rng = pd.RangeIndex(lo, hi + 1)
    return s_pat.reindex(rng, fill_value=0.0), s_ctl.reindex(rng, fill_value=0.0)


def _stress_rnet(tr):
    """G7：primary 是 tp1_full，出場價與費用無關 → 以 stress 費率就地重算。
    未成交（fill 為 NaN）維持 R_net = 0。"""
    out = tr["R_net"].to_numpy().copy()
    m = tr["fill"].notna().to_numpy()
    sub = tr[m]
    out[m] = [bt.r_net_single(r.fill, r.sl, r.exit_px, int(r.direction),
                              r.entry_leg, stress=cfg.STRESS_MULT)
              for r in sub.itertuples()]
    t2 = tr.copy()
    t2["R_net"] = out
    return t2


def _ablations(tr):
    """spec §6.4 的兩組消融切片（揭露用，各計一次試驗）。"""
    nominal = cfg.NOMINAL_AD_UPPER
    tol_ok = tr.apply(lambda r: abs(r["ratio_ad_xa"] - nominal[r["pattern"]])
                      / nominal[r["pattern"]] <= 0.03, axis=1)
    d_out = tr["pattern"].isin(("alt_bat", "butterfly", "crab", "deep_crab",
                                "shark"))
    out = {}
    for name, mask in (("tight_tol", tol_ok), ("d_beyond_x", d_out),
                       ("d_within_x", ~d_out)):
        sub = tr[mask]
        oos = sub[sub["as_of"] > cfg.IS_END_MS]
        out[name] = dict(
            n=len(sub),
            er_net=float(sub["R_net"].mean()),
            oos_sr=ms.daily_sr(ms.daily_series(oos)) if len(oos) else 0.0)
    return out


def _endpoint(tr):
    """spec §6.7：IS/OOS 分界 ±7 天，看 OOS lower_95 是否變號。"""
    out = {}
    for name, shift in (("minus7d", -7), ("base", 0), ("plus7d", 7)):
        cut = cfg.IS_END_MS + shift * DAY_MS
        oos = tr[tr["as_of"] > cut]
        out[name] = ms.lower_95_of_mean(ms.daily_series(oos), f"EP{shift}")
    signs = {k: v > 0 for k, v in out.items()}
    out["flipped"] = len(set(signs.values())) > 1
    return out


def stage_gates():
    tr = pd.read_parquet(CACHE / "primary_trades.parquet")
    ct = pd.read_parquet(CACHE / "control_trades.parquet")
    cells = json.loads((CACHE / "cells_sharpe.json").read_text())
    selected = compute_selected(tr)
    res = {"selected": selected}

    res["G2_lower95"] = ms.lower_95_of_mean(ms.daily_series(tr), "M-G2")
    s_pat, s_ctl = _series_pair(tr, ct)
    res["G3_lower95_diff"] = ms.lower_95_of_paired_diff(s_pat, s_ctl, "M-G3")
    res["G3_arm_means"] = dict(pattern=float(s_pat.mean()),
                               control=float(s_ctl.mean()))

    oos_tr = tr[tr["as_of"] > cfg.IS_END_MS]
    s_oos = ms.daily_series(oos_tr)
    sr_list = [cells[k] for k in sorted(cells)]
    g4 = mg.gate_g4(sr_list, s_oos)
    res["G4_psr"], res["G4_sr"], res["G4_sr_star"] = \
        float(g4["psr"]), float(g4["sr"]), float(g4["sr_star"])

    res["G5_lower95_oos"] = ms.lower_95_of_mean(s_oos, "M-G5")
    hold = tr[tr["symbol"].map(mg.is_holdout)]
    res["G6_lower95_holdout"] = ms.lower_95_of_mean(ms.daily_series(hold), "M-G6")
    res["G7_lower95_stress"] = ms.lower_95_of_mean(
        ms.daily_series(_stress_rnet(tr)), "M-G7")

    g = dict(G2=res["G2_lower95"] > 0, G3=res["G3_lower95_diff"] > 0,
             G4=res["G4_psr"] >= 0.95, G5=res["G5_lower95_oos"] > 0,
             G6=res["G6_lower95_holdout"] > 0, G7=res["G7_lower95_stress"] > 0)
    res["gates"] = g
    res["verdict"] = mg.verdict(g)
    res["ablation"] = _ablations(tr)
    res["endpoint"] = _endpoint(tr)
    res["exit_reason_counts"] = tr["exit_reason"].value_counts().to_dict()
    res["selected_oos_lower95"] = (
        ms.lower_95_of_mean(ms.daily_series(
            oos_tr[oos_tr["pattern"].isin(selected)]), "M-G5sel")
        if selected and len(oos_tr[oos_tr["pattern"].isin(selected)]) else None)

    (CACHE / "gates_results.json").write_text(
        json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("primary", "all"):
        stage_primary()
    if what in ("cells", "all"):
        tr = pd.read_parquet(CACHE / "primary_trades.parquet")
        stage_cells(compute_selected(tr))
    if what in ("gates", "all"):
        stage_gates()


if __name__ == "__main__":
    main()
