# HL 錢包 0xf97a…ddd1 複查（2026-10-15）：crypto／美股／合併三段跟單比較

地址：`0xf97ad6704baec104d00b88e0c157e2b7b3a1ddd1`（gridbot 原型錢包）。初版 2026-09-21 在 `reports/wallet-0xf97a-2026-09/`。
本次使用者的問題：把帳戶拆成「只有 crypto」「只有美股」「美股＋crypto」三部分，哪一部分跟單的勝率與 Sharpe 較高。
完整報告併入 pandora 同一份：`~/projects/obsidian/pandora/wallets/hl-0xf97a...ddd1-深度接刀階梯HYPE網格.md`（最上面「更新 2026-10-15」節）。

## 結論

- **勝率不分段**：crypto 87.9%、美股 81.3%、其他 HIP-3 78.7%、合併 84.8%（回合勝率）；日勝率 55–66%。勝率來自「賺一點就吃單出、虧的抱著」的出場方式，三段相同，不是選段的依據。
- **Sharpe（perp 按 HL 日收盤 MTM，共同窗口 2026-01-26 → 10-15）**：其他 HIP-3 3.85 ＞ crypto 3.01 ＞ 美股 1.56；合併 3.71、crypto＋美股 3.23。三段日損益相關只有 0.04–0.17，所以合併優於單挑 crypto。美股段最低：PnL 的 90% 集中在 5 天（SNDK／MU 2026-06～08），10 月 7 檔股票多單浮虧 −16k。
- **跟單評分（spec v0.6）**：美股 89 通過、其他 HIP-3 96 通過（部位小、MDD 占權益 <2.5%）；crypto 84、合併 84 都卡 G3（移除最佳 15–16 天轉負）。注意 copier 淨利≈領單者 2 倍是 C_t/L_t 比例膨脹（領單者 2026 年提走 1.9M＋送出 1.2M，L_t 從 1.9M 降到 0.6–0.8M），不是模型跟得比較好。
- **其他 HIP-3 的好數字是一次 regime**：CL 原油 64 趟 94% 勝 +75k（空單為主，2026-05 一個月 +53k＝全段一半）＋三星／海力士多單。美股段是 AI 硬體股那一波。crypto 段賺最多（perp +840k）、PF 47，但 MTM 回撤 15–18%、單日 20% 事件集中（2025-10-10）。
- **增量（9/20 → 10/15）**：3,466 筆、已實現 +33.9k、無 ≥10k 大日；現在 12 個部位全多（HYPE 5,000 顆 399k、7 檔股票 288k）、毛曝險 1.01× 權益、浮虧 −32.6k；57 張掛單（55 買）名目 2.53M＝權益 3.1 倍。

## 資料與腳本（自 `wallets-batch-2026-09b/scripts/` 複製，兩處修正＋一支新腳本）

```
fetch_wallet.py → fetch_twap.py（0 筆）→ fetch_funding_recent.py → equity_recon.py → triage.py → analyze.py（0 real DRIFT）
segments.py 0xf97ad670           → data/0xf97ad670/segments.{txt,json}   三段拆分（本次新增）
copyscore.py 0xf97ad670 [--segment crypto|us_stock|other]  → copyscore[_seg].{txt,json}
```

| 項目 | 說明 |
|---|---|
| `segments.py`（新） | coin → crypto／us_stock／other 分類表（xyz dex 名單手寫：美國上市單一股票／ADR／ETF／指數＝美股；商品、外匯、非美股票、未上市＝其他）；每段回合（與 analyze.py 同一翻倉切法）、已實現與 MTM 日損益、Sharpe（$ 口徑 √365，含零日）、Sortino、MDD（$ 與占 L_t）、日勝率、最佳 1／5 日占比、分季、逐時、月表；另給 crypto_perp（不含現貨）與共同窗口表 |
| `copyscore.py --segment`（改） | 依 `segments.json` 只保留該段 fills，輸出 `copyscore_<seg>.*`；比例分母仍是領單者總權益 L_t |
| `copyscore.py` 種子修正（改） | **窗口起點已有部位要種子化**：fills 被 API 截斷時，某幣第一筆 fill 的 `startPosition` ≠ 0；原版 book 從 0 起算，HYPE 25k 顆多單被當成 25k 顆空單，copier 在 2026-09-03 以 67× 槓桿「爆倉」、領單者 MTM 淨 −101k。修正後以第一筆價格補一筆合成開倉（`synthetic_seed`），領單者 MTM +1.04M、合併分數 84。`segments.py` 的 MTM book 同樣種子化 |
| `increment.txt` | 9/20 快照 → 10/15 的增量：掉出窗口的 9/18–9/25 成交 −178k、新增 3,466 筆 +33.9k、帳本流向、HYPE 逐日部位 |
| `segments_combo.txt` | crypto_perp＋us_stock 合併序列、三個窗口（全／共同／2026-03 起）的 Sharpe、三段相關係數 |

## 資料極限

- 成交 36,690 筆＝API 保留上限，最早 2025-09-26（初版的 9/18–9/25 已掉出，含三個 −35k～−68k 的 HYPE 大虧日）。全窗口已實現 +888k vs 初版 +676k 的差＝掉出 −178k ＋ 增量 +34k，不是新賺的。
- 權益對帳差 −2.2%（793,103 vs portfolio 810,561）：PIP 5,011 顆、HAR 3,834 顆現貨幣未計價（約 12.6k）。
- MTM 用 HL 1d 收盤，日粒度；窗口起點部位以第一筆價格當成本（起點未實現＝0 的約定），所以 2025-09 的 HYPE 浮虧不在 MTM 序列裡。現貨只算已實現（closedPnl 是對歷史成本的會計數，9/30 −131k 仍在 crypto 段）。
- 美股／其他兩段的分類是手寫名單；`para:MELI`、`xyz:CBRS`、`xyz:DRAM` 歸「未分類 HIP-3」進其他段。
- 跟單評分的 C_t/L_t 比例在領單者提款後膨脹到約 3–4×（spec v0.4 §1.2 凍結：L_t＝交易所自報權益，不淨化存提）；segment 分數與整體分數之間不可加總。
- 300 顆批次（`wallets-batch-2026-09b`）跑的是未種子化的 copyscore.py：窗口起點帶著大部位的錢包分數可能失真，尚未重跑。
