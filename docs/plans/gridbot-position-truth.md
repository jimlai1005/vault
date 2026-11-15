# gridbot：熔斷出清以交易所部位為準（position truth）

狀態：**owner 已確認（2026-11-14），派工中**。D1–D3 均採建議案。進度見文末「執行紀錄」。
範圍：`src/hlvault/gridbot/`、`tests/test_gridbot_*.py`、`reports/gridbot-design.md`。不動 carry／momentum／cta。
部署：改完不自動上線；上線步驟見 T6，restart 前必問 owner。

## 1. 事故事實（2026-11-05，線上 journal＋交易所成交對帳）

- 15:26:28／15:27:28／15:28:28 UTC 連續三個 cycle 回撤 20.6%／20.8%／20.1%（peak $1,408.80）→ 熔斷**有在 20% 觸發**。
- 15:28:35–15:29:07 flatten 送出 22 筆市價平倉（HYPE 8、BTC 8、ETH 6），全部成交。
- 但 flatten 只平 `state.open_lots` 記得的 lot。交易所上另有引擎沒記到的部位：
  BTC 0.00962、ETH 0.0972、HYPE 7.43（當時名目約 $1,523）。這些沒被平、沒有 TP、沒有停損。
- halt 之後引擎每分鐘只印 HALTED，不再看部位。這三筆隨市場再跌，總值 $1,126 → $836（回撤 40.7%）。
- 2026-11-14 03:55 UTC owner 指示下已手動市價平倉（BTC @66,960、ETH @1,890.3、HYPE @67.599），
  `ALLOCATED_CAPITAL` 1300→800、state 重設、服務重啟。**線上程式仍是舊版（0d1547c），以下漏洞都還在。**

## 2. 根因（程式位置以 `src/hlvault/gridbot/live.py` 目前行號）

| # | 漏洞 | 位置 | 機制 |
|---|---|---|---|
| R1 | flatten 只平 state 記得的 | `_flatten_everything` L253–276 | 迴圈跑 `c["armed"]`／`c["open_lots"]`，從不讀交易所 szi；平完也不驗證 |
| R2 | 撤單撞上成交 → lot 被遺忘（約 14 筆，主因） | `sync_coin` L367–369、`_cancel` L439–448 | 重新置中時 `pop` 後 `_cancel`；單已成交時 HL 回 status ok＋statuses 內含 error，`_cancel` 不解析回應，一律當成功 |
| R3 | 成交查詢視窗錯位（9 筆） | `_on_buy_filled` L391–395 | 用 `last_fill_check_ms`（上一 cycle 結束）當起點查 fills，找不到就「treating as cancelled」並丟掉 armed 紀錄 |
| R4 | 部分成交只記第一筆（6 筆） | `_on_buy_filled` L392 | `next(...)` 只取第一筆 fill 的 size 掛 TP |
| R5 | 名目上限與停損對未追蹤部位全盲 | `sync_coin` L321–323、L365、L375 | 都從 `open_lots` 加總 |
| R6 | halt 之後沒有人再看部位 | `check_drawdown` L136–140 | halted 直接 return |

10-05 → 11-05 對帳：交易所買單成交 vs journal 記到：HYPE 213/200、BTC 130/122、ETH 54/52，漏約 6%，全在買側。

## 3. 設計

單一原則：**部位以交易所為準，state 只是引擎的帳。任何「要平多少」「現在持有多少」的問題，只能經同一個閘門函數回答。**

### 3.1 部位真相閘門

`exchange_utils.py` 新增：

```python
def read_positions(info, address: str, coins: list[str]) -> dict[str, float]:
    """回傳 {coin: szi}（無部位為 0.0）。讀取失敗一律 raise，絕不回空 dict。"""
```

- 「讀不到」≠「沒部位」：例外往上拋，呼叫端各自決定（flatten 判未完成、sync 跳過該 cycle）。
- 只涵蓋預設 perp dex 的 `COIN_UNIVERSE`。gridbot 不交易其他 dex 與現貨。
- `live.py` 內所有需要實際部位的地方只能呼叫它；驗收用 grep 證明沒有第二條路徑。

### 3.2 熔斷出清（R1、R6）

