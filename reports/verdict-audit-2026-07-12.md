# Verdict Audit 綜合報告（sub-project J）

日期：2026-07-12｜方法：finder（sonnet）×9 → verifier 獨立重現 ×6 → placebo 對照 ×1 → opus 二審
範圍：全部 8 個 NO-GO 判定＋跨案成本掃描。憲法見 `docs/superpowers/plans/2026-07-12-verdict-audit-plan.md`。

## 0. 執行摘要

- **沒有任何一案達到「立即翻案」標準**（bug 修正後過原 gate 的決策相關格，或假設修正＋樣本外確認）。
- **一個高期望值重開案**：momentum——vol-target sizing＋補漏算的 funding 後，4/6 參數組通過
  全部原 gate；這是全場唯一「不是挑格挑出來」的翻案線索（機制是 spec 自己的 MDD 預算）。
- **一個強制性 verdict 修正**：trader-selection OOS——真 bug（年資 gate 把上架前 0 填充當
  交易史）使原判「決定性為負」失真，真相是「證據不足、雜訊主導」（修正後三配置 |t|<1.1）。
- **五個報告修正級發現**（不動判定、要改已 commit 的報告與程式）＋兩個衛生級 bug 修。
- 審計統計聲明：9 案 × 6-7 維度 ≈ **56+ 次找錯機會**；兩個 maybe-flip 恰好聚集在資料最薄的
  兩案（n=5 單格、無第二 OOS 窗）——opus 二審指出這種聚集本身即 selection artifact 的證據。

## 1. 逐案處置表（全部經 verifier 重現）

| 案 | 關鍵發現 | 處置 | 依據 |
|---|---|---|---|
| momentum | 【假設】flat-3x sizing 是 MDD -65% 的主因：20% vol-target＋funding 後 4/6 組過全部原 gate（Sharpe 0.57-0.69、MDD -17~-20%）；【bug】funding 全漏（方向：原判過寬）；【bug】spec 承諾的 walk-forward OOS＋DSR 從未實作、窗口未釘死 | **重開案**（owner 裁決 A） | `audit/J-momentum-findings.md`＋verifier 無前視確認 |
| oos-trader-selection | 【bug】年資 gate 零填充：45 天選手過 180 天門檻、單一地址驅動全部負報酬（剔除後 -22~-25%→≈0）；α 檢定 power 僅 4-6%；「吃到 beta」敘事與資料矛盾（r²=0.007）；宇宙凍結違反 spec point-in-time（方向：過寬） | **verdict 修正**（B） | `audit/J-oos-findings.md` |
| stablepairs | 【bug】z 暖機錯誤（先裁後滾＋min_periods=1）：修正後 27 格中 1 格翻轉（USDe z_peg@2.0→3.11×，n=5）；【假設】USDe staking 機會成本漏計（~1.4-11bps，吃掉該格 margin）；量能下限條款未實作 | **衛生修正，不追單格**（C） | `audit/J-stablepairs-findings.md` |
| pair-trading | 【假設，事後】剔 HYPE/TAO/TON 後 60d 家族翻正（+1.84/+1.81/+0.92）；placebo 對照×2 確認非宇宙縮小效應（placebo 組仍 -1.2）；但「剔除事後最爛 3 幣」在純雜訊下也會變好——placebo 不能洗掉這層 | **線索保留，設計 ex-ante 過濾器後新窗重測**（D） | `audit/J-pairtrading-findings.md`＋placebo log |
| cta-phase2b | 【假設，雙向抵消】Li&Ji effective-N=7.31→門檻 2.48，t=2.14 仍不過；Newey-West HAC 把 t 降到 1.91，關閉寬鬆方法的唯一 PASS 路徑；funding 影響 +0.016t 可忽略 | **無動作，NO-GO 被加固**；verdict 加穩健性附錄（E） | `audit/J-cta2b-findings.md` |
| trend-filtered-grid | 【bug】聚合 MDD 分母錯（$1k vs $4.67k：65.2%→13.96%，該格會 PASS）但 PnL 兩腿獨立判死；【bug】4h vol 窗硬編碼錯，修正後更差；濾波逐幣異質性未落檔 | **報告修正**（E） | `audit/J-trendgrid-findings.md` |
| scalp | 【bug】entry_ts 索引錯位→月度敘事失真（pooled PF/n/t 不受影響）；【bug】decomposition「毛移動」仍含滑價（F2 真零成本毛 edge +2.80bps 非 +0.88，仍 << 成本） | **報告修正＋lib 修 bug**（E） | `audit/J-scalp-findings.md` |
| compound | 【品味】12% 目標出處不可追溯；無 bug；偏誤方向（若有）為過寬 | **owner 重錨定目標**（F） | `audit/J-compound-findings.md` |
| 跨案成本 | 無 ORDER_SLIPPAGE 誤用；費率差異全有解釋；funding 處理地圖（momentum 缺席為最大項，已入案 1） | 無動作 | `audit/J-cross-costs-scan.md` |

