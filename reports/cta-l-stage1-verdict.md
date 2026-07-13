# CTA Staged Sizing（sub-project L）Stage 1 Verdict

**狀態：定稿（2026-07-13，owner 裁決）。**
**判定：Stage 1 五關全過（依 owner 裁決之 MDD 固定基底慣例，spec §8 修正案 1）→
B1 確立（V1 成為新 baseline）、Stage 2 開啟（依 spec 紀律：先 commit Stage 2 協議
細化再動工）。**

兩點必須與判定同時讀：
1. **G-L2 是邊緣 PASS（4/6 恰踩門檻），且其 PASS/FAIL 取決於一個 spec 未預先寫死、
   事後由 owner 裁決的公式慣例**——在證據鏈指向的另一讀法下它是 3/6 FAIL、全案 NO-GO
   （§4 完整揭露）。依 spec §6.5，本判定不得被引述為「穩健通過」。
2. 修正案是在**看到它會翻轉結論之後**通過的（post-hoc），此性質已記錄於 spec §8 與本檔 §3。

Spec：`docs/superpowers/specs/2026-07-13-cta-staged-sizing-design.md`（預註冊 `bac27c7`；
修正案 1 與本 verdict 同日 commit）。執行軌跡見 §8。

## 1. Gate 結果（官方：固定基底慣例，spec §8 修正案 1）

主窗 2020-09-14→2026-06-30（2116 日），標準成本 0.055%/side，config `4h-p10-fuel24`
（short book），B0 = m≡1.0 固定 notional，V1 = σ_target 60%／EWMA span 180／
clip [0.25, 1.0]、進場鎖定、cap-only。全精度來源：`data/cache/cta_l/gates_table_t6.md`
（盲測驗證者表，經機械對帳證明與實作者 pipeline 換式後 71/71 逐位一致）。

| Gate | 定義（spec §3:107-111） | 結果 | 判定 |
|---|---|---|---|
| G-L1 | 全窗 MAR(V1) ≥ 1.3×MAR(B0) | 0.2994 vs 0.1089，比值 **2.75** | PASS |
| G-L2 | 6 折中 ≥4 折 MAR(V1) ≥ MAR(B0) | **4/6**（F1✓ F2✓ F3✗ F4✗ F5✓ F6✓） | **PASS（邊緣）** |
| G-L3 | paired block bootstrap ΔSharpe 90% CI 下界 > −0.15 | Δ=+0.193，CI [−0.029, +0.416] | PASS |
| G-L4 | 成本 ×1.5 下重複 G-L1 | 比值 3.33 | PASS |
| G-L5 | 端點 −30/−60/−90d 方向零翻轉 | 3/3 V1≥B0 | PASS |

全窗數字（固定基底）：B0 年化 +3.66%、MDD −33.62%、Sharpe 0.307；V1 年化 +4.55%、
MDD **−15.21%**、Sharpe 0.500。trades 兩腿同為 759 筆（sizing 不改變進出場，T2 guard 證明）。

**G-L2 邊緣性（spec §6.5）**：4/6 恰好踩線；關鍵折 F5（2025）V1 僅領先 3.9%
（7.92 vs 7.63），F3/F4（2023/2024 平盤年）V1 落後。逐年一致性的證據本質上是弱的——
在兩種慣例下 G-L2 都貼著門檻（4/6 vs 3/6），這一點不因裁決而改變。

## 2. 驗證事件：兩份獨立計算在 G-L2 相反（本案最重要的過程紀錄）

- 實作者（T5，`scripts/cta_l_stage1_gates.py`）：MDD=(eq−peak)/peak（running-peak）
  → G-L2 **3/6 FAIL**。
- 盲測驗證者（T6，`scripts/cta_l_stage1_verify_t6.py`，只拿 spec §2-§3 原文＋csv，
  禁讀實作）：MDD=(eq−peak)/eq₀（固定基底）→ G-L2 **4/6 PASS**。
- 機械對帳（fresh agent，腳本已收入 repo，見 §8）：把 T5 pipeline 的 MDD 公式換成
  固定基底、其餘一切不動，**71/71 個數值格與 T6 逐位一致（殘差 0）**——慣例差是唯一
  根因。G-L3 的 CI 微差（[−0.031,0.419] vs [−0.029,0.416]）為同 seed 下 bootstrap 抽樣
  結構不同，點估計位元級一致，gate 不受影響。
- spec §2:39-42 寫「固定 $500 基底……非複利，MDD 同基底計算」，未寫顯式公式——
  協議級劣定義，預註冊時經兩輪 opus 對抗審查未被發現。

## 3. 裁決鏈與 owner 裁決

1. **opus 盲測初判**（只給 spec 原文）：判固定基底、高信心（§3:114 縮放不變性代數僅
   固定基底成立；§6:178 歸因；分子單位）。並預留一刀定案檢驗：−148% artifact 是否曾負權益。
2. **provenance 開獎**（機械對帳溯源）：−148% 出自 **running-peak** 公式
   （`cta_proxy_multiyear.py:115` → `cta_proxy_lib.py:224-225`），layer2b 腳註自證非複利
   曲線跌破零；repo 三個先例＋方法論模板實算腳本皆 running-peak；spec §1:20 自引
   「MDD 錨 −32%」與 running-peak 的 −32.504% 吻合（固定基底為 −33.619%）。