`_flatten_everything` 改為：

1. 撤單：讀交易所 `open_orders`，撤掉 `COIN_UNIVERSE` 內**所有**掛單（不看 state）。
2. 平倉：`read_positions` → 每個 szi ≠ 0 的幣 `market_close(coin, abs(szi))`。
3. 驗證：再讀一次，`COIN_UNIVERSE` 全部 szi == 0 且無掛單才回 True；否則最多重試 3 輪。
4. 成功才清空 state 的 `armed`／`open_lots`；失敗保留並設 `state["flatten_pending"] = True`。
5. `check_drawdown` 的 halted 分支：`flatten_pending` 為 True 時每個 cycle 重跑 1–3，成功後清旗標並發 Telegram。
   旗標為 False 時 halted 期間**不碰部位**（owner 可能在停機期間自己手動開倉）。
6. 告警文字改成事實：成功寫「已驗證 szi=0」；未完成列出每個幣剩餘 szi。

停損路徑（`sync_coin` L321–340）同樣改用交易所 szi 當平倉量。

### 3.3 不再漏記買單（R2、R3、R4）

- `_cancel` 回傳三態：`"cancelled"`／`"gone"`（回應含「never placed, already canceled, or filled」類 error）／`"failed"`（例外或其他 error）。
  既有呼叫端只認 `"cancelled"` 為成功。
- 新增 `_resolve_buy(coin, level, oid)`：用 `info.query_order_by_oid` 取該單最終狀態與成交量（origSz − 剩餘 sz）。
  - 成交量 > 0 → 以**總成交量**建 lot 並掛 TP（取代現在的 `_on_buy_filled` 內文）。
  - 成交量 == 0 且狀態為 canceled／rejected → 才可從 `armed` 移除。
  - 查詢失敗或狀態不明 → **保留 `armed` 紀錄**，下個 cycle 再查。不再有「找不到就當取消」。
- 重新置中（L367–369）：先 `_cancel`，結果不是 `"cancelled"` 就走 `_resolve_buy`，不可先 `pop`。
- 部分成交後仍在掛的單：維持 armed，等它完全成交或被撤時一次結算。

### 3.4 每 cycle 對帳（R5）

`sync_coin` 開頭：`szi = read_positions(...)[coin]`，`tracked = Σ open_lots.size`，`gap = szi − tracked`。

- 名目上限改用 `abs(szi) × mid`（交易所實際部位），不是 `open_lots` 加總。
- `gap` 超過一個最小下單單位、且連續 2 個 cycle → Telegram 告警（幣、szi、tracked、gap）＋該幣停掛新買單，直到 gap 消失。
- **不自動交易未追蹤部位**（見待裁決 D2）。
- `--status` 每個幣多印 `szi／tracked／gap`。

## 4. Tasks

全部 `@inline`（需理解既有 sync 流程與 SDK 回應格式），依序派 `builder`，每個 task 主線程親跑驗收指令。

| # | 內容 | 檔案 | 驗收 |
|---|---|---|---|
| T1 | `read_positions` 閘門＋單元測試（讀取失敗 raise、無部位回 0.0） | `exchange_utils.py`、`tests/test_gridbot_exchange_utils.py` | `.venv/bin/pytest tests/test_gridbot_exchange_utils.py -q` 全綠 |
| T2 | `_cancel` 三態＋`_resolve_buy`＋重新置中順序（§3.3） | `live.py`、`tests/test_gridbot_live_reconcile.py` | 新增測試涵蓋：撤單撞成交、查詢視窗外成交、三筆部分成交加總、查詢失敗保留 armed；全綠 |
| T3 | `_flatten_everything`／停損改以交易所為準＋`flatten_pending` 重試（§3.2） | `live.py`、`tests/test_gridbot_drawdown_guard.py` | 新增測試：state 空但交易所有部位 → 全平；平倉部分成交 → 重試；讀部位失敗 → 回 False 且不清 state；halted＋旗標 False 不送任何單 |
| T4 | 每 cycle 對帳、上限改用 szi、gap 告警與停買、`--status`（§3.4） | `live.py`、`tests/test_gridbot_live_reconcile.py` | 新增測試：gap 連 2 cycle → 告警一次＋不掛新買單；gap 消失 → 恢復 |
| T5 | 變異驗收：對 R1–R4 各植入一個回歸（還原舊行為），證明測試會紅；附路徑計數器 > 0 | 測試檔內或 `scripts/` 一次性腳本 | 四個變異全部被抓到，輸出貼進回報 |
| T6 | 上線（主線程＋owner，不派工）：`reviewer` 審完 → owner 同意 → 部署 → restart → 觀察 3 個 cycle → `--status` 的 gap 全為 0 | — | 線上 journal 與 `--status` 輸出 |
| T7 | `reports/gridbot-design.md` 更新出清與對帳語意 | 文件 | read-back |

