"""Copy-trade score, spec v0.5 (docs/plans/copytrade-score.md).

Simulates a delayed, proportionally-sized copier of a wallet's perp fills over
its FULL trading history, applies three gates and a five-dimension 100-point
score. D1 (跟單可複製性) is three separate tests (a: normal, sampled per-event
delay / b: three execution-stress scenarios, worst taken / c: per-event miss
recovery, computed in closed form, not simulated) per the coordinator's
2026-09-24 v0.3 decision.

Usage:  python copyscore.py <addr10>
Reads:  data/<addr10>/{fills.json.gz, twap_fills.json.gz, portfolio.json,
        funding.json, ledger.json}
Writes: data/<addr10>/copyscore.json, data/<addr10>/copyscore.txt

Data sources: public Hyperliquid /info endpoint + public Binance FAPI klines
only. No .env* is read; no order/transfer code is imported or called.
"""
import argparse
import gzip
import json
import math
import os
import pathlib
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import pandas as pd

VAULT_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(VAULT_ROOT / "scripts"))
import scalp_lib as sl  # noqa: E402  (binance_perp_symbols/binance_symbol/pull_binance_1m/candles_to_df/get_candles)

ROOT = pathlib.Path(__file__).resolve().parent.parent  # reports/wallets-batch-2026-09
CANDLE_DIR = ROOT / "data" / "_candles"

# ============================================================================
# ⚙ / ⚙⚙ tunable parameters (plan §1–§3, §7 assumptions list)
# ============================================================================
SEED = 20260924
TAKER_FEE_BPS = 4.5                 # plan §1.3, HL base taker tier ("你的費率")
T3_K = 0.25                         # plan §1.4 T3 model coefficient
HL_1M_RETENTION_DAYS = 3.5          # plan §1.4, HL candleSnapshot 1m retention
HL_1M_RETENTION_MS = int(HL_1M_RETENTION_DAYS * 86_400_000)

# ⚙⚙ delay distribution — NO real measurement yet (plan §7): lognormal placeholder,
# median 3s / P95 15s (self-hosted copytrader: WS fill notice -> order ack).
DELAY_MEDIAN_S = 3.0
DELAY_P95_S = 15.0
DELAY_MU = math.log(DELAY_MEDIAN_S)
DELAY_SIGMA = math.log(DELAY_P95_S / DELAY_MEDIAN_S) / 1.6448536269514722  # z_0.95
DELAY_CAP_S = 300.0  # sampling ceiling: bounds fetch-window size; P(lognormal > 300s) ~1e-6, negligible

S_N_BPS = 5.0                       # ⚙ baseline slippage s_n
STRESS_DELAY_S = DELAY_P95_S * 2    # (i)/(iii): fixed 30s, not sampled
STRESS_SLIP_BPS = S_N_BPS * 2       # (ii)/(iii): 2x slippage
RECON_TICK_MS = 60_000              # ⚙ reconciliation cadence for D1-c

T2_MIN_CUM_NOTIONAL = 0.95          # ⚙ T2 scope rule: >=95% cum notional OR top 12, whichever is MORE coins
T2_TOP_N = 12
BINANCE_CLUSTER_GAP_MS = 24 * 3_600_000     # merge Binance 1m fetch windows within 1 day of each other
BINANCE_CLUSTER_LEAD_MS = 5 * 60_000
BINANCE_CLUSTER_LAG_MS = 15 * 60_000        # covers DELAY_CAP_S(300s) + RECON_TICK(60s) + margin

E_MIN_FLOOR = 1000.0                # ⚙ plan v0.4 §0: E_min = max($1,000, 1% x leader's W-peak equity)
STOPOUT_LEVERAGE = 50.0             # ⚙ plan v0.5 §1.4b: copier stop-out if C_t<=0 or gross/C_t > 50x
E_MIN_PEAK_FRAC = 0.01

GATE_G2_MAX_LEVERAGE = 3.0
GATE_G2_WORST_DAY_FRAC = 0.15
GATE_G3_MIN_DAYS = 3
GATE_G3_PCT_ACTIVE = 0.05

D1_A_ANCHOR = (0.80, 1.00)          # r<=80% -> 0, r>=100% -> 1
D1_BC_ANCHOR = (0.50, 0.90)         # r<=50% -> 0, r>=90% -> 1

D2_ANCHORS = {
    "mdd": (0.10, 0.30),
    "worst_day": (0.03, 0.15),
    "worst_week": (0.06, 0.25),
    "dd_days": (30, 180),
    "lev_peak": (1.0, 5.0),
}
D3_ANCHOR_MHIT = (0.4, 0.8)
D3_ANCHOR_ROB = (0.0, 0.5)
D3_ANCHOR_CONC = (1.0, 0.25)
D4_ANCHOR = (-0.5, 0.5)
D4_RB_FLOOR = 0.05
D5_ANCHOR_HISTORY = (90, 365)
D5_ANCHOR_COVERAGE = (0.5, 1.0)
D5_ANCHOR_PRICE_LEVEL = (0.5, 0.9)
D5_SPLIT_FRAC = 0.75

ASSUMPTIONS = []


def note(msg):
    if msg not in ASSUMPTIONS:
        ASSUMPTIONS.append(msg)


# ============================================================================
# small pure helpers
# ============================================================================
def sign(x):
    return 1.0 if x > 0 else (-1.0 if x < 0 else 0.0)


def is_spot(coin):
    return coin.startswith("@") or "/" in coin


def day_ms(date_str):
    return int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def ms_to_date(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def date_range(w0_ms, w1_ms):
    d0 = datetime.fromtimestamp(w0_ms / 1000, tz=timezone.utc).date()
    d1 = datetime.fromtimestamp(w1_ms / 1000, tz=timezone.utc).date()
    out, cur = [], d0
    while cur < d1:
        out.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return out


def lin_score(x, zero_at, one_at):
    if one_at == zero_at:
        return 1.0 if x >= one_at else 0.0
    t = (x - zero_at) / (one_at - zero_at)
    return max(0.0, min(1.0, t))


def d4_score(x):
    lo, hi = D4_ANCHOR
    return lin_score(x, lo, hi)


# ============================================================================
# position book — shared realized/unrealized accounting for leader & copier
# ============================================================================
class PositionBook:
    __slots__ = ("qty", "avg_cost")

    def __init__(self):
        self.qty = 0.0
        self.avg_cost = 0.0

    def apply_trade(self, delta, price):
        if delta == 0:
            return 0.0
        realized = 0.0
        if self.qty == 0 or (delta > 0) == (self.qty > 0):
            new_qty = self.qty + delta
            self.avg_cost = price if self.qty == 0 else (
                (self.avg_cost * abs(self.qty) + price * abs(delta)) / abs(new_qty)
            )
            self.qty = new_qty
        else:
            close_qty = min(abs(delta), abs(self.qty))
            realized = close_qty * (price - self.avg_cost) * sign(self.qty)
            crossed = abs(delta) > abs(self.qty)
            self.qty = self.qty + delta
            if crossed:
                self.avg_cost = price
            elif abs(self.qty) < 1e-9:
                self.qty = 0.0
                self.avg_cost = 0.0
        return realized


# ============================================================================
# candle fetch + cache layer — shared ACROSS WALLETS by symbol/coin (public
# HL /info + public Binance FAPI only). Interval-tracked so a later wallet's
# narrower/wider need against an already-cached symbol only fetches the gap.
# ============================================================================
def fetch_hl_paged(coin, interval, start_ms, end_ms, bar_ms, cap=5000):
    rows, cur = [], start_ms
    while cur < end_ms:
        win_end = min(cur + cap * bar_ms, end_ms)
        # NOTE: sl.get_candles() -> scalp_lib.info() already retries 5x with its own
        # exponential backoff (up to ~31s) on 429/5xx. A persistently-failing request
        # (observed: HL candleSnapshot 500s on some HIP-3/numbered coin identifiers,
        # e.g. "#3940" — not transient, retrying never helps) should fail fast rather
        # than being retried again on top of that; one extra attempt is enough to
        # absorb a genuinely transient blip without multiplying worst-case latency.
        batch = None
        for attempt in range(2):
            try:
                batch = sl.get_candles(coin, interval, cur, win_end)
                break
            except Exception:
                if attempt == 1:
                    raise
                time.sleep(3)
        time.sleep(0.35)
        if not batch:
            cur = win_end
            continue
        rows.extend(batch)
        last_t = max(int(b["t"]) for b in batch)
        cur = max(last_t + bar_ms, cur + bar_ms)
    return sl.candles_to_df(rows)


def merge_intervals(intervals):
    intervals = sorted(tuple(x) for x in intervals)
    out = []
    for s, e in intervals:
        if out and s <= out[-1][1] + 60_000:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def is_covered(intervals, s, e):
    return any(a <= s and e <= b for a, b in intervals)


def cluster_ranges(times, gap_ms, lead_ms, lag_ms):
    times = sorted(times)
    if not times:
        return []
    ranges = []
    cur_s = cur_e = times[0]
    for t in times[1:]:
        if t - cur_e > gap_ms:
            ranges.append((cur_s - lead_ms, cur_e + lag_ms))
            cur_s = t
        cur_e = t
    ranges.append((cur_s - lead_ms, cur_e + lag_ms))
    return ranges


def ensure_range(key, ranges, fetch_fn, stats):
    """Shared-by-`key` interval cache: fetch only the parts of `ranges` not
    already covered by a prior call (this wallet or an earlier one) for the
    same key. Persists a parquet (bars) + json (covered intervals) pair.
    A range that still fails after fetch_hl_paged's own retries is SKIPPED
    (not fatal to the whole wallet run) — noted, and left uncovered so a
    later run can retry it."""
    pq = CANDLE_DIR / f"{key}.parquet"
    meta = CANDLE_DIR / f"{key}.meta.json"
    df = pd.DataFrame(columns=["t", "o", "h", "l", "c", "v", "n", "ts"])
    intervals = []
    if pq.exists() and meta.exists():
        try:
            df = pd.read_parquet(pq)
            intervals = [tuple(x) for x in json.loads(meta.read_text())["covered"]]
        except Exception as exc:
            # a concurrent writer (N=2 wallets sharing this symbol's cache) can race
            # a plain to_parquet() into a corrupt file; treat as empty and refetch —
            # the atomic replace below prevents this going forward.
            note(f"{key}: cache file unreadable ({exc}); treated as empty and will be refetched/rewritten")
            df = pd.DataFrame(columns=["t", "o", "h", "l", "c", "v", "n", "ts"])
            intervals = []
    changed = False
    for s, e in ranges:
        if s >= e or is_covered(intervals, s, e):
            stats["hits"] += 1
            continue
        stats["misses"] += 1
        try:
            new_df = fetch_fn(s, e)
        except Exception as exc:
            note(f"{key}: fetch failed for range [{s},{e}] after retries ({exc}); skipped, left uncovered")
            continue
        if new_df is not None and len(new_df):
            df = pd.concat([df, new_df], ignore_index=True).drop_duplicates("t").sort_values("t").reset_index(drop=True)
        intervals = merge_intervals(intervals + [(s, e)])
        changed = True
    if changed:
        CANDLE_DIR.mkdir(parents=True, exist_ok=True)
        # atomic write (tmp + os.replace): N=2 wallets can share this symbol's cache
        # concurrently; a plain to_parquet() can be torn by a racing writer.
        tmp_pq = pq.with_name(pq.name + f".tmp{os.getpid()}")
        df.to_parquet(tmp_pq)
        os.replace(tmp_pq, pq)
        tmp_meta = meta.with_name(meta.name + f".tmp{os.getpid()}")
        tmp_meta.write_text(json.dumps({"covered": [list(x) for x in intervals]}))
        os.replace(tmp_meta, meta)
    return df


def hl_universe(stats):
    """Coins HL's candleSnapshot can plausibly serve right now, cached & shared.
    Discovered empirically (2026-09-24): fills can carry a numbered coin id
    (e.g. "#3940") for an asset no longer in HL's current perp/spot universe —
    candleSnapshot then returns HTTP 500 EVERY time (permanent, not transient;
    retrying wastes ~1-2min per interval per such coin). Coins outside this set
    skip straight past T1/T2/HL-1h/HL-1d to avoid that cost; they simply have
    no HL/Binance price data (T3_missing / no MTM price), which is a real data
    limitation, not a bug — flagged in assumptions when it happens."""
    p = CANDLE_DIR / "hl_universe.json"
    if p.exists():
        stats["hits"] += 1
        return set(json.loads(p.read_text()))
    stats["misses"] += 1
    meta, _ctxs = sl.info({"type": "metaAndAssetCtxs"})
    sm = sl.info({"type": "spotMeta"})
    names = {m["name"] for m in meta["universe"]} | {u["name"] for u in sm["universe"]}
    CANDLE_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sorted(names)))
    return names