3. **opus 重審**（補交 provenance）：改判 **running-peak 為作者本意**、高信心。自認原判
   錯在把未經驗證的散文式性質宣告排在作者實算慣例之上。
4. **owner 裁決（2026-07-13，行使 plan T7 預寫裁決權）**：裁定預註冊本意為**固定基底**，
   以 spec §8 修正案 1 顯式寫死公式＋數值錨。本 verdict 依裁決改判。
   如實記錄：此裁決與步驟 2-3 的證據鏈方向相反，且發生於結果已知之後（post-hoc）；
   owner 是 spec 的作者與唯一權威，裁決權本身無疑義，記錄僅為完整性。

## 4. 另一讀法（running-peak，證據鏈指向的作者本意）下的結果——完整揭露

G-L1 比值 2.70 PASS、**G-L2 3/6 FAIL**（F5 翻向：8.23 vs 8.94，V1 落後 8%；F3/F4 差距
−0.053／−0.026 MAR）、G-L3/G-L4（3.27）/G-L5 同 PASS → **4/5，依 spec §3 語義全案
NO-GO、收檔禁變體**。全窗數字：B0 MDD −32.50%、V1 MDD −14.95%（全精度來源
`data/cache/cta_l/gates_table.md`）。任何引用本 verdict 的後續研究，必須同時引用本節。

## 5. 兩種讀法皆成立的結果（與 K 案互證）

不論慣例：**回撤圍堵再次驗證**——V1 將 MDD 從 −32.5% 壓到 −14.9%（running-peak）／
−33.6% 壓到 −15.2%（固定基底），MAR 比值 2.70-2.75×，成本 ×1.5 與三個端點全部穩健，
ΔSharpe 點估計 +0.19（非劣性大幅過關）。弱點軸只有一條：**逐年一致性**（2023/2024
平盤年 V1 不優於 B0）。與 K verdict §3 的限縮結論同構：vol-target 是可複用的「回撤
圍堵層」，不是逐 regime 皆改善的 alpha。m 分佈（trade 級，n=759）：median 0.869、
m=1.0 佔 35.7%、觸地板 0.66%——乘數實際在工作，非貼邊。敏感度組（σ_target 40/80、
span 90/360）全窗 MAR 0.234-0.295，皆 >2× B0——圍堵結論對參數不脆弱（一致性結論
未做敏感度折表，不外推）。

## 6. 誠實條款（繼承 spec §6，加上本次新增）

1. Proxy 極限：funding≠持倉、volume≠OI（layer2b 量級偏弱），全部 L 結論繼承。
2. pseudo-OOS：資料已被反覆探索；本 verdict 的 PASS 不構成實盤訊號生死判定，
   live 配置維持凍結（sizing 變更仍屬紅線，逐次 owner 核准）。
3. funding accrual 未建模（方向幅度未知）。
4. 常數（σ_target 60%、clip 0.25、4/6、−0.15）是 ex-ante 判斷非校準。
5. G-L2 兩種慣例下都貼門檻（4/6 邊緣 PASS vs 3/6 FAIL）：不得寫「穩健通過」；
   B1 的確立主要靠 G-L1/G-L4/G-L5 的圍堵證據，不靠一致性證據。
6. headline 判定含一步 owner 的 post-hoc 慣例裁決（§3.4），與證據鏈方向相反——
   引用本 verdict 時此事實不可省略。

## 7. 協議教訓（依 maintenance.md 寫回制度）

1. **gate 公式必須以顯式方程式＋一個可機器驗證的數值錨例預註冊**——散文式定義擋不住
   雙讀法。本案有四道防線（預註冊兩輪 opus 對抗審查、spec §2「同源同基」條款、
   discretion log 制度、盲測驗證）仍讓劣定義活到看結果之後才爆。已寫入 judgment.md §5。
2. 盲測驗證者的價值：**它抓到的不是計算錯誤，是協議劣定義**——兩份計算都「對」，
   對的是不同的題目。維持 T6 制度。
3. 證據優先序（opus 重審自陳）：spec 內嵌具體數值（可反推公式）＞ 同模板實算先例 ＞
   未經驗證的散文式性質宣告。

## 8. 追溯

- 引擎與驗收：`scripts/cta_l_stage1.py`（T2/T3，四條 guard＋三條 σ 驗收全過）、
  `scripts/cta_l_stage1_selftest.py`、`scripts/cta_l_stage1_selftest_t3.py`、
  `scripts/cta_l_stage1_runs.py`（T4，14 runs → `data/cache/cta_l/`，gitignored 可重生）。
- Gate 計算：`scripts/cta_l_stage1_gates.py`（T5，running-peak 版）；盲測重算
  `scripts/cta_l_stage1_verify_t6.py`（T6，固定基底版＝修正案 1 官方公式）。
- 對帳：`scripts/cta_l_stage1_recon_mdd.py`（T5 pipeline 換固定基底重算全表）＋
  `scripts/cta_l_stage1_recon_diff.py`（對 gates_table_t6.md 逐格比對，71/71 一致）。
- −148% artifact 溯源：`reports/cta_proxy_layer2b_verdict.md:82,86-90`；
  opus 兩輪裁決全文存 session 記錄。
- 下一步：Stage 2 協議細化（三個逐一掙門票 ablation：事件日曆／crowd 百分位訊號強度／
  BTC-200SMA regime），依 spec §4-§5 與修正案 1 的公式紀律，先 commit 再動工。
