"""JSON persistence for live grid state — reconciled against the exchange's
own open-orders each cycle (exchange is the source of truth), same philosophy
as hl-copytrader's diff-based reconciliation."""
from __future__ import annotations

import json
from pathlib import Path


def default_state() -> dict:
    return {
        "halted": False,
        "peak_equity": 0.0,
        "last_fill_check_ms": 0,
        "coins": {},   # coin -> {anchor, step_pct, notional_per_level,
                       #          max_position_notional, armed: {level: oid},
                       #          open_lots: {level: {entry_price,size,tp_price,tp_oid}},
                       #          stopped_until_ms: int|None}
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return default_state()
    with open(path) as f:
        return json.load(f)


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(path)