共同要求（寫進每份派工 prompt）：

- 測試不得打到真實服務；`Info`／`Exchange` 一律用 fake，沿用既有測試檔的作法。
- `query_order_by_oid` 與 cancel 回應的**欄位名是假設**：builder 須先以唯讀呼叫取一筆真實 payload 樣本（已成交單、已撤單各一），把樣本存成測試 fixture，再寫解析。
- 所有外部呼叫經 `resilience.py` 的邊界；`market_close` 屬 reduce-only 冪等，可重試；`order` 開倉不可盲重試。
- 不改熔斷門檻、equity basis、三 cycle 確認、re-arm 語意。

## 5. 裁決（owner 2026-11-14 確認）

- **D1 出清範圍**：只平 `COIN_UNIVERSE` 的永續。現貨（UBTC 等）不賣。
- **D2 未追蹤部位（gap）**：只告警＋該幣停掛新買單＋計入名目上限。不自動補掛 TP、不自動平差額。
- **D3 halted 期間**：`flatten_pending` 為 False 時不碰部位、不送任何單。

## 5.1 已實測的真實 payload（2026-11-14，公開 info API `orderStatus`，即 SDK `info.query_order_by_oid(user, oid)`）

```json
{"status":"order","order":{"order":{"coin":"BTC","side":"B","limitPx":"76605.0","sz":"0.0","oid":595708894064,"timestamp":1793890875821,"triggerCondition":"N/A","isTrigger":false,"triggerPx":"0.0","children":[],"isPositionTpsl":false,"reduceOnly":false,"orderType":"Limit","origSz":"0.00113","tif":"Alo","cloid":null},"status":"filled","statusTimestamp":1793892281291}}
{"status":"order","order":{"order":{"coin":"BTC","side":"B","limitPx":"77995.0","sz":"0.00111","oid":595704127885,"timestamp":1793890754015,"triggerCondition":"N/A","isTrigger":false,"triggerPx":"0.0","children":[],"isPositionTpsl":false,"reduceOnly":false,"orderType":"Limit","origSz":"0.00111","tif":"Alo","cloid":null},"status":"canceled","statusTimestamp":1793890875224}}
{"status":"unknownOid"}
```

- `sz` 是**剩餘量**、`origSz` 是原始量 → 成交量 = `origSz − sz`。回應沒有成交均價；買單是 Alo（只做 maker），成交價 = `limitPx`，lot 的 `entry_price` 用 `limitPx`。
- 外層 `status` 為 `"order"` 才有內容；`"unknownOid"` 視為「狀態不明」→ 保留 armed，下輪再查。
- 內層 `status` 已見過 `open`／`filled`／`canceled`；其他值（如各種 `*Rejected`、`*Canceled`）一律用「成交量 > 0 → 建 lot；成交量 == 0 且不是 `open` → 移除」判斷，**不要列舉字串**。
- **cancel 回應未經實測**（取樣要送簽章動作，禁止）。推定形狀：成功 `{"status":"ok","response":{"type":"cancel","data":{"statuses":["success"]}}}`；失敗時 statuses 內是 `{"error": "..."}`。
  裁決：`_cancel` 只在 statuses 全為 `"success"` 時回 `"cancelled"`；其餘任何情況回 `"unconfirmed"`（例外回 `"failed"`）。
  **邏輯不得依賴 error 文字**：非 `"cancelled"` 一律交給 `_resolve_buy` 查單決定。§3.3 的 `"gone"` 以此為準改名為 `"unconfirmed"`。
