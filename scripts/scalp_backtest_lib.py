"""Backtest core for sub-project H. Signals on CLOSED bars only; fills at next bar open."""
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Trade:
    coin: str
    side: int
    entry_i: int
    exit_i: int
    entry_px: float
    exit_px: float
    gross_bps: float
    net_bps: float
    exit_reason: str


def prep(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare bars with returns, vol, and ATR."""
    out = df.copy()
    out["ret"] = np.log(out["c"] / out["c"].shift(1))
    out["sigma"] = out["ret"].ewm(span=240, min_periods=240).std()
    vmean = out["v"].rolling(240).mean()
    vstd = out["v"].rolling(240).std()
    out["vol_z"] = (out["v"] - vmean) / vstd
    tr = np.maximum(
        out["h"] - out["l"],
        np.maximum(
            (out["h"] - out["c"].shift(1)).abs(),
            (out["l"] - out["c"].shift(1)).abs()
        )
    )
    out["atr14"] = tr.rolling(14).mean()
    return out


def simulate(
    df,
    sig,
    hold_bars,
    stop_atr_mult,
    fee_bps,
    slip_bps,
    coin="",
    target_px=None,
    stop_px=None,
) -> list:
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
            i += 1
            continue

        e_i = i + 1
        e_px = o[e_i] * (1 + s * slip_bps / 1e4)
        stop = stop_px[i] if stop_px is not None else e_px - s * stop_atr_mult * atr[i]
        tgt = target_px[i] if target_px is not None else None

        exit_i, exit_px, reason = None, None, None
        last = min(e_i + hold_bars, n - 1)

        for j in range(e_i, last + 1):
            if s == 1 and l[j] <= stop:  # gap-through: fill at the worse of stop/open
                exit_i, exit_px, reason = j, min(stop, o[j]), "stop"
                break
            if s == -1 and h[j] >= stop:
                exit_i, exit_px, reason = j, max(stop, o[j]), "stop"
                break
            if tgt is not None and ((s == 1 and h[j] >= tgt) or (s == -1 and l[j] <= tgt)):
                exit_i, exit_px, reason = j, tgt, "target"
                break

        if exit_i is None:
            exit_i, exit_px, reason = last, o[last], "time"

        exit_px = exit_px * (1 - s * slip_bps / 1e4)
        gross = s * (exit_px / e_px - 1) * 1e4 + 2 * slip_bps  # gross excludes slip
        net = s * (exit_px / e_px - 1) * 1e4 - 2 * fee_bps

        trades.append(
            Trade(coin, int(s), e_i, exit_i, e_px, exit_px, gross, net, reason)
        )
        i = exit_i + 1  # one position per coin, no overlap

    return trades


def metrics(trades, df=None) -> dict:
    """Calculate backtest metrics from trades."""
    if not trades:
        return {"n": 0}

    net = np.array([t.net_bps for t in trades])
    wins, losses = net[net > 0], net[net <= 0]
    pf = wins.sum() / max(1e-9, -losses.sum()) if len(losses) else float("inf")
    eq = net.cumsum()
    mdd = float((eq - np.maximum.accumulate(eq)).min())
    t_stat = float(
        net.mean() / (net.std(ddof=1) + 1e-12) * np.sqrt(len(net))
    )

    out = {
        "n": len(net),
        "pf": round(float(pf), 3),
        "win": round(float((net > 0).mean()), 3),
        "avg_net_bps": round(float(net.mean()), 2),
        "mdd_bps": round(mdd, 1),
        "t_stat": round(t_stat, 2),
    }

    if df is not None:
        mon = pd.Series(
            net,
            index=df["ts"].iloc[[t.entry_i for t in trades]].values
        )
        by_m = mon.groupby(pd.Series(mon.index).dt.to_period("M").values).sum()
        out["months_pos"] = f"{int((by_m > 0).sum())}/{len(by_m)}"

    return out


def walk_forward(df, configs, run_fn, train_days=60, test_days=30):
    """run_fn(df_slice, config) -> trades. Select best config on train (by pf, n>=20),
    apply to test; concatenate OOS trades. Returns (oos_trades, picks)."""
    ts = df["ts"]
    start, end = ts.iloc[0], ts.iloc[-1]
    oos, picks, cur = [], [], start + pd.Timedelta(days=train_days)

    while cur + pd.Timedelta(days=test_days) <= end:
        tr_df = df[
            (ts >= cur - pd.Timedelta(days=train_days)) & (ts < cur)
        ].reset_index(drop=True)
        te_df = df[
            (ts >= cur) & (ts < cur + pd.Timedelta(days=test_days))
        ].reset_index(drop=True)

        scored = []
        for cfg in configs:
            m = metrics(run_fn(tr_df, cfg))
            if m.get("n", 0) >= 20:
                scored.append((m["pf"], cfg))

        if scored:
            best = max(scored, key=lambda x: x[0])[1]
            oos.extend(run_fn(te_df, best))
            picks.append((str(cur.date()), best))

        cur += pd.Timedelta(days=test_days)

    return oos, picks


def simulate_maker(
    df,
    sig,
    limit_px,
    target_px,
    stop_px,
    fee_maker_bps,
    fee_taker_bps,
    slip_bps,
    entry_ttl=3,
    hold_bars=60,
    coin="",
) -> list:
    """Maker entry fade: limit order w/ TTL, pessimistic fill & exit rules.

    sig[i] in {+1,-1,0} decided at bar i close -> maker order placed for bars [i+1..i+entry_ttl].
    Entry fill: first bar j where l[j] < limit_px[i] (long) or h[j] > limit_px[i] (short),
    fills at limit_px[i] with maker fee, zero entry slip.

    Exit priority (starting bar after entry):
    1. STOP: active from entry bar; taker exit (fee_taker_bps + 1x slip);
       gap-through fills at worse of stop/open
    2. TARGET: strict h[k] > T (long) / l[k] < T (short), valid only from bar AFTER
       entry; maker exit (fee_maker_bps, ZERO slip)
    3. TIME-STOP: at open[entry_j + hold_bars]; taker exit (fee_taker_bps + 1x slip)

    Cost contract (registered F2b rules): slip is paid ONLY on the taker exit leg
    (stop/time), once. Maker legs (entry, target exit) pay zero slip.
    net_bps = side*(exit_px/entry_px - 1)*1e4 - entry_fee - exit_fee - exit_slip.
    """
    trades, i, n = [], 0, len(df)
    o, h, l, atr = df["o"].values, df["h"].values, df["l"].values, df["atr14"].values
    sig = np.asarray(sig)
    limit_px = np.asarray(limit_px)

    while i < n - 2:
        s = sig[i]
        if s == 0 or np.isnan(atr[i]):
            i += 1
            continue

        # Maker entry: try to fill during [i+1 .. i+entry_ttl]
        entry_j, entry_px = None, None
        for j in range(i + 1, min(i + entry_ttl + 1, n)):
            if s == 1 and l[j] < limit_px[i]:  # long: low < limit
                entry_j, entry_px = j, limit_px[i]
                break
            elif s == -1 and h[j] > limit_px[i]:  # short: high > limit
                entry_j, entry_px = j, limit_px[i]
                break

        # If no fill within TTL, skip
        if entry_j is None:
            i = min(i + entry_ttl + 1, n - 1)
            continue

        # Entered at entry_j with entry_px (limit_px[i]), maker fee
        stop = stop_px[i] if stop_px is not None else np.nan
        tgt = target_px[i] if target_px is not None else np.nan

        exit_j, exit_px, reason = None, None, None
        last = min(entry_j + hold_bars, n - 1)

        # Exit logic: STOP first (same bar as entry), then TARGET (from next bar), then TIME
        for k in range(entry_j, last + 1):
            # STOP: active from entry bar (k >= entry_j)
            if not np.isnan(stop):
                if s == 1 and l[k] <= stop:  # gap-through: fill at worse of stop/open
                    exit_j, exit_px, reason = k, min(stop, o[k]), "stop"
                    break
                elif s == -1 and h[k] >= stop:
                    exit_j, exit_px, reason = k, max(stop, o[k]), "stop"
                    break

            # TARGET: strict cross, only valid from bar after entry (k > entry_j)
            if not np.isnan(tgt) and k > entry_j:
                if s == 1 and h[k] > tgt:
                    exit_j, exit_px, reason = k, tgt, "target"
                    break
                elif s == -1 and l[k] < tgt:
                    exit_j, exit_px, reason = k, tgt, "target"
                    break

        # TIME-STOP if no stop/target triggered
        if exit_j is None:
            exit_j, exit_px, reason = last, o[last], "time"

        # Cost model per registered F2b rules (slip ONLY on taker exit leg, once):
        # - target exit  -> maker leg: fee_maker_bps, ZERO slip
        # - stop/time    -> taker leg: fee_taker_bps + 1x slip
        if reason == "target":
            exit_fee = fee_maker_bps
            exit_slip = 0.0
        else:  # "stop" / "time"
            exit_fee = fee_taker_bps
            exit_slip = slip_bps

        # gross = raw price move (no costs); exit_px is the raw fill price
        gross = s * (exit_px / entry_px - 1) * 1e4
        net = gross - fee_maker_bps - exit_fee - exit_slip

        trades.append(
            Trade(coin, int(s), entry_j, exit_j, entry_px, exit_px, gross, net, reason)
        )
        i = exit_j + 1  # Move past this exit, no overlap

    return trades
