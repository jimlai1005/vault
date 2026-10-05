# gridbot 熔斷器權益 basis：納入現貨幣 + unified hold 修正 Implementation Plan

> **For agentic workers:** 逐 task 執行，每個 task 結束前跑該 task 的驗收指令並貼輸出。
> 每個 task 標 `@inline`（builder）或 `@sdd`（impl-worker）。不得改動 plan 以外的檔案。
> 測試絕不可打真實網路（全域工程原則 #4）：所有 `info` 一律用 fake。

**Goal:** `get_full_account_equity` 要把錢包裡所有現貨幣（以 USDC 對 mid 計價）算進權益，並以 env `EQUITY_SPOT_BASIS` 控制（預設 `all`＝所有現貨幣；`usdc`＝只看 USDC，即現行行為）。同時修正 unified account 下 spot `hold` 被算兩次的問題，讓讀值對得上 Hyperliquid 網頁的帳戶總值。

**背景（為什麼）：** 2026-09-22 owner 用約 $699 USDC 買進 0.0082 UBTC 現貨，47 秒後熔斷器讀到 $1,662 → $915（−45%）而 flatten＋halt——basis 只算 spot USDC ＋ perp accountValue，對現貨幣全盲。2026-10-05 手動解除後實測：掛單 18 張、零部位時 spot USDC total 686.48、hold 46.42、perp accountValue ≈ 46.4，basis 讀 732.6；HL 自己的 portfolio accountValue 是 686 ＋ UBTC 市值。unified account（`userAbstraction == "unifiedAccount"`）的 perp 保證金是從 spot `hold` 扣的，`spot.total + accountValue` 把 hold 多算一次。正確式（memory 事故 #6、本次實測）：

```
E = (spot_usdc.total − spot_usdc.hold  if unified else spot_usdc.total)
  + perp.marginSummary.accountValue
  + Σ_{coin ≠ USDC, total > 0} total(coin) × mid(coin/USDC)      # EQUITY_SPOT_BASIS=all 時
```

實測驗證數字（2026-10-05 07:50 UTC，平倉前）：(685.65 − 176.38) + 173.03 + 0.0081968513 × 86244 ≈ 1,389.3，HL portfolio 當時 ≈ 1,390。

**Architecture:** 全部改動集中在 `src/hlvault/gridbot/exchange_utils.py`（新增 `equity_breakdown()` 回傳分桶 dict，`get_full_account_equity()` 改為加總它）、`src/hlvault/gridbot/config.py`（一個新 env）、`src/hlvault/gridbot/live.py`（`--status` 印分桶）。`get_account_equity`（momentum 共用）**一字不動**。live.py 的熔斷邏輯（`check_drawdown`／`rearm_if_recovered`）**不動**，呼叫簽名維持 `get_full_account_equity(info, address)`（`tests/test_gridbot_drawdown_guard.py` 有 16 處用兩參數 lambda monkeypatch，改簽名會全紅）。

**Tech Stack:** Python 3.9 相容（本機 venv 是 3.9；不要用 `X | None` 以外的 3.10 語法，檔頭已有 `from __future__ import annotations`）、hyperliquid-python-sdk `Info`（`user_state`、`spot_user_state`、`spot_meta`、`all_mids`、`post`）、pytest。

**API 事實（2026-10-05 實測，不要再查）：**
- `spot_user_state(addr)["balances"]` 每筆：`{"coin": "UBTC", "token": 197, "total": "0.0081968513", "hold": "0.0"}`；USDC 的 `token` 是 `0`。
- `spot_meta()["universe"]` 每筆：`{"name": "@142", "index": 142, "tokens": [197, 0]}`；`tokens[0]` 是 base token index、`tokens[1]` 是 quote。USDC 對就是 `tokens[1] == 0`。
- `all_mids()` 的現貨 key 是 pair name（`"@142"` → `"86365.5"`），**沒有** `"UBTC"` 或 `"UBTC/USDC"` 這種 key。
- `info.post("/info", {"type": "userAbstraction", "user": addr})` 回傳字串，unified 帳戶是 `"unifiedAccount"`。

---

## Task 1 `@inline`：config 新 env `EQUITY_SPOT_BASIS`

**Files:**
- Modify: `src/hlvault/gridbot/config.py`（在 `DRAWDOWN_CONFIRM_CYCLES` 那行之後加）
- Test: `tests/test_gridbot_config_equity_basis.py`（新檔）

- [ ] **Step 1: 寫失敗測試**

```python
"""EQUITY_SPOT_BASIS env parsing — gridbot circuit-breaker equity basis switch."""
import importlib

from hlvault.gridbot import config as cfg


def test_default_is_all():
    assert cfg.EQUITY_SPOT_BASIS == "all"


def test_env_usdc_is_accepted(monkeypatch):
    monkeypatch.setenv("EQUITY_SPOT_BASIS", " USDC  # comment")
    importlib.reload(cfg)
    try:
        assert cfg.EQUITY_SPOT_BASIS == "usdc"
    finally:
        monkeypatch.delenv("EQUITY_SPOT_BASIS")
        importlib.reload(cfg)


def test_env_invalid_value_raises(monkeypatch):
    monkeypatch.setenv("EQUITY_SPOT_BASIS", "everything")
    try:
        import pytest
        with pytest.raises(ValueError, match="EQUITY_SPOT_BASIS"):
            importlib.reload(cfg)
    finally:
        monkeypatch.delenv("EQUITY_SPOT_BASIS")
        importlib.reload(cfg)
```

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_gridbot_config_equity_basis.py -v`
Expected: `test_default_is_all` FAIL with `AttributeError: ... has no attribute 'EQUITY_SPOT_BASIS'`

- [ ] **Step 3: 實作**

在 `config.py` 的 `DRAWDOWN_CONFIRM_CYCLES = ...` 那行之後加：

```python
# Which spot holdings the circuit-breaker equity basis counts.
#   "all"  (default): USDC + every other spot coin at its coin/USDC mid — the
#          owner trades spot in this wallet (2026-09-22: a $699 USDC->UBTC buy
#          read as a -45% drawdown and tripped a phantom flatten+halt).
#   "usdc": USDC only (the pre-2026-10 behaviour; use when a spot coin has no
#          USDC pair and you accept that buying it reads as a drawdown).
EQUITY_SPOT_BASIS = _env_str("EQUITY_SPOT_BASIS", "all").lower()
if EQUITY_SPOT_BASIS not in ("all", "usdc"):
    raise ValueError(f"EQUITY_SPOT_BASIS must be 'all' or 'usdc', got {EQUITY_SPOT_BASIS!r}")
```

- [ ] **Step 4: 跑測試確認通過**

Run: `.venv/bin/pytest tests/test_gridbot_config_equity_basis.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/gridbot/config.py tests/test_gridbot_config_equity_basis.py
git commit -m "feat(gridbot): EQUITY_SPOT_BASIS env switch (all|usdc) for circuit-breaker equity basis"
```

---

## Task 2 `@inline`：`equity_breakdown()` ＋ 現貨幣計價 ＋ unified hold 修正

**Files:**
- Modify: `src/hlvault/gridbot/exchange_utils.py:74-102`（整個 `get_full_account_equity` 換掉；`get_account_equity` 48-71 行**不動**）
- Test: `tests/test_gridbot_exchange_utils.py`（既有 `_FakeInfoFull` 44-54 行擴充；既有 3 個 `test_full_equity_*` 必須維持通過）

**設計：**

```python
def equity_breakdown(info, address: str, spot_basis: str | None = None) -> dict[str, float]:
    """回傳 {"spot_usdc": float, "spot_hold_adjust": float (<= 0), "spot_coins": float,
    "perp_account_value": float}。spot_basis None → 讀 cfg.EQUITY_SPOT_BASIS。"""

def get_full_account_equity(info, address: str, spot_basis: str | None = None) -> float:
    return sum(equity_breakdown(info, address, spot_basis).values())