- builder 不得對真實交易所送任何簽章動作（下單／撤單／改槓桿）；唯讀 info 查詢可以。

## 6. 資料極限

- 根因筆數（14／9／6）來自 11-07 的 journal 與成交對帳，三類有重疊，合計不等於漏記總數 23。
- 修完後 gap 預期為 0，但 §3.4 的對帳是偵測器，不保證沒有第四種漏記路徑；T6 觀察期與之後的 gap 告警才是證據。

## 執行紀錄

- 2026-11-14：本地 `src/hlvault/gridbot/*.py` 與線上主機逐檔 md5 相同（線上 `0d1547c` ＝ 本地工作樹內容）。
- 2026-11-14 T1 完成，主線程親跑：`tests/test_gridbot_exchange_utils.py` 33 個全過、`tests/test_gridbot_*.py` 89 個全過。
  builder 決策已採納：payload 任一筆格式壞（含不在 `coins` 的幣）就 raise；`szi` 為 NaN／inf raise；同幣重複條目 raise；`assetPositions == []` 是合法的全平。
- 2026-11-14 T2 完成，主線程親跑：`tests/test_gridbot_*.py` 110 個全過（主線程把 `tests/test_gridbot_alerts.py:173` 的 `_cancel` stub 從 `True` 改成 `"cancelled"`，配合新的三態契約）。
  `live.py` 已無 `user_fills_by_time`／`treating as cancelled`。builder 決策已採納：止盈掛失敗保留 armed 下輪重試；dry-run oid 直接移除；`open_notional` 在重新置中後才算；成交量用 `round(…, szDecimals)`。
- **裁決 R-A（T2 留下的缺口，併入 T3）**：重新置中撤單後**不論撤單結果都呼叫 `_resolve_buy`**（撤單成功但先前已部分成交的單，成交部分要建 lot）。
  T2 的測試 (f)「cancelled 時不查單」改為「cancelled＋查單為零成交 → armed 移除、無 lot」，並新增「cancelled＋查單顯示部分成交 → 建 lot」。
- **裁決 R-B（併入 T3）**：停損區塊對 armed 買單比照處理——撤單後一律 `_resolve_buy`；平倉量取交易所 szi，不再用 `open_lots` 加總，
  因此「止盈單其實已成交卻又照 state 多賣」的問題一併消失（`market_close` 是 reduce-only，量以 szi 為準）。
- 2026-11-14 T3（＋R-A、R-B）完成，主線程親跑：`tests/test_gridbot_*.py` 135 passed；`live.py` 內 `user_state`／`assetPositions` 零命中，讀部位四處全經 `read_positions`；`_market_flatten` 兩個呼叫的量都是 `abs(szi)`。
  builder 決策已採納：dry-run 出清不讀不送；`_stop_loss_exit` 以讀回的掛單（不是撤單回應）判定止盈單是否還在；trip 當下先把 `flatten_pending=True` 連同 `halted` 落盤再出清。
- **裁決 R-C**：停損平掉該幣的**全部** szi（永續部位不可分割；與 D1 熔斷出清一致）。owner 在同一幣手動開的永續會一併被平——已告知 owner。
- **裁決 R-D（併入 T4）**：出清每一輪在「送完撤單／平倉」與「讀回驗證」之間等 1 秒（`time.sleep(1)`，僅 live），避免查詢延遲造成假的「未驗證」告警。測試不得真的睡（monkeypatch）。
- **裁決 R-E（併入 T4）**：`rearm_if_recovered` 遇 `flatten_pending` 為 True 時，先跑一次 `_flatten_everything`；未驗證成功就維持 halted（發 alert），成功才進入原本的回撤檢查。
- **裁決 R-F（併入 T4；新發現的第二個超額來源）**：名目上限目前只在「掛新單」時檢查 `open_lots 名目 + 一層 ≤ 上限`，**不計已掛的買單**。
  持有 6 層 lot 時下方仍可掛著 6 張買單，急跌時全數成交 → 部位可達上限的約 2 倍（11-05 flatten 平掉 HYPE 8、BTC 8 個 lot，超過 `NUM_LEVELS=6`，即為實證）。
  回測 `strategy.step` L134–136 是在**成交時**擋上限（實盤做不到），所以實盤與回測行為不一致。
  修法：每個 cycle 以 `曝險 = abs(szi) × mid`（交易所實際部位）計，維持 `曝險 + Σ 掛著的買單名目 ≤ max_position_notional`：
  超出時從**最深**的買單開始撤（撤後照 R-A 一律 `_resolve_buy`）；掛新單時同一條不等式（含本 cycle 已掛的）。
  效果：任何行情下該幣永續名目不超過上限（差額只剩一個 cycle 內的價格變動）。這會減少持倉時下方的掛單數，是讓實盤回到回測語意，待 owner 於上線前知悉。
