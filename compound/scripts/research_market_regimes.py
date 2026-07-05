#!/usr/bin/env python
"""Market regime analysis across BTC halving cycles.

Classifies each day into one of four regimes using a 30-day rolling window:
  T = |30d log return| / (30d daily-return std * sqrt(30))   (rolling |Sharpe|)
  V = 30d annualized volatility (std * sqrt(365))
  T > T_TH            -> trend-up / trend-down (by sign of 30d return)
  T <= T_TH, V >= V_TH -> high-vol chop  (grid-friendly)
  T <= T_TH, V < V_TH  -> low-vol drift  (neither)

Phases relative to halving: H+0-6m / 6-12m / 12-18m / 18-30m / 30-48m.
Halvings: 2016-07-09, 2020-05-11, 2024-04-20.
"""
import numpy as np
import pandas as pd

CSV = "/Users/jim/projects/compound/data/btcusd_1D.csv"
HALVINGS = [pd.Timestamp("2016-07-09"), pd.Timestamp("2020-05-11"), pd.Timestamp("2024-04-20")]
DATA_END_SENTINEL = pd.Timestamp("2100-01-01")
PHASES = [("H+0-6m", 0, 6), ("H+6-12m", 6, 12), ("H+12-18m", 12, 18),
          ("H+18-30m", 18, 30), ("H+30-48m", 30, 48)]
DAYS_PER_MONTH = 30.4375
WIN = 30
REGIMES = ["trend-up", "trend-down", "hv-chop", "lv-drift"]


def load():
    df = pd.read_csv(CSV)
    df["date"] = pd.to_datetime(df["date_iso"]).dt.tz_localize(None).dt.normalize()
    df = df.sort_values("date").drop_duplicates("date").set_index("date")
    # drop last (possibly partial) day
    df = df.iloc[:-1]
    df["logret"] = np.log(df["close"]).diff()
    df["ret30"] = np.log(df["close"]).diff(WIN)
    df["std30"] = df["logret"].rolling(WIN).std()
    df["T"] = (df["ret30"].abs() / (df["std30"] * np.sqrt(WIN))).replace([np.inf, -np.inf], np.nan)
    df["V"] = df["std30"] * np.sqrt(365)  # annualized
    df["sma200"] = df["close"].rolling(200).mean()
    df["macro_up"] = df["close"] > df["sma200"]
    return df


def classify(df, t_th, v_th):
    reg = pd.Series("lv-drift", index=df.index, dtype=object)
    trend = df["T"] > t_th
    reg[trend & (df["ret30"] > 0)] = "trend-up"
    reg[trend & (df["ret30"] <= 0)] = "trend-down"
    reg[~trend & (df["V"] >= v_th)] = "hv-chop"
    reg[df["T"].isna() | df["V"].isna()] = np.nan
    return reg


def phase_of(date, halving):
    dm = (date - halving).days / DAYS_PER_MONTH
    for name, lo, hi in PHASES:
        if lo <= dm < hi:
            return name
    return None


def tag_phases(df):
    cycle = pd.Series(np.nan, index=df.index, dtype=object)
    phase = pd.Series(np.nan, index=df.index, dtype=object)
    bounds = HALVINGS + [DATA_END_SENTINEL]
    for i, h in enumerate(HALVINGS):
        nxt = bounds[i + 1]
        mask = (df.index >= h) & (df.index < nxt)
        cycle[mask] = f"C{2016 + 4 * i}"
        phase[mask] = [phase_of(d, h) for d in df.index[mask]]
    df = df.copy()
    df["cycle"], df["phase"] = cycle, phase
    return df


def share_table(df, reg_col="regime"):
    """cycle x phase x regime share (%). Returns dict of DataFrames."""
    sub = df.dropna(subset=[reg_col, "phase"])
    out = {}
    for cyc in ["C2016", "C2020", "C2024", "ALL"]:
        s = sub if cyc == "ALL" else sub[sub["cycle"] == cyc]
        if s.empty:
            continue
        ct = pd.crosstab(s["phase"], s[reg_col])
        ct = ct.reindex(index=[p[0] for p in PHASES], columns=REGIMES).fillna(0).astype(int)
        n = ct.sum(axis=1)
        pct = ct.div(n, axis=0).mul(100)
        pct["n_days"] = n
        out[cyc] = pct
    return out


def run_lengths(reg):
    """mean/median consecutive-run length per regime."""
    r = reg.dropna()
    runs = {k: [] for k in REGIMES}
    cur, cnt = None, 0
    for v in r:
        if v == cur:
            cnt += 1
        else:
            if cur is not None:
                runs[cur].append(cnt)
            cur, cnt = v, 1
    runs[cur].append(cnt)
    return {k: (np.mean(v) if v else np.nan, np.median(v) if v else np.nan,
                sum(1 for x in v if x >= 14) / len(v) * 100 if v else np.nan, len(v))
            for k, v in runs.items()}


