"""Sub-project N — 執行入口。

用法：.venv/bin/python scripts/n_run.py {flow|events|feat|arms|gates|all}

【預註冊研究】spec: docs/superpowers/specs/2026-08-09-liquidity-sweep-orderflow-design.md
所有門檻在看到結果前已寫定。本檔不得引入任何 spec 沒有的自由參數。

pilot（4 幣 × 2023H1）依 spec §3.4 **只用於機制驗證**——終局分布合理、
曝險比落帶、特徵可計算——**不得用於判定任何 gate 或更動任何參數**
（§11.6：pilot 統計力不足以判定）。

架構：原始 trades 不保留。逐棒聚合（小）落 sidecar 供 CVD；事件級 D_sweep
在該日檔仍在時算出並寫進事件表。正式範圍可串流（下載→萃取→丟棄）。
"""
import json
import pathlib
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import m_backtest as mbt  # noqa: E402
import n_backtest as nbt  # noqa: E402
import n_config as cfg  # noqa: E402
import n_control as nc  # noqa: E402
import n_data as nd  # noqa: E402
import n_features as nf  # noqa: E402
import n_gates as ngt  # noqa: E402
import n_orderflow as nof  # noqa: E402
import n_stats as nst  # noqa: E402
import n_sweep as nsw  # noqa: E402

CACHE = pathlib.Path(cfg.CACHE_DIR_N)
IV = cfg.PRIMARY["interval"]
BAR = cfg.BAR_MS[IV]