- 2026-11-14 T4（＋R-D、R-E、R-F）完成，主線程親跑：`tests/test_gridbot_*.py` 159 passed in ~1s；`live.py` 內 `user_state`／`assetPositions` 零命中。
  builder 決策已採納：gap 取絕對值（交易所少於帳上也算）；dry-run 不計 gap；上限比較加 1e-9 相對容差；本 cycle 讀 szi 之後才建的 lot 另加進 exposure（偏保守）。
- 2026-11-14 T5 由主線程親做（`scratchpad/mutate.py`，逐一植入、跑測試、還原）：8 個變異全部被抓到——
  R1 平倉量用 state（13 紅）、R1b 不讀回驗證（7）、R2 重新置中撤單後遺忘（4）、R3 查不到單當取消（3）、R4 被撤單忽略部分成交（2）、
  R5 上限不計掛單（3）、R5b 上限用帳上 lot（2）、R6 halted 不重試未完成出清（2 紅）。還原後 159 passed。
- 2026-11-14 reviewer（opus，fresh）審查：1 Critical／1 Warning／1 Suggestion，三個重現測試在 `scratchpad/rev/test_repro.py`，主線程親跑確認三個都重現。其餘（armed 移除路徑、出清不會送開倉單、`flatten_pending` 轉移、D1–D3、舊 state 相容、resilience 分類）reviewer 未發現問題。
- **裁決 R-G（Critical，必修）**：停損沒平乾淨時，下一輪若價格回到停損價之上，`_on_tp_filled` 會把止盈單已被撤的 lot 當成止盈成交而刪掉 → 部位被遺忘。
  修法：state 每個幣加 `stop_pending`（舊 state 無此鍵 → False）。停損觸發時**先**設 True 並落盤，再呼叫 `_stop_loss_exit`；
  `stop_pending` 為 True 的 cycle，不論現價在哪，`sync_coin` 一律只做「重跑 `_stop_loss_exit`」然後 return（不進對帳、不掛單、不跑 `_on_tp_filled`）；
  驗證成功才清 `open_lots`、設冷卻、`stop_pending=False`。第一次失敗發一次 Telegram（幣、剩餘 szi 或「讀不到」），成功後再發一次「已驗證」；失敗期間不每輪重發。
  `_stop_loss_exit` 的讀回前比照 R-D 等 `FLATTEN_SETTLE_SECONDS`。熔斷出清成功（`_clear_tracked_books`）時把各幣 `stop_pending` 清為 False。
- **裁決 R-H（Warning）**：`openOrders` 的 `origSz` **已由主線程實測存在**（2026-11-14 真實回應：`{"coin":"ETH","side":"B","limitPx":"1890.3","sz":"0.0259","oid":604689778624,"timestamp":1794631103414,"origSz":"0.0259"}`），欄位假設成立。
  但「對帳連續讀不到 → 靜默停掛」的失敗模式成立：state 每個幣加 `reconcile_fail_cycles`，連續讀不到達 `RECONCILE_FAIL_ALERT_CYCLES = 5` 時發一次 Telegram（附最後一次錯誤），恢復可讀時歸零（之後可再告警）。不因此出清或 halt。
- **裁決 R-I（Suggestion，採納）**：gap 告警改用旗標而非 `== 2`：`gap_cycles >= GAP_ALERT_CYCLES and not gap_alerted` 時告警並設 `gap_alerted=True`；gap 消失時兩者歸零。
  `_clear_tracked_books`（熔斷出清成功）與停損驗證成功時，把該幣 `gap_cycles`、`gap_alerted` 歸零。
