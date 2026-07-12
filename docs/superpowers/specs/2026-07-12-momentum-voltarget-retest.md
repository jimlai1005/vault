# Momentum Vol-Target 重測協議（sub-project J，item A）

日期：2026-07-12｜狀態：**預先註冊——本檔 commit 後才准跑正式數字**
依據：`reports/verdict-audit-2026-07-12.md` §2（審計發現原 NO-GO 主因是 flat-3x sizing
＋funding 漏算，非訊號無效）；審計重現碼 `reports/audit/repro_momentum_sizing_funding.py`
（已經 fresh verifier 確認無前視、重用原訊號函數）。

## 1. 唯一被檢驗的假說

「momentum 訊號（`src/hlvault/momentum/signals.py`，**零改動**）在 portfolio vol-target
sizing 下、計入 funding 與滑價後，通過原判定的全部 gate。」
訊號參數、宇宙（BTC/ETH/SOL/HYPE）、再平衡頻率全部維持原判設定。

## 2. 預先鎖定的配置

- **主配置（唯一受判定）**：目標年化波動 20%（＝spec 的 MDD 預算推導值）、
  realized vol 回看 20 交易日、槓桿上限 3x（維持原判、不得上調）、無前視
  （t 日倉位只用 ≤t−1 資訊，沿用審計重現碼的因果結構）。
- 敏感度呈報組（**只呈報、不得改選**）：target ∈ {15%, 25%} × lookback ∈ {20d, 40d}。
- 成本：fee 0.05%/side（原判值，不下調）＋ **新增** slippage 0.01%/side（原判漏項，從嚴）；
  funding PnL 按 HL `fundingHistory` 實際費率逐日計入（多單付正費率、空單收正費率）。
- 資料窗**釘死**：2024-07-02 00:00 UTC → 2026-07-02 00:00 UTC 日線，與原判同源同窗；
  腳本內硬編碼時間戳，禁止「從今天回推 N 天」。

## 3. Gates（全部對主配置判定）

| Gate | 判準 | 出處 |
|---|---|---|
| G-A1 | 全窗淨 Sharpe ≥ 0.5 且 總報酬 > 0 且 MDD ≤ 20% | 原判三關原封不動 |
| G-A2 | split-half：前半與後半各自 Sharpe > 0 且 MDD ≤ 25% | 一致性（防單段 regime 撐全場） |
| G-A3 | **DSR > 0**（95% 信心）：試驗數 N=8（原判 1＋審計變體 6＋本主配置 1），SR 方差取自 8 個試驗的實際 SR，偏度/峰度取自主配置日報酬 | Bailey & López de Prado deflated Sharpe |
| G-A4 | 成本 ×1.5（fee 與 slip 同乘）下：Sharpe ≥ 0.4 且 MDD ≤ 22% | 成本穩健性 |

**判定語義（先寫死）**：四關全過 → **conditional GO（假說復活級）**——因為審計已看過
同窗結果，本重測不構成樣本外證據；真 OOS＝下一階段 paper/forward（§5）。
任一關不過 → momentum 維持 NO-GO，本線收檔，不再有下一輪 sizing 變體。

## 4. 誠實條款

- 審計發現的「窗口未釘死」與「spec 承諾 walk-forward OOS＋DSR 未實作」在本協議中
  以 §2 釘窗與 G-A2/G-A3 補課；原 spec 的 walk-forward 在「無參數選擇」的本設計下
  退化為 no-lookahead＋split-half，如實聲明。
- funding 資料若有缺洞（API 保留期／幣種上市晚），缺洞期以 0 計並在報告標注天數。
- 敏感度組若與主配置判定方向矛盾（主過、多數敏感度不過），verdict 必須降級敘述。

## 5. 通過後的路徑（先寫死，防止臨場加速）

conditional GO → 引擎 sizing 實作（`src/hlvault/momentum/risk.py` 加 vol-target，
帶回歸測試）→ **paper/dry-run ≥ 4 週**（真 OOS）→ 屆時實測 Sharpe 方向為正且
MDD 路徑符合模型 → **上實盤前必問 owner（紅線）**，初始規模由 owner 依配置框架定。

## 6. 執行與驗證

實作腳本 `scripts/research_momentum_voltarget.py`（基於審計重現碼改造：釘窗、加滑價、
split-half、DSR、gates 表）；輸出 `reports/momentum-voltarget-retest-verdict.md` 草稿
＋逐日報酬 csv（`data/momentum_retest/` gitignored）。fresh verifier 從 csv 重算
全部 gate 數字；opus 第二意見只看數字表。