def prefetch(coins, coin_span, t2_scope, W0, W1, now_ms, stats):
    """coins: ALL coins with events (needed for HL 1d/1h — MTM + T3 fallback).
    t2_scope: subset also eligible for the Binance 1m proxy (T2)."""
    CANDLE_DIR.mkdir(parents=True, exist_ok=True)
    universe = hl_universe(stats)
    dead_coins = sorted(c for c in coins if c not in universe)
    if dead_coins:
        note(f"{len(dead_coins)} coin(s) not in HL's current perp/spot universe (delisted/renamed identifier — "
             f"candleSnapshot returns HTTP 500 for these, verified, not a transient issue): {dead_coins[:10]}"
             f"{'...' if len(dead_coins) > 10 else ''}. Skipped entirely (T1/T2/HL-1h/HL-1d); no MTM price / "
             "always T3_missing for these coins.")
    sym_path = CANDLE_DIR / "binance_symbols.json"
    if sym_path.exists():
        avail = set(json.loads(sym_path.read_text()))
        stats["hits"] += 1
    else:
        avail = sl.binance_perp_symbols()
        sym_path.write_text(json.dumps(sorted(avail)))
        stats["misses"] += 1

    verbose = os.environ.get("COPYSCORE_VERBOSE")
    bin1m, hl1h, hl1d, hl1m_recent = {}, {}, {}, {}
    dead_set = set(dead_coins)
    for coin in coins:
        if coin in dead_set:
            bin1m[coin], hl1h[coin], hl1d[coin], hl1m_recent[coin] = {}, {}, {}, {}
            continue
        span0, span1 = coin_span[coin]
        t_coin0 = time.time()

        df1h = ensure_range(f"HL_{coin}_1h", [(span0 - 5 * 60_000, span1 + 5 * 60_000)],
                             lambda s, e, c=coin: fetch_hl_paged(c, "1h", s, e, 3_600_000), stats)
        hl1h[coin] = dict(zip(df1h["t"].tolist(), zip(df1h["h"].tolist(), df1h["l"].tolist()))) if len(df1h) else {}
        if verbose:
            print(f"  [{coin}] 1h done +{time.time()-t_coin0:.1f}s", file=sys.stderr, flush=True)

        df1d = ensure_range(f"HL_{coin}_1d", [(W0 - 86_400_000, W1 + 86_400_000)],
                             lambda s, e, c=coin: fetch_hl_paged(c, "1d", s, e, 86_400_000), stats)
        hl1d[coin] = {ts.strftime("%Y-%m-%d"): c for ts, c in zip(df1d["ts"], df1d["c"])} if len(df1d) else {}
        if verbose:
            print(f"  [{coin}] 1d done +{time.time()-t_coin0:.1f}s", file=sys.stderr, flush=True)

        if now_ms - span0 <= HL_1M_RETENTION_MS:
            r_start = max(span0, now_ms - HL_1M_RETENTION_MS) - 5 * 60_000
            r_end = span1 + int(DELAY_CAP_S * 1000) + RECON_TICK_MS + 5 * 60_000
            dfr = ensure_range(f"HL_{coin}_1m_recent", [(r_start, r_end)],
                                lambda s, e, c=coin: fetch_hl_paged(c, "1m", s, e, 60_000), stats)
            hl1m_recent[coin] = dict(zip(dfr["t"].tolist(), zip(dfr["o"].tolist(), dfr["c"].tolist()))) if len(dfr) else {}
        else:
            hl1m_recent[coin] = {}
        if verbose:
            print(f"  [{coin}] 1m_recent done +{time.time()-t_coin0:.1f}s", file=sys.stderr, flush=True)

        if coin in t2_scope:
            sym = sl.binance_symbol(coin, avail)
            if sym:
                ts_ = [t for t in _event_times_cache.get(coin, [])]
                ranges = cluster_ranges(ts_, BINANCE_CLUSTER_GAP_MS, BINANCE_CLUSTER_LEAD_MS, BINANCE_CLUSTER_LAG_MS)
                if verbose:
                    print(f"  [{coin}] binance {sym}: {len(ranges)} cluster range(s) {ranges}", file=sys.stderr, flush=True)
                df = ensure_range(f"{sym}_1m", ranges, lambda s, e, sym=sym: sl.pull_binance_1m(sym, s, e), stats)
                bin1m[coin] = dict(zip(df["t"].tolist(), zip(df["o"].tolist(), df["c"].tolist()))) if len(df) else {}
                if verbose:
                    print(f"  [{coin}] binance done +{time.time()-t_coin0:.1f}s ({len(df)} bars)", file=sys.stderr, flush=True)
            else:
                bin1m[coin] = {}
                note(f"{coin}: in T2 scope but no Binance USDT-perp symbol found; falls back to T1/T3")
        else:
            bin1m[coin] = {}

    return bin1m, hl1h, hl1d, hl1m_recent


_event_times_cache = {}  # coin -> [event times] ; populated by main() before prefetch()