- 不處理（記錄在案）：讀不到 szi 的那一輪 R-F 不撤超額買單；gap 擴大不再次告警；止盈單回應遺失時的重複止盈（reduce-only，gap 偵測可抓）；`last_fill_check_ms` 已無人讀取但保留寫入。
- 2026-11-14 R-G／R-H／R-I 完成，主線程親跑：`tests/test_gridbot_*.py` 175 passed；變異驗收重跑，R1–R5b 七個仍全部被抓到。
  builder 決策已採納：每幣多一個 `stop_alerted` 旗標（已落盤）；停損第一次就平乾淨時維持不發 Telegram；`stop_pending` 的處理排在 `_ensure_leverage` 與冷卻判斷之前。
- 2026-11-14 複審（opus，fresh，只看 R-G／H／I 的差異）：無 Critical，4 Warning、1 Suggestion；重現測試在 `scratchpad/rev2/test_rev2_repro.py`，主線程親跑確認重現。
  `stop_pending` 所有轉移經核對無誤（沒有路徑會在未驗證前刪 lot、掛買單或清旗標）。
- **裁決 R-J（W1＋W4，結構性收斂）**：停損出清不再自己寫一套——`_stop_loss_exit(coin)` 改成「單幣版的熔斷出清」：
  `_flatten_round([coin])` → 等 `FLATTEN_SETTLE_SECONDS` → `_verify_flat([coin])`。即：撤掉交易所上**該幣所有掛單**（不論 state 認不認得）、平掉該幣全部 szi、讀回（先讀掛單、再讀部位）確認該幣無掛單且 szi == 0。
  驗證成功 → 清該幣的 `armed` 與 `open_lots`（全部 szi 已平，任何買單成交都已包含在內，不需再逐張 `_resolve_buy`、不再對空倉掛止盈）。
  失敗細節沿用 `_verify_flat` 的字串給告警。這同時消掉 W1（平完後才結算的 armed 讓該幣永久卡住）與 W4（state 不認得的掛單在冷卻期殘留）。
  owner 在該幣手動掛的單會被一併撤掉（與 R-C、D1 一致）。
- **裁決 R-K（W3）**：`run_once` 對每個幣的 `sync_coin` 各自 try／except，一個幣丟例外不得中斷其他幣（含它們的 `stop_pending` 出清）。
  R-H 的「連續讀不到」計數擴大為涵蓋整個 `sync_coin`：未捕捉例外、`mid <= 0`、`open_orders` 讀取失敗、`_reconcile` 讀不到，都算一次失敗（同一 cycle 只加一次）；
  該幣一個 cycle 完整跑完且對帳可讀才歸零。沿用 `reconcile_fail_cycles` 與 `RECONCILE_FAIL_ALERT_CYCLES`，用一個 helper 統一記錄與告警。`stop_pending` 的 cycle 不計入（它有自己的告警）。
- **裁決 R-L**：停損驗證成功**一律**發一則 Telegram（幣、已驗證、冷卻時數），不論之前有沒有失敗過——實現的停損虧損 owner 必須知道。失敗告警仍只發一次。
- **裁決 R-M（W2 的不改行為部分）**：`_halted_reminder` 的訊息列出目前 `stop_pending` 為 True 的幣（若有）。
  **待 owner 裁決 D4**：halted（且 `flatten_pending` 為 False，例如 equity 連續讀不到而停機）期間，是否仍要繼續跑未完成的停損出清？目前（依 D3）不跑。
- **測試補強（Suggestion）**：加入 `stop_pending` 跨多輪、`run_once` 走「stop_pending → 熔斷出清失敗 → halted → restart re-arm」整段、出清中途丟例外後下輪接續；並守住「停損讀回前有等 `FLATTEN_SETTLE_SECONDS`」。
- 2026-11-14 R-J／R-K／R-L／R-M＋測試補強完成，主線程親跑：`tests/test_gridbot_*.py` 198 passed in ~1.3s；變異驗收重跑 R1–R5b 七個全被抓到；
  兩輪審查的重現測試（`scratchpad/rev/`、`scratchpad/rev2/`）除 r2（＝待裁決的 D4）外全部不再重現。停損路徑已無 `_resolve_buy`，`_flatten_round`／`_verify_flat` 由熔斷與停損共用。
  builder 決策已採納：dry-run 停損不發 Telegram；冷卻中與 `stop_pending` 的 cycle 不計入連續失敗；告警文字改 "COIN CYCLE FAILING"；`sync_coin` 為包裝層（計數落盤後重拋，由 `run_once` 逐幣隔離）。