## 2. 為什麼 momentum 是唯一重開案（而兩個 maybe-flip 不是）

- momentum 的修正**不是從結果回推**：20% vol-target 是 spec 自己的 MDD 預算、教科書技巧、
  跨參數鄰域穩健（過關組 {15%,20%,40d}；失敗的是極端參數）；且 verifier 確認無前視、
  重用原訊號碼。它輸在 sizing 層，訊號層的 alpha 未被原判測試過。
- stablepairs 單格（n=5、27 選 1、非 headline 格）與 pair-trading 剔幣（從本窗最大虧損回推）
  都是多重比較的典型產物；opus 二審與兩位 finder 一致標注不可直接翻案。
- **憲法漏洞修正（本審計的自我發現）**：「bug 修正後過原 gate＝翻案」須追加
  「**且為決策相關（headline）格**」——stablepairs F1 字面滿足卻是挑格產物。

## 3. Owner 裁決清單（勾選後進 phase 3）

- **A. momentum 重開案**【主判＋opus 一致：推薦 GO】：實作 portfolio vol-target sizing
  （順帶補 spec 欠的 walk-forward OOS＋DSR、釘死資料窗）→ 預先註冊 gate（原三關＋DSR>0，
  OOS 段判定）→ 過了才是 conditional GO → paper。估 ~1 天。
- **B. OOS verdict 修正**【推薦 GO，便宜】：修年資 gate bug（point-in-time 真實交易日）＋
  amend verdict（「決定性為負」→「證據不足/檢定力不足」＋修正 beta 敘事）。
  是否重建整條 copy-trading 管線（大工程、α 檢定 power 要重設計）另案裁決。
- **C. stablepairs 衛生修正**【推薦 GO，~1h】：修 z 暖機 bug、補量能下限條款、重跑 27 格
  落檔；單格翻轉不開專案（staking 成本吃掉 margin＋n=5）。
- **D. pair-trading ex-ante 過濾器**【中性，owner 定】：把「HYPE/TAO/TON 毒性」翻譯成
  不引用損益的 ex-ante 規則（上市月齡下限／訓練窗相關性穩定度），新資料窗（HL 1h 滾動累積）
  預先註冊重測。等窗期 ≥2-3 個月，可先掛著。
- **E. 報告修正批次**【推薦 GO，機械，~2h】：scalp entry_ts bug＋verdict §4 修正＋
  decomposition 重標（+2.80bps）；trendgrid MDD 註記；CTA verdict 穩健性附錄。
- **F. 品味項**：compound 12% 目標重錨定；stablepairs 3× 係數維持；
  **提供錢包地址跑實際費率**（`scripts/scalp_fee_check.py --user`，全部成本假設的地面真相，
  第三次提醒）。

## 4. 二審與分歧

opus 二審獨立得出與主判一致的處置與排序（momentum 最高 EV）；其三項方法學批評已採納入檔：
(1) oos/pair-trading 的 verifier 與 finder 共用快取與生產函式，只證算術一致不證資料獨立；
(2) 本審計只查 NO-GO，結構上單邊——「過寬」方向的發現全部只會加固 NO-GO；
(3) 憲法的翻案標準需加 headline-格條款（§2）。placebo 對照的「必要非充分」詮釋為主判補充，
無分歧。

## 5. 產物

findings×9＋重現腳本：`reports/audit/J-*.md`、`reports/audit/repro_*.py`；
placebo：scratchpad `PLACEBO_VERDICT.md`（結論已入 §1 表）。
所有數字經 fresh-context verifier 重現；審計期間零修改既有檔案（git 驗證）。