```

規則：
1. `spot_usdc` = USDC balance 的 `total`（找不到 USDC 筆 → 0.0）。
2. `spot_hold_adjust`：呼叫 `info.post("/info", {"type": "userAbstraction", "user": address})`；回傳 `== "unifiedAccount"` 時為 `-float(usdc_balance["hold"])`，否則 `0.0`。`hold` 欄位缺 → 0。
3. `perp_account_value` = `user_state(address).get("marginSummary", {}).get("accountValue", 0.0)`（維持既有容錯：缺 marginSummary → 0）。
4. `spot_coins`：`spot_basis == "usdc"` → 0.0 且**不呼叫** `spot_meta`／`all_mids`。`"all"` → 對每筆 `coin != "USDC"` 且 `float(total) > 0` 的 balance：用 `balance["token"]` 在 `spot_meta()["universe"]` 找 `tokens == [token, 0]` 的 pair，取 `all_mids()[pair["name"]]`，累加 `total × mid`。找不到 USDC 對或 mid 缺 → `raise ValueError(f"spot coin {coin} (token {token}) has no USDC pair/mid — cannot value equity")`。**不要默默跳過**：少算會讓 owner 一買幣就幻影熔斷；raise 會被 `check_drawdown` 當 failed read（跳過 cycle、不 flatten、10 次後 halt 不 flatten），這是正確的失敗方向（「讀不到錢 ≠ 錢虧光」）。
5. `spot_meta()` 與 `all_mids()` 各只呼叫一次（且只在有非 USDC 餘額時才呼叫）。
6. `cfg` 用函式內 `from hlvault.gridbot import config as cfg` 延遲匯入（exchange_utils 被 momentum 共用，不要在模組層級 import gridbot config）。

- [ ] **Step 1: 擴充 fake 並寫失敗測試**

把 `_FakeInfoFull` 換成（保留原建構子參數順序，舊測試不用改）：

```python
class _FakeInfoFull:
    def __init__(self, account_value, spot_usdc, hold=0.0, abstraction="none",
                 coins=None, universe=None, mids=None):
        self._av = account_value
        self._spot = spot_usdc
        self._hold = hold
        self._abstraction = abstraction
        self._coins = coins or []          # list of (coin, token, total)
        self._universe = universe or []    # list of (pair_name, base_token, quote_token)
        self._mids = mids or {}
        self.calls = []

    def user_state(self, address):
        return {"marginSummary": {"accountValue": str(self._av)},
                "assetPositions": [], "withdrawable": "0"}

    def spot_user_state(self, address):
        bals = [{"coin": "USDC", "token": 0, "total": str(self._spot), "hold": str(self._hold)}]
        bals += [{"coin": c, "token": t, "total": str(tot), "hold": "0.0"} for c, t, tot in self._coins]
        return {"balances": bals}

    def post(self, path, payload):
        self.calls.append(("post", payload["type"]))
        assert payload == {"type": "userAbstraction", "user": "0xabc"}
        return self._abstraction

    def spot_meta(self):
        self.calls.append(("spot_meta",))
        return {"universe": [{"name": n, "index": i, "tokens": [b, q]}
                             for i, (n, b, q) in enumerate(self._universe)],
                "tokens": []}

    def all_mids(self):
        self.calls.append(("all_mids",))
        return dict(self._mids)
```

新增測試（接在既有 `test_full_equity_tolerates_missing_margin_summary` 之後；`_Empty` 那個測試的 fake 沒有 `post`／`spot_meta`，請給它加 `def post(self, path, payload): return "none"`，其 balances 只有 USDC 所以不會碰 spot_meta）：

```python
def test_full_equity_counts_spot_coins_at_usdc_mid():
    # 2026-09-22 incident shape: owner swapped ~$699 USDC into 0.0082 UBTC.
    # Old basis dropped by the whole purchase; new basis must be flat.
    info = _FakeInfoFull(account_value=0.0, spot_usdc=686.21,
                         coins=[("UBTC", 197, 0.0081968513)],
                         universe=[("@142", 197, 0), ("@234", 197, 360)],
                         mids={"@142": "86244.0", "@234": "86300.0"})
    bd = equity_breakdown(info, "0xabc", spot_basis="all")
    assert abs(bd["spot_coins"] - 0.0081968513 * 86244.0) < 1e-6
    assert abs(get_full_account_equity(info, "0xabc", spot_basis="all")
               - (686.21 + 0.0081968513 * 86244.0)) < 1e-6
    assert info.calls.count(("spot_meta",)) == 1 and info.calls.count(("all_mids",)) == 1


def test_full_equity_usdc_basis_ignores_spot_coins_and_skips_meta_calls():
    info = _FakeInfoFull(account_value=10.0, spot_usdc=100.0,
                         coins=[("UBTC", 197, 1.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "86244.0"})
    assert get_full_account_equity(info, "0xabc", spot_basis="usdc") == 110.0
    assert ("spot_meta",) not in info.calls and ("all_mids",) not in info.calls


def test_full_equity_zero_balance_coins_do_not_trigger_meta_calls():
    info = _FakeInfoFull(account_value=0.0, spot_usdc=50.0,
                         coins=[("USDE", 235, 0.0), ("USDT0", 268, 0.0)])
    assert get_full_account_equity(info, "0xabc", spot_basis="all") == 50.0
    assert ("spot_meta",) not in info.calls


def test_full_equity_raises_when_spot_coin_has_no_usdc_pair():
    import pytest
    info = _FakeInfoFull(account_value=0.0, spot_usdc=50.0,
                         coins=[("XYZ", 999, 3.0)],
                         universe=[("@500", 999, 360)], mids={"@500": "1.0"})
    with pytest.raises(ValueError, match="XYZ"):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_full_equity_unified_account_does_not_double_count_hold():
    # measured 2026-10-05 07:50 UTC before the owner closed manual positions:
    # spot USDC total 685.65 (hold 176.38), perp accountValue 173.03, UBTC 0.0081968513 @ 86244
    # HL portfolio accountValue at that moment ~1,390
    info = _FakeInfoFull(account_value=173.03, spot_usdc=685.65, hold=176.38,
                         abstraction="unifiedAccount",
                         coins=[("UBTC", 197, 0.0081968513)],
                         universe=[("@142", 197, 0)], mids={"@142": "86244.0"})
    bd = equity_breakdown(info, "0xabc", spot_basis="all")
    assert abs(bd["spot_hold_adjust"] + 176.38) < 1e-9
    total = get_full_account_equity(info, "0xabc", spot_basis="all")
    assert abs(total - ((685.65 - 176.38) + 173.03 + 0.0081968513 * 86244.0)) < 1e-6
    assert 1385.0 < total < 1395.0


def test_full_equity_non_unified_account_keeps_hold():
    # non-unified: spot hold is just resting spot orders — still the owner's money
    info = _FakeInfoFull(account_value=20.0, spot_usdc=100.0, hold=30.0, abstraction="none")
    bd = equity_breakdown(info, "0xabc", spot_basis="all")
    assert bd["spot_hold_adjust"] == 0.0
    assert get_full_account_equity(info, "0xabc", spot_basis="all") == 120.0


def test_full_equity_default_basis_comes_from_config(monkeypatch):
    from hlvault.gridbot import config as cfg
    info = _FakeInfoFull(account_value=0.0, spot_usdc=100.0,
                         coins=[("UBTC", 197, 1.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "5.0"})
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "usdc")
    assert get_full_account_equity(info, "0xabc") == 100.0
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "all")
    assert get_full_account_equity(info, "0xabc") == 105.0
```

檔頭 import 改成 `from hlvault.gridbot.exchange_utils import (equity_breakdown, get_account_equity, get_full_account_equity, round_price, round_size, ...)`（保留原本其他匯入）。

- [ ] **Step 2: 跑測試確認失敗**

Run: `.venv/bin/pytest tests/test_gridbot_exchange_utils.py -v`
Expected: ImportError `cannot import name 'equity_breakdown'`

- [ ] **Step 3: 實作**

把 `exchange_utils.py` 74-102 行整段換成：

```python
def _usdc_pair_names(spot_meta: dict) -> dict[int, str]:
    """base token index -> spot pair name quoted in USDC (token 0), e.g. 197 -> "@142"."""
    out: dict[int, str] = {}
    for pair in spot_meta.get("universe", []):
        toks = pair.get("tokens") or []
        if len(toks) == 2 and int(toks[1]) == 0 and int(toks[0]) not in out:
            out[int(toks[0])] = pair["name"]
    return out


