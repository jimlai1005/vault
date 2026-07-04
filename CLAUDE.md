# vault 專案指引

Hyperliquid 量化交易 monorepo。**這個 repo 管理實盤資金**——先讀完「實盤紅線」再動手。

## 實盤紅線（違反任何一條前，必須先問使用者並取得明確同意）

- `.env.carry`、`.env.gridbot`、`.env.momentum` 是**實盤錢包的真實鑰匙**，`.env.research` 是真實 API key。
  不要印出內容、不要複製到別處、不要在測試或範例中載入。
- 以下操作**碰真錢**，執行前必問：
  - `deploy/` 下任何 `.sh` 或對 `hl-carry`／`hl-gridbot`／`hl-momentum` service 的 start／stop／restart
  - `scripts/setup_carry_wallet.py` 及任何會送出交易、轉帳、下單的腳本
  - 修改 `src/hlvault/carry/`、`gridbot/`、`momentum/` 中正在實盤運行的邏輯後的部署
- 測試絕不能打到真實服務（全域工程原則第 4 條）。跑 `pytest` 前確認外部呼叫已被 mock。

## 目錄地圖

- `src/hlvault/` — 主套件。`carry/`、`gridbot/`、`momentum/` 是三個實盤引擎；`io/` 是外部呼叫邊界；`notify/` 是通知。
- `scripts/` — 研究與運維腳本。`research_*.py` 是一次性研究、`run_*.py` 是回測入口。
- `reports/` — 研究結論。`*-verdict.md` 是各子專案的最終判定（GO／NO-GO）。
- `docs/superpowers/specs/`、`plans/` — 子專案的設計與計畫文件。
- `deploy/` — systemd service 檔與部署腳本（碰錢，見紅線）。
- `tests/` — pytest。用 `.venv`：`source .venv/bin/activate` 或 `.venv/bin/pytest`。

## Hyperliquid／資料 API 事實（實測查證 2026-07-04，引擎設計前先讀）

- Agent/API key **不能**做 usdClassTransfer／提領等 user-signed actions（要 master key）——設計不得依賴程式自動做 spot↔perp 劃轉。
- `withdrawable` 已內含 unrealizedPnl；`accountValue == totalMarginUsed + withdrawable` **僅在無掛單時**成立（掛單保證金令 accountValue 波動＝gridbot 幻影回撤事故根源）。
- equity basis 依錢包形態各異（三次事故教訓，見全域工程原則第 1 條）：重用任何 basis 前，先盤點該錢包價值躺在哪幾個桶（spot 現金/spot 幣/perp 部位/perp 自由保證金/掛單保證金），每桶恰好算一次，並與網站顯示總值對帳。
- 現貨價格規則 ≤5 有效位且 ≤(8−szDecimals) 小數；永續是 (6−szDecimals)。HYPE/USDC spot pair = `"@107"`。
- candleSnapshot 單次上限 ~5000 根；Binance OI/多空比免費層僅 ~30 天；Coinalyze free（key 在 `.env.research`，header `api_key`，時間戳為**秒**）歷史約 335 天、40 req/min。

## 慣例

- 研究子專案流程：spec（docs/superpowers/specs/）→ 研究腳本（scripts/）→ verdict 報告（reports/）→ commit。
- Commit message：`docs:`／`feat:`／`fix:`／`chore:` 前綴，一行說清楚，內文交代動機。子專案用字母代號（如「sub-project G」）。
- 研究結論要寫明資料來源與其極限（例如 proxy 資料要標註 proxy）；GO／NO-GO 判定要附依據數字。
- 大量讀取 reports/ 或 scripts/ 來回答問題時，照全域規則派 subagent 摘要，不要把原始檔全文讀進主對話。
