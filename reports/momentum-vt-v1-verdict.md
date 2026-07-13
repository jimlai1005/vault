# Momentum-VT v1 Verdict：**NO-GO（依預先註冊 gate，本線收檔）**

日期：2026-07-13｜sub-project K｜協議：`docs/superpowers/specs/2026-07-13-momentum-vt-v1-protocol.md`
驗證：fresh verifier 從 8 格逐日 csv 重算全部 gate 數字（<1% 全數精確）＋ opus 二審收斂。

## 0. 一句話結論

Owner 的動態倉位框架把 momentum 從「Sharpe 0.22／MDD -65%」帶到「六年 OOS 八格全正、
主格 Sharpe 0.855／MDD -15.4%、2022 熊市 +7.5%」——**煞車完全驗證**；但引擎（訊號）
的 edge 集中在 2020-2022 強趨勢期、2023 起平盤，被 DSR（0.683<0.95）與 split-half
（後半 -0.05）兩關正確攔下。依協議：v1 NO-GO 收檔、無參數微調輪；預先封存的條件變數
是唯一合法的 v2 路徑，holdout（2026-H1）完好未動、留給 v2。

## 1. Gates 判定（主格 cell 2：15%/40d/U-fixed；OOS 2020-07→2025-12，2010 天）

| Gate | 判準 | 結果 | 數字 |
|---|---|---|---|
| G-K1 | Sharpe≥0.6 且 DSR(N=17)≥0.95 | **FAIL** | Sharpe 0.855 ✓／PSR 0.683 ✗；HAC-t 2.004 |
| G-K2 | MDD ≤20% | PASS | -15.35% |
| G-K3 | ≥3/5 時代為正、≥2 在乾淨窗 | PASS | 牛 +70.9%、熊22 +7.5%、熊25H2 +3.0%（震盪23 -1.5%、牛尾 -2.1%） |
| G-K4 | 鄰域 ≥2 格 Sharpe≥0.3 同號 | PASS | 3/3（1.036/1.012/0.550） |
| G-K5 | 端點穩＋split-half 各半>0＋成本×1.5≥0.45 | **FAIL** | 端點 0.853-0.859 穩✓、成本×1.5 0.831✓、split 1.532/**-0.052** ✗ |

8 格全覽：固定宇宙四格 Sharpe 0.86-1.04、PIT 四格 0.49-0.68，全正；MDD 全部 15.3-19.7%
（緊貼 20% 設計上限＝vol-target 與 DD 階梯確實 binding）。成本＋funding 全計入（缺洞 0 天）。

## 2. 兩個 FAIL 的實質（opus 二審精煉，採納）

- **G-K1（DSR）對試驗集構造穩健**：即使只用本次 8 個同窗格重算（V 縮到 1.34e-4），
  DSR≈0.90 仍不過；raw 訊號本就只有 HAC-t≈2.0 的勉強顯著，誠實的多重檢定折損
  正確地把它壓下去。非混叢集人為造成。
- **G-K5（split-half）與時代表互為佐證**：全部累積 edge 在 2023-04 之前（強趨勢期，
  且**雙向**都賺——2022 熊市空側 +7.5%）。辨別維度是**趨勢持續性**，不是方向；
  「哪個 regime 變數能捕捉它」仍是假說（信心低-中，屬事後分期敘事）。

## 3. Owner 命題的判定：框架本身

「給策略煞車，不是放寬速限」——**煞車層驗證通過，但限縮表述**：
- 已證：MDD 從 -65% 圍堵到全格 ≤19.7%（貼設計上限）；DD 階梯全程行為正常；
  執行期抓出並修復兩個邊角死鎖（§4b-5 小活躍集、§4b-7b 空簿吸收態），皆有單元測試。
- 未證（opus 反面提醒，採納）：階梯在震盪期低點砍倉、晚回補，可能**本身貢獻了
  2023-25 的平盤**——「訊號死了」與「煞車放血」無法在本資料分離。
- 結論：對其他策略是「**回撤圍堵層**的可複用預設（連同 19 條測試移植）」，
  **不是**報酬中性的 drop-in 標配；逐策略須重測其與報酬的交互。sub-project L
  （CTA staged sizing）可直接引用本結論與引擎。

## 4. v2 路徑（owner 裁決；協議預先允許）

封存的條件變數是唯一合法重開方式。優先序依 §2 證據：**A2a 訊號強度縮放**（趨勢
持續性維度，與失敗模式對位）> A2b 200SMA 方向閘（會錯砍 2022 空側獲利，對位差）
> A2c 事件日曆。方法論陷阱（opus，全部採納入 v2 前置條件）：
1. **試驗數累計**：v2 的 DSR 帶著 v1 的 17 個試驗繼續加，不得歸零。
2. **資料窗污染聲明**：「2023+ 平盤」的觀察已污染 2020-25 窗對 regime 假說的檢定力；
   v2 的真 OOS 只剩上鎖的 holdout（2026-H1，僅 6 個月）＋前向 paper。
3. 分期邊界與 regime 變數定義必須在看數字前預先註冊。
4. holdout 維持上鎖直到 v2 gates 註冊完成，屆時一次跑完封存。

## 5. 紀律紀錄

- §4b 累計 9 條執行期裁決，全部在污染窗（dev）內攔截：quote-volume 誤篩、funding
  分頁、滯後慣例、subset-cov、小活躍集 cap、空簿死鎖、端點適配、煙測誤觸 formal
  （作廢隔離＋N 16→17＋機械鎖補救）。
- 正式運行一格一 commit（`reports/k-formal-runs/`）；formal 視窗運行後重新上鎖；
  **holdout 從未被任何進程觸碰**。
- 所有 gate 數字經 fresh verifier 自 csv 重算（equity/ret 自洽 1e-5、OOS 日期精確、
  funding 非零驗證）；opus 二審獨立收斂 NO-GO。

## 6. 資產清單

引擎 `scripts/k_vt_engine.py`（19 測試）、runner＋gates `scripts/research_k_vt_v1.py`／
`k_gates_eval.py`（雙視窗機械鎖）、六年半資料底座（529 symbols 日線＋PIT 宇宙時間表＋
全史 funding）、`reports/k-gates-draft.md`（數字全表）、`reports/k-engine-attribution.md`
（引擎歸因）、本檔。momentum 原案兩個 NO-GO 不變；本 verdict 掛 Momentum-VT v1。