def equity_breakdown(info, address: str, spot_basis: str | None = None) -> dict[str, float]:
    """The whole wallet, every bucket counted exactly once, as separate buckets
    so --status can be checked against the exchange UI bucket by bucket:

      spot_usdc          spot USDC balance `total`
      spot_hold_adjust   minus USDC `hold` on a unified account (that hold IS the
                         perp margin already inside accountValue — counting both
                         double-counts it; 2026-10-05 measured: hold 176.38 vs
                         accountValue 173.03 with manual positions open). 0 on a
                         non-unified account, where hold is resting spot orders.
      spot_coins         every other spot coin with total > 0 at its coin/USDC mid
                         (EQUITY_SPOT_BASIS=all) or 0 (EQUITY_SPOT_BASIS=usdc).
                         2026-09-22 incident: a $699 USDC->UBTC spot buy read as a
                         -45% drawdown through the old USDC-only basis and tripped
                         a phantom flatten+halt. A coin with no USDC pair raises —
                         undercounting is the dangerous direction (phantom halt),
                         a raised read is handled as a failed read upstream
                         (skip cycle, never flatten).
      perp_account_value perp marginSummary.accountValue (2026-07-21 incident:
                         cash parked as perp free margin must count).

    get_account_equity above is momentum's basis for ITS wallet shape — untouched."""
    if spot_basis is None:
        from hlvault.gridbot import config as cfg
        spot_basis = cfg.EQUITY_SPOT_BASIS
    if spot_basis not in ("all", "usdc"):
        raise ValueError(f"spot_basis must be 'all' or 'usdc', got {spot_basis!r}")

    perp = info.user_state(address)
    account_value = float(perp.get("marginSummary", {}).get("accountValue", 0.0))

    spot = info.spot_user_state(address)
    balances = spot.get("balances", [])
    spot_usdc = 0.0
    usdc_hold = 0.0
    for bal in balances:
        if bal.get("coin") == "USDC":
            spot_usdc = float(bal.get("total", 0.0))
            usdc_hold = float(bal.get("hold", 0.0))
            break

    hold_adjust = 0.0
    abstraction = info.post("/info", {"type": "userAbstraction", "user": address})
    if abstraction == "unifiedAccount":
        hold_adjust = -usdc_hold

    spot_coins = 0.0
    if spot_basis == "all":
        held = [(b.get("coin"), int(b.get("token", -1)), float(b.get("total", 0.0)))
                for b in balances if b.get("coin") != "USDC" and float(b.get("total", 0.0)) > 0.0]
        if held:
            pairs = _usdc_pair_names(info.spot_meta())
            mids = info.all_mids()
            for coin, token, total in held:
                pair = pairs.get(token)
                mid = mids.get(pair) if pair is not None else None
                if mid is None:
                    raise ValueError(
                        f"spot coin {coin} (token {token}) has no USDC pair/mid — cannot value equity"
                    )
                spot_coins += total * float(mid)

    return {
        "spot_usdc": spot_usdc,
        "spot_hold_adjust": hold_adjust,
        "spot_coins": spot_coins,
        "perp_account_value": account_value,
    }


def get_full_account_equity(info, address: str, spot_basis: str | None = None) -> float:
    """Sum of equity_breakdown() — the gridbot circuit breaker's one equity basis
    (CLAUDE.md #1: current and peak always from this same function)."""
    return sum(equity_breakdown(info, address, spot_basis).values())
```

- [ ] **Step 4: 跑測試確認通過（含既有測試）**

Run: `.venv/bin/pytest tests/test_gridbot_exchange_utils.py tests/test_gridbot_drawdown_guard.py tests/test_gridbot_config_equity_basis.py -v`
Expected: 全部 passed（既有 3 個 `test_full_equity_*`、`test_full_equity_tolerates_missing_margin_summary`、drawdown_guard 全部維持綠）。`_FakeInfoFull(account_value=46.63, spot_usdc=1048.04)` 預設 `abstraction="none"`、無 coins，所以 1094.67 那題不變。

- [ ] **Step 5: 跑 momentum 相關測試確認共用函式沒被波及**

Run: `.venv/bin/pytest tests/ -q -k "momentum or gridbot" 2>&1 | tail -3`
Expected: passed，0 failed

- [ ] **Step 6: Commit**

```bash
git add src/hlvault/gridbot/exchange_utils.py tests/test_gridbot_exchange_utils.py
git commit -m "fix(gridbot): equity basis counts spot coins at USDC mid and stops double-counting unified-account hold