def bar_start(t_ms, bar_ms):
    return (t_ms // bar_ms) * bar_ms


def M_from_1m_dict(d, t, t_end):
    b1, b2 = bar_start(t, 60_000), bar_start(t_end, 60_000)
    if b1 == b2:
        return 1.0  # plan §1.4: same 1m bar -> M=1, delay cost is slippage-only
    row1, row2 = d.get(b1), d.get(b2)
    if row1 is None or row2 is None:
        return None
    c1, o2 = row1[1], row2[0]
    if not c1:
        return None
    return o2 / c1


def resolve_M(coin, t, delta_s, sign_dir, now_ms, bin1m, hl1h, hl1m_recent, t2_allowed):
    t_end = t + int(delta_s * 1000)
    if now_ms - t <= HL_1M_RETENTION_MS:
        m = M_from_1m_dict(hl1m_recent.get(coin, {}), t, t_end)
        if m is not None:
            return m, "T1"
    if t2_allowed:
        m = M_from_1m_dict(bin1m.get(coin, {}), t, t_end)
        if m is not None:
            return m, "T2"
    hb = bar_start(t, 3_600_000)
    hl = hl1h.get(coin, {}).get(hb)
    if hl is not None and hl[1]:
        h, l = hl
        m = 1 + sign_dir * T3_K * (h / l - 1) * math.sqrt(delta_s / 3600)
        return m, "T3"
    note(f"{coin}: no T1/T2/T3 price data at t={t}; M forced to 1.0 (T3_missing)")
    return 1.0, "T3_missing"


# ============================================================================
# leader event reconstruction (v0.3: adds `kind` open/reduce, plan §1.1)
# ============================================================================
def load_fills_merged(D):
    fills = json.load(gzip.open(D / "fills.json.gz"))
    n_twap = 0
    tw_path = D / "twap_fills.json.gz"
    if tw_path.exists():
        have = {f["tid"] for f in fills}
        extra = [f for f in json.load(gzip.open(tw_path)) if f["tid"] not in have]
        fills.extend(extra)
        n_twap = len(extra)
    fills.sort(key=lambda f: f["time"])
    return fills, n_twap


def build_events(fills, W0, W1):
    evs = []
    leader_qty = defaultdict(float)
    for f in fills:
        if is_spot(f["coin"]):
            continue
        if not (W0 <= f["time"] < W1):
            continue
        sp = float(f["startPosition"])
        delta = float(f["sz"]) * (1.0 if f["side"] == "B" else -1.0)
        ep = sp + delta
        kind = "open" if abs(ep) > abs(sp) else "reduce"
        leader_qty[f["coin"]] += delta
        evs.append({
            "t": f["time"], "coin": f["coin"], "delta": delta, "kind": kind,
            "price": float(f["px"]), "fee": float(f["fee"]),
            "closedPnl": float(f["closedPnl"]),
            "leader_target": leader_qty[f["coin"]],
        })
    return evs, dict(leader_qty)


# ============================================================================
# simulation — v0.3: every event executes (NO random miss/catchup in a/b;
# miss-recovery is D1-c's closed-form per-event calc, done separately below).
# Day-driven proportional sizing (plan §1.2, unchanged from v0.2).
# ============================================================================
def simulate_copier_v3(evs, days, L_series, E0, E_min, delay_fn, slip_bps, seed, now_ms,
                        bin1m, hl1h, hl1m_recent, price_lookup, t2_scope, funding_by_day):
    rng = random.Random(seed)
    evs_by_day = defaultdict(list)
    for ev in evs:
        evs_by_day[ms_to_date(ev["t"])].append(ev)

    scratch_book = defaultdict(PositionBook)
    follower_qty = defaultdict(float)
    target = defaultdict(float)
    trades = []
    level_counts = Counter()
    slip = slip_bps / 1e4

    C = E0
    prev_unreal = 0.0
    last_price = {}
    floored_days = 0
    max_ratio = 0.0

    for d in days:
        L_d = L_series.get(d, E0)
        denom = max(L_d, E_min) if L_d is not None else E_min  # plan v0.4 §0/§1.2: floor at E_min
        if L_d is None or L_d < E_min:
            floored_days += 1
        ratio = C / denom if denom > 0 else 0.0
        max_ratio = max(max_ratio, ratio)

        realized_today = 0.0
        fee_today = 0.0
        for ev in sorted(evs_by_day.get(d, []), key=lambda x: x["t"]):
            target[ev["coin"]] += ev["delta"] * ratio
            gap = target[ev["coin"]] - follower_qty[ev["coin"]]
            if abs(gap) < 1e-12:
                continue
            delay_s = delay_fn(ev, rng)
            sdir = sign(gap)
            M, level = resolve_M(ev["coin"], ev["t"], delay_s, sdir, now_ms, bin1m, hl1h, hl1m_recent,
                                  ev["coin"] in t2_scope)
            level_counts[level] += 1
            p_exec = ev["price"] * M * (1 + slip * sdir)
            fee = TAKER_FEE_BPS / 1e4 * abs(gap) * p_exec
            realized_today += scratch_book[ev["coin"]].apply_trade(gap, p_exec)
            fee_today += fee
            follower_qty[ev["coin"]] += gap
            trades.append({
                "t": ev["t"] + int(delay_s * 1000), "coin": ev["coin"], "qty": gap, "price": p_exec, "fee": fee,
                "kind": ev["kind"], "delay_s": delay_s, "event_t": ev["t"], "event_price": ev["price"], "sdir": sdir,
            })

        gross = 0.0
        unreal = 0.0
        for coin, bk in scratch_book.items():
            if abs(bk.qty) < 1e-9:
                continue
            px = price_lookup.get(coin, {}).get(d, last_price.get(coin))
            if px is None:
                continue
            last_price[coin] = px
            gross += abs(bk.qty) * px
            unreal += bk.qty * (px - bk.avg_cost)
        unreal_change = unreal - prev_unreal
        prev_unreal = unreal
        funding = funding_by_day.get(d, 0.0)
        C_new = C + realized_today - fee_today + funding + unreal_change

        # plan v0.5 §1.4b: copier is a real account — stop-out (liquidation) if
        # equity <= 0 or leverage > 50x at today's MTM. Close everything at
        # today's close (no fee/slippage — spec doesn't charge for the forced
        # close), floor equity at 0, and follow NO further events afterward.
        # C_new<=0: leverage (gross/C_t) is mathematically undefined — report None
        # (coordinator 2026-09-24 correction: do not print a gross/epsilon fake number).
        equity_wiped = C_new <= 0
        lev_today = None if equity_wiped else gross / C_new
        if equity_wiped or (lev_today is not None and lev_today > STOPOUT_LEVERAGE):
            for coin, bk in list(scratch_book.items()):
                if abs(bk.qty) < 1e-9:
                    continue
                px = last_price.get(coin)
                if px is None:
                    continue
                qty_close = -bk.qty
                bk.apply_trade(qty_close, px)
                trades.append({
                    "t": day_ms(d) + 1, "coin": coin, "qty": qty_close, "price": px, "fee": 0.0,
                    "kind": "stopout_close", "delay_s": 0.0, "event_t": day_ms(d), "event_price": px,
                    "sdir": sign(qty_close),
                })
            C = max(C_new, 0.0)
            lev_desc = "undefined (C_t<=0)" if equity_wiped else f"{lev_today:.2f}x"
            extra = (" Note: day-granularity MTM cannot see intraday spikes, only the end-of-day snapshot, "
                     f"so the observed value can exceed {STOPOUT_LEVERAGE:.0f}x by more than a small margin."
                     if (lev_today is not None and lev_today > STOPOUT_LEVERAGE * 1.2) else "")
            note(f"STOP-OUT on {d}: C_t={'<=0' if equity_wiped else f'{C_new:,.2f}'}, leverage={lev_desc} "
                 f"(> {STOPOUT_LEVERAGE:.0f}x or equity<=0) — closed all positions at close, equity floored at "
                 f"${C:,.2f}, no further events followed (plan v0.5 §1.4b).{extra}")
            # plan v0.5 §1.4b: "槓桿尖峰取爆倉日前的最大值（含爆倉日）" — the stop-out day's PRE-close
            # leverage must be captured here; the official run_daily_mtm_v2 re-derivation of daily_gross
            # would only see the ALREADY-closed (flat) position on that day and report 0.
            return trades, level_counts, d, lev_today

        C = C_new

    if floored_days:
        note(f"L_t (leader daily equity) was below E_min (${E_min:,.2f}) on {floored_days}/{len(days)} day(s) of the "
             f"scored window; the max(L_t, E_min) floor (plan v0.4 §0/§1.2) capped the sizing ratio there "
             f"(peak ratio observed: {max_ratio:,.2f}x).")
    return trades, level_counts, None, None


def compute_miss_losses(baseline_trades, now_ms, bin1m, hl1h, hl1m_recent, t2_scope, slip_bps):
    """plan §3 D1-c (v0.4 sign fix): for each baseline (test-a) trade, the isolated
    effect of that ONE event faulting (missed until the next 60s reconciliation
    tick), in closed form (no re-simulation):
      loss(e) = qty * (p_recon - p_exec) + (catch-up slippage + catch-up fee)
    qty is SIGNED (buy positive, sell negative); loss CAN be negative (a missed
    buy followed by a price drop before catch-up is a net benefit). v0.3 had the
    first term's sign flipped — fixed here per the coordinator's 2026-09-24
    correction (plan §3 D1-c). r_c(e) = (copier_net_normal-loss)/leader_net."""
    slip = slip_bps / 1e4
    losses_open, losses_reduce = [], []
    for tr in baseline_trades:
        t = tr["event_t"]
        t_plus_delta = t + int(tr["delay_s"] * 1000)
        t_recon = ((t_plus_delta // RECON_TICK_MS) + 1) * RECON_TICK_MS
        recon_delay_s = (t_recon - t) / 1000.0
        sdir = tr["sdir"]
        M, _level = resolve_M(tr["coin"], t, recon_delay_s, sdir, now_ms, bin1m, hl1h, hl1m_recent,
                               tr["coin"] in t2_scope)
        p_recon = tr["event_price"] * M
        p_recon_exec = p_recon * (1 + slip * sdir)
        catchup_fee = TAKER_FEE_BPS / 1e4 * abs(tr["qty"]) * p_recon_exec
        catchup_slip_cost = abs(tr["qty"]) * p_recon * slip
        loss = tr["qty"] * (p_recon - tr["price"]) + (catchup_slip_cost + catchup_fee)
        (losses_open if tr["kind"] == "open" else losses_reduce).append(loss)
    return losses_open, losses_reduce


def run_daily_mtm_v2(trades, W0, W1, price_lookup, funding_by_day):
    days = date_range(W0, W1)
    by_day = defaultdict(list)
    for tr in trades:
        by_day[ms_to_date(tr["t"])].append(tr)

    books = defaultdict(PositionBook)
    daily_net, daily_gross, daily_pos = {}, {}, {}
    prev_unreal = 0.0
    last_price = {}

    for d in days:
        realized_today = 0.0
        fee_today = 0.0
        for tr in sorted(by_day.get(d, []), key=lambda x: x["t"]):
            realized_today += books[tr["coin"]].apply_trade(tr["qty"], tr["price"])
            fee_today += tr["fee"]

        gross, unreal, pos_snap = 0.0, 0.0, {}
        for coin, book in books.items():
            if abs(book.qty) < 1e-9:
                continue
            px = price_lookup.get(coin, {}).get(d, last_price.get(coin))
            if px is None:
                continue
            last_price[coin] = px
            gross += abs(book.qty) * px
            unreal += book.qty * (px - book.avg_cost)
            pos_snap[coin] = book.qty

        unreal_change = unreal - prev_unreal
        prev_unreal = unreal
        funding = funding_by_day.get(d, 0.0)
        daily_net[d] = realized_today - fee_today + funding + unreal_change
        daily_gross[d] = gross
        daily_pos[d] = pos_snap

    return days, daily_net, daily_gross, daily_pos


def build_funding_by_day(funding, W0, W1):
    out = defaultdict(float)
    for r in funding:
        t = r["time"]
        if W0 <= t < W1:
            out[ms_to_date(t)] += float(r["delta"]["usdc"])
    return dict(out)


def build_leader_equity_daily(portfolio, anchor_v0, W0, W1, leader_daily_net, days):
    """v0.4 §1.2: L_t = the leader's REAL reported equity, linearly interpolated
    from portfolio.allTime.accountValueHistory to each day's 00:00 UTC boundary.
    No input/output netting (v0.3's netting was wrong per the coordinator's
    2026-09-24 correction: the leader sizes positions against what they actually
    have, deposits and all; only C_t, the copier's OWN equity, should stay
    unaffected by the leader's deposits/withdrawals — and it already does,
    since C_t only ever accumulates the copier's own simulated daily net).
    Falls back to the leader's own fills-based MTM curve (anchor_v0 + cumsum of
    leader_daily_net) for any day outside accountValueHistory's covered range.
    """
    avh = sorted(((int(t), float(v)) for t, v in portfolio["allTime"]["accountValueHistory"]), key=lambda p: p[0])

    def raw_interp(t):
        if not avh or t < avh[0][0] or t > avh[-1][0]:
            return None
        for i in range(len(avh) - 1):
            t0, v0 = avh[i]
            t1, v1 = avh[i + 1]
            if t0 <= t <= t1:
                if t1 == t0:
                    return v0
                frac = (t - t0) / (t1 - t0)
                return v0 + frac * (v1 - v0)
        return avh[-1][1]

    leader_mtm_curve = {}
    cum = anchor_v0
    for d in days:
        cum += leader_daily_net.get(d, 0.0)
        leader_mtm_curve[d] = cum

    L, fallback_days = {}, []
    for d in days:
        t = day_ms(d)
        raw = raw_interp(t)
        if raw is None:
            L[d] = leader_mtm_curve[d]
            fallback_days.append(d)
        else:
            L[d] = raw
    return L, fallback_days


def cut_episodes_for_conc(all_fills, W1, price_lookup, last_day):
    perp = [f for f in all_fills if not is_spot(f["coin"]) and f["time"] < W1]
    episodes = []
    cur = {}
    for f in perp:
        c = f["coin"]
        sp = float(f["startPosition"])
        delta = float(f["sz"]) * (1.0 if f["side"] == "B" else -1.0)
        ep = sp + delta
        px = float(f["px"])
        if cur.get(c) is None or abs(sp) < 1e-9:
            cur[c] = {"coin": c, "t0": f["time"], "pnl": 0.0, "fee": 0.0, "n": 0, "book": PositionBook()}
        r = cur[c]
        r["pnl"] += float(f["closedPnl"])
        r["fee"] += float(f["fee"])
        r["n"] += 1
        r["book"].apply_trade(delta, px)
        flipped = (sp > 0 > ep) or (sp < 0 < ep)
        if abs(ep) < 1e-9 or flipped:
            r["t1"] = f["time"]
            r["net"] = r["pnl"] - r["fee"]
            r["open"] = False
            episodes.append(r)
            cur[c] = None
            if flipped:
                nb = PositionBook()
                nb.apply_trade(ep, px)
                cur[c] = {"coin": c, "t0": f["time"], "pnl": 0.0, "fee": 0.0, "n": 0, "book": nb}
    for c, r in cur.items():
        if r is None:
            continue
        px_end = price_lookup.get(c, {}).get(last_day)
        unreal = r["book"].qty * (px_end - r["book"].avg_cost) if px_end is not None else 0.0
        if px_end is None:
            note(f"{c}: no W-end price for open episode unrealized valuation; unrealized treated as 0 for conc")
        r["t1"] = None
        r["net"] = (r["pnl"] - r["fee"]) + unreal
        r["open"] = True
        episodes.append(r)
    return episodes


def curve_analytics(days, daily_net, daily_gross, E0):
    net_series = [daily_net.get(d, 0.0) for d in days]
    equity = []
    eq = E0
    for n in net_series:
        eq += n
        equity.append(eq)
    equity_start = [E0] + equity[:-1]
    floor = E0 * 0.01 if E0 else 1.0
    floored = False

    running_peak = E0
    dd_days = 0
    max_dd_days = 0
    mdd = 0.0
    for e in equity:
        if e > running_peak:
            running_peak = e
            dd_days = 0
        else:
            dd_days += 1
        denom = running_peak if running_peak > floor else floor
        if running_peak <= floor:
            floored = True
        mdd = max(mdd, (running_peak - e) / denom) if denom > 0 else mdd
        max_dd_days = max(max_dd_days, dd_days)

    worst_day_list = []
    for i, n in enumerate(net_series):
        base = equity_start[i]
        denom = base if base > floor else floor
        if base <= floor:
            floored = True
        worst_day_list.append(n / denom if denom > 0 else 0.0)
    worst_day_frac = min(worst_day_list) if worst_day_list else 0.0

    if len(net_series) >= 7:
        worst_week_list = []
        for i in range(len(net_series) - 6):
            base = equity_start[i]
            denom = base if base > floor else floor
            worst_week_list.append(sum(net_series[i:i + 7]) / denom if denom > 0 else 0.0)
        worst_week_frac = min(worst_week_list)
    else:
        base = equity_start[0] if equity_start else E0
        denom = base if base > floor else floor
        worst_week_frac = sum(net_series) / denom if denom > 0 else 0.0

    lev_list = []
    for i, d in enumerate(days):
        g = daily_gross.get(d, 0.0)
        e = equity[i]
        denom = e if e > floor else floor
        if e <= floor:
            floored = True
        lev_list.append(g / denom if denom > 0 else 0.0)
    lev_peak = max(lev_list) if lev_list else 0.0

    if floored:
        note("D2/gate denominators (peak/day-equity C_t) floored at 1% of E0 on at least one day to avoid divide-by-zero")

    return {
        "equity": equity, "equity_start": equity_start, "net_series": net_series,
        "mdd": mdd, "dd_days": max_dd_days,
        "worst_day_frac": worst_day_frac, "worst_week_frac": worst_week_frac,
        "lev_peak": lev_peak,
    }


def active_days(trades):
    return sorted({ms_to_date(tr["t"]) for tr in trades})


def remove_best_days(daily_net, days, n_active):
    n_remove = max(GATE_G3_MIN_DAYS, round(GATE_G3_PCT_ACTIVE * n_active))
    values = [daily_net.get(d, 0.0) for d in days]
    total = sum(values)
    best = sorted(values, reverse=True)[:n_remove]
    reduced = total - sum(best)
    return total, reduced, n_remove


def delay_sampled(ev, rng):
    return min(rng.lognormvariate(DELAY_MU, DELAY_SIGMA), DELAY_CAP_S)


def make_delay_fixed(x):
    return lambda ev, rng: x


def write_unscorable(D, addr_full, addr10, W0_raw, W1, E_min, L_peak, reason):
    """plan v0.4 §0: no day in the full-history window ever reaches E_min (or no
    events remain after the push) -> score 0, gate FAIL, ranked last."""
    note(f"UNSCORABLE: {reason}")
    zero_gate = {"worst_stress_scenario": None, "net": 0.0, "pass": False}
    out = {
        "spec_version": "v0.5",
        "addr": addr_full, "addr10": addr10,
        "unscorable": True, "unscorable_reason": reason,
        "E_min": E_min, "L_peak": L_peak, "stopout_date": None, "stopout_leverage": None,
        "stopout_leverage_threshold": STOPOUT_LEVERAGE, "stopout_stress": {},
        "window": {"start": ms_to_date(W0_raw), "end": ms_to_date(W1 - 1), "start_ms": W0_raw, "end_ms": W1,
                   "days": round((W1 - W0_raw) / 86_400_000)},
        "seed": SEED, "E0": None,
        "delay_dist": {"median_s": DELAY_MEDIAN_S, "p95_s": DELAY_P95_S, "mu": DELAY_MU, "sigma": DELAY_SIGMA, "cap_s": DELAY_CAP_S},
        "s_n_bps": S_N_BPS, "taker_fee_bps": TAKER_FEE_BPS, "stress_delay_s": STRESS_DELAY_S,
        "stress_slip_bps": STRESS_SLIP_BPS, "recon_tick_ms": RECON_TICK_MS,
        "coins": [], "t2_scope": [],
        "n_events_W": 0, "n_twap_merged": 0,
        "leader": {"net_total": 0.0},
        "gate": {"G1": dict(zero_gate), "G2": {**zero_gate, "peak_leverage": 0.0, "worst_day_frac": 0.0,
                                                 "max_leverage_anchor": GATE_G2_MAX_LEVERAGE, "worst_day_anchor": -GATE_G2_WORST_DAY_FRAC},
                 "G3": {**zero_gate, "n_removed_days": 0, "net_before": 0.0, "net_after": 0.0}, "overall": False},
        "D1": {"score": 0.0, "a": 0.0, "b": 0.0, "c": 0.0, "r_normal": 0.0,
               "r_stress": {"i": 0.0, "ii": 0.0, "iii": 0.0, "worst": 0.0},
               "r_miss": {"open": 0.0, "reduce": 0.0, "worst": 0.0},
               "net_normal": 0.0, "net_stress": {}},
        "D2": {"score": 0.0, "sub_scores": {}, "mdd": 0.0, "worst_day_frac": 0.0, "worst_week_frac": 0.0,
               "dd_days": 0, "lev_peak": 0.0},
        "D3": {"score": 0.0, "m_hit": 0.0, "S_mhit": 0.0, "regime_score": 0.0, "dominant_coin": None,
               "rob": 0.0, "S_rob": 0.0, "conc": 0.0, "S_conc": 0.0, "n_w_episodes": 0, "n_open_w_episodes": 0},
        "D4": {"score": 0.0, "R_b": 0.0, "R_b_star": 0.0, "R_c": 0.0, "excess": 0.0, "sigma_b": 0.0, "sigma_c": 0.0},
        "D5": {"score": 0.0, "hist_days": 0.0, "S_hist": 0.0, "coverage": 0.0, "S_cov": 0.0,
               "price_level_frac": 0.0, "S_price": 0.0, "retain_front": 0.0, "retain_back": 0.0, "fwd_score": 0.0},
        "total": 0,
        "level_counts": {}, "monthly": {},
        "assumptions": list(ASSUMPTIONS),
        "data_limits": [
            "延遲成本用 Binance 1m 代理／HL 1m 的相對變動估算（保真 0.7–0.9 → 偏樂觀）；δ 小於 1 分鐘時延遲成本幾乎只剩滑價。",
            "跟單者資金費 = 領單者 funding 列（只有前 500 筆）= 下界。",
            "延遲分布是假設值（未有實測）；漏單恢復是模型內的逐事件精算，不是實盤跟單記錄；前瞻分項是同窗口切分。",
        ],
    }
    (D / "copyscore.json").write_text(json.dumps(out, indent=2, sort_keys=True))
    txt = (
        "=" * 92 + "\n"
        f"COPY-TRADE SCORE  {addr_full}  ({addr10})   [spec v0.5]\n"
        f"UNSCORABLE: {reason}\n"
        + "=" * 92 + "\n\n"
        "== GATE ==\nno day reaches E_min -> GATE OVERALL: FAIL\n\n"
        "== D1 ==\n0 / 35 (unscorable)\n\n== D2 ==\n0 / 30\n\n== D3 ==\n0 / 20\n\n== D4 ==\n0 / 10\n\n== D5 ==\n0 / 5\n\n"
        "== TOTAL ==\nTOTAL = 0 / 100 (門檻 未通過 — 無法評分：權益過小)\n\n"
        f"E_min = ${E_min:,.2f}  L_peak = ${L_peak:,.2f}\n"
    )
    (D / "copyscore.txt").write_text(txt)
    print(txt)


# ============================================================================
# main
# ============================================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("addr10")
    args = ap.parse_args()

    D = ROOT / "data" / args.addr10
    addr_full = args.addr10
    addrs_path = ROOT / "addrs.txt"
    if addrs_path.exists():
        for a in addrs_path.read_text().split():
            if a.startswith(args.addr10):
                addr_full = a
                break

    t_start = time.time()
    fills, n_twap = load_fills_merged(D)
    portfolio = dict(json.load(open(D / "portfolio.json")))
    funding = json.load(open(D / "funding.json"))
    ledger = json.load(open(D / "ledger.json"))

    perp_fills_all = [f for f in fills if not is_spot(f["coin"])]
    if not perp_fills_all:
        print("no perp fills — nothing to score", file=sys.stderr)
        sys.exit(1)

    # --- v0.4 §0: raw full-history window (no E0/E_min applied yet) ---
    first_t, last_t = perp_fills_all[0]["time"], perp_fills_all[-1]["time"]
    W0_raw = day_ms(ms_to_date(first_t))
    W1 = day_ms(ms_to_date(last_t)) + 86_400_000

    evs_all, _ = build_events(fills, W0_raw, W1)
    if not evs_all:
        print("no perp events in window — nothing to score", file=sys.stderr)
        sys.exit(1)

    coins = sorted({ev["coin"] for ev in evs_all})
    coin_span = {}
    global _event_times_cache
    _event_times_cache = {}
    for c in coins:
        ts = sorted(ev["t"] for ev in evs_all if ev["coin"] == c)
        coin_span[c] = (ts[0], ts[-1])
        _event_times_cache[c] = ts

    # --- v0.3 §1.4 T2 scope: >=95% cumulative notional OR top 12, whichever is MORE coins
    # (computed from the FULL raw history, since T2 scope selection and price prefetch must
    # happen before we know the E_min-pushed start day — see below) ---
    notional_by_coin = defaultdict(float)
    for ev in evs_all:
        notional_by_coin[ev["coin"]] += abs(ev["delta"]) * ev["price"]
    ranked = sorted(notional_by_coin.items(), key=lambda kv: -kv[1])
    total_notional = sum(v for _, v in ranked) or 1.0
    set_95, cum = [], 0.0
    for c, v in ranked:
        cum += v
        set_95.append(c)
        if cum / total_notional >= T2_MIN_CUM_NOTIONAL:
            break
    set_12 = [c for c, _ in ranked[:T2_TOP_N]]
    t2_scope = set(set_95) if len(set_95) >= len(set_12) else set(set_12)
    note(f"T2 (Binance proxy) scope = {len(t2_scope)}/{len(coins)} coins "
         f"({'95% cum-notional rule' if len(set_95) >= len(set_12) else 'top-12 rule'} was larger); "
         f"remaining {len(coins) - len(t2_scope)} coin(s) use T1 (if recent) or T3 only. Computed from the "
         "wallet's full raw history (not the E_min-pushed scored window) since it feeds price prefetch.")

    now_ms = int(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)

    stats = {"hits": 0, "misses": 0}
    t_fetch0 = time.time()
    bin1m, hl1h, hl1d, hl1m_recent = prefetch(coins, coin_span, t2_scope, W0_raw, W1, now_ms, stats)
    fetch_elapsed = time.time() - t_fetch0

    price_lookup = hl1d
    days_raw = date_range(W0_raw, W1)
    funding_by_day_raw = build_funding_by_day(funding, W0_raw, W1)

    # --- leader's own daily net over the FULL raw history (feeds L_t's MTM-curve fallback
    # and the E_min/peak calculation; NOT the scored leader curve — that's rebuilt below once
    # the E_min-pushed start day is known) ---
    leader_trades_raw = [{"t": ev["t"], "coin": ev["coin"], "qty": ev["delta"], "price": ev["price"], "fee": ev["fee"]} for ev in evs_all]
    _, leader_daily_net_raw, _, _ = run_daily_mtm_v2(leader_trades_raw, W0_raw, W1, price_lookup, funding_by_day_raw)

    avh_sorted = sorted(((int(t), float(v)) for t, v in portfolio["allTime"]["accountValueHistory"]), key=lambda p: p[0])
    anchor_v0 = avh_sorted[0][1] if avh_sorted else 0.0
    L_raw, l_fallback_days_raw = build_leader_equity_daily(portfolio, anchor_v0, W0_raw, W1, leader_daily_net_raw, days_raw)
    note(
        "L_t (leader daily equity for proportional sizing, v0.4 §1.2) = linear interpolation of "
        "portfolio.allTime.accountValueHistory to each day's 00:00 UTC boundary — the leader's REAL reported "
        "equity, NOT netted against deposits/withdrawals (v0.3's netting was reverted; the leader sizes "
        "positions against what they actually have). Falls back to the leader's own fills-based MTM curve on "
        f"{len(l_fallback_days_raw)}/{len(days_raw)} day(s) of the full raw history outside accountValueHistory's "
        "covered range."
    )

    # --- v0.4 §0: E_min floor and the pushed start day ---
    L_peak = max(L_raw.values()) if L_raw else 0.0
    E_min = max(E_MIN_FLOOR, E_MIN_PEAK_FRAC * L_peak)
    start_day = next((d for d in days_raw if L_raw[d] >= E_min), None)

    if start_day is not None:
        W0 = day_ms(start_day)
        evs, _ = build_events(fills, W0, W1)
    else:
        W0, evs = None, []

    if start_day is None or not evs:
        reason = (
            f"no day in the full-history window ({ms_to_date(W0_raw)}..{ms_to_date(W1 - 1)}) has L_t >= E_min "
            f"(${E_min:,.2f} = max(${E_MIN_FLOOR:,.0f}, {E_MIN_PEAK_FRAC:.0%} x L_peak ${L_peak:,.2f}))"
            if start_day is None else
            f"L_t first reached E_min (${E_min:,.2f}) on {start_day}, but no perp events remain in "
            f"[{start_day}, {ms_to_date(W1 - 1)}] to score"
        )
        write_unscorable(D, addr_full, args.addr10, W0_raw, W1, E_min, L_peak, reason)
        return

    note(f"start day pushed from {ms_to_date(W0_raw)} (first fill) to {start_day} (first day L_t >= E_min, "
         f"${E_min:,.2f}); {len(evs_all) - len(evs)} earlier event(s) ignored per plan v0.4 §0.")

    days = date_range(W0, W1)
    last_day = days[-1]
    funding_by_day = build_funding_by_day(funding, W0, W1)
    L_series = {d: L_raw[d] for d in days}
    E0 = L_series[days[0]]

    # --- leader curve, rescoped to the pushed window ---
    leader_trades = [{"t": ev["t"], "coin": ev["coin"], "qty": ev["delta"], "price": ev["price"], "fee": ev["fee"]} for ev in evs]
    _, leader_daily_net, leader_daily_gross, leader_daily_pos = run_daily_mtm_v2(leader_trades, W0, W1, price_lookup, funding_by_day)
    leader_net_total = sum(leader_daily_net.values())

    def zero_fill_after(daily_net, daily_gross, daily_pos, stopout_day):
        """plan v0.5 §1.4b: curve stays flat (no funding, no notional) after stop-out."""
        if not stopout_day:
            return daily_net, daily_gross, daily_pos
        past = False
        for d in days:
            if past:
                daily_net[d] = 0.0
                daily_gross[d] = 0.0
                daily_pos[d] = {}
            if d == stopout_day:
                past = True
        return daily_net, daily_gross, daily_pos

    t_sim0 = time.time()
    # ---------------- D1-a: normal, per-event sampled delay ----------------
    trades_a, level_counts_a, stopout_a, lev_at_stopout_a = simulate_copier_v3(
        evs, days, L_series, E0, E_min, delay_sampled, S_N_BPS, SEED, now_ms,
        bin1m, hl1h, hl1m_recent, price_lookup, t2_scope, funding_by_day,
    )
    _, daily_net_a, daily_gross_a, daily_pos_a = run_daily_mtm_v2(trades_a, W0, W1, price_lookup, funding_by_day)
    daily_net_a, daily_gross_a, daily_pos_a = zero_fill_after(daily_net_a, daily_gross_a, daily_pos_a, stopout_a)
    copier_net_normal = sum(daily_net_a.values())

    # ---------------- D1-b: three stress scenarios, worst taken ----------------
    stress_defs = {
        "i": (make_delay_fixed(STRESS_DELAY_S), S_N_BPS),
        "ii": (delay_sampled, STRESS_SLIP_BPS),
        "iii": (make_delay_fixed(STRESS_DELAY_S), STRESS_SLIP_BPS),
    }
    stress_nets = {}
    stress_level_counts = {}
    stopout_stress = {}
    for key, (dfn, slip_bps) in stress_defs.items():
        trades_s, lc_s, stopout_s, _lev_at_stopout_s = simulate_copier_v3(
            evs, days, L_series, E0, E_min, dfn, slip_bps, SEED, now_ms,
            bin1m, hl1h, hl1m_recent, price_lookup, t2_scope, funding_by_day,
        )
        _, dn_s, dg_s, dp_s = run_daily_mtm_v2(trades_s, W0, W1, price_lookup, funding_by_day)
        dn_s, dg_s, dp_s = zero_fill_after(dn_s, dg_s, dp_s, stopout_s)
        stress_nets[key] = sum(dn_s.values())
        stress_level_counts[key] = lc_s
        stopout_stress[key] = stopout_s

    worst_stress_key = min(stress_nets, key=stress_nets.get)
    g1_val = stress_nets[worst_stress_key]
    g1_pass = g1_val > 0
    r_stress = {k: (v / leader_net_total if leader_net_total > 0 else 0.0) for k, v in stress_nets.items()}
    r_stress["worst"] = min(r_stress.values())

    # ---------------- D1-c: per-event miss-recovery (closed form) ----------------
    # exclude the forced stop-out closing trade(s) — a "fault" on a liquidation
    # close isn't a leader-mirroring event, plan §3 D1-c doesn't cover it.
    trades_a_events = [tr for tr in trades_a if tr["kind"] != "stopout_close"]
    losses_open, losses_reduce = compute_miss_losses(trades_a_events, now_ms, bin1m, hl1h, hl1m_recent, t2_scope, S_N_BPS)
    if leader_net_total > 0:
        r_miss_open = min(((copier_net_normal - loss) / leader_net_total) for loss in losses_open) if losses_open else 1.0
        r_miss_reduce = min(((copier_net_normal - loss) / leader_net_total) for loss in losses_reduce) if losses_reduce else 1.0
    else:
        r_miss_open = r_miss_reduce = 0.0
    r_miss_worst = min(r_miss_open, r_miss_reduce)
    note(
        "D1-c loss(e) = qty*(p_recon - p_exec) + (catch-up slippage + catch-up fee), qty signed (v0.4 sign fix "
        "vs v0.3, which had the first term negated). loss(e) can be negative (a missed trade followed by a "
        "favorable price move before catch-up is a net benefit). Does not add back the fee/slippage the "
        "original (now-skipped) t+δ trade would have paid — the formula as given only adds the catch-up leg's "
        "own friction, so loss(e) is the INCREMENTAL cost of deferring this one trade, not a full "
        "swap-accounting of both legs."
    )
    sim_elapsed = time.time() - t_sim0

    r_normal = (copier_net_normal / leader_net_total) if leader_net_total > 0 else 0.0
    S_a = lin_score(r_normal, *D1_A_ANCHOR)
    S_b = lin_score(r_stress["worst"], *D1_BC_ANCHOR)
    S_c = lin_score(r_miss_worst, *D1_BC_ANCHOR)
    D1_a_score = 5 * S_a
    D1_b_score = 20 * S_b
    D1_c_score = 10 * S_c
    D1 = D1_a_score + D1_b_score + D1_c_score

    n_active = len(active_days(trades_a))
    normal_analytics = curve_analytics(days, daily_net_a, daily_gross_a, E0)
    equity_wiped_stopout = stopout_a is not None and lev_at_stopout_a is None
    if lev_at_stopout_a is not None:
        # plan v0.5 §1.4b: "槓桿尖峰取爆倉日前的最大值（含爆倉日）" — the official daily_gross_a for
        # the stop-out day itself is already post-close (0), so fold in the pre-close value directly.
        normal_analytics["lev_peak"] = max(normal_analytics["lev_peak"], lev_at_stopout_a)
    elif equity_wiped_stopout:
        # C_t<=0 stop-out: leverage is undefined, not reportable as a number (coordinator
        # 2026-09-24 correction). For internal scoring/gate purposes only (never displayed),
        # treat it as maximally bad — equity wiped to zero is at least as severe as any
        # finite leverage reading, so this must still fail G2 / score 0 on this sub-metric.
        normal_analytics["lev_peak"] = max(normal_analytics["lev_peak"], D2_ANCHORS["lev_peak"][1])
    lev_peak_display = None if equity_wiped_stopout else normal_analytics["lev_peak"]

    # ---------------- GATE ----------------
    g2_lev = normal_analytics["lev_peak"]
    g2_worst = normal_analytics["worst_day_frac"]
    g2_pass = (g2_lev <= GATE_G2_MAX_LEVERAGE) and (g2_worst >= -GATE_G2_WORST_DAY_FRAC)

    g3_total, g3_reduced, g3_n = remove_best_days(daily_net_a, days, n_active)
    g3_pass = g3_reduced > 0

    gate_pass = g1_pass and g2_pass and g3_pass

    # ---------------- D2 ----------------
    d2_scores = {
        "mdd": lin_score(normal_analytics["mdd"], D2_ANCHORS["mdd"][1], D2_ANCHORS["mdd"][0]),
        "worst_day": lin_score(abs(normal_analytics["worst_day_frac"]), D2_ANCHORS["worst_day"][1], D2_ANCHORS["worst_day"][0]),
        "worst_week": lin_score(abs(normal_analytics["worst_week_frac"]), D2_ANCHORS["worst_week"][1], D2_ANCHORS["worst_week"][0]),
        "dd_days": lin_score(normal_analytics["dd_days"], D2_ANCHORS["dd_days"][1], D2_ANCHORS["dd_days"][0]),
        "lev_peak": lin_score(normal_analytics["lev_peak"], D2_ANCHORS["lev_peak"][1], D2_ANCHORS["lev_peak"][0]),
    }
    D2 = 30 * (sum(d2_scores.values()) / len(d2_scores))

    # ---------------- D3 ----------------
    by_month = defaultdict(float)
    for d in days:
        by_month[d[:7]] += daily_net_a.get(d, 0.0)
    months = sorted(by_month)
    m_hit = sum(1 for m in months if by_month[m] > 0) / len(months) if months else 0.0
    S_mhit = lin_score(m_hit, *D3_ANCHOR_MHIT)

    dominant_coin = max(notional_by_coin, key=notional_by_coin.get) if notional_by_coin else None
    down_months_net = []
    for m in months:
        m_days = [d for d in days if d[:7] == m]
        prices = [price_lookup.get(dominant_coin, {}).get(d) for d in m_days]
        prices = [p for p in prices if p is not None]
        if len(prices) < 2:
            continue
        if prices[-1] / prices[0] - 1 < 0:
            down_months_net.append(by_month[m])
    regime_score = 0.5 if not down_months_net else (1.0 if sum(down_months_net) / len(down_months_net) >= 0 else 0.0)

    d3_total, d3_reduced, d3_n = remove_best_days(daily_net_a, days, n_active)
    rob = (d3_reduced / d3_total) if d3_total > 0 else 0.0
    S_rob = lin_score(rob, *D3_ANCHOR_ROB) if d3_total > 0 else 0.0

    cut_episodes = cut_episodes_for_conc(fills, W1, price_lookup, last_day)
    w_episodes = [e for e in cut_episodes if e["t0"] < W1 and (e["open"] or e["t1"] >= W0)]
    n_open_w_episodes = sum(1 for e in w_episodes if e["open"])
    if leader_net_total > 0 and w_episodes:
        max_ep = max(w_episodes, key=lambda e: abs(e["net"]))
        conc = abs(max_ep["net"]) / leader_net_total
    else:
        max_ep = None
        conc = 1.0
    S_conc = lin_score(conc, *D3_ANCHOR_CONC)

    D3 = 20 * ((S_mhit + regime_score + S_rob + S_conc) / 4)

    # ---------------- D4 ----------------
    exposure = {c: [] for c in coins}
    for d in days:
        L_d = max(L_series.get(d, E0), E_min)  # v0.4 §0/§1.2 floor
        for c in coins:
            qty = leader_daily_pos.get(d, {}).get(c, 0.0)
            px = price_lookup.get(c, {}).get(d)
            exposure[c].append((qty * px / L_d) if (px and L_d) else 0.0)

    R_b = 0.0
    coin_ret_series = {}
    for c in coins:
        prices = [price_lookup.get(c, {}).get(d) for d in days]
        p0 = next((p for p in prices if p is not None), None)
        p1 = next((p for p in reversed(prices) if p is not None), None)
        buyhold = (p1 / p0 - 1) if (p0 and p1) else 0.0
        mean_exp = sum(exposure[c]) / len(exposure[c]) if exposure[c] else 0.0
        R_b += mean_exp * buyhold
        rets = [0.0]
        for i in range(1, len(prices)):
            pa, pb = prices[i - 1], prices[i]
            rets.append((pb / pa - 1) if (pa and pb) else 0.0)
        coin_ret_series[c] = rets

    bench_daily = [sum(exposure[c][i] * coin_ret_series[c][i] for c in coins) for i in range(len(days))]
    floor_c = E0 * 0.01 if E0 else 1.0
    copier_daily_ret = [
        daily_net_a.get(d, 0.0) / (normal_analytics["equity_start"][i] if normal_analytics["equity_start"][i] > floor_c else floor_c)
        for i, d in enumerate(days)
    ]
    sigma_b = statistics.pstdev(bench_daily[1:]) if len(bench_daily) > 1 else 0.0
    sigma_c = statistics.pstdev(copier_daily_ret[1:]) if len(copier_daily_ret) > 1 else 0.0
    R_b_star = R_b * (sigma_c / sigma_b) if sigma_b > 0 else R_b

    R_c = copier_net_normal / E0 if E0 else 0.0
    excess = R_c - R_b_star
    D4 = 10 * d4_score(excess / max(abs(R_b_star), D4_RB_FLOOR))

    # ---------------- D5 ----------------
    hist_days = (perp_fills_all[-1]["time"] - perp_fills_all[0]["time"]) / 86_400_000 if len(perp_fills_all) > 1 else 0.0
    S_hist = lin_score(hist_days, *D5_ANCHOR_HISTORY)

    ledger_span_ms = now_ms - ledger[0]["time"] if ledger else None
    fills_span_ms = perp_fills_all[-1]["time"] - perp_fills_all[0]["time"] if len(perp_fills_all) > 1 else 0.0
    coverage = (fills_span_ms / ledger_span_ms) if ledger_span_ms else 0.0
    S_cov = lin_score(coverage, *D5_ANCHOR_COVERAGE)

    total_level_events = sum(level_counts_a.values())
    t1t2 = level_counts_a.get("T1", 0) + level_counts_a.get("T2", 0)
    price_level_frac = (t1t2 / total_level_events) if total_level_events else 0.0
    S_price = lin_score(price_level_frac, *D5_ANCHOR_PRICE_LEVEL)

    split_t = W0 + int(D5_SPLIT_FRAC * (W1 - W0))
    front_days = [d for d in days if day_ms(d) < split_t]
    back_days = [d for d in days if day_ms(d) >= split_t]
    copier_front = sum(daily_net_a.get(d, 0.0) for d in front_days)
    copier_back = sum(daily_net_a.get(d, 0.0) for d in back_days)
    leader_front = sum(leader_daily_net.get(d, 0.0) for d in front_days)
    leader_back = sum(leader_daily_net.get(d, 0.0) for d in back_days)
    retain_front = (copier_front / leader_front) if leader_front > 0 else 0.0
    retain_back = (copier_back / leader_back) if leader_back > 0 else 0.0
    if sign(copier_back) != sign(copier_front):
        fwd_score = 0.0
    elif retain_back >= retain_front / 2 if retain_front != 0 else True:
        fwd_score = 1.0
    else:
        fwd_score = 0.5

    D5 = 5 * ((S_hist + S_cov + S_price + fwd_score) / 4)

    total_score = max(0, min(100, round(D1 + D2 + D3 + D4 + D5)))
    elapsed = time.time() - t_start

    def lc(counter):
        return {k: v for k, v in sorted(counter.items())}

    out = {
        "spec_version": "v0.5",
        "addr": addr_full, "addr10": args.addr10,
        "unscorable": False,
        "window": {"start": ms_to_date(W0), "end": ms_to_date(W1 - 1), "start_ms": W0, "end_ms": W1,
                   "days": round((W1 - W0) / 86_400_000)},
        "window_raw": {"start": ms_to_date(W0_raw), "end": ms_to_date(W1 - 1)},
        "seed": SEED, "generated_now_ms": now_ms,
        "E0": E0, "E_min": E_min, "L_peak": L_peak,
        "stopout_date": stopout_a, "stopout_leverage": lev_at_stopout_a, "stopout_leverage_threshold": STOPOUT_LEVERAGE,
        "stopout_stress": stopout_stress,
        "delay_dist": {"median_s": DELAY_MEDIAN_S, "p95_s": DELAY_P95_S, "mu": DELAY_MU, "sigma": DELAY_SIGMA, "cap_s": DELAY_CAP_S},
        "s_n_bps": S_N_BPS, "taker_fee_bps": TAKER_FEE_BPS, "stress_delay_s": STRESS_DELAY_S,
        "stress_slip_bps": STRESS_SLIP_BPS, "recon_tick_ms": RECON_TICK_MS,
        "coins": coins, "t2_scope": sorted(t2_scope),
        "n_events_W": len(evs), "n_twap_merged": n_twap,
        "leader": {"net_total": leader_net_total},
        "gate": {
            "G1": {"worst_stress_scenario": worst_stress_key, "net": g1_val, "pass": g1_pass},
            "G2": {"peak_leverage": lev_peak_display, "worst_day_frac": g2_worst,
                   "max_leverage_anchor": GATE_G2_MAX_LEVERAGE, "worst_day_anchor": -GATE_G2_WORST_DAY_FRAC, "pass": g2_pass},
            "G3": {"n_removed_days": g3_n, "net_before": g3_total, "net_after": g3_reduced, "pass": g3_pass},
            "overall": gate_pass,
        },
        "D1": {
            "score": D1, "a": D1_a_score, "b": D1_b_score, "c": D1_c_score,
            "r_normal": r_normal,
            "r_stress": {"i": r_stress["i"], "ii": r_stress["ii"], "iii": r_stress["iii"], "worst": r_stress["worst"]},
            "r_miss": {"open": r_miss_open, "reduce": r_miss_reduce, "worst": r_miss_worst},
            "net_normal": copier_net_normal, "net_stress": stress_nets,
        },
        "D2": {"score": D2, "sub_scores": d2_scores, "mdd": normal_analytics["mdd"],
               "worst_day_frac": normal_analytics["worst_day_frac"], "worst_week_frac": normal_analytics["worst_week_frac"],
               "dd_days": normal_analytics["dd_days"], "lev_peak": lev_peak_display},
        "D3": {"score": D3, "m_hit": m_hit, "S_mhit": S_mhit, "regime_score": regime_score, "dominant_coin": dominant_coin,
               "rob": rob, "S_rob": S_rob, "conc": conc, "S_conc": S_conc,
               "n_w_episodes": len(w_episodes), "n_open_w_episodes": n_open_w_episodes},
        "D4": {"score": D4, "R_b": R_b, "R_b_star": R_b_star, "R_c": R_c, "excess": excess, "sigma_b": sigma_b, "sigma_c": sigma_c},
        "D5": {"score": D5, "hist_days": hist_days, "S_hist": S_hist, "coverage": coverage, "S_cov": S_cov,
               "price_level_frac": price_level_frac, "S_price": S_price,
               "retain_front": retain_front, "retain_back": retain_back, "fwd_score": fwd_score},
        "total": total_score,
        "level_counts": {"a_normal": lc(level_counts_a), **{f"b_{k}": lc(v) for k, v in stress_level_counts.items()}},
        "monthly": {m: {"copier_net_normal": by_month[m], "leader_net": sum(leader_daily_net.get(d, 0.0) for d in days if d[:7] == m)} for m in months},
        "assumptions": list(ASSUMPTIONS),
        "data_limits": [
            "延遲成本用 Binance 1m 代理／HL 1m 的相對變動估算（保真 0.7–0.9 → 偏樂觀）；δ 小於 1 分鐘時延遲成本幾乎只剩滑價。",
            "跟單者資金費 = 領單者 funding 列（只有前 500 筆）= 下界。",
            "延遲分布是假設值（未有實測）；漏單恢復是模型內的逐事件精算，不是實盤跟單記錄；前瞻分項是同窗口切分。",
        ],
        "timing": {"fetch_seconds": round(fetch_elapsed, 1), "sim_seconds": round(sim_elapsed, 1), "total_seconds": round(elapsed, 1),
                   "cache_hits": stats["hits"], "cache_misses": stats["misses"]},
    }

    (D / "copyscore.json").write_text(json.dumps({k: v for k, v in out.items() if k != "timing"}, indent=2, sort_keys=True))

    # ---------------- text report ----------------
    lines = []
    lines.append("=" * 92)
    lines.append(f"COPY-TRADE SCORE  {addr_full}  ({args.addr10})   [spec v0.5]")
    lines.append(f"window W (full history, raw): {out['window_raw']['start']} -> {out['window_raw']['end']}   scored window (E_min-pushed): {out['window']['start']} -> {out['window']['end']}  ({out['window']['days']}d)   seed={SEED}")
    lines.append(f"E0=${E0:,.2f}   E_min=${E_min:,.2f}   L_peak=${L_peak:,.2f}")
    lines.append(f"D1 tests: a=normal(sampled delay median {DELAY_MEDIAN_S}s/P95 {DELAY_P95_S}s) b=stress(worst of i/ii/iii) c=miss-recovery(closed-form)")
    lines.append("=" * 92)

    lev_display_str = "—（權益歸零）" if lev_peak_display is None else f"{lev_peak_display:.2f}x"
    lines.append("")
    lines.append("== GATE ==")
    if stopout_a:
        lines.append(f"** 模擬跟單者於 {stopout_a} 爆倉（plan v0.5 §1.4b：C_t<=0 或槓桿 > {STOPOUT_LEVERAGE:.0f}x）**")
    lines.append(f"G1 延遲後仍有收益 (stress worst={worst_stress_key}): net = ${g1_val:,.2f} > 0  -> {'PASS' if g1_pass else 'FAIL'}")
    lines.append(f"G2 庫存風險有限 (normal a): peak_leverage={lev_display_str} (<= {GATE_G2_MAX_LEVERAGE}x)  worst_day={g2_worst:.2%} (>= -{GATE_G2_WORST_DAY_FRAC:.0%})"
                 + (f"  [爆倉於 {stopout_a}]" if stopout_a else "") + f"  -> {'PASS' if g2_pass else 'FAIL'}")
    lines.append(f"G3 不依賴少數行情 (normal a): 移除最佳 {g3_n} 天後 net = ${g3_reduced:,.2f} (原 ${g3_total:,.2f})  -> {'PASS' if g3_pass else 'FAIL'}")
    lines.append(f"GATE OVERALL: {'PASS' if gate_pass else 'FAIL'}")

    lines.append("")
    lines.append("== D1 跟單可複製性 (35 = 5+20+10) ==")
    lines.append(f"score = {D1:.2f} / 35")
    lines.append(f"  a 正常跟單(5): r_normal={r_normal:.3f}  score={D1_a_score:.2f}")
    lines.append(f"  b 執行壓力(20): r_i={r_stress['i']:.3f} r_ii={r_stress['ii']:.3f} r_iii={r_stress['iii']:.3f} worst={r_stress['worst']:.3f} (scenario {worst_stress_key})  score={D1_b_score:.2f}")
    lines.append(f"  c 漏單恢復(10): r_open={r_miss_open:.3f} r_reduce={r_miss_reduce:.3f} worst={r_miss_worst:.3f}  score={D1_c_score:.2f}")

    lines.append("")
    lines.append("== D2 下檔控制 (權重30，跟單者normal-a) ==")
    lines.append(f"score = {D2:.2f} / 30")
    lines.append(f"  MDD           {normal_analytics['mdd']:.2%}   S={d2_scores['mdd']:.3f}")
    lines.append(f"  最差日        {normal_analytics['worst_day_frac']:.2%}   S={d2_scores['worst_day']:.3f}")
    lines.append(f"  最差週(7日)   {normal_analytics['worst_week_frac']:.2%}   S={d2_scores['worst_week']:.3f}")
    lines.append(f"  最長回撤天數  {normal_analytics['dd_days']}天   S={d2_scores['dd_days']:.3f}")
    lines.append(f"  槓桿尖峰      {lev_display_str}  S={d2_scores['lev_peak']:.3f}")

    lines.append("")
    lines.append("== D3 獲利穩健性 (權重20，跟單者normal-a) ==")
    lines.append(f"score = {D3:.2f} / 20")
    lines.append(f"  m_hit(正月占比) = {m_hit:.2%} ({sum(1 for m in months if by_month[m] > 0)}/{len(months)})  S={S_mhit:.3f}")
    lines.append(f"  regime (主力幣={dominant_coin})  score={regime_score:.2f}")
    lines.append(f"  rob   = {d3_reduced:,.2f}/{d3_total:,.2f} = {rob:.3f}  S={S_rob:.3f}")
    lines.append(f"  conc  = {conc:.3f}  S={S_conc:.3f} (episodes: {len(w_episodes)} in W, {n_open_w_episodes} open)")

    lines.append("")
    lines.append("== D4 超額收益 (權重10) ==")
    lines.append(f"score = {D4:.2f} / 10")
    lines.append(f"  R_b={R_b:.4f}  R_b*={R_b_star:.4f}  R_c={R_c:.4f}  excess={excess:.4f}")

    lines.append("")
    lines.append("== D5 證據品質 (權重5) ==")
    lines.append(f"score = {D5:.2f} / 5")
    lines.append(f"  歷史長度 {hist_days:.0f}天  S={S_hist:.3f}")
    lines.append(f"  覆蓋率 {coverage:.2%}  S={S_cov:.3f}")
    lines.append(f"  價格級別(T1+T2占比) {price_level_frac:.2%}  S={S_price:.3f}")
    lines.append(f"  前瞻切分: retain_front={retain_front:.3f} retain_back={retain_back:.3f}  fwd_score={fwd_score:.2f}")

    lines.append("")
    lines.append("== TOTAL ==")
    lines.append(f"TOTAL = D1+D2+D3+D4+D5 = {D1:.2f}+{D2:.2f}+{D3:.2f}+{D4:.2f}+{D5:.2f} = {total_score} / 100")
    lines.append(f"(門檻 {'通過' if gate_pass else '未通過'})")

    lines.append("")
    lines.append("== 價格級別占比 (test a, normal) ==")
    tot_lc = sum(level_counts_a.values())
    pct = {k: (v / tot_lc * 100 if tot_lc else 0.0) for k, v in level_counts_a.items()}
    lines.append("  " + "  ".join(f"{k}={v:.1f}%" for k, v in sorted(pct.items())))
    lines.append(f"  合計 = {sum(pct.values()):.1f}%  (events={tot_lc})")

    lines.append("")
    lines.append("== T2 範圍 ==")
    lines.append(f"  {len(t2_scope)}/{len(coins)} 幣進 T2（Binance 代理）：{sorted(t2_scope)}")

    lines.append("")
    lines.append("== 月表：跟單者(normal-a) vs 領單者 淨損益 ==")
    lines.append(f"  {'month':<10}{'copier_net':>16}{'leader_net':>16}")
    for m in months:
        lines.append(f"  {m:<10}{by_month[m]:>16,.2f}{sum(leader_daily_net.get(d, 0.0) for d in days if d[:7] == m):>16,.2f}")

    lines.append("")
    lines.append("== 資料極限 (plan §4) ==")
    for x in out["data_limits"]:
        lines.append(f"  - {x}")

    lines.append("")
    lines.append("== ASSUMPTIONS ==")
    for a in ASSUMPTIONS:
        lines.append(f"  - {a}")

    lines.append("")
    lines.append(f"timing: fetch={fetch_elapsed:.1f}s sim={sim_elapsed:.1f}s total={elapsed:.1f}s  cache: {stats['hits']} hit / {stats['misses']} miss")
    lines.append("=" * 92)

    (D / "copyscore.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
