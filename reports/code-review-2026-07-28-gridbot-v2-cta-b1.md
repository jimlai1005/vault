# Code Review — 2026-07-28（gridbot 熔斷器 v2＋CTA B1 部署波）

Owner 睡前委託的收尾審查。範圍：最近五個 commit（`4c27858`…`c00cad5`）。
方法：三個 fresh-context reviewer（opus×1、sonnet×2）＋haiku 機械 read-back，
**所有 finding 的引用行號與行為皆由主對話親自複驗**，測試由主對話親跑
（`.venv/bin/pytest` gridbot＋CTA 五個測試檔：**114 passed**）。

**重要：本審查只產出文件，未修改任何引擎程式碼、未啟停任何 service、未部署。**

---

## 總判定

| Commit | 對象 | 判定 |
|---|---|---|
| `c00cad5` | gridbot 熔斷器 v2（實盤） | **7 個 finding（2 高、1 中高、3 中、1 中低），需 owner 裁決後修** |
| `4c27858` | CTA B1 vol-target sizing | **通過**。bit-identical 宣稱成立（結構性＋identity test），cap-only／entry-locked 皆結構性保證 |
| `882f184` | hl-cta-b1 部署包 | **通過**。機密安全（範本全佔位符、歷史無真值）、.gitignore、systemd、runbook 路徑逐條核對皆過；一處 commit 歸屬誤述已修（本 commit） |
| `dc027fd`、`c3da3c3` | 純文件 | 落檔完整，未深審內容 |

文件與版本管理：工作樹乾淨、與 origin/main 同步、無 stash；六個關鍵交付檔完整
非空；memory 索引與目錄一致；事故 #4 已入工程原則。

---

## gridbot 熔斷器 v2 findings（全部經主對話親驗）

### F1（高）failed-read 護欄漏接「單腿缺失」——事故 #4 的同型復發路徑
- `src/hlvault/gridbot/exchange_utils.py:94-102`：perp／spot 兩支 API 缺欄一律
  `.get(..., 0.0)` 靜默補零；`src/hlvault/gridbot/live.py:117` 護欄只認 `current <= 0.0`。
- 觸發情境:spot `/info` 回 200 但缺 `balances`（降級／格式異動），perp 正常 →
  equity 只剩 accountValue（依 2026-07-25 實測錢包形態約 $46.63/$1094.67），是「看起來合理
  的正數」，護欄放行 → 幻影 ~95.7% 回撤，debounce 只延後 3 cycle（~3 分鐘），照樣 flatten＋halt。
- 加重因素：`tests/test_gridbot_exchange_utils.py:71-80` 的
  `test_full_equity_tolerates_missing_margin_summary` 把「缺 marginSummary 回 spot-only」
  **固化成期望行為**，這條測試在保護這個洞。
- 修法方向（待 owner 裁決）：equity 函式對缺 key 直接拋（讓 failed-read 路徑接手），
  或對「單 cycle 跌幅異常大」也視為 failed read。

### F2（高）`_market_flatten` 宣告 `-> bool` 但永遠回傳 None，flatten 全被誤判失敗
- `src/hlvault/gridbot/live.py:398-405`：dry-run 路徑 `return`（None）、成功路徑無 return、
  例外路徑無 return。呼叫端 `live.py:216-217`、`live.py:279-280` 都拿回傳值當「平倉已確認」。
- 後果一：`_flatten_everything()` 即使全部成功也永遠印
  `SAFETY-CRITICAL: not everything could be flattened`（狼來了），且 `open_lots` 永不清除。
- 後果二（更嚴重）：stop-loss 路徑（`live.py:279-288`）永不清 `open_lots`、永不設
  `stopped_until_ms` → cooldown 形同不存在，價格在 stop 之下的每個 cycle 都對已平部位
  重複送 `market_close`。
- 註記：bug 早於 c00cad5（`401f499` 改簽名未改函式體），但它是熔斷器唯一的執行動作。
- 修法方向：成功 `return True`、例外 `return False`、dry-run `return True`，補測試。

### F3（中高）bootstrap 的 peak 種子來自 config 常數，與 current 不同源（工程原則 #1）
- `src/hlvault/gridbot/live.py:95`：`peak_equity = cfg.ALLOCATED_CAPITAL`（env 常數），
  current 來自 API。`exchange_utils.py` docstring 宣稱同源，與此矛盾。
- 觸發情境：state file 不存在（新機、cache 被清、或 owner 刪 state file 自救）且錢包實際
  餘額 < `ALLOCATED_CAPITAL × (1 − MAX_DRAWDOWN_PCT)` → 幻影回撤直接 halt；且
  `rearm_if_recovered`（`live.py:162`）對著同一個幻影 peak 算，**v2 的重啟自助復盤在
  這條路徑失效**，owner 又被逼回手改 state file。
