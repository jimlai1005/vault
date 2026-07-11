"""F3 session-effect statistics for sub-project H.

Computes hourly (UTC) × weekday statistics without strategy backtest:
1. Average net drift (bps/hour), realized volatility, volume share heatmaps (markdown tables)
2. Boundary effect: ±5min around hour boundary vs full-sample baseline
3. Stability split: data split in half, check if top-3 |drift| hour×dow cells are same-signed

Output: reports/scalp-f3-session-stats.md
"""
from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
import scalp_lib as s


def load_coins(coins_arg: str | None = None) -> list[str]:
    """Load coin list from --coins arg or shortlist.json."""
    if coins_arg:
        return coins_arg.split(",")

    shortlist_path = Path(s.DATA_DIR) / "shortlist.json"
    if shortlist_path.exists():
        with open(shortlist_path) as f:
            return [item["coin"] for item in json.load(f)]
    return []


def compute_hourly_stats(df: pd.DataFrame) -> dict:
    """
    Compute hour×weekday heatmaps:
      - drift_bps: average log return in bps/hour
      - vol_realized: realized volatility
      - vol_share: volume as fraction of daily total

    Returns dict with keys: drift_bps, vol_realized, vol_share (each 24×7 grid)
    """
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    # Log returns in bps
    df["ret"] = np.log(df["c"] / df["c"].shift(1))
    df["ret_bps"] = df["ret"] * 1e4

    # Hour and weekday
    df["hour"] = df["ts"].dt.hour
    df["weekday"] = df["ts"].dt.dayofweek
    df["date"] = df["ts"].dt.date

    # Daily volume
    daily_vol = df.groupby("date")["v"].sum().reset_index()
    daily_vol.columns = ["date", "daily_vol"]
    df = df.merge(daily_vol, on="date")
    df["vol_share"] = df["v"] / df["daily_vol"] * 100  # Convert to percentage

    # Group by (hour, weekday)
    grouped = df.groupby(["hour", "weekday"]).agg({
        "ret_bps": "mean",
        "v": lambda x: np.std(np.log(x / x.shift(1)) * 1e4) if len(x) > 1 else np.nan,
        "vol_share": "mean"
    }).reset_index()

    grouped.columns = ["hour", "weekday", "drift_bps", "vol_realized", "vol_share"]

    # Build 24×7 grids
    grids = {}
    for metric in ["drift_bps", "vol_realized", "vol_share"]:
        grid = np.full((24, 7), np.nan)
        for _, row in grouped.iterrows():
            h, d = int(row["hour"]), int(row["weekday"])
            grid[h, d] = row[metric]
        grids[metric] = grid

    return grids, grouped, df


def format_heatmap_table(grid: np.ndarray, label: str, fmt: str = ".0f") -> str:
    """
    Format 24×7 grid as markdown table.
    grid: 24×7 array with NaN for sparse cells
    fmt: format string for values (e.g. ".0f" for int, ".2f" for float)
    Returns markdown table string.
    """
    # Days of week header
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    lines = [f"## {label}"]
    lines.append("")
    lines.append("| Hour | " + " | ".join(dow_names) + " |")
    lines.append("|------|" + "|".join(["----"] * 7) + "|")

    for h in range(24):
        row_vals = []
        for d in range(7):
            v = grid[h, d]
            if np.isnan(v):
                row_vals.append("-")
            else:
                row_vals.append(f"{v:{fmt}}")
        lines.append(f"| {h:2d}:00 | " + " | ".join(row_vals) + " |")

    return "\n".join(lines)


def compute_boundary_effect(df: pd.DataFrame) -> str:
    """
    Compute ±5min around hour boundary effect.
    Returns markdown text with comparison to full-sample baseline.
    """
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["ret_bps"] = np.log(df["c"] / df["c"].shift(1)) * 1e4

    # Baseline: full sample average
    baseline = df["ret_bps"].mean()

    # Identify boundary windows: :00 minute ± 5 min
    df["minute"] = df["ts"].dt.minute
    boundary_window = df[(df["minute"] >= 55) | (df["minute"] <= 4)]
    boundary_mean = boundary_window["ret_bps"].mean()

    away_window = df[(df["minute"] >= 15) & (df["minute"] <= 44)]
    away_mean = away_window["ret_bps"].mean()

    lines = ["## Boundary Effect (±5min around hour boundary)"]
    lines.append("")
    lines.append("| Metric | Value (bps) |")
    lines.append("|--------|------------|")
    lines.append(f"| Full-sample baseline | {baseline:.2f} |")
    lines.append(f"| Boundary window (:00±5min) | {boundary_mean:.2f} |")
    lines.append(f"| Away window (:15-:44) | {away_mean:.2f} |")
    lines.append("")
    lines.append("**Note:** Binance proxy data; HL-native verification deferred to forward-test phase.")
    lines.append("")

    return "\n".join(lines)


