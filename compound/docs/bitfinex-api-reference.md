# Bitfinex API v2 — Margin Funding (Lending) REST Reference

Scope: every REST endpoint needed to build a USD auto-lending engine.
Compiled 2026-07-04 from the official docs (docs.bitfinex.com), the official Python SDK
(github.com/bitfinexcom/bitfinex-api-py), and **live responses from the public API**
(entries marked `[verified live 2026-07-04]` were checked against actual `api-pub.bitfinex.com`
responses on that date).

Base URLs:

| Kind | Base |
|---|---|
| Public (market data) | `https://api-pub.bitfinex.com/v2/` |
| Authenticated | `https://api.bitfinex.com/v2/` |

General v2 conventions:

- All responses are **JSON arrays without keys**. Field meaning is positional. Some positions
  are permanent `null` placeholders — **index by absolute position, never by "skip the nulls"**.
- Timestamps are **milliseconds** since epoch (`MTS`) unless noted.
- Error responses have the shape `["error", CODE, "MESSAGE"]` (e.g. `["error",10100,"apikey: invalid"]`,
  `["error",10114,"nonce: small"]`). Rate limiting is a special case, see §6.
- Funding symbols are `f` + currency: `fUSD`, `fUST`, `fBTC`. Some *write* endpoints instead take a bare
  currency (`USD`) — each endpoint below states which form it takes. Mixing them up is a classic bug.

---

## 1. Authentication (all `auth/*` endpoints)

