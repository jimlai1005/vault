"""JSON persistence for the live carry engine. Positions are always re-read
from the exchange each cycle (source of truth); only circuit-breaker and
signal bookkeeping persists here."""
from __future__ import annotations

import json
from pathlib import Path


def default_state() -> dict:
    return {
        "halted": False,
        "peak_equity": 0.0,
        "_alerted_this_halt": False,
        "_flatten_complete": False,
        "last_funding_check_ms": 0,
        "funding_ok": False,
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