def compute_stability_split(grids: dict, grouped: pd.DataFrame, df: pd.DataFrame) -> tuple:
    """
    Split data in half temporally. For top-3 |drift| hour×dow cells,
    check if they are same-signed in both halves.
    Returns (markdown_text, stable_count, top_cells).
    """
    lines = ["## Stability Analysis (temporal split)"]
    lines.append("")

    # Check data window
    ts_min = df["ts"].min()
    ts_max = df["ts"].max()
    duration = (ts_max - ts_min).days

    if duration < 14:
        lines.append(f"**Data window: {duration} days** — insufficient data for stability split")
        lines.append("")
        return "\n".join(lines), 0, []

    midpoint = ts_min + (ts_max - ts_min) / 2

    # Recompute grids for each half
    def build_half_grid(df_half):
        df_half = df_half.copy()
        df_half["hour"] = df_half["ts"].dt.hour
        df_half["weekday"] = df_half["ts"].dt.dayofweek
        grouped_half = df_half.groupby(["hour", "weekday"])["ret_bps"].mean().reset_index()
        grid = np.full((24, 7), np.nan)
        for _, row in grouped_half.iterrows():
            h, d = int(row["hour"]), int(row["weekday"])
            grid[h, d] = row["ret_bps"]
        return grid

    df_full = df.copy()
    df_full["ret_bps"] = np.log(df_full["c"] / df_full["c"].shift(1)) * 1e4

    df_early = df_full[df_full["ts"] < midpoint]
    df_late = df_full[df_full["ts"] >= midpoint]

    grid_early = build_half_grid(df_early)
    grid_late = build_half_grid(df_late)

    # Find top-3 |drift| cells in the full grid
    drift_grid = grids["drift_bps"]
    abs_drift = np.abs(drift_grid)

    # Flatten and get top-3 (skip NaN)
    flat_idx = np.argsort(-abs_drift.ravel())
    top_cells = []
    for idx in flat_idx:
        if len(top_cells) >= 3:
            break
        h, d = np.unravel_index(idx, abs_drift.shape)
        if not np.isnan(drift_grid[h, d]):
            top_cells.append((h, d))

    lines.append(f"**Data window: {duration} days, split at {midpoint.date()}**")
    lines.append("")
    lines.append("| Hour×Dow | Full avg (bps) | Early half (bps) | Late half (bps) | Same sign? |")
    lines.append("|----------|----------------|-----------------|-----------------|------------|")

    stable_count = 0
    for h, d in top_cells:
        full_val = drift_grid[h, d]
        early_val = grid_early[h, d]
        late_val = grid_late[h, d]

        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        cell_label = f"{h:02d}:{dow_names[d]}"

        # Check same-signed
        if np.isnan(early_val) or np.isnan(late_val):
            same_sign = "insufficient data"
        else:
            same_sign = "✓ YES" if (early_val * late_val > 0) else "✗ NO"
            if early_val * late_val > 0:
                stable_count += 1

        early_str = f"{early_val:.2f}" if not np.isnan(early_val) else "-"
        late_str = f"{late_val:.2f}" if not np.isnan(late_val) else "-"

        lines.append(f"| {cell_label} | {full_val:.2f} | {early_str} | {late_str} | {same_sign} |")

    lines.append("")

    return "\n".join(lines), stable_count, top_cells


def find_candidate_windows(grids: dict, top_cells: list, stable_count: int) -> str:
    """
    Identify candidate windows worth rule-making (≤2 total).
    Stable cells (same-signed halves) are listed as candidates (up to 2).
    """
    lines = ["## Candidate Windows for Rule-making"]
    lines.append("")

    if stable_count == 0:
        lines.append("No stable session-effect hot spots detected in this dataset.")
        lines.append("")
    else:
        dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        drift_grid = grids["drift_bps"]

        # List top stable cells (up to 2)
        candidates = []
        for h, d in top_cells:
            if len(candidates) >= 2:
                break
            drift = drift_grid[h, d]
            if not np.isnan(drift):
                candidates.append((h, d, drift))

        if candidates:
            lines.append(f"**{len(candidates)} stable candidate(s) identified (limit: 2):**")
            lines.append("")
            for i, (h, d, drift) in enumerate(candidates, 1):
                lines.append(f"**Candidate {i}: {h:02d}:{dow_names[d]} (drift: {drift:.2f} bps)**")
                lines.append("")
        else:
            lines.append("No stable candidates identified.")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="F3 session-effect statistics")
    parser.add_argument("--coins", default=None, help="Comma-separated coin list (default: shortlist.json)")
    args = parser.parse_args()

    coins = load_coins(args.coins)
    if not coins:
        print("ERROR: No coins found")
        sys.exit(1)

    print(f"Analyzing {len(coins)} coin(s): {coins}")

    # Process each coin
    all_reports = []
    for coin in coins:
        data_path = Path(s.DATA_DIR) / f"{coin}_1m.csv.gz"
        if not data_path.exists():
            print(f"WARN: {coin} data not found at {data_path}")
            continue

        print(f"Loading {coin}...")
        try:
            df = s.load_df(f"{coin}_1m")
        except Exception as e:
            print(f"ERROR loading {coin}: {e}")
            continue

        print(f"  {len(df)} bars, {df['ts'].min()} to {df['ts'].max()}")

        grids, grouped, df_proc = compute_hourly_stats(df)

        # Build report for this coin
        lines = [f"# F3 Session Effect: {coin}"]
        lines.append("")

        # Heatmaps
        lines.append(format_heatmap_table(grids["drift_bps"], "Hourly Net Drift (bps)", fmt=".1f"))
        lines.append("")
        lines.append(format_heatmap_table(grids["vol_realized"], "Realized Volatility (bps)", fmt=".2f"))
        lines.append("")
        lines.append(format_heatmap_table(grids["vol_share"], "Volume Share (%)", fmt=".1f"))
        lines.append("")

        # Boundary effect
        lines.append(compute_boundary_effect(df_proc))

        # Stability analysis
        stability_text, stable_count, top_cells = compute_stability_split(grids, grouped, df_proc)
        lines.append(stability_text)

        # Candidate windows
        lines.append(find_candidate_windows(grids, top_cells, stable_count))

        all_reports.append("\n".join(lines))

    # Write master report
    output_path = Path("reports") / "scalp-f3-session-stats.md"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    master = "\n\n---\n\n".join(all_reports)
    with open(output_path, "w") as f:
        f.write(master)

    print(f"✓ Report written to {output_path}")


if __name__ == "__main__":
    main()