def main():
    df = tag_phases(load())
    df["regime"] = classify(df, 1.0, 0.40)
    # gridbot sweet spot: (trend-up OR hv-chop) AND macro uptrend (close > SMA200)
    df["grid_sweet"] = df["regime"].isin(["trend-up", "hv-chop"]) & df["macro_up"]

    print("=" * 88)
    print("BASE CASE: T>1.0, V>=40%  | phase x regime share (%)")
    print("=" * 88)
    for cyc, tbl in share_table(df).items():
        print(f"\n--- {cyc} ---")
        print(tbl.round(1).to_string())

    print("\n" + "=" * 88)
    print("GRIDBOT SWEET ZONE: (trend-up OR hv-chop) AND close>SMA200  | share of phase days (%)")
    print("=" * 88)
    sub = df.dropna(subset=["regime", "phase"])
    gs = sub.groupby(["cycle", "phase"])["grid_sweet"].mean().mul(100).unstack("cycle")
    gs["ALL"] = sub.groupby("phase")["grid_sweet"].mean().mul(100)
    gs = gs.reindex([p[0] for p in PHASES])
    print(gs.round(1).to_string())

    print("\n" + "=" * 88)
    print("TREND-DOWN detail: share per cycle x phase (%) and where it concentrates")
    print("=" * 88)
    td = sub.assign(is_td=sub["regime"] == "trend-down")
    tdt = td.groupby(["cycle", "phase"])["is_td"].mean().mul(100).unstack("cycle")
    tdt["ALL"] = td.groupby("phase")["is_td"].mean().mul(100)
    print(tdt.reindex([p[0] for p in PHASES]).round(1).to_string())
    # distribution of trend-down days across phases
    tdd = sub[sub["regime"] == "trend-down"].groupby("phase").size()
    print("\ntrend-down day counts by phase (ALL cycles):")
    print(tdd.reindex([p[0] for p in PHASES]).fillna(0).astype(int).to_string())

    print("\n" + "=" * 88)
    print("PERSISTENCE: run lengths per regime (base thresholds)")
    print("=" * 88)
    rl = run_lengths(df["regime"])
    print(f"{'regime':<12}{'mean_d':>8}{'median_d':>10}{'%runs>=14d':>12}{'n_runs':>8}")
    for k, (m, md, p14, n) in rl.items():
        print(f"{k:<12}{m:>8.1f}{md:>10.1f}{p14:>12.1f}{n:>8}")

    print("\n" + "=" * 88)
    print("SENSITIVITY: T in {0.8,1.0,1.2} x V in {30%,40%,50%} -- ALL-cycle regime shares (%)")
    print("=" * 88)
    rows = []
    for t_th in [0.8, 1.0, 1.2]:
        for v_th in [0.30, 0.40, 0.50]:
            r = classify(df, t_th, v_th)
            s = pd.concat([r, df["phase"]], axis=1, keys=["reg", "phase"]).dropna()
            tot = s["reg"].value_counts(normalize=True).mul(100)
            # key metrics: trend-down share in H+18-30m, hv-chop overall, td overall
            m1830 = s[s["phase"] == "H+18-30m"]["reg"].value_counts(normalize=True).mul(100)
            rows.append({
                "T_th": t_th, "V_th": int(v_th * 100),
                "trend-up": tot.get("trend-up", 0), "trend-down": tot.get("trend-down", 0),
                "hv-chop": tot.get("hv-chop", 0), "lv-drift": tot.get("lv-drift", 0),
                "td@18-30m": m1830.get("trend-down", 0),
            })
    sens = pd.DataFrame(rows)
    print(sens.round(1).to_string(index=False))

    print("\n" + "=" * 88)
    print("STRUCTURAL CHANGE: per-cycle stats over comparable window (H+0 to H+26.3m)")
    print("=" * 88)
    # 2024 cycle only has data to H+~26.3m; compare same window across cycles
    end_m = (df.index.max() - HALVINGS[2]).days / DAYS_PER_MONTH
    print(f"(2024 cycle data ends at H+{end_m:.1f}m; comparing all cycles on H+0..{end_m:.1f}m)")
    for i, h in enumerate(HALVINGS):
        w = df[(df.index >= h) & (df.index < h + pd.Timedelta(days=end_m * DAYS_PER_MONTH))]
        w = w.dropna(subset=["regime"])
        vc = w["regime"].value_counts(normalize=True).mul(100)
        print(f"C{2016+4*i}: n={len(w):>4}  medV={w['V'].median()*100:5.1f}%  medT={w['T'].median():.2f}  "
              f"up={vc.get('trend-up',0):4.1f}%  down={vc.get('trend-down',0):4.1f}%  "
              f"chop={vc.get('hv-chop',0):4.1f}%  drift={vc.get('lv-drift',0):4.1f}%")
    # yearly vol decay
    print("\nMedian 30d annualized vol by year:")
    yv = df.groupby(df.index.year)["V"].median().mul(100).round(1)
    print(yv.to_string())

    # per-cycle trend run lengths (trend shortening?)
    print("\nMean trend-up run length by cycle (days):")
    for i, h in enumerate(HALVINGS):
        nxt = (HALVINGS + [DATA_END_SENTINEL])[i + 1]
        w = df[(df.index >= h) & (df.index < nxt)]
        rl_c = run_lengths(w["regime"])
        print(f"C{2016+4*i}: trend-up mean={rl_c['trend-up'][0]:.1f}  trend-down mean={rl_c['trend-down'][0]:.1f}  "
              f"hv-chop mean={rl_c['hv-chop'][0]:.1f}")

    # counts for warnings
    print(f"\nTotal classified days: {df['regime'].notna().sum()}, in-phase days: {len(sub)}")
    print(f"Phase coverage note: C2016 H+30-48m truncated at 2020-05-11 halving "
          f"(H+{(HALVINGS[1]-HALVINGS[0]).days/DAYS_PER_MONTH:.1f}m); "
          f"C2020 H+30-48m truncated at 2024-04-20 (H+{(HALVINGS[2]-HALVINGS[1]).days/DAYS_PER_MONTH:.1f}m); "
          f"C2024 ends at H+{end_m:.1f}m (H+18-30m partial, later phases absent).")


if __name__ == "__main__":
    main()