# ── pilot 範圍（先驗選定，非依結果；spec §3.4）──────────────────────────
PILOT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "GALAUSDT"]
PILOT_START_MS = int(pd.Timestamp("2023-01-01", tz="UTC").value // 10 ** 6)
PILOT_END_MS = int(pd.Timestamp("2023-07-01", tz="UTC").value // 10 ** 6)
# 對照臂最遠位移 300 根 + 最長持有 100 根 = 400 根，事件窗須留此緩衝，
# 否則末段事件的對照落在無資料區、被大量記 nodata 而壓低曝險比。
EVENT_END_MS = PILOT_END_MS - (cfg.CONTROL_DELTA_MAX + cfg.MAX_HOLD_BARS) * BAR


def _kline(symbol):
    b = mbt.load_bars(symbol, IV)
    return pd.DataFrame({k: b[k] for k in ("t", "o", "h", "l", "c")}), b


def _days_of(t0, t1):
    return [d.strftime("%Y-%m-%d") for d in
            pd.date_range(pd.Timestamp(t0, unit="ms", tz="UTC").normalize(),
                          pd.Timestamp(t1, unit="ms", tz="UTC").normalize(),
                          freq="D")]


# ══════════════════════════════════════════════════════════════════════
def stage_flow(symbols=None):
    """逐棒訂單流 sidecar（delta / notional / n_trades / cvd）。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    for s in (symbols or PILOT_SYMBOLS):
        out = nof.bars_path(s, IV)
        if out.exists():
            print(f"  {s}: sidecar 已存在，跳過", flush=True)
            continue
        frames = []
        for day in _days_of(PILOT_START_MS, PILOT_END_MS - 1):
            p = nd.day_path(s, day)
            if not p.exists():
                continue
            frames.append(nof.build_bars(nd.load_day(s, day), BAR))
        if not frames:
            print(f"  {s}: 無日檔，跳過", flush=True)
            continue
        g = (pd.concat(frames, ignore_index=True)
             .groupby("t", sort=True)[["delta", "notional", "n_trades"]]
             .sum().reset_index())
        g["cvd"] = g["delta"].cumsum()          # P8：自可用資料最早棒起累加
        g.to_parquet(out, index=False)
        print(f"  {s}: {len(g)} 根棒 -> {out.name}", flush=True)


# ══════════════════════════════════════════════════════════════════════
def stage_events(symbols=None):
    """掃單事件表 + 池表（只用 K 線，不需 trades）。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    L = cfg.PRIMARY["pivot_l"]
    for s in (symbols or PILOT_SYMBOLS):
        df, _ = _kline(s)
        pt = nsw.pool_table(df, L)
        pt.to_parquet(CACHE / f"pools_{s}_{IV}_L{L}.parquet", index=False)
        ev = nsw.build_events(df, s, IV, L)
        ev = ev[(ev["t_j"] >= PILOT_START_MS) & (ev["t_j"] < EVENT_END_MS)]
        ev.to_parquet(CACHE / f"events_{s}_{IV}_L{L}.parquet", index=False)
        print(f"  {s}: 池 {len(pt):,} 個｜窗內事件 {len(ev):,} 個", flush=True)


# ══════════════════════════════════════════════════════════════════════
def _day_of(t_ms):
    return pd.Timestamp(int(t_ms), unit="ms", tz="UTC").strftime("%Y-%m-%d")


def _attach_by_day(frame, symbol, bars_of):
    """逐日載入 trades 計算特徵。

    【不可一次載入整段】：BTC 181 天約 4.9 億列，一次載入會耗盡記憶體。
    依事件所屬日分組，每天只載一次、算完即釋放（單日約 270 萬列 ≈ 130 MB）。
    缺檔的日子不放進 dict → n_features.attach 記 NaN → 下游記 nodata（P13）。
    """
    if not len(frame):
        return frame
    out = []
    for day, grp in frame.groupby(frame["t_j"].map(_day_of), sort=True):
        p = nd.day_path(symbol, day)
        idx_map = {}
        if p.exists():
            tr = nd.load_day(symbol, day)
            idx_map[day] = (tr, nof.build_index(tr, BAR))
        out.append(nf.attach(grp, bars_of, idx_map, BAR))
        idx_map.clear()
    return pd.concat(out, ignore_index=True)


def stage_feat(symbols=None):
    """事件臂與對照臂各自附上訂單流特徵（P14：對照在自己的棒上重算）。"""
    L = cfg.PRIMARY["pivot_l"]
    for s in (symbols or PILOT_SYMBOLS):
        ev = pd.read_parquet(CACHE / f"events_{s}_{IV}_L{L}.parquet")
        if not len(ev):
            print(f"  {s}: 無事件，跳過", flush=True)
            continue
        _, bars = _kline(s)
        n_bars = len(bars["t"])
        ctl = []
        for e in ev.to_dict("records"):
            ctl.extend(nc.make_controls(e, bars, n_bars))
        ct = pd.DataFrame(ctl)
        bars_of = nof.load_bars_of(s, IV)
        ev2 = _attach_by_day(ev, s, bars_of)
        ct2 = _attach_by_day(ct, s, bars_of)
        ev2.to_parquet(CACHE / f"featev_{s}.parquet", index=False)
        ct2.to_parquet(CACHE / f"featct_{s}.parquet", index=False)
        nod_e = int((~np.isfinite(ev2["d_sweep"])).sum())
        nod_c = int((~np.isfinite(ct2["d_sweep"])).sum()) if len(ct2) else 0
        print(f"  {s}: 事件 {len(ev2):,}（nodata {nod_e}）｜"
              f"對照 {len(ct2):,}（nodata {nod_c}）｜"
              f"ABS {ev2['abs_ok'].mean():.1%} DIV {ev2['div_ok'].mean():.1%}",
              flush=True)


# ══════════════════════════════════════════════════════════════════════
def _run_arm(symbols, arm):
    """單一臂：事件臂與對照臂各自過濾＋回測。回傳 (ev_trades, ct_trades, stat)。"""
    L = cfg.PRIMARY["pivot_l"]
    er, cr = [], []
    stat = {"n_events": 0, "n_pass": 0, "n_ctl": 0, "n_ctl_pass": 0}
    for s in symbols:
        fe = CACHE / f"featev_{s}.parquet"
        if not fe.exists():
            continue
        ev = pd.read_parquet(fe)
        ct = pd.read_parquet(CACHE / f"featct_{s}.parquet")
        pt = pd.read_parquet(CACHE / f"pools_{s}_{IV}_L{L}.parquet")
        _, bars = _kline(s)
        for src, sink, key in ((ev, er, "n_pass"), (ct, cr, "n_ctl_pass")):
            for e in src.to_dict("records"):
                if key == "n_pass":
                    stat["n_events"] += 1
                else:
                    stat["n_ctl"] += 1
                # 兩臂共用同一個過濾器入口（結構性公平保證）
                if not nc.FILTER_ENTRYPOINT(arm, e):
                    continue
                stat[key] += 1
                r = nbt.simulate_event(bars, e, pt, require_orderflow=True)
                r.update(event_id=e["event_id"], symbol=s,
                         direction=int(e["direction"]))
                if "parent_id" in e:
                    r["parent_id"] = e["parent_id"]
                sink.append(r)
    evt = pd.DataFrame(er)
    ctt = pd.DataFrame(cr)
    if len(ctt):
        ctt = nc.renormalize_weights(ctt)
    return evt, ctt, stat


def stage_arms(symbols=None):
    syms = symbols or PILOT_SYMBOLS
    out = {}
    for arm in cfg.ARMS:
        evt, ctt, stat = _run_arm(syms, arm)
        evt.to_parquet(CACHE / f"arm_ev_{arm.replace('+', '_')}.parquet", index=False)
        ctt.to_parquet(CACHE / f"arm_ct_{arm.replace('+', '_')}.parquet", index=False)
        w = float(ctt["weight"].sum()) if len(ctt) else 0.0
        ratio = nst.exposure_ratio(len(evt), w)
        res = dict(**stat, n_ev_trades=int(len(evt)), n_ct_trades=int(len(ctt)),
                   ctl_weight_sum=w, exposure_ratio=ratio,
                   exposure_ok=nst.exposure_ok(ratio))
        if len(evt) and len(ctt):
            res["E_R_event"] = nst.weighted_event_mean(evt)
            res["E_R_control"] = nst.weighted_event_mean(ctt)
            res["exit_reasons"] = {k: int(v) for k, v
                                   in evt["exit_reason"].value_counts().items()}
        out[arm] = res
        print(f"  {arm:16s} 事件 {len(evt):>6,} 對照 {len(ctt):>7,} "
              f"曝險比 {ratio:.3f} {'OK' if res['exposure_ok'] else '**出帶**'}",
              flush=True)
    (CACHE / "arms.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return out


# ══════════════════════════════════════════════════════════════════════
def stage_gates(g0_pass=True, g1_pass=True):
    """十道 gate。pilot 統計力不足，本階段只驗機制（spec §11.6）。"""
    arms = json.loads((CACHE / "arms.json").read_text())
    primary = cfg.PRIMARY["arm"]
    res = {}
    for arm, a in arms.items():
        if "E_R_event" not in a:
            res[arm] = {"verdict": "作廢（無交易）"}
            continue
        ev = pd.read_parquet(CACHE / f"arm_ev_{arm.replace('+', '_')}.parquet")
        ct = pd.read_parquet(CACHE / f"arm_ct_{arm.replace('+', '_')}.parquet")
        g2 = nst.cluster_boot_lower95(ev, None, f"N-G2-{arm}")
        g3 = nst.cluster_boot_lower95(ev, ct, f"N-G3-{arm}")
        res[arm] = dict(E_R_event=a["E_R_event"], E_R_control=a["E_R_control"],
                        G2_lower95=g2, G3_lower95_diff=g3,
                        exposure_ratio=a["exposure_ratio"],
                        exposure_ok=a["exposure_ok"])
    # N-G8：吸收的邊際貢獻（sweep+ABS vs sweep_only）
    if all(k in res and "E_R_event" in res[k] for k in ("sweep+ABS", "sweep_only")):
        a = pd.read_parquet(CACHE / "arm_ev_sweep_ABS.parquet")
        b = pd.read_parquet(CACHE / "arm_ev_sweep_only.parquet")
        res["_G8_abs_marginal_lower95"] = nst.cluster_boot_lower95(a, b, "N-G8")
    res["_note"] = ("pilot 統計力不足以判定任何 gate（spec §11.6）；"
                    "本輸出僅供機制驗證，不得作為判定依據。")
    (CACHE / "gates_pilot.json").write_text(
        json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return res


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("flow", "all"):
        stage_flow()
    if what in ("events", "all"):
        stage_events()
    if what in ("feat", "all"):
        stage_feat()
    if what in ("arms", "all"):
        stage_arms()
    if what in ("gates", "all"):
        stage_gates()


if __name__ == "__main__":
    main()
