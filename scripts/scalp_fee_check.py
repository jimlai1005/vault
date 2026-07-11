#!/usr/bin/env python3
"""Fee ground-truth check for Hyperliquid (sub-project H).

Queries userFees endpoint for maker/taker rates, or uses defaults.
Writes: data/scalp/fees.json with {"taker", "maker", "source", "ts"}.
"""
import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

# Add scripts dir to path to import scalp_lib
sys.path.insert(0, str(Path(__file__).parent))
import scalp_lib as sl


DEFAULT_TAKER = 0.00045
DEFAULT_MAKER = 0.00015
OUTPUT_FILE = "data/scalp/fees.json"


def check_fees(user_addr=None):
    """Fetch fees from Hyperliquid userFees or use defaults.

    Args:
        user_addr: Optional public Hyperliquid address (e.g. "0x...").

    Returns:
        (taker, maker, source) tuple.
    """
    if user_addr:
        try:
            result = sl.info({"type": "userFees", "user": user_addr})
            # Check if expected fields exist
            if "userCrossRate" not in result or "userAddRate" not in result:
                print("[ENDPOINT-MISMATCH] userFees response missing expected fields:")
                print(json.dumps(result, indent=2))
                return DEFAULT_TAKER, DEFAULT_MAKER, "endpoint-mismatch"

            taker = float(result["userCrossRate"])
            maker = float(result["userAddRate"])
            addr_short = user_addr[:6]
            source = f"userFees:{addr_short}"
            return taker, maker, source
        except Exception as e:
            print(f"[WARNING] userFees query failed: {e}")
            return DEFAULT_TAKER, DEFAULT_MAKER, "default"
    else:
        print("[WARNING] No --user provided, using default rates")
        return DEFAULT_TAKER, DEFAULT_MAKER, "default"


def main():
    parser = argparse.ArgumentParser(description="Check Hyperliquid fee rates")
    parser.add_argument("--user", help="User address (public, hex format)", default=None)
    args = parser.parse_args()

    taker, maker, source = check_fees(args.user)

    # Prepare output
    output = {
        "taker": taker,
        "maker": maker,
        "source": source,
        "ts": datetime.utcnow().isoformat() + "Z"
    }

    # Create directory if needed
    Path(OUTPUT_FILE).parent.mkdir(parents=True, exist_ok=True)

    # Write JSON
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Fees written to {OUTPUT_FILE}")
    print(f"  taker: {taker}, maker: {maker}, source: {source}")


if __name__ == "__main__":
    main()