- 2026-11-14 第三輪複審（opus，fresh，只看 R-J～R-M 的差異）：**結論可上線**，無 Critical；1 Warning＋2 Suggestion 皆不擋上線。主線程已直接修掉並加測試：
  halted 提醒在 `flatten_pending` 為 True 時不再寫「NOT retried」；停損驗證成功時 `reconcile_fail_cycles` 歸零；`test_gridbot_stop_exit_converge.py` 一條被寫在註解裡的斷言改成真的執行。
  主線程親跑：`tests/test_gridbot_*.py` 200 passed；整個 `tests/` 全綠；`scratchpad/rev3/` 的兩個重現測試不再重現。
- 2026-11-14 T7 完成：`reports/gridbot-design.md` 第 3 點之後補上「Exit semantics as implemented」。
- 已知未處理（複審「觀察」，另開題）：冷卻 24h 期間該幣不做對帳；`save_state` 持續失敗（磁碟滿）會擋住告警與熔斷出清；卡住的 `stop_pending` 在非 halted 狀態只告警一次；D4 待 owner 裁決。
- **T6 上線前置事實**：線上 `0d1547c` 是 `origin/main` 的祖先，`origin/main` 領先 24 個 commit，但 `src/hlvault`、`deploy`、`pyproject.toml` 零差異 → 線上 `git pull` 只會帶進本次 gridbot 改動。
  舊 state 檔相容（新鍵皆 `.get` 預設）。上線步驟：commit → push → 併入 main → 線上 `git pull` → `sudo systemctl restart hl-gridbot` → 觀察 3 個 cycle、`--status` 三個幣 gap 為 0。**restart 前必須 owner 同意。**
- **2026-11-15 T6 上線（owner：「上線吧」）**：本地分支 fast-forward 到 `origin/main` 後重跑（gridbot 200 passed、整個 `tests/` 635 passed）→ commit `32c569d` → push `main`。
  線上 00:25 UTC 備份 state（`gridbot_state.json.bak-20261115-002507`）→ `git pull --ff-only`（`0d1547c` → `32c569d`）→ `sudo systemctl restart hl-gridbot`（00:25:52 UTC）。服務 active、無例外、未 halted。
  owner 未另外表態的兩項依現況上線：**R-F 保留**（上限計入掛著的買單）；**D4 未實作**（維持 D3：halted 且 `flatten_pending` False 時不跑未完成的停損出清，只在提醒中列出該幣）。
- **上線當下的線上事實（新版 `--status`，restart 前唯讀執行）**：舊版在 11/14 03:55 重啟後的 20.5 小時內又漏記了部位——
  HYPE szi 1.42／帳上 0.94／gap **+0.48**；BTC 0.00726／0.00645／gap **+0.00081**；ETH 0.2383／0.1848／gap **+0.0535**（合計名目約 $180，都沒有止盈單）。
  journal 佐證（舊版日誌 `order gone but no matching fill found — treating as cancelled`）：ETH level -4（14:03）、ETH level -11（20:55）、BTC level -8（15:39），筆數與 ETH 兩格、BTC 一格的 gap 吻合；
  HYPE 那一格沒有對應日誌，推定走的是 R2（重新置中撤單撞成交，舊版不留紀錄）——此為推定，未逐筆對成交。
  另外舊版上限不計掛單（R-F 所修）的後果已實際發生：BTC 曝險約 $470（上限 $320）、ETH 約 $430（上限 $294），三幣合計約 $990，高於 `ALLOCATED_CAPITAL=800`。