Source: https://docs.bitfinex.com/docs/rest-auth ("Authenticated endpoints require users to sign
their requests using a pair of API-KEY and API-SECRET"), signature mechanics confirmed from the
official SDK source `bfxapi/rest/_interface/middleware.py`
(https://github.com/bitfinexcom/bitfinex-api-py, method `__get_authentication_headers`).

- All authenticated endpoints are **HTTP POST** (even read endpoints, `auth/r/*`).
- Body is JSON (`content-type: application/json`). If an endpoint needs no params, send `{}`.
- Signature payload: `"/api/v2/" + endpoint + nonce + rawBodyString` concatenated with **no separators**
  (if there is no body, omit it). `endpoint` is the path after `/v2/`, e.g. `auth/w/funding/offer/submit`.
- Signature: **HMAC-SHA384** of that string, key = API secret, output as **hex digest**.
- Headers: `bfx-nonce`, `bfx-apikey`, `bfx-signature`.

Nonce (source: https://docs.bitfinex.com/docs/requirements-and-limitations):

> "The only requirement for the nonce is that it needs to be strictly increasing."
> "The nonce provided must be strictly increasing but should not exceed the MAX_SAFE_INTEGER
> constant value of 9007199254740991."

The official Python SDK uses **microseconds**: `str(round(time.time() * 1_000_000))`
(≈1.78e15 today, safely below 9.007e15). Milliseconds also work, but once a key has ever been used
with a larger nonce you can never send a smaller one — pick microseconds and stay there.
**One API key = one nonce stream**: two processes (or two overlapping requests) sharing a key will
race nonces and get `["error",10114,"nonce: small"]`. Serialize authed requests per key, or use one
key per process.

Python reference implementation:

```python
import hashlib, hmac, json, time
import requests

API_BASE = "https://api.bitfinex.com/v2/"

def bfx_post(endpoint: str, body: dict, key: str, secret: str):
    # endpoint e.g. "auth/w/funding/offer/submit" (no leading slash)
    nonce = str(round(time.time() * 1_000_000))          # microseconds, strictly increasing
    raw_body = json.dumps(body)                           # serialize ONCE
    message = f"/api/v2/{endpoint}{nonce}{raw_body}"      # no separators
    sig = hmac.new(secret.encode("utf8"),
                   message.encode("utf8"),
                   hashlib.sha384).hexdigest()
    headers = {
        "bfx-nonce": nonce,
        "bfx-apikey": key,
        "bfx-signature": sig,
        "content-type": "application/json",
    }
    # CRITICAL: send the exact string that was signed. Use data=raw_body,
    # NOT json=body (requests may re-serialize with different spacing → signature mismatch).
    return requests.post(API_BASE + endpoint, headers=headers, data=raw_body, timeout=30)
```

API key permissions needed: the key must have "Margin Funding" read+write and "Wallets" read
enabled (set when creating the key in the UI).

---

## 2. Rate units — read this first

| Place | Unit | Example |
|---|---|---|
| Funding **ticker** (FRR, BID, ASK, LAST) | **rate per day**, decimal (1% = 0.01) | `0.000371` = 0.0371 %/day ≈ 13.5 % APR |
| Funding **book** RATE | rate per day, decimal | same |
| Funding **candles** OHLC | rate per day, decimal | `[verified live]` values match ticker |
| Funding **trades** RATE | rate per day, decimal | same |
| **Offer submit / offers / loans / credits** RATE | rate per day, decimal — docs: *"Rate of the offer (percentage expressed as decimal number i.e. 1% = 0.01)"* and submit param is literally described as *"Daily rate"* | you submit `0.0003` to ask 0.03 %/day |
| **Funding stats** FRR | **1/365 of the daily rate** (the odd one out) | see §3.5 quote |

APR ≈ daily_rate × 365 (Bitfinex UI shows this). Empirical cross-check 2026-07-04:
ticker FRR `0.0003715...`; funding-stats FRR `0.00000102`; `0.00000102 × 365 = 0.0003723` ✓.

---

## 3. Public endpoints (`https://api-pub.bitfinex.com/v2/`)

No auth headers. GET requests.

### 3.1 Funding ticker

- **GET** `https://api-pub.bitfinex.com/v2/ticker/fUSD`
- Source: https://docs.bitfinex.com/reference/rest-public-ticker — rate limit **90 req/min**.

Response for funding symbols (`[verified live 2026-07-04]`, 17 elements):

```
[0.0003715..., 0.0003013..., 120, 28731155.02, 0.000149, 2, 5996865.89,
 0.00003788, 0.1474, 0.00029488, 263021222.26, 0.00037104, 0.00007945,
 null, null, 60617019.59, 1469734163000]
```

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | FRR | float | "Flash Return Rate - average of all fixed rate funding over the last hour" (daily rate) |
| 1 | BID | float | Best bid rate (borrower demand) |
| 2 | BID_PERIOD | int | Bid period in days |
| 3 | BID_SIZE | float | Sum of the 25 highest bid sizes |
| 4 | ASK | float | Best ask rate (lender offers — **your side**) |
| 5 | ASK_PERIOD | int | Ask period in days |
| 6 | ASK_SIZE | float | Sum of the 25 lowest ask sizes |
| 7 | DAILY_CHANGE | float | Absolute rate change over the day |
| 8 | DAILY_CHANGE_RELATIVE | float | Relative change (×100 for %) |
| 9 | LAST_PRICE | float | Rate of last funding trade |
| 10 | VOLUME | float | Volume in the period |
| 11 | HIGH | float | Day high rate |
| 12 | LOW | float | Day low rate |
| 13 | — | null | placeholder |
| 14 | — | null | placeholder |
| 15 | FRR_AMOUNT_AVAILABLE | float | "The amount of funding that is available at the Flash Return Rate" |
| 16 | (FIRST_TRADE, per docs page) | int | ms timestamp; present in live responses — do not rely on it, parse only 0–15 |

### 3.2 Funding order book

- **GET** `https://api-pub.bitfinex.com/v2/book/fUSD/{precision}?len={1|25|100|250}`
- Precisions: `P0` (finest) … `P4`, `R0` (raw, per-offer). `len` defaults to 25.
- Source: https://docs.bitfinex.com/reference/rest-public-book — rate limit **240 req/min**.

Aggregated (`P0`–`P4`) funding entry (`[verified live]`):

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | RATE | float | Rate level (daily) |
| 1 | PERIOD | int | Period level (days) |
| 2 | COUNT | int | Number of orders at this rate/period level |
| 3 | AMOUNT | float | Total amount at level; **sign = side, see below** |

Raw (`R0`) funding entry (`[verified live]`): `[OFFER_ID, PERIOD, RATE, AMOUNT]`
(note RATE and PERIOD swap positions vs P0 — offer id first).

**Side convention** — docs: *"if AMOUNT > 0 then ask else bid"* (funding books).
- `AMOUNT > 0` → **ask = funding offered by lenders** (where your offers sit).
- `AMOUNT < 0` → **bid = borrower demand**.
The array returns bids first, then asks (with `len=25` you get 50 rows: 25 bids + 25 asks).
This is the **opposite intuition from trading books** (where bids are positive) — key trap.
`[verified live]`: top-of-array rows had negative amounts and matched ticker BID/BID_PERIOD.

### 3.3 Funding candles

- **GET** `https://api-pub.bitfinex.com/v2/candles/{key}/{section}`
- `section` ∈ `last` (single most-recent candle array) | `hist` (array of candles).
- Query params (hist): `limit` (int, **max 10 000**), `start` (ms, MTS ≥ start), `end` (ms, MTS ≤ end),
  `sort` (`+1` ascending, `-1` descending; default -1).
- Timeframes: `1m, 5m, 15m, 30m, 1h, 3h, 6h, 12h, 1D, 1W, 14D, 1M`.
- Source: https://docs.bitfinex.com/reference/rest-public-candles — rate limit **30 req/min**.

**Key syntax for funding candles** (docs quote):

> "Be sure to specify a period or aggregated period when retrieving funding candles. If you wish
> to mimic the candles found in the UI, use the following setup to aggregate all funding candles:
> **a30:p2:p30**."

- Single period: `trade:{tf}:fUSD:p{N}` — candles of funding trades with period exactly N days.
  e.g. `trade:1D:fUSD:p2` `[verified live]`
- Aggregated periods: `trade:{tf}:fUSD:a{AGG}:p{START}:p{END}` — aggregates periods START…END days.
  UI-equivalent for USD: `trade:1D:fUSD:a30:p2:p30` `[verified live]`
  (`a30` = aggregation window parameter, `p2:p30` = period range 2–30 days).

Candle array (`[verified live]`):

| Idx | Field | Meaning |
|---|---|---|
| 0 | MTS | candle open time, ms |
| 1 | OPEN | first rate (daily) |
| 2 | CLOSE | last rate |
| 3 | HIGH | highest rate |
| 4 | LOW | lowest rate |
| 5 | VOLUME | total amount funded in window |

### 3.4 Funding trades history

- **GET** `https://api-pub.bitfinex.com/v2/trades/fUSD/hist?limit=…&start=…&end=…&sort=…`
- `limit` max 10 000 (default 125); `start`/`end` ms; `sort` +1/-1.
- Source: https://docs.bitfinex.com/reference/rest-public-trades — rate limit **15 req/min** (low!).

Funding trade array (`[verified live]`: `[427038382,1783180369000,150,0.00023466,120]`):

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | ID | int | Trade id |
| 1 | MTS | int | ms timestamp |
| 2 | AMOUNT | float | Amount; sign = taker direction (positive/negative) |
| 3 | RATE | float | "Rate at which funding transaction occurred" (daily) |
| 4 | PERIOD | int | "Amount of time the funding transaction was for" (days) |

(Trading pairs have `[ID, MTS, AMOUNT, PRICE]` — funding replaces PRICE with RATE+PERIOD.)

### 3.5 Funding stats

- **GET** `https://api-pub.bitfinex.com/v2/funding/stats/fUSD/hist?limit=…&start=…&end=…`
- `limit` max **250**. Data points are ~hourly.
- Source: https://docs.bitfinex.com/reference/rest-public-funding-stats — rate limit **not stated
  on the reference page**; budget it conservatively (treat like trades, ≤15 req/min).

**Unit warning** — docs quote for the FRR field:

> "1/365th of Flash Return Rate (To get the daily rate, use: rate x 365. To get the daily rate as
> percentage use: rate x 365 x 100. To get APR as percentage use rate x 100 x 365 x 365.)"

Response array (`[verified live 2026-07-04]`:
`[1783177500000,null,null,0.00000102,80.4,null,null,5986423138.37,5917128689.59,null,null,355454209.10]`):

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | MTS | int | ms timestamp |
| 1–2 | — | null | placeholders |
| 3 | FRR | float | **1/365 of daily FRR** — multiply by 365 to compare with ticker/offers |
| 4 | AVG_PERIOD | float | Average period of funding provided (days) |
| 5–6 | — | null | placeholders |
| 7 | FUNDING_AMOUNT | float | Total funding provided |
| 8 | FUNDING_AMOUNT_USED | float | Total funding provided that is used in positions |
| 9–10 | — | null | placeholders |
| 11 | FUNDING_BELOW_THRESHOLD | float | "Sum of open funding offers < 0.75%" (APR threshold) |

Utilization = idx8 / idx7 — a core signal for a lending engine.

---

## 4. Authenticated endpoints (`https://api.bitfinex.com/v2/`)

All POST, all signed (§1). Empty params ⇒ body `{}`.

### 4.1 Wallets (read funding-wallet USD balance)

- **POST** `https://api.bitfinex.com/v2/auth/r/wallets`, body `{}`
- Source: https://docs.bitfinex.com/reference/rest-auth-wallets — rate limit **90 req/min**.

Returns an array of wallet arrays:

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | WALLET_TYPE | string | `exchange` \| `margin` \| `funding` |
| 1 | CURRENCY | string | e.g. `USD`, `UST`, `BTC` |
| 2 | BALANCE | float | Total balance |
| 3 | UNSETTLED_INTEREST | float | Unsettled interest |
| 4 | AVAILABLE_BALANCE | float | "Wallet balance available for orders/withdrawal/transfer" — **use this, not [2], to size new offers** ([2] includes amounts already lent out / in open offers) |
| 5 | LAST_CHANGE | string | Description of last ledger entry (may be null) |
| 6 | LAST_CHANGE_METADATA | json | Optional details object (may be null) |

Lendable USD = the row where `[0]=="funding" and [1]=="USD"`, field `[4]`.

### 4.2 Submit funding offer (the core write)

- **POST** `https://api.bitfinex.com/v2/auth/w/funding/offer/submit`
- Source: https://docs.bitfinex.com/reference/rest-auth-submit-funding-offer — rate limit **90 req/min**.

Body parameters:

| Param | Type | Req | Meaning (docs wording) |
|---|---|---|---|
| `type` | string | yes | `"LIMIT"` \| `"FRRDELTAFIX"` \| `"FRRDELTAVAR"` |
| `symbol` | string | yes | "Symbol for desired pair (fUSD, fBTC, etc..)" — **f-prefixed** |
| `amount` | **string** | yes | "Amount (positive for offer, negative for bid)" — positive = lend |
| `rate` | **string** | yes | "Daily rate" — decimal, 1% = 0.01. For FRRDELTA* types this is the **delta from FRR** (0 = exactly FRR) |
| `period` | int | yes | "Time period of offer. Minimum 2 days. Maximum 120 days." (integer days) |
| `flags` | int | no | sum of flags; `64` = hidden ("does not appear in the offer book", source: https://docs.bitfinex.com/docs/flag-values). Hidden offers pay a higher funding fee (18% vs 15%, §7) |

Type semantics: `LIMIT` = fixed rate you specify. `FRRDELTAFIX` = pegged to FRR±delta, rate fixed
at fill time. `FRRDELTAVAR` = floating FRR±delta over the life of the loan (shows as RATE_TYPE
`VAR` on the resulting loan/credit).

Example body: `{"type":"LIMIT","symbol":"fUSD","amount":"150.0","rate":"0.0003","period":2}`

Response — notification wrapper:

| Idx | Field | Meaning |
|---|---|---|
| 0 | MTS | ms timestamp |
| 1 | TYPE | request type tag — docs table prints "on-req", live responses are known to return `"fon-req"`; **do not branch on this string, branch on [6] STATUS** |
| 2 | MESSAGE_ID | int or null |
| 3 | — | placeholder |
| 4 | FUNDING_OFFER_ARRAY | the offer, format identical to §4.5 (idx 0–19) |
| 5 | CODE | int or null (W.I.P. per docs) |
| 6 | STATUS | `"SUCCESS"` \| `"ERROR"` \| `"FAILURE"` … |
| 7 | TEXT | human-readable, e.g. "Submitting funding bid of 150.0 USD at 0.0300 for 2 days." |

On semantic rejection (below minimum, bad rate, insufficient balance) you may get either
STATUS != SUCCESS or an HTTP-level `["error",code,msg]` — handle both, and treat them as
**semantic failures: do not retry** with the same params.

### 4.3 Cancel funding offer (single)

- **POST** `https://api.bitfinex.com/v2/auth/w/funding/offer/cancel`
- Body: `{"id": <int64 offer id>}` (int, not string)
- Source: https://docs.bitfinex.com/reference/rest-auth-cancel-funding-offer — **90 req/min**.
- Response: notification wrapper as §4.2 (docs table shows TYPE "on-req"; live known "foc-req");
  `[4]` = the canceled offer array (STATUS field inside it becomes `CANCELED`).
- Canceling an id that no longer exists (already filled/canceled) returns an error notification —
  treat as reconciliation signal, not as transient failure; re-read active offers (§4.5).

### 4.4 Cancel ALL funding offers

- **POST** `https://api.bitfinex.com/v2/auth/w/funding/offer/cancel/all`
- Body: `{"currency":"USD"}` — **bare currency, no `f` prefix**; docs: "Specifying a currency is
  optional. If the currency param is omitted, all open offers will be cancelled." (across all currencies)
- Source: https://docs.bitfinex.com/reference/rest-auth-cancel-all-funding-offers — **90 req/min**.
- Response notification: `[1] TYPE = "foc_all-req"` ("funding offer cancel all request", per docs),
  `[6] STATUS`, `[7] TEXT`.

### 4.5 Active funding offers (read)

- **POST** `https://api.bitfinex.com/v2/auth/r/funding/offers/fUSD` (body `{}`)
  or `…/auth/r/funding/offers` without symbol → all currencies.
- Source: https://docs.bitfinex.com/reference/rest-auth-funding-offers — **90 req/min**.

Array of offers; offer array layout (also used inside §4.2/§4.3 notifications):

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | ID | int | Offer id |
| 1 | SYMBOL | string | e.g. `fUSD` |
| 2 | MTS_CREATED | int | ms |
| 3 | MTS_UPDATED | int | ms |
| 4 | AMOUNT | float | **Remaining** amount |
| 5 | AMOUNT_ORIG | float | Original amount |
| 6 | TYPE | string | `LIMIT` / `FRRDELTAFIX` / `FRRDELTAVAR` |
| 7–8 | — | null | placeholders |
| 9 | FLAGS | int/obj | "Future params object (stay tuned)" |
| 10 | STATUS | string | `ACTIVE`, `PARTIALLY FILLED` (in notifications also `EXECUTED`, `CANCELED`) |
| 11–13 | — | null | placeholders |
| 14 | RATE | float | Daily rate, decimal (1% = 0.01) |
| 15 | PERIOD | int | days |
| 16 | NOTIFY | int | 0/1 |
| 17 | HIDDEN | int | null/0 = false, 1 = true |
| 18 | — | null | placeholder |
| 19 | RENEW | int | 0/1 |

### 4.6 Funding loans vs funding credits (your money that is lent out)

Both are your **filled** lends; the split is whether the borrower is using them:

- **Loans** = "Funds not used in active positions" (docs wording).
  **POST** `https://api.bitfinex.com/v2/auth/r/funding/loans/fUSD` (body `{}`)
  Source: https://docs.bitfinex.com/reference/rest-auth-funding-loans — **90 req/min**.
- **Credits** = funds **used in active positions** (earning; tied to a trading pair).
  **POST** `https://api.bitfinex.com/v2/auth/r/funding/credits/fUSD` (body `{}`)
  Source: https://docs.bitfinex.com/reference/rest-auth-funding-credits — **90 req/min**.

Shared array layout (credits have one extra trailing field):

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | ID | int | Loan/credit id |
| 1 | SYMBOL | string | `fUSD` |
| 2 | SIDE | int | "1 if you are the lender, 0 if you are both the lender and borrower, -1 if you're the borrower" |
| 3 | MTS_CREATE | int | ms |
| 4 | MTS_UPDATE | int | ms |
| 5 | AMOUNT | float | "Amount of funds provided" |
| 6 | FLAGS | int/obj | future params |
| 7 | STATUS | string | `ACTIVE` |
| 8 | RATE_TYPE | string | `FIXED` or `VAR` (FRR-pegged) |
| 9–10 | — | null | placeholders |
| 11 | RATE | float | Daily rate, decimal |
| 12 | PERIOD | int | days |
| 13 | MTS_OPENING | int | ms loan opened |
| 14 | MTS_LAST_PAYOUT | int | ms of last interest payout |
| 15 | NOTIFY | int | 0/1 |
| 16 | HIDDEN | int | 0/1 |
| 17 | — | null | placeholder |
| 18 | RENEW | int | 0/1 |
| 19 | — | null | placeholder (legacy RATE_REAL slot) |
| 20 | NO_CLOSE | int | "If funding will be returned when position is closed. 0 if false, 1 if true" |
| 21 | POSITION_PAIR | string | **credits only** — "Pair of the position that the funding was used for" |

Total lent = Σ amounts over loans + credits. Only credits are attached to borrower positions;
loans sit taken-but-unused (still earning per their contract — see support links in §7).

### 4.7 Funding auto-renew

- **POST** `https://api.bitfinex.com/v2/auth/w/funding/auto`
- Source: https://docs.bitfinex.com/reference/rest-auth-funding-auto-renew — **90 req/min**.

Body:

| Param | Type | Req | Meaning |
|---|---|---|---|
| `status` | int | yes | "1 to activate, 0 to deactivate" |
| `currency` | string | yes | **bare currency** e.g. `"USD"` (not fUSD) |
| `amount` | string | no | Max amount to auto-renew; docs reference says "Minimum 50 USD equivalent", defaults to full amount — see minimum-size caveat in §7 |
| `rate` | string | no | "Percentage rate at which to auto-renew. (rate == 0 to renew at FRR). Defaults to FRR if omitted" — daily decimal |
| `period` | int | no | days; "Defaults to 2 if omitted" |

Response notification: `[1] TYPE = "fa-req"`, `[4]` = `[CURRENCY, PERIOD, RATE, THRESHOLD]`
(THRESHOLD = max auto-renew amount), `[6] STATUS`, `[7] TEXT`.

Note: an engine that re-offers programmatically generally wants auto-renew **off** (status 0) so
returned funds come back to the wallet for the engine to re-price.

### 4.8 Ledgers — realized interest income

- **POST** `https://api.bitfinex.com/v2/auth/r/ledgers/USD/hist` (bare currency in path; omit the
  currency segment → all currencies)
- Body params: `category` (int), `start` (ms), `end` (ms), `limit` (int, **max 2500**)
- Source: https://docs.bitfinex.com/reference/rest-auth-ledgers — **90 req/min**.

**Category `28` = "Margin Swap Interest Payment"** — funding interest credits. Filter body:
`{"category": 28, "start": …, "end": …, "limit": 2500}`. Entries appear with description
"Margin Funding Payment on wallet funding" and are credited **daily around 01:30 UTC**
(source: Bitfinex Help Center, see §7). Ledger array:

| Idx | Field | Type | Meaning |
|---|---|---|---|
| 0 | ID | int | Ledger entry id |
| 1 | CURRENCY | string | `USD` |
| 2 | WALLET | string/null | wallet of the entry (`funding`) |
| 3 | MTS | int | ms timestamp |
| 4 | — | null | placeholder |
| 5 | AMOUNT | float | Amount changed (interest credited, **already net of the 15%/18% fee**) |
| 6 | BALANCE | float | Balance after change |
| 7 | — | null | placeholder |
| 8 | DESCRIPTION | string | e.g. "Margin Funding Payment on wallet funding" |

Daily interest reconciliation = Σ AMOUNT of category-28 entries per day.

---

## 5. Rate limits summary

Per-endpoint limits from the reference pages; global policy from
https://docs.bitfinex.com/docs/requirements-and-limitations:

> "An IP address can be rate limited if it has sent too many requests per minute. The current rate
> limit is between 10 and 90 requests per minute, depending on the specific REST API endpoint."
> When limited: "the API will return the JSON response {\"error\": \"ERR_RATE_LIMIT\"}" and
> "the IP is blocked for 60 seconds and cannot make any requests during that time."

| Endpoint | Limit (req/min) |
|---|---|
| `ticker` | 90 |
| `book` | 240 |
| `candles` | 30 |
| `trades/{sym}/hist` | **15** |
| `funding/stats` | not stated — budget ≤15 |
| `auth/r/wallets` | 90 |
| `auth/w/funding/offer/submit` | 90 |
| `auth/w/funding/offer/cancel` | 90 |
| `auth/w/funding/offer/cancel/all` | 90 |
| `auth/r/funding/offers` | 90 |
| `auth/r/funding/loans` | 90 |
| `auth/r/funding/credits` | 90 |
| `auth/w/funding/auto` | 90 |
| `auth/r/ledgers` | 90 |

Handling (fits the transient/semantic split):

- Rate-limit response (HTTP 429 and/or body `{"error":"ERR_RATE_LIMIT"}` — match on the **body**,
  which is the documented contract) → **transient**: back off ≥60 s (the documented block length),
  then resume; exponential backoff on repeats. Retrying inside the 60 s window only extends pain.
- Public polling budget for one lending engine: book+ticker at a few req/min is far under limits;
  the tight ones are `trades` (15/min) and `candles` (30/min) — cache these.
- `["error",10114,"nonce: small"]` → serialization bug on your side, not transient. Fix nonce stream.
- Offer submit/cancel are **not idempotent** — on timeout/ambiguous failure do NOT blind-retry;
  reconcile via §4.5 active offers, then act.

---

## 6. Funding offer lifecycle

```
submit (§4.2)
  └─ notification SUCCESS → offer ACTIVE in book        [visible via §4.5, status ACTIVE]
       ├─ cancel (§4.3/4.4) → CANCELED, funds → wallet available balance
       └─ taken (fully or partially; partial fills shrink AMOUNT, status PARTIALLY FILLED)
            └─ becomes a contract for `period` days:
                 ├─ shows in loans  (§4.6)  while not deployed in a position
                 └─ shows in credits (§4.6) while used in a position (POSITION_PAIR set)
                      • interest accrues; payouts land daily ~01:30 UTC as ledger cat-28 entries
                      • MTS_LAST_PAYOUT updates on each payout
            └─ at expiry (or borrower close, subject to NO_CLOSE):
                 ├─ RENEW=1 / auto-renew on → re-offered per auto-renew settings (§4.7)
                 └─ otherwise principal returns to funding wallet available balance
```

An engine loop therefore watches: wallet available (§4.1) → place/reprice offers (§4.2/4.3) →
track fills (§4.5 vs §4.6) → verify income (§4.8).

---

## 7. Key traps (each answered explicitly)

1. **Rate unit**: submit/offers/loans/credits/ticker/book/candles/trades all use **daily rate as a
   decimal** (docs: "Daily rate", "percentage expressed as decimal number i.e. 1% = 0.01").
   The single exception is **funding stats FRR = 1/365 of the daily rate** (docs quote in §3.5,
   verified empirically). Never feed a funding-stats FRR straight into an offer.
2. **Minimum offer**: **$150 (or equivalent) per offer** — Bitfinex Help Center: "The minimum
   amount for a single offer of Funding is $150 or the equivalent in other currencies"
   (https://support.bitfinex.com/hc/en-us/articles/213918949). Below-minimum submits are rejected
   (semantic error). Discrepancy note: the auto-renew reference page says amount "Minimum 50 USD
   equivalent" — for engine sizing use ≥150; treat 50 as auto-renew-parameter-specific at best.
3. **Period**: integer days, **2–120** (docs: "Minimum 2 days. Maximum 120 days.").
4. **Nonce**: strictly increasing per API key, ≤ 9 007 199 254 740 991; SDK convention is
   microseconds (`time.time()*1_000_000`). One key per process; serialize authed calls.
5. **amount/rate are JSON strings** in write bodies (`"150.0"`, `"0.0003"`), `period`/`id`/`status`
   are ints. Positive amount = lend (offer), negative = borrow (bid).
6. **Symbol vs currency format**: `fUSD` for submit/offers/loans/credits and public endpoints;
   bare `USD` for cancel-all, auto-renew, and the ledgers path.
7. **Book side sign**: in funding books `AMOUNT > 0 = ask (lenders)`, `< 0 = bid (borrowers)` —
   inverted vs trading books. Your competition for lending is the **ask** side / ticker `ASK`.
8. **Sign & send identical bytes**: sign `json.dumps(body)` and POST exactly that string
   (`data=raw_body`); letting the HTTP lib re-serialize breaks the signature.
9. **Don't branch on notification TYPE strings** ("fon-req" observed live vs "on-req" printed in
   docs tables); branch on `STATUS` (index 6) and reconcile via reads.
10. **Fees on earnings**: Bitfinex takes **15.0%** of generated funding interest, **18.0% for hidden
    offers** (https://www.bitfinex.com/fees/), LEO holders get up to −5%. Interest accrues per
    second with a one-hour minimum and is credited daily ~01:30 UTC (Help Center:
    https://support.bitfinex.com/hc/en-us/articles/115004554309, /213918989). Ledger amounts are
    net of the fee.
11. **429/ERR_RATE_LIMIT** blocks the IP for 60 s — a hot retry loop keeps you blocked (§5).
12. **Offer fills are partial**: track `AMOUNT` vs `AMOUNT_ORIG`; a "filled" offer disappears from
    §4.5 and its remainder appears in §4.6.

---

## 8. Sources

- Submit offer: https://docs.bitfinex.com/reference/rest-auth-submit-funding-offer
- Cancel offer: https://docs.bitfinex.com/reference/rest-auth-cancel-funding-offer
- Cancel all: https://docs.bitfinex.com/reference/rest-auth-cancel-all-funding-offers
- Active offers: https://docs.bitfinex.com/reference/rest-auth-funding-offers
- Loans: https://docs.bitfinex.com/reference/rest-auth-funding-loans
- Credits: https://docs.bitfinex.com/reference/rest-auth-funding-credits
- Auto-renew: https://docs.bitfinex.com/reference/rest-auth-funding-auto-renew
- Wallets: https://docs.bitfinex.com/reference/rest-auth-wallets
- Ledgers: https://docs.bitfinex.com/reference/rest-auth-ledgers
- Ticker: https://docs.bitfinex.com/reference/rest-public-ticker
- Book: https://docs.bitfinex.com/reference/rest-public-book
- Candles: https://docs.bitfinex.com/reference/rest-public-candles
- Trades: https://docs.bitfinex.com/reference/rest-public-trades
- Funding stats: https://docs.bitfinex.com/reference/rest-public-funding-stats
- Auth & limits: https://docs.bitfinex.com/docs/rest-auth , https://docs.bitfinex.com/docs/requirements-and-limitations
- Flags: https://docs.bitfinex.com/docs/flag-values
- Official SDK (signature code): https://github.com/bitfinexcom/bitfinex-api-py (`bfxapi/rest/_interface/middleware.py`)
- Minimum offer / interest & fees: https://support.bitfinex.com/hc/en-us/articles/213918949 ,
  https://support.bitfinex.com/hc/en-us/articles/115004554309 , https://www.bitfinex.com/fees/
- Live verification: `api-pub.bitfinex.com` responses fetched 2026-07-04 (marked `[verified live]`).
