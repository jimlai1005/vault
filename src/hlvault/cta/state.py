"""JSON persistence for the live CTA engine. Live perp positions are always
re-read from the exchange (source of truth) each cycle; only circuit-breaker
bookkeeping and per-coin entry metadata (entry price/stop/time — needed by the
strategy-level 2xATR stop and the 14d-max-hold, which the exchange does not
track for us) persist here."""
from __future__ import annotations

import json
from pathlib import Path


def default_state() -> dict:
    return {
        "halted": False,
        "peak_equity": 0.0,
        "_alerted_this_halt": False,
        "_flatten_complete": False,
        "last_rebalance_ms": 0,
        "entries": {},   # coin -> {dir, entry_px, stop, entry_ms}
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
