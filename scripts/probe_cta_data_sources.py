#!/usr/bin/env python3
"""
CTA Data Feasibility Probe — public APIs, no keys, no trading.
Tests actual data depth and granularity for Binance, Coinalyze, Hyperliquid.
Records results to data/cache/cta_probe/ with ACTUAL row counts and timestamps.
"""

import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta
from pathlib import Path

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "HYPEUSDT"]
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "cta_probe"
TIMEOUT = 20
MAX_RETRIES = 2

def make_request(url, headers=None):
    """Make HTTP request with retry logic and timeout."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                return response.read().decode('utf-8'), response.status
        except urllib.error.HTTPError as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            return json.dumps({"error": f"HTTP {e.code}", "url": url}), e.code
        except urllib.error.URLError as e:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            return json.dumps({"error": str(e.reason), "url": url}), None
        except Exception as e:
            return json.dumps({"error": str(e), "url": url}), None
    return json.dumps({"error": "Max retries exceeded"}), None

def probe_binance_klines():
    """Test Binance klines depth with limit=1500."""
    print("\n=== BINANCE KLINES ===")
    results = {}

    for symbol in SYMBOLS:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=4h&limit=1500"
        print(f"  Testing {symbol}...")
        body, status = make_request(url)

        try:
            data = json.loads(body)
            if isinstance(data, list) and len(data) > 0:
                results[symbol] = {
                    "row_count": len(data),
                    "earliest_ts_ms": data[0][0],
                    "earliest_ts_iso": datetime.fromtimestamp(data[0][0] / 1000).isoformat(),
                    "latest_ts_ms": data[-1][0],
                    "latest_ts_iso": datetime.fromtimestamp(data[-1][0] / 1000).isoformat(),
                    "status": "success"
                }
                print(f"    ✓ {len(data)} rows, earliest: {results[symbol]['earliest_ts_iso']}")
            else:
                results[symbol] = {"status": "error", "response": data}
                print(f"    ✗ Unexpected response: {str(data)[:100]}")
        except Exception as e:
            results[symbol] = {"status": "error", "error": str(e)}
            print(f"    ✗ Error parsing: {e}")

    return results

def probe_binance_open_interest():
    """Test Binance openInterestHist endpoint."""
    print("\n=== BINANCE OPEN INTEREST ===")
    results = {}

    for symbol in SYMBOLS:
        url = f"https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=4h&limit=500"
        print(f"  Testing {symbol}...")
        body, status = make_request(url)

        try:
            data = json.loads(body)
            if isinstance(data, list) and len(data) > 0:
                results[symbol] = {
                    "row_count": len(data),
                    "earliest_ts_ms": data[0].get("timestamp"),
                    "earliest_ts_iso": datetime.fromtimestamp(data[0].get("timestamp", 0) / 1000).isoformat() if data[0].get("timestamp") else None,
                    "latest_ts_ms": data[-1].get("timestamp"),
                    "latest_ts_iso": datetime.fromtimestamp(data[-1].get("timestamp", 0) / 1000).isoformat() if data[-1].get("timestamp") else None,
                    "status": "success",
                    "sample_fields": list(data[0].keys())
                }
                print(f"    ✓ {len(data)} rows, earliest: {results[symbol]['earliest_ts_iso']}")
            else:
                results[symbol] = {"status": "error", "response": data}
                print(f"    ✗ Unexpected response: {str(data)[:100]}")
        except Exception as e:
            results[symbol] = {"status": "error", "error": str(e)}
            print(f"    ✗ Error parsing: {e}")

    return results

def probe_binance_long_short_ratio():
    """Test Binance topLongShortAccountRatio and globalLongShortAccountRatio."""
    print("\n=== BINANCE LONG/SHORT RATIO (TOP ACCOUNTS) ===")
    results = {}

    for symbol in SYMBOLS:
        url = f"https://fapi.binance.com/futures/data/topLongShortAccountRatio?symbol={symbol}&period=4h&limit=500"
        print(f"  Testing {symbol}...")
        body, status = make_request(url)

        try:
            data = json.loads(body)
            if isinstance(data, list) and len(data) > 0:
                results[symbol] = {
                    "row_count": len(data),
                    "earliest_ts_ms": data[0].get("timestamp"),
                    "earliest_ts_iso": datetime.fromtimestamp(data[0].get("timestamp", 0) / 1000).isoformat() if data[0].get("timestamp") else None,
                    "latest_ts_ms": data[-1].get("timestamp"),
                    "latest_ts_iso": datetime.fromtimestamp(data[-1].get("timestamp", 0) / 1000).isoformat() if data[-1].get("timestamp") else None,
                    "status": "success",
                    "sample_fields": list(data[0].keys())
                }
                print(f"    ✓ {len(data)} rows, earliest: {results[symbol]['earliest_ts_iso']}")
            else:
                results[symbol] = {"status": "error", "response": data}
                print(f"    ✗ Unexpected response: {str(data)[:100]}")
        except Exception as e:
            results[symbol] = {"status": "error", "error": str(e)}
            print(f"    ✗ Error parsing: {e}")

    return results

def probe_binance_global_long_short_ratio():
    """Test Binance globalLongShortAccountRatio."""
    print("\n=== BINANCE LONG/SHORT RATIO (GLOBAL) ===")
    results = {}

    for symbol in SYMBOLS:
        url = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={symbol}&period=4h&limit=500"
        print(f"  Testing {symbol}...")
        body, status = make_request(url)

        try:
            data = json.loads(body)
            if isinstance(data, list) and len(data) > 0:
                results[symbol] = {
                    "row_count": len(data),
                    "earliest_ts_ms": data[0].get("timestamp"),
                    "earliest_ts_iso": datetime.fromtimestamp(data[0].get("timestamp", 0) / 1000).isoformat() if data[0].get("timestamp") else None,
                    "latest_ts_ms": data[-1].get("timestamp"),
                    "latest_ts_iso": datetime.fromtimestamp(data[-1].get("timestamp", 0) / 1000).isoformat() if data[-1].get("timestamp") else None,
                    "status": "success",
                    "sample_fields": list(data[0].keys())
                }
                print(f"    ✓ {len(data)} rows, earliest: {results[symbol]['earliest_ts_iso']}")
            else:
                results[symbol] = {"status": "error", "response": data}
                print(f"    ✗ Unexpected response: {str(data)[:100]}")
        except Exception as e:
            results[symbol] = {"status": "error", "error": str(e)}
            print(f"    ✗ Error parsing: {e}")

    return results

def probe_coinalyze():
    """Test Coinalyze API WITHOUT key (expect 401)."""
    print("\n=== COINALYZE (NO KEY) ===")

    # Test with one symbol to see the auth requirement
    url = "https://api.coinalyze.net/v1/open-interest-history?symbols=BTCUSDT_PERP.A&interval=4hour&from=0&to=9999999999"
    print(f"  Testing Coinalyze without API key...")
    print(f"  URL: {url}")

    body, status = make_request(url)

    result = {
        "status": status,
        "requires_auth": status == 401,
        "response": body[:200] if isinstance(body, str) else str(body)[:200]
    }

    print(f"    HTTP {status}: {result['response']}")

    return result

def probe_hyperliquid_info():
    """Test Hyperliquid info endpoint — try openInterestHistory which should error."""
    print("\n=== HYPERLIQUID (INFO ENDPOINT) ===")

    url = "https://api.hyperliquid.xyz/info"
    print(f"  Testing Hyperliquid info endpoint...")

    # Try to get openInterestHistory which should fail
    payload = json.dumps({
        "type": "openInterestHistory",
        "coin": "BTC"
    }).encode('utf-8')

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            body = response.read().decode('utf-8')
            status = response.status
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8') if e.fp else str(e)
        status = e.code
    except Exception as e:
        body = str(e)
        status = None

    try:
        data = json.loads(body)
    except:
        data = body

    result = {
        "endpoint": "POST /info",
        "request_type": "openInterestHistory",
        "status": status,
        "response": str(data)[:300]
    }

    print(f"    HTTP {status}: openInterestHistory request returned {result['response']}")

    return result

def main():
    print(f"CTA Data Feasibility Probe")
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Symbols: {SYMBOLS}")
    print(f"Cache: {CACHE_DIR}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    all_results = {
        "timestamp": datetime.now().isoformat(),
        "symbols": SYMBOLS,
        "binance_klines": probe_binance_klines(),
        "binance_open_interest": probe_binance_open_interest(),
        "binance_long_short_ratio_top": probe_binance_long_short_ratio(),
        "binance_long_short_ratio_global": probe_binance_global_long_short_ratio(),
        "coinalyze": probe_coinalyze(),
        "hyperliquid": probe_hyperliquid_info(),
    }

    # Save full results
    output_file = CACHE_DIR / f"probe_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n✓ Full results saved to {output_file}")
    print(f"Completed: {datetime.now().isoformat()}")

    return all_results

if __name__ == "__main__":
    main()