- 修法方向：bootstrap peak 用 `get_full_account_equity()` 實測值。

### F4（中）debounce 視窗期間（breach 1/3、2/3）整個 sync 跳過
- `src/hlvault/gridbot/live.py:130-141` return True → `run_once()`（`live.py:410-411`）直接
  return：真實急跌的頭 ~2 分鐘，armed 買單留在場上繼續往下接、per-coin stop-loss 不評估。
  v1 是首次 breach 即平。
- 修法方向：首次 breach 先撤 armed 買單（可逆止血），flatten 留給 confirm。

### F5（中）equity 讀取失敗連帶關掉不需要 equity 的價格型 stop-loss
- `src/hlvault/gridbot/live.py:116/123` → `_equity_read_failed` return True（`live.py:200`）→
  整個 cycle 跳過。equity 讀不到期間（最多 MAX_BAD_EQUITY_READS 個 cycle，之後 halt 繼續
  跳過），`all_mids` 正常也不跑 stop-loss。
- 修法方向：failed-read 只停「以 equity 為依據的動作」，價格型風控照跑。

### F6（中）「重啟＝owner 的 re-arm 意圖」在 systemd 下不成立
- `src/hlvault/gridbot/live.py:418` 進圈前無條件 `rearm_if_recovered()`；
  `deploy/hl-gridbot.service:18-19` 是 `Restart=on-failure`／`RestartSec=10`。
- 觸發情境：OOM／crash-restart 也會觸發 re-arm，只要讀值回門檻內就自動解除 halt，
  全程無人看過。搭配 F2（flatten 誤判、部位追蹤可能不乾淨）風險放大。
- 修法方向：re-arm 改用 owner 明確訊號（rearm flag 檔或 `--rearm` 旗標）。

### F7（中低）basis 切換沒有 peak 遷移
- `src/hlvault/gridbot/live.py:127`：`peak = max(舊 basis 存的 peak, 新 basis current)`——
  一次跨 basis 比較。一般方向自癒（新 basis 通常較大）；但舊 peak 若寫於「大浮盈＋高
  保證金占用」時刻，新 basis 追不上，回撤被系統性高估。gridbot 量級小，列中低。

### 觀察（非 finding）
- `live.py:195-196` 訊息只教 state-file surgery，漏了 v2 新增的「重啟即 re-arm」桿
  （`live.py:110-111` 有寫），兩處文案不一致。
- gridbot 全模組零 notifier（`src/hlvault/notify/` 現成未接）——SAFETY-CRITICAL 告警只落
  journald，工程原則 #3 的「大聲」目前等於「有 log」。
- `config.py:37-38` `DRAWDOWN_CONFIRM_CYCLES` 無下限檢查（0／負值＝debounce 失效）。
- 測試側 socket guard 是唯一防線（`config.py` import 時即 load 實盤 .env），符合原則 #4
  最低要求，無第二道。

## CTA B1（4c27858）審查摘要
- bit-identical：`live.py:462-472` 關閉時 `m_mult=1.0`，`×1.0` 為 IEEE754 精確運算；
  `test_sigma_target_default_off_notional_and_log_unchanged` 為行為級 identity test。成立。
- cap-only：`SIGMA_CLIP_HI` 硬編 1.0 不開放 env——結構性不可能放大。
- entry-locked：`m` 只在 entry 分支算一次，全檔無讀回——重啟不重算。
- 凍結參數：60%/180/0.25 與 spec 一致；`SIGMA_TARGET` 預設 None＝off。
- 觀察：sizing fail-safe 只 warning 不送 Telegram；退化行為（m=1.0）本身安全，僅可觀測性弱。

## 部署包（882f184）審查摘要
- env 範本全佔位符、`git log --all` 確認歷史無真值；`.gitignore` 新行正確擋 `.env.cta-b1`
  且無誤擋；systemd unit 與 `hl-cta2.service` 慣例逐行一致；runbook 引用路徑／行號／算式
  逐條核對正確；每步驟碰錢／不碰錢標註齊全。
- 已修：DOT 修復 commit 歸屬誤述（`docs/runbooks/cta-b1-deploy.md`，原寫「與本 runbook
  同一 commit」，實為 `4c27858`）。

## 待 owner 裁決事項（醒來後）
1. F1–F6 是否排修？建議順序：F2（機械修、低爭議）→ F3 → F1 → F5 → F4/F6（涉及設計取捨）。
   修完屬「修改實盤運行邏輯」，部署前依紅線需你點頭。
2. gridbot 要不要接 `src/hlvault/notify/`（觀察項，兩個引擎審查都指到告警可觀測性）。
3. docs/runbooks/ 目前只有 CTA B1 一份；gridbot 熔斷器 v2 的 owner 操作說明散在 code
   docstring 與 log 文案——要不要補一份 gridbot runbook。
