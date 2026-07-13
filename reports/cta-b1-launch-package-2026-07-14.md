# CTA-B1 實例上線包——宇宙選擇與交付總結（2026-07-14 夜間作業）

**狀態：code 與部署套件全部就緒並 commit；服務未安裝未啟動（碰錢步驟依紅線留給 owner）。**
**新實例定義：CTA short book（`4h-p10-fuel24`）＋ B1 vol-target sizing（超一變身）＋
六幣宇宙 BTC/ETH/SOL/DOGE/XRP/DOT（無 HYPE）＋新錢包（待 owner 提供）。**

## 1. 宇宙選擇 verdict

候選普查（8 幣，HL 上市＋Binance ≥5 年歷史兩硬條件）→ 7 幣入回測 →
12 幣 B0/B1 全表＋9 組合對照（`scripts/research_cta_b1_universe.py`，管線與已驗證的
`data/cache/cta_l/` 結果 spot-check 逐位一致）。

- 有正 edge：DOT（B1 Sharpe 0.580/MAR 0.479/PF 1.470）、LTC、BCH、AVAX；
  **BNB（Sharpe −0.51）與 LINK（−0.16）為持續性負 edge，排除穩健**；ADA 邊際。
- **選定 5＋DOT**：唯一使組合四指標同時改善的候選（Sharpe 0.504→0.616、固定基底
  MDD −15.2%→−13.0%、MAR 0.304→0.422、pnl +43%）。
- **opus 二審（獨立重算，同意）誠實條款，原文採用**：
  > 本次選定 DOT 的穩健結論是「在既有 5 幣外增添一顆低相關的乾淨趨勢幣」；DOT 相對
  > LTC/AVAX/BCH 的 Sharpe 領先（0.62 vs 0.56-0.58）在雜訊範圍內，選定 DOT 的實質
  > 依據是其對現有帳本的最低相關性（vs BTC/ETH ≈0.10，使組合平均相關 0.26→0.23），
  > 而非回測報酬排名。DOT 自身 edge 集中於 2023、2025 兩年，2024/2026-YTD 平盤——
  > forward-test 初期出現空側平盤屬正常，不應據以否定。
- HYPE 不入新宇宙：僅 13 個月歷史、TV 回測 PF<1；第一實例含 HYPE 是 live 遺留、
  非驗證結果（第一實例不動）。
- **極限標註**：in-sample 宇宙選擇（7 選 1 多重比較）；Binance proxy 非 HL 行情、
  funding 為 Binance；新錢包本身即此建議的 forward-test。5+DOT+BCH 組合未測，
  未測不上（opus 註記）。

## 2. Live 引擎 B1（opt-in，超一）

`src/hlvault/cta/`：`SIGMA_TARGET` env 未設＝完全關閉（位元級不變，wallet A／cta2
零影響）；設 0.60 ＝ 進場 notional × m。σ＝零均值 EWMA（span 180、√2190 年化）於
closed frame 評估（時序經 opus 逐 bar 對齊驗證＝研究引擎 shift-by-one）；m 進場鎖定
（結構性）；`SIGMA_CLIP_HI=1.0` 不開放 env（結構性 cap-only）；σ 不可得→m=1 大聲
fail-safe；config 守衛拒絕 `SIGMA_TARGET<=0`。decision log 附 `m=/sigma=`。

驗證軌跡：**295 tests 全綠**（新增 25：EWMA 獨立手算對照、預設關閉恆等、m 鎖定、
gross-cap 用縮放後 notional、舊 state 相容、守衛正反向）；opus fresh 審查
「無 blocker/major、可 commit」，4 個 minor 全數修畢。`BINANCE_SYMBOLS` 補 DOT
（純新增鍵，現有實例死碼）。

## 3. 部署套件（owner 動手用）

- `deploy/env.cta-b1.example` — env 範本（33 變數 100% 對照 config.py；錢包 key、
  Coinalyze key 留佔位）。
- `deploy/hl-cta-b1.service` — systemd unit（`CTA_ENV_FILE` 多實例機制；state 檔
  自動隔離為 `cta-b1_state.json`，與兩既有實例零碰撞，已實測推導）。
- `docs/runbooks/cta-b1-deploy.md` — 八步啟用教學（每步標註機器/使用者/碰不碰錢）、
  回滾程序、「引擎停止≠部位不存在」提醒。
- **部署位置建議：同一顆 Lightsail**（systemd 隔離＋獨立 env/state、佔用極小、
  免金鑰搬運；唯一共同故障面＝整機當機，可接受）。注意 Coinalyze 免費 key 40 req/min：
  三實例共用需申請獨立 key 或全部 .env 設 throttle（範本註解有兩選項）。完全隔離的
  新開 Lightsail 路徑亦附於 runbook。
- git pull 不影響運行中服務（舊進程用已載入 code）；**不要 restart 現有服務**。

## 4. Owner 明早的動作清單

1. 提供新錢包地址＋入金（碰錢）。
2. （選）申請第二把 Coinalyze key。
3. 照 runbook 填 `.env.cta-b1` → 伺服器 git pull → dry-run → `systemctl enable --now
   hl-cta-b1`（碰錢，紅線步驟）→ 驗證清單（decision log 的 m=/sigma=、--status、
   HL 網頁對帳）。
4. TV 側如需對照：`scripts/tv_cta_strategy.pine` 已含 B1 三開關版。

## 5. 追溯

普查/回測：`scripts/research_cta_b1_universe_pull.py`、`research_cta_b1_universe.py`、
`data/cache/cta_b1_universe/{per_coin_b0_b1,combos}.csv`（gitignored 可重生）。
引擎與測試：`src/hlvault/cta/{config,live,signals}.py`、`tests/test_cta_{config,live,signals}.py`。
審查軌跡（opus 引擎審查全文、宇宙二審全文）：session 記錄；關鍵結論已錄本檔。
B1 定義與研究依據：`reports/cta-l-stage1-verdict.md`（含 §4 另一讀法揭露，引用必附）。
「B1 變身／超一」呼叫詞已入 memory（`b1-transformation`）。