2026-09-22: a \$699 USDC->UBTC spot buy read as a -45% drawdown through the
USDC-only basis and tripped a phantom flatten+halt. EQUITY_SPOT_BASIS=all
(default) values every spot coin at its coin/USDC mid; =usdc keeps the old
behaviour. On a unified account spot USDC hold is the perp margin already in
accountValue, so it is subtracted (measured 2026-10-05 against HL portfolio)."
```

---

## Task 3 `@sdd`：`hl-gridbot --status` 印分桶

**Files:**
- Modify: `src/hlvault/gridbot/live.py:450-456`（`main()` 的 `if args.status:` 區塊）
- Modify: `src/hlvault/gridbot/live.py:22-24`（import 行加 `equity_breakdown`）

- [ ] **Step 1: 改 import**

把 `from hlvault.gridbot.exchange_utils import (` 那段加上 `equity_breakdown,`（保持字母序，放在 `MAX_LEVERAGE_FALLBACK` 之後、`get_full_account_equity` 之前）。

- [ ] **Step 2: 改 status 區塊**

把

```python
    if args.status:
        engine.bootstrap_if_needed()
        equity = get_full_account_equity(engine.info, cfg.WALLET_ADDRESS)
        print(f"equity: ${equity:,.2f}  halted={engine.state.get('halted')}")
```

換成

```python
    if args.status:
        engine.bootstrap_if_needed()
        buckets = equity_breakdown(engine.info, cfg.WALLET_ADDRESS)
        equity = sum(buckets.values())
        print(f"equity: ${equity:,.2f}  halted={engine.state.get('halted')}  "
              f"peak=${engine.state.get('peak_equity', 0.0):,.2f}  "
              f"spot_basis={cfg.EQUITY_SPOT_BASIS}")
        for name, val in buckets.items():
            print(f"  {name:<20} ${val:,.2f}")
```

- [ ] **Step 3: 驗收**

Run: `.venv/bin/python -c "import ast,sys; ast.parse(open('src/hlvault/gridbot/live.py').read()); print('syntax ok')" && grep -c "equity_breakdown" src/hlvault/gridbot/live.py`
Expected: `syntax ok` 然後 `2`（import 一次、呼叫一次）

Run: `.venv/bin/pytest tests/test_gridbot_drawdown_guard.py tests/test_gridbot_live_reconcile.py -q 2>&1 | tail -2`
Expected: passed，0 failed

- [ ] **Step 4: Commit**

```bash
git add src/hlvault/gridbot/live.py
git commit -m "feat(gridbot): --status prints equity buckets for UI reconciliation"
```

---

## 主線程驗收（builder 不做）

1. `.venv/bin/pytest tests/ -q` 全綠。
2. 本機 `.venv/bin/hl-gridbot --status`（唯讀，不下單）：`spot_usdc + spot_coins + spot_hold_adjust + perp_account_value` 要與 HL `portfolio` 端點的最新 `accountValueHistory` 值相差 < 1%。
3. 派 `reviewer` 對照本 plan 審 `git diff c00cad5..HEAD -- src/hlvault/gridbot tests/`。
4. **部署碰實盤（紅線）**：server 追 `main`，需 merge → `git pull` → `sudo systemctl restart hl-gridbot`。重啟時 `rearm_if_recovered` 不會重置 peak，而新 basis 會多算 UBTC（約 +$707），peak 會自然上修、不會觸發熔斷。**執行前問 owner。**

## 完成狀態（2026-10-05 09:11 UTC 部署上線）

- Task 1–7 全部完成，8 個 commit cherry-pick 到 `main`（`036a8e8`…`0d1547c`）並 push；server `~/vault` 已 pull 到 `0d1547c`。
- 本機 `tests/` 505 passed（分支）／418 passed（main，不含 sweep-n 測試）。兩輪 opus 審查無 Critical。
- 部署實作：`.env.gridbot` 加 `TELEGRAM_BOT_TOKEN`／`TELEGRAM_CHAT_ID`（自 `.env.cta` 複製，備份在 `~/backups/`）；state 檔 `peak_equity` 736.84 → 1,391.60（新 basis 當下值，備份在 `~/backups/`）；`systemctl restart hl-gridbot`；重啟後 `--status` equity 1,390.94 ＝ portfolio_value，journald 無 HALTED、無 Telegram warning；測試告警 `send_alert` 回 True。
- 告警前綴 `[hl-gridbot]`。
- 下面的「進度與待決事項」是部署前的紀錄，保留供追溯。

## 進度與待決事項（2026-10-05 部署前）

- Task 1／2／3 已完成並 commit（0d435d5、cf0fa12、6517839、0bb2ca3，在 `liquidity-sweep-n` 分支上，**尚未部署**）。全套測試 487 passed。
- 主線程驗收：本機 `hl-gridbot --status` 讀 1,394.94 vs HL `portfolio` 最新點 1,394.85（差 0.01%）。
- reviewer（opus）Critical：`spot_hold_adjust` 扣掉整筆 USDC `hold`，但現貨限價買單凍結的 USDC 也在 `hold` 裡、不在 perp accountValue → owner 掛一張 $700 UBTC 限價買單 3 分鐘就會幻影熔斷。**未實測**（需真的掛單），但與 HL 現貨掛單行為一致，視為成立。HL 文件沒有定義 `hold`。
- reviewer Warning：HIP-3 builder dex 保證金也從 hold 扣但沒加回；staked HYPE／vault equity 不在 basis；無 USDC 對的粉塵幣會讓網格 10 分鐘後停機。
- 實測新事實：`portfolio` 端點最後一點是**查詢當下即時算的**（age 0.2 s、值隨 UBTC mid 變動），且等於 UI 顯示的帳戶總值（含現貨幣、hold 正確處理；依 wallet-analysis 對帳經驗也含 staked HYPE 與 vault）。

**owner 2026-10-05 裁決：採 (C)**。Task 4 實作；Task 5 加 Telegram 告警（owner 同日要求：熔斷後要持續發 TG 直到他處理）。

**原三個方案（留作紀錄）：**
- (A) 拿掉 `spot_hold_adjust`：回到 spot.total ＋ accountValue ＋ 現貨幣。無少算風險，但 unified 下掛單／部位保證金會多算一次（上限≈hold，10/05 實測 46～176），峰值被抬高後平倉時會出現 hold/峰值 的幻影回撤（10/05 A 點約 11%）。
- (B) hold 只扣 perp 部分：hold − Σ(現貨 USDC 計價買單 sz×limitPx，從 `openOrders` 取)。多一個呼叫；HIP-3 與 staking 仍不在 basis。
- (C) **建議**：`EQUITY_SPOT_BASIS=all` 改用 HL `portfolio` 最新 `accountValueHistory` 點（HL 自己的全錢包總值，與 UI 完全一致、含所有桶）；`usdc` 維持 spot USDC ＋ accountValue。`--status` 同時印分桶與 portfolio 值，兩者差 >2% 時 log warning。代價：桶的組成是 HL 的黑盒，但正是 owner 對帳用的那個數字（工程原則 #1 同源）。

---

## Task 4 `@inline`：`all` basis 改用 HL `portfolio` 即時帳戶總值

**動機：** HL `portfolio` 端點最後一點是查詢當下算的（實測 age 0.2 s、值隨 mid 變動），就是 owner 在網頁看到的帳戶總值，含現貨幣、unified hold、staking、vault。改用它後 basis 與 UI 同源（工程原則 #1），reviewer 的 hold Critical 與 HIP-3／staking Warning 一併消失。`usdc` 模式維持 2026-07-25 的舊算法（spot USDC total ＋ perp accountValue）。`equity_breakdown` 降級為 `--status` 的對帳資訊，不再定義權益。

**API 事實（2026-10-05 實測）：** `info.post("/info", {"type": "portfolio", "user": addr})` 回傳 list of pairs：`[["day", {"accountValueHistory": [[ts_ms, "1393.66"], ...], "pnlHistory": [...], "vlm": "..."}], ["week", {...}], ["month", {...}], ["allTime", {...}], ["perpDay", ...], ...]`。`dict(resp)["day"]["accountValueHistory"][-1]` 的 ts 與查詢時刻差 <1 s。

**Files:**
- Modify: `src/hlvault/gridbot/config.py`（`EQUITY_SPOT_BASIS` 之後加 `PORTFOLIO_MAX_AGE_SECONDS`）
- Modify: `src/hlvault/gridbot/exchange_utils.py`（`_usdc_pair_names` 保留；`equity_breakdown` 與 `get_full_account_equity` 重寫；新增 `get_portfolio_account_value`）
- Modify: `src/hlvault/gridbot/live.py` `main()` 的 `--status` 區塊
- Test: `tests/test_gridbot_exchange_utils.py`（Task 2 加的 7 個 `test_full_equity_*` 測試**全部換掉**為下列測試；Task 2 之前就存在的 `test_full_equity_is_spot_plus_perp_account_value`、`test_full_equity_counts_free_margin_the_old_basis_missed`、`test_full_equity_tolerates_missing_margin_summary` 改成呼叫時傳 `spot_basis="usdc"`，其餘不動）

- [ ] **Step 1: config**

在 `EQUITY_SPOT_BASIS` 的 raise 之後加：

```python
# EQUITY_SPOT_BASIS=all reads HL's own whole-wallet account value from the
# `portfolio` endpoint (the number the web UI shows; last point is computed at
# query time, measured age 0.2s on 2026-10-05). A point older than this is a
# failed read (skip cycle, never flatten), not a drawdown.
PORTFOLIO_MAX_AGE_SECONDS = _env_float("PORTFOLIO_MAX_AGE_SECONDS", "300")
```

- [ ] **Step 2: 寫測試（先紅）**

`_FakeInfoFull` 加 `portfolio=None` 參數與 `post` 分支（把 Task 2 的 `post` 換成這個）：

```python
    def __init__(self, account_value, spot_usdc, hold=0.0, abstraction="none",
                 coins=None, universe=None, mids=None, portfolio=None):
        ...（既有欄位照舊）
        self._portfolio = portfolio  # list of (ts_ms, value) or None

    def post(self, path, payload):
        self.calls.append(("post", payload["type"]))
        assert payload["user"] == "0xabc"
        if payload["type"] == "userAbstraction":
            return self._abstraction
        if payload["type"] == "portfolio":
            if self._portfolio is None:
                raise RuntimeError("portfolio endpoint down")
            hist = [[ts, str(v)] for ts, v in self._portfolio]
            return [["day", {"accountValueHistory": hist, "pnlHistory": [], "vlm": "0"}],
                    ["week", {"accountValueHistory": hist, "pnlHistory": [], "vlm": "0"}]]
        raise AssertionError(payload)
```

新測試（取代 Task 2 的 7 個）：

```python
import time


def _now_ms():
    return int(time.time() * 1000)


def test_all_basis_returns_portfolio_latest_point():
    # 2026-10-05: HL portfolio 1393.66 = USDC 686.48 + UBTC 708.46 - hold already handled by HL
    info = _FakeInfoFull(account_value=46.42, spot_usdc=686.48, hold=46.42,
                         portfolio=[(_now_ms() - 3_600_000, 1356.36), (_now_ms(), 1393.66)])
    assert get_full_account_equity(info, "0xabc", spot_basis="all") == 1393.66
    assert ("spot_meta",) not in info.calls


def test_all_basis_stale_point_raises(monkeypatch):
    from hlvault.gridbot import config as cfg
    monkeypatch.setattr(cfg, "PORTFOLIO_MAX_AGE_SECONDS", 300)
    info = _FakeInfoFull(account_value=0.0, spot_usdc=1.0,
                         portfolio=[(_now_ms() - 10 * 60_000, 1393.66)])
    import pytest
    with pytest.raises(ValueError, match="stale"):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_all_basis_empty_history_raises():
    import pytest
    info = _FakeInfoFull(account_value=0.0, spot_usdc=1.0, portfolio=[])
    with pytest.raises(ValueError, match="portfolio"):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_all_basis_endpoint_error_propagates():
    import pytest
    info = _FakeInfoFull(account_value=0.0, spot_usdc=1.0, portfolio=None)
    with pytest.raises(RuntimeError):
        get_full_account_equity(info, "0xabc", spot_basis="all")


def test_usdc_basis_is_spot_usdc_total_plus_account_value_unchanged():
    # pre-2026-10 behaviour, byte-for-byte: no hold adjustment, no spot coins, no portfolio call
    info = _FakeInfoFull(account_value=46.42, spot_usdc=686.48, hold=46.42,
                         abstraction="unifiedAccount", coins=[("UBTC", 197, 1.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "86000"},
                         portfolio=[(_now_ms(), 9999.0)])
    assert abs(get_full_account_equity(info, "0xabc", spot_basis="usdc") - 732.90) < 1e-9
    assert ("post", "portfolio") not in info.calls and ("spot_meta",) not in info.calls


def test_default_basis_comes_from_config(monkeypatch):
    from hlvault.gridbot import config as cfg
    info = _FakeInfoFull(account_value=10.0, spot_usdc=100.0, portfolio=[(_now_ms(), 555.0)])
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "usdc")
    assert get_full_account_equity(info, "0xabc") == 110.0
    monkeypatch.setattr(cfg, "EQUITY_SPOT_BASIS", "all")
    assert get_full_account_equity(info, "0xabc") == 555.0


def test_breakdown_is_informational_and_never_raises_on_unpriced_coin():
    info = _FakeInfoFull(account_value=46.42, spot_usdc=686.48, hold=46.42,
                         abstraction="unifiedAccount",
                         coins=[("UBTC", 197, 0.0081968513), ("XYZ", 999, 3.0)],
                         universe=[("@142", 197, 0)], mids={"@142": "86244.0"},
                         portfolio=[(_now_ms(), 1393.66)])
    bd = equity_breakdown(info, "0xabc")
    assert bd["spot_usdc_total"] == 686.48
    assert bd["spot_usdc_hold"] == 46.42
    assert abs(bd["spot_coins"] - 0.0081968513 * 86244.0) < 1e-6
    assert bd["perp_account_value"] == 46.42
    assert bd["portfolio_value"] == 1393.66
    assert bd["unpriced_coins"] == ["XYZ"]
    assert bd["abstraction"] == "unifiedAccount"
```

- [ ] **Step 3: 實作**

`exchange_utils.py`：保留 `_usdc_pair_names`；把 `equity_breakdown` 與 `get_full_account_equity` 換成：

```python
def get_portfolio_account_value(info, address: str) -> tuple[float, int]:
    """HL's own whole-wallet account value (the web UI number) and its
    timestamp (ms), from the `portfolio` endpoint's latest "day" point.
    Measured 2026-10-05: the last point is computed at query time (age 0.2s)
    and moves with spot-coin mids; includes spot coins, perp (all dexes),
    unified-account hold handling, staking and vault equity. Raises ValueError
    if the response has no usable point — the caller treats that as a failed
    read (skip cycle, never flatten)."""
    resp = info.post("/info", {"type": "portfolio", "user": address})
    periods = dict(resp) if isinstance(resp, list) else dict(resp or {})
    hist = (periods.get("day") or {}).get("accountValueHistory") or []
    if not hist:
        raise ValueError("portfolio endpoint returned no accountValueHistory")
    ts, val = hist[-1]
    return float(val), int(ts)


def equity_breakdown(info, address: str) -> dict:
    """Informational buckets for --status so the owner can reconcile against the
    exchange UI. Never raises on an unpriceable coin (lists it instead). NOT the
    circuit-breaker basis — see get_full_account_equity."""
    perp = info.user_state(address)
    account_value = float(perp.get("marginSummary", {}).get("accountValue", 0.0))
    spot = info.spot_user_state(address)
    balances = spot.get("balances", [])
    spot_usdc = 0.0
    usdc_hold = 0.0
    for bal in balances:
        if bal.get("coin") == "USDC":
            spot_usdc = float(bal.get("total", 0.0))
            usdc_hold = float(bal.get("hold", 0.0))
            break
    abstraction = info.post("/info", {"type": "userAbstraction", "user": address})
    held = [(b.get("coin"), int(b.get("token", -1)), float(b.get("total", 0.0)))
            for b in balances if b.get("coin") != "USDC" and float(b.get("total", 0.0)) > 0.0]
    spot_coins = 0.0
    unpriced: list[str] = []
    if held:
        pairs = _usdc_pair_names(info.spot_meta())
        mids = info.all_mids()
        for coin, token, total in held:
            pair = pairs.get(token)
            mid = mids.get(pair) if pair is not None else None
            if mid is None:
                unpriced.append(coin)
            else:
                spot_coins += total * float(mid)
    try:
        portfolio_value, portfolio_ts = get_portfolio_account_value(info, address)
    except Exception as e:  # informational only — show the failure, don't hide the rest
        portfolio_value, portfolio_ts = float("nan"), 0
    return {
        "spot_usdc_total": spot_usdc,
        "spot_usdc_hold": usdc_hold,
        "spot_coins": spot_coins,
        "perp_account_value": account_value,
        "portfolio_value": portfolio_value,
        "portfolio_ts_ms": portfolio_ts,
        "unpriced_coins": unpriced,
        "abstraction": abstraction,
    }


def get_full_account_equity(info, address: str, spot_basis: str | None = None) -> float:
    """The gridbot circuit breaker's ONE equity basis (CLAUDE.md #1: current and
    peak always from this same function).

    EQUITY_SPOT_BASIS=all (default): HL `portfolio` latest account value — the
    web-UI number, every bucket counted once by the exchange itself. 2026-09-22
    incident: a $699 USDC->UBTC spot buy read as a -45% drawdown through the
    USDC-only basis and tripped a phantom flatten+halt. A point older than
    PORTFOLIO_MAX_AGE_SECONDS raises (failed read upstream: skip cycle, never flatten).

    EQUITY_SPOT_BASIS=usdc: spot USDC total + perp accountValue, the 2026-07-25
    basis, unchanged (measured then against the UI with no spot coins held).

    get_account_equity above is momentum's basis for ITS wallet shape — untouched."""
    import time as _time
    from hlvault.gridbot import config as cfg
    if spot_basis is None:
        spot_basis = cfg.EQUITY_SPOT_BASIS
    if spot_basis == "usdc":
        perp = info.user_state(address)
        account_value = float(perp.get("marginSummary", {}).get("accountValue", 0.0))
        spot_usdc = 0.0
        for bal in info.spot_user_state(address).get("balances", []):
            if bal.get("coin") == "USDC":
                spot_usdc = float(bal.get("total", 0.0))
                break
        return spot_usdc + account_value
    if spot_basis != "all":
        raise ValueError(f"spot_basis must be 'all' or 'usdc', got {spot_basis!r}")
    value, ts = get_portfolio_account_value(info, address)
    age_s = _time.time() - ts / 1000.0
    if age_s > cfg.PORTFOLIO_MAX_AGE_SECONDS:
        raise ValueError(f"portfolio account value is stale ({age_s:.0f}s old > {cfg.PORTFOLIO_MAX_AGE_SECONDS:.0f}s)")
    return value
```

`live.py` `--status` 區塊換成：

```python
    if args.status:
        engine.bootstrap_if_needed()
        bd = equity_breakdown(engine.info, cfg.WALLET_ADDRESS)
        try:
            equity = get_full_account_equity(engine.info, cfg.WALLET_ADDRESS)
            eq_str = f"${equity:,.2f}"
        except Exception as e:
            eq_str = f"UNREADABLE ({e})"
        print(f"equity: {eq_str}  basis={cfg.EQUITY_SPOT_BASIS}  halted={engine.state.get('halted')}  "
              f"peak=${engine.state.get('peak_equity', 0.0):,.2f}")
        print(f"  portfolio_value      ${bd['portfolio_value']:,.2f}  (HL UI number, abstraction={bd['abstraction']})")
        print(f"  spot_usdc_total      ${bd['spot_usdc_total']:,.2f}  (hold ${bd['spot_usdc_hold']:,.2f})")
        print(f"  spot_coins           ${bd['spot_coins']:,.2f}" + (f"  unpriced={bd['unpriced_coins']}" if bd['unpriced_coins'] else ""))
        print(f"  perp_account_value   ${bd['perp_account_value']:,.2f}")
        for coin, c in engine.state["coins"].items():
            print(f"  {coin}: anchor={c['anchor']:.6g} step={c['step_pct']*100:.3f}% "
                  f"armed={len(c['armed'])} open_lots={len(c['open_lots'])}")
        return
```

- [ ] **Step 4: 驗收**

Run: `.venv/bin/pytest tests/test_gridbot_exchange_utils.py tests/test_gridbot_drawdown_guard.py tests/test_gridbot_config_equity_basis.py -v -o addopts="" 2>&1 | tail -5`
Expected: 全 passed。
Run: `.venv/bin/pytest tests/ -q -o addopts="" 2>&1 | tail -1` → `N passed`，0 failed。
Run: `git diff cf0fa12 -- src/hlvault/gridbot/exchange_utils.py | grep "^-def\|^-    def"` → 只允許出現 `-def equity_breakdown` 與 `-def get_full_account_equity`（`get_account_equity` 不能出現）。

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/gridbot/config.py src/hlvault/gridbot/exchange_utils.py src/hlvault/gridbot/live.py tests/test_gridbot_exchange_utils.py
git commit -m "fix(gridbot): EQUITY_SPOT_BASIS=all reads HL portfolio account value (the UI number) instead of summing buckets

Owner decision 2026-10-05. Bucket summation needed a unified-account hold
adjustment that would also subtract resting spot-order reservations (phantom
drawdown direction). HL's own portfolio value is computed at query time,
matches the web UI, and already includes spot coins, hold, staking and vaults."
```

---

## Task 5 `@inline`：Telegram 告警（觸發即發、停機期間持續提醒、復盤通知）

**動機：** gridbot 目前沒有任何 Telegram（`.env.gridbot` 無鍵、程式未呼叫 `send_alert`）；9/22 熔斷後 owner 13 天後才發現。owner 要求：熔斷後持續發 TG 直到他處理。

**既有慣例（照抄）：** `src/hlvault/momentum/live.py:70-93`（`send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID, msg)`；`send_alert` 永不 raise）；`src/hlvault/momentum/config.py:84-85` 的 env 命名。`tests/conftest.py` 有 autouse 禁網 fixture，測試裡一律 monkeypatch `live_mod.send_alert`。

**Files:**
- Modify: `src/hlvault/gridbot/config.py`（加 3 個 env）
- Modify: `src/hlvault/gridbot/live.py`（import；`check_drawdown`、`rearm_if_recovered`、`_equity_read_failed`、`_flatten_everything`）
- Test: `tests/test_gridbot_alerts.py`（新檔）

- [ ] **Step 1: config**

```python
# Telegram alerts (same bot/chat convention as carry/momentum/cta). Empty = alerts
# dropped with a warning log; send_alert never raises.
TELEGRAM_BOT_TOKEN = _env_str("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _env_str("TELEGRAM_CHAT_ID", "")
# While halted, repeat the reminder this often until the owner re-arms
# (2026-09-22: a halt went unnoticed for 13 days with log-only alerting).
HALT_ALERT_INTERVAL_MINUTES = _env_float("HALT_ALERT_INTERVAL_MINUTES", "60")
```

- [ ] **Step 2: 寫測試（先紅）** `tests/test_gridbot_alerts.py`

```python
"""gridbot Telegram alerting: trip -> immediate alert; halted -> periodic reminder;
re-arm -> resumed alert. send_alert is always monkeypatched (no network in tests)."""
import json

import pytest

from hlvault.gridbot import config as cfg
from hlvault.gridbot import live as live_mod
from hlvault.gridbot.live import GridBotEngine


@pytest.fixture
def engine(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cfg, "MAX_DRAWDOWN_PCT", 0.20)
    monkeypatch.setattr(cfg, "DRAWDOWN_CONFIRM_CYCLES", 1)
    monkeypatch.setattr(cfg, "MAX_BAD_EQUITY_READS", 2)
    monkeypatch.setattr(cfg, "HALT_ALERT_INTERVAL_MINUTES", 60)
    monkeypatch.setattr(cfg, "TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(cfg, "TELEGRAM_CHAT_ID", "chat")
    sent = []
    monkeypatch.setattr(live_mod, "send_alert", lambda tok, chat, msg: sent.append(msg) or True)
    e = GridBotEngine.__new__(GridBotEngine)
    e.info = object()
    e.exchange = None
    e.live_trading = False
    e._leverage_set = set()
    e.state = {"halted": False, "peak_equity": 1000.0, "last_fill_check_ms": 0,
               "coins": {}, "bad_equity_reads": 0, "drawdown_breach_cycles": 0}
    e.sent = sent
    return e


def test_trip_sends_immediate_alert_with_numbers(engine, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    monkeypatch.setattr(engine, "_flatten_everything", lambda: True)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is True
    assert len(engine.sent) == 1
    assert "30.0%" in engine.sent[0] and "1,000.00" in engine.sent[0] and "700.00" in engine.sent[0]
    assert engine.state["last_halt_alert_ms"] > 0


def test_trip_with_incomplete_flatten_alerts_twice(engine, monkeypatch):
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    monkeypatch.setattr(engine, "_flatten_everything", lambda: False)
    engine.check_drawdown()
    assert any("FLATTEN INCOMPLETE" in m for m in engine.sent)


def test_halted_reminder_repeats_only_after_interval(engine, monkeypatch):
    engine.state["halted"] = True
    engine.state["last_halt_alert_ms"] = 0
    now = [10_000_000_000]
    monkeypatch.setattr(live_mod.time, "time", lambda: now[0] / 1000.0)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine.check_drawdown()
    assert len(engine.sent) == 1 and "HALTED" in engine.sent[0]
    engine.check_drawdown()                       # same minute -> no new alert
    assert len(engine.sent) == 1
    now[0] += 59 * 60_000
    engine.check_drawdown()
    assert len(engine.sent) == 1
    now[0] += 2 * 60_000                          # 61 min after first -> reminder
    engine.check_drawdown()
    assert len(engine.sent) == 2
    assert "restart hl-gridbot" in engine.sent[1]


def test_halted_reminder_survives_equity_read_failure(engine, monkeypatch):
    engine.state["halted"] = True
    engine.state["last_halt_alert_ms"] = 0

    def boom(info, addr):
        raise RuntimeError("api down")
    monkeypatch.setattr(live_mod, "get_full_account_equity", boom)
    engine.check_drawdown()
    assert len(engine.sent) == 1 and "unreadable" in engine.sent[0].lower()


def test_rearm_sends_resumed_alert(engine, monkeypatch):
    engine.state["halted"] = True
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 950.0)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is False
    assert len(engine.sent) == 1 and "RE-ARMED" in engine.sent[0]


def test_rearm_still_breaching_alerts_with_reason(engine, monkeypatch):
    engine.state["halted"] = True
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    engine.rearm_if_recovered()
    assert engine.state["halted"] is True
    assert len(engine.sent) == 1 and "still" in engine.sent[0].lower() and "30.0%" in engine.sent[0]


def test_unreadable_equity_halt_alerts(engine, monkeypatch):
    def boom(info, addr):
        raise RuntimeError("api down")
    monkeypatch.setattr(live_mod, "get_full_account_equity", boom)
    engine.check_drawdown()
    assert engine.sent == []                      # 1/2 failed reads: no alert yet
    engine.check_drawdown()                       # 2/2 -> halt without flatten
    assert engine.state["halted"] is True
    assert any("UNREADABLE" in m for m in engine.sent)


def test_alert_failure_never_blocks_halt(engine, monkeypatch):
    monkeypatch.setattr(live_mod, "send_alert", lambda tok, chat, msg: False)
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)
    monkeypatch.setattr(engine, "_flatten_everything", lambda: True)
    assert engine.check_drawdown() is True
    assert engine.state["halted"] is True
```

- [ ] **Step 3: 實作** `live.py`

import：`from hlvault.notify.telegram import send_alert`（放在 `from hyperliquid.info import Info` 之後）。確認模組已 `import time`（`sync_coin` 用到 `time.time()`，所以已經有）。

在 `check_drawdown` 之前加兩個 method：

```python
    # ---- alerting ---------------------------------------------------
    def _alert(self, msg: str) -> None:
        """Telegram, never raises (notify.telegram contract); prefix identifies the engine."""
        send_alert(cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID, f"[hl-gridbot] {msg}")

    def _halted_reminder(self) -> None:
        """While halted, re-send the reminder every HALT_ALERT_INTERVAL_MINUTES so a
        halt cannot go unnoticed (2026-09-22: 13 days). Includes a fresh equity
        read when possible so the owner can judge whether a restart will re-arm."""
        now_ms = int(time.time() * 1000)
        last = int(self.state.get("last_halt_alert_ms", 0))
        if now_ms - last < cfg.HALT_ALERT_INTERVAL_MINUTES * 60_000:
            return
        peak = self.state.get("peak_equity", 0.0)
        try:
            current = get_full_account_equity(self.info, cfg.WALLET_ADDRESS)
            dd = (peak - current) / peak if peak > 0 else 0.0
            reading = f"now ${current:,.2f}, drawdown {dd:.1%} vs peak ${peak:,.2f}"
        except Exception as e:
            reading = f"equity unreadable ({e!r}), peak ${peak:,.2f}"
        self._alert(f"HALTED — not trading. {reading}. "
                    f"To re-arm: sudo systemctl restart hl-gridbot "
                    f"(resumes only if drawdown < {cfg.MAX_DRAWDOWN_PCT:.0%}; otherwise edit the state file).")
        self.state["last_halt_alert_ms"] = now_ms
        save_state(cfg.STATE_FILE, self.state)
```

`check_drawdown` 改動（其餘行不動）：

```python
        if self.state.get("halted"):
            logger.error("HALTED — restart the service to re-arm (resumes only if drawdown "
                         "has recovered); or clear 'halted' in the state file after review")
            self._halted_reminder()
            return True
        ...
            if breach >= cfg.DRAWDOWN_CONFIRM_CYCLES:
                self._alert(f"DRAWDOWN CIRCUIT BREAKER TRIPPED: {drawdown:.1%} "
                            f"(peak ${peak:,.2f} -> now ${current:,.2f}) — flattening and halting.")
                self.state["halted"] = True
                self.state["last_halt_alert_ms"] = int(time.time() * 1000)
                save_state(cfg.STATE_FILE, self.state)   # persist the halt BEFORE flattening (crash mid-flatten must not lose it)
                if not self._flatten_everything():
                    self._alert("FLATTEN INCOMPLETE — some grid positions/orders may remain open, manual check required.")
```

`_flatten_everything` 末尾改為回傳 bool：

```python
        if any_failed:
            logger.error("SAFETY-CRITICAL: not everything could be flattened — manual check required")
        return not any_failed
```

`_equity_read_failed` 在 `self.state["halted"] = True` 之後加：

```python
            self._alert(f"EQUITY UNREADABLE for {bad_reads} consecutive cycles — halted WITHOUT flatten. "
                        f"Last error: {reason}. Check the API/wallet, then: sudo systemctl restart hl-gridbot")
            self.state["last_halt_alert_ms"] = int(time.time() * 1000)
```

`rearm_if_recovered`：三個「staying halted」分支各加一句 `self._alert(...)`（讀值失敗：`"Restart requested but equity re-check failed ({e!r}) — still halted."`；implausible：`"Restart requested but equity re-check implausible (${current:,.2f}) — still halted."`；still breaching：`f"Restart requested but still breaching: drawdown {drawdown:.1%} >= {cfg.MAX_DRAWDOWN_PCT:.0%} (peak ${peak:,.2f} -> ${current:,.2f}) — still halted. Recover equity or reset peak in the state file."`），並在每個分支 `return` 前把 `self.state["last_halt_alert_ms"] = int(time.time() * 1000)` 寫入並 `save_state`。RE-ARMED 分支加 `self._alert(f"RE-ARMED on restart: drawdown {drawdown:.1%} < {cfg.MAX_DRAWDOWN_PCT:.0%} (peak ${peak:,.2f} -> ${current:,.2f}) — resuming trading.")`。

- [ ] **Step 4: 驗收**

Run: `.venv/bin/pytest tests/test_gridbot_alerts.py -v -o addopts="" 2>&1 | tail -12` → 8 passed。
Run: `.venv/bin/pytest tests/ -q -o addopts="" 2>&1 | tail -1` → 0 failed（既有 `test_gridbot_drawdown_guard.py` 沒 patch `send_alert`，但 token 為空時 `send_alert` 只 log warning、不碰網路，應維持綠；若有紅，優先在該測試檔的 fixture 補 `monkeypatch.setattr(live_mod, "send_alert", lambda *a: True)`，不要改產品碼）。
Run: `grep -c "_alert(" src/hlvault/gridbot/live.py` → ≥ 9。

- [ ] **Step 5: Commit**

```bash
git add src/hlvault/gridbot/config.py src/hlvault/gridbot/live.py tests/test_gridbot_alerts.py
git commit -m "feat(gridbot): Telegram alerts — trip, hourly halted reminder, re-arm outcome

2026-09-22 halt went unnoticed for 13 days (log-only). Same bot/chat env
convention as carry/momentum/cta; send_alert never raises so the safety path
is unaffected by delivery failures."
```

---

## Task 6 `@inline`：`_market_flatten` 永遠回傳 None（既有 bug，Task 5 builder 發現）

**動機：** `live.py` 的 `_market_flatten` 簽名是 `-> bool`，但成功路徑沒有 `return`，永遠回 `None`。後果：`_flatten_everything` 的 `cancelled and flattened` 永遠為假 → lot 永遠不會從 state 刪除、永遠印「FLATTEN FAILED」、Task 5 之後每次熔斷都多發一則「FLATTEN INCOMPLETE」誤報；`sync_coin` 停損分支同樣永遠走「incomplete, will retry」，下一週期若仍低於停損價會再呼叫一次 `market_close`（reduce-only，不會翻倉，但是多餘動作）。**9/22 實證**：journald 寫 `ETH level 122: FLATTEN FAILED (cancel=True flatten=None)`，而交易所 fills 顯示 05:21:36 該 0.0238 ETH 確實已市價平掉——state 殘留 lot 就是這個 bug 造成的。

**SDK 事實：** `ResilientExchange.market_close` 透傳 SDK 回傳值。SDK `Exchange.market_close(coin, sz)`：找到該幣部位 → 回傳 `self.order(...)` 的回應 dict（成功形如 `{"status": "ok", "response": {"type": "order", "data": {"statuses": [{"filled": {...}}]}}}`；單筆被拒形如 `statuses: [{"error": "..."}]`；整體失敗 `{"status": "err", "response": "..."}`）；**找不到部位 → 回傳 `None`**（沒東西可平＝已經是平的）。

**Files:**
- Modify: `src/hlvault/gridbot/live.py` `_market_flatten`（約 448-455 行）
- Test: `tests/test_gridbot_alerts.py`（同檔追加，沿用其 `engine` fixture）

- [ ] **Step 1: 測試（先紅）** 追加到 `tests/test_gridbot_alerts.py`：

```python
class _FakeExchange:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def market_close(self, coin, sz):
        self.calls.append((coin, sz))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_market_flatten_returns_true_on_filled(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": {"totalSz": "0.0238", "avgPx": "2722.9", "oid": 1}}]}}})
    assert engine._market_flatten("ETH", 0.0238) is True
    assert engine.exchange.calls == [("ETH", 0.0238)]


def test_market_flatten_returns_true_when_no_position_left(engine):
    # SDK returns None when the coin has no position: nothing to close == flat
    engine.live_trading = True
    engine.exchange = _FakeExchange(None)
    assert engine._market_flatten("ETH", 0.0238) is True


def test_market_flatten_returns_false_on_rejected_status(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"error": "Insufficient margin"}]}}})
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_returns_false_on_err_status(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "err", "response": "rate limited"})
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_returns_false_on_exception(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange(RuntimeError("connection reset"))
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_dry_run_returns_true_without_calling_exchange(engine):
    engine.live_trading = False
    engine.exchange = _FakeExchange(RuntimeError("must not be called"))
    assert engine._market_flatten("ETH", 0.0238) is True
    assert engine.exchange.calls == []


def test_flatten_everything_drops_lot_only_when_both_cancel_and_flatten_confirmed(engine, monkeypatch):
    engine.state["coins"] = {"ETH": {"armed": {}, "open_lots": {
        "122": {"entry_price": 2749.6, "size": 0.0238, "tp_price": 2761.7, "tp_oid": 1}},
        "stopped_until_ms": None}}
    monkeypatch.setattr(engine, "_cancel", lambda coin, oid: True)
    monkeypatch.setattr(engine, "_market_flatten", lambda coin, size: True)
    assert engine._flatten_everything() is True
    assert engine.state["coins"]["ETH"]["open_lots"] == {}
    engine.state["coins"]["ETH"]["open_lots"]["122"] = {"entry_price": 2749.6, "size": 0.0238, "tp_price": 2761.7, "tp_oid": 1}
    monkeypatch.setattr(engine, "_market_flatten", lambda coin, size: False)
    assert engine._flatten_everything() is False
    assert "122" in engine.state["coins"]["ETH"]["open_lots"]
```

- [ ] **Step 2: 實作** 把 `_market_flatten` 換成：

```python
    def _market_flatten(self, coin: str, size: float) -> bool:
        """True only when the exchange confirmed the close (or reports no position
        left to close — SDK market_close returns None then). Pre-2026-10 this never
        returned True: 2026-09-22 the ETH lot WAS closed on the exchange but state
        logged 'FLATTEN FAILED (flatten=None)' and kept the lot forever."""
        if not self.live_trading:
            logger.info(f"[DRY RUN] flatten {coin} size={size}")
            return True
        try:
            result = self.exchange.market_close(coin, size)
        except Exception as e:
            logger.error(f"{coin}: SAFETY-CRITICAL flatten failed, manual intervention needed: {e}")
            return False
        if result is None:
            logger.warning(f"{coin}: market_close found no position to close — treating as flat")
            return True
        if result.get("status") != "ok":
            logger.error(f"{coin}: SAFETY-CRITICAL flatten rejected: {result}")
            return False
        statuses = (result.get("response", {}).get("data", {}) or {}).get("statuses", [])
        errors = [s["error"] for s in statuses if isinstance(s, dict) and "error" in s]
        if errors:
            logger.error(f"{coin}: SAFETY-CRITICAL flatten rejected: {errors}")
            return False
        return True
```

- [ ] **Step 3: 驗收**

Run: `.venv/bin/pytest tests/test_gridbot_alerts.py -v -o addopts="" 2>&1 | tail -18` → 15 passed。
Run: `.venv/bin/pytest tests/ -q -o addopts="" 2>&1 | tail -1` → 0 failed。

- [ ] **Step 4: Commit**

```bash
git add src/hlvault/gridbot/live.py tests/test_gridbot_alerts.py
git commit -m "fix(gridbot): _market_flatten reports the exchange outcome instead of always None

Found while wiring alerts: the success path never returned, so every flatten
was logged as FAILED and the lot stayed in state (2026-09-22: ETH lot 122 was
closed on-exchange at 05:21:36 but state kept it). None from market_close
means no position left, which is flat."
```

---

## Task 7 `@inline`：reviewer 二審 Warning 修正（部分成交、告警順序）

**動機（reviewer 2026-10-05 二審）：**
- W1：`_market_flatten` 只看 `error`。SDK `market_close` 是 5% 滑價的 IOC 限價單，薄盤時可能只成交一部分、剩餘量自動取消，回應仍是 `{"filled": {"totalSz": <小於要求量>}}` → 目前回 True → `_flatten_everything` 刪 lot、停損分支清 `open_lots` 進 cooldown，交易所殘留部位無人追蹤（工程原則 #3）。
- W2：`check_drawdown` 熔斷分支把 `_alert` 排在 `halted=True`／`save_state`／flatten 之前；`send_alert` 最壞 10s×3＋backoff ≈ 33 秒，Telegram 卡住會拖慢平倉、且期間 halt 尚未落盤。

**Files:**
- Modify: `src/hlvault/gridbot/live.py`（`_market_flatten` 末段；`check_drawdown` 熔斷分支的順序）
- Test: `tests/test_gridbot_alerts.py`（追加 2 個測試）

- [ ] **Step 1: 測試（先紅）** 追加：

```python
def test_market_flatten_returns_false_on_partial_fill(engine):
    # IOC with 5% slippage can fill only part of the size in a thin book; the rest is
    # cancelled by the exchange. That is NOT flat — the lot must stay tracked.
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": {"totalSz": "0.0100", "avgPx": "2722.9", "oid": 1}}]}}})
    assert engine._market_flatten("ETH", 0.0238) is False


def test_market_flatten_accepts_fill_within_size_rounding(engine):
    engine.live_trading = True
    engine.exchange = _FakeExchange({"status": "ok", "response": {"type": "order", "data": {
        "statuses": [{"filled": {"totalSz": "0.02379", "avgPx": "2722.9", "oid": 1}}]}}})
    assert engine._market_flatten("ETH", 0.0238) is True


def test_trip_persists_halt_to_disk_before_flatten_and_alerts_after(engine, monkeypatch):
    import json as _json
    order = []
    monkeypatch.setattr(live_mod, "get_full_account_equity", lambda info, addr: 700.0)

    def fake_flatten():
        on_disk = _json.loads(cfg.STATE_FILE.read_text())
        order.append(("flatten", on_disk.get("halted"), len(engine.sent)))
        return True
    monkeypatch.setattr(engine, "_flatten_everything", fake_flatten)
    engine.check_drawdown()
    # flatten ran with halted already persisted and before any Telegram round-trip
    assert order == [("flatten", True, 0)]
    assert len(engine.sent) == 1 and "TRIPPED" in engine.sent[0]
```

- [ ] **Step 2: 實作**

`_market_flatten` 末段（`errors` 檢查之後、`return True` 之前）加部分成交檢查：

```python
        filled = sum(float(s["filled"].get("totalSz", 0.0)) for s in statuses
                     if isinstance(s, dict) and "filled" in s)
        if filled + 1e-9 < size * 0.995:   # IOC partial fill: remainder was cancelled by the exchange
            logger.error(f"{coin}: SAFETY-CRITICAL flatten PARTIAL: filled {filled} of {size} — position still open")
            return False
        return True
```

`check_drawdown` 熔斷分支改成這個順序（告警移到 flatten 之後；其餘不變）：

```python
            if breach >= cfg.DRAWDOWN_CONFIRM_CYCLES:
                self.state["halted"] = True
                self.state["last_halt_alert_ms"] = int(time.time() * 1000)
                save_state(cfg.STATE_FILE, self.state)   # persist the halt BEFORE flattening
                flattened = self._flatten_everything()
                self._alert(f"DRAWDOWN CIRCUIT BREAKER TRIPPED: {drawdown:.1%} "
                            f"(peak ${peak:,.2f} -> now ${current:,.2f}) — flattened and halted.")
                if not flattened:
                    self._alert("FLATTEN INCOMPLETE — some grid positions/orders may remain open, manual check required.")
```

- [ ] **Step 3: 驗收**

Run: `.venv/bin/pytest tests/test_gridbot_alerts.py -v -o addopts="" 2>&1 | tail -22` → 18 passed。
Run: `.venv/bin/pytest tests/ -q -o addopts="" 2>&1 | tail -1` → 0 failed。

- [ ] **Step 4: Commit**

```bash
git add src/hlvault/gridbot/live.py tests/test_gridbot_alerts.py
git commit -m "fix(gridbot): partial IOC fill is not flat; alert after flatten so Telegram can never delay it"
```

**未實作、刻意略過：** 方案 (C) 提到的「分桶與 portfolio 差 >2% log warning」——`--status` 已並列印出兩者，owner 目視即可，不另加邏輯。

**部署步驟（碰實盤，逐步問 owner）：**
1. `.env.gridbot` 加 `TELEGRAM_BOT_TOKEN`／`TELEGRAM_CHAT_ID`（同台 `.env.cta` 已有，`grep ^TELEGRAM_ .env.cta >> .env.gridbot`，不印內容）。
2. 把 7 個 gridbot commit 帶到 `main`（cherry-pick 或 merge），push；server `git pull`。
3. **重設 state 檔 `peak_equity` 為當下 `portfolio` 值**（reviewer W3：舊 basis 的峰值不可直接與新 basis 比；舊峰值 732 含 hold 重複計算）。備份 state 檔後改。
4. `sudo systemctl restart hl-gridbot`；等兩週期看 journald 無 HALTED、`hl-gridbot --status` 的 equity 與 portfolio_value 一致、TG 收到（可暫時用 `--once`？否——改為人工觸發：不做，只確認 log 有 `Telegram` 相關 warning 為零）。

**部署前置（owner 動手或授權）：** `.env.gridbot` 加 `TELEGRAM_BOT_TOKEN`／`TELEGRAM_CHAT_ID`（同台 `.env.cta` 已有這兩個鍵，可 `grep ^TELEGRAM_ .env.cta >> .env.gridbot`，不印出內容）。

## 不在範圍

- `get_account_equity`（momentum／carry 共用）不動。
- `check_drawdown`／`rearm_if_recovered` 邏輯不動。
- 非 USDC 計價的現貨對（如 UBTC/USDH）不用來估值。