- **新版上線後的行為（00:25–00:29 UTC，4 個 cycle，journal 親讀）**：三個幣第 1 cycle 記 gap、第 2 cycle 起「position gap persists — not placing new buys」，沒有任何自動賣出（符合 D2）；
  既有止盈單不受影響。**驗收條件「三個幣 gap 為 0」未達成**——gap 是舊版留下的，新版依 D2 不自動處理，需 owner 決定那約 $180 未追蹤部位要平掉、自己掛止盈、或留著（留著期間三個幣都不會掛新買單）。
- **上線觀察抓到的缺陷 R-N（已修，見下一筆 commit）**：R-F 撤單迴圈用 `len(c["armed"])` 當「還掛著的買單數」。交易所確認撤單後，`orderStatus` 會短暫仍回 `open`，
  `_resolve_buy` 因此保留 armed 紀錄到下個 cycle 才結算，計數不降 → HYPE 只需撤 3 張卻把 6 張全撤（00:25:54–58 的日誌一路印 `5 resting buys`）。方向偏保守（少掛買單、下個 cycle 會補回），不造成超限。
  修法：迴圈內加 `shed` 計數，撤單結果為 `"cancelled"` 且紀錄仍在時不再算作掛著；`"unconfirmed"`／`"failed"` 仍算掛著。下方掛新買單的迴圈刻意不改（待結算紀錄仍算掛著，偏保守）。
  測試：`test_d2b_status_lag_after_cancel_does_not_shed_more_than_the_excess`（還原修法後會紅，主線程親跑確認）、`test_d2c_unconfirmed_cancel_still_counts_as_resting`。gridbot 202 passed、整個 `tests/` 637 passed。
  先前「已實測 payload」的極限在此應驗：cancel 之後 `orderStatus` 的時序從未實測，測試用的 fake 一律立即回 `canceled`，所以三輪審查與變異驗收都看不到（工程原則 #6：離線測試證明邏輯，不證明時序）。
- 2026-11-15 R-N 複審（opus，fresh，只看這個修正）：結論可上線，1 Warning——被 `shed` 扣掉的買單若在讀 szi 之後、撤單之前部分成交，那段成交既不在 `exposure` 也不在掛單數裡（危險方向，但 < 一格、只是潛在部位、下個 cycle 自行修正）。
  主線程採納並補上：只要有未結算的 shed 紀錄就保留一格名目（至多一張 shed 買單可能處於此狀態——能碰到它的賣壓會把較淺的買單全數吃完，而全數成交的單撤單不會被確認、不計入 shed）。
  結果：延遲情境下撤「超額＋1」張（實例 4 張，修前 6 張），保留的那一格下個 cycle 補掛。測試 `test_d2d_part_fill_hidden_behind_a_lagging_cancel_cannot_breach_the_cap`（即審查員的重現）；
  變異驗收：拿掉保留 → d2b、d2d 紅；還原成 `32c569d` → d2b 紅。gridbot 203 passed、整個 `tests/` 638 passed；`scratchpad/rev4/` 兩個重現測試皆通過。
  審查員的「觀察」未處理：dry-run 帶真 oid 時 log 失真；延遲超過一個 cycle 會退回多撤（偏保守）；測試 fake 對不在簿上的 oid 撤單也回 success、撤部分成交單時把剩餘量寫成原始量（與真實交易所不一致，既有問題）。
- **2026-11-15 R-N 上線**：commit `004a537` → push `main` → 線上 `git pull --ff-only` → restart（00:36:26 UTC）。觀察 4 個 cycle（00:36–00:39）：服務 active、未 halted、無例外；
  三個幣維持「gap → 不掛新買單」，沒有自動賣出。`--status`（00:40 UTC）：equity $780.01、peak $839.87（回撤 7.1%）；HYPE gap +0.48、BTC +0.00081、ETH +0.0535，三幣 armed 皆 0。
  三幣 `gap_alerted` 皆為 True（告警函式已呼叫；Telegram 實際送達與否從主機端無法驗證）。
- **收尾狀態**：T1–T7 與 R-A～R-N 全部完成並上線。未結事項：(1) 舊版留下的約 $180 未追蹤部位待 owner 處理（處理前三個幣不掛新買單；BTC／ETH 即使 gap 歸零，曝險仍高於上限，要等止盈把部位降到上限以下才會再掛買單）；
  (2) D4 未實作；(3) 上面各輪「已知未處理／觀察」項目。
