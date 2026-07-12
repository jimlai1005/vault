# Momentum Vol-Target Retest Verdict：**NO-GO，本線收檔**

**狀態：定稿（2026-07-12）——fresh verifier 重算通過＋opus 二審收斂，見文末終審章節**

依據：`docs/superpowers/specs/2026-07-12-momentum-voltarget-retest.md`；基底碼：`reports/audit/repro_momentum_sizing_funding.py`；腳本：`scripts/research_momentum_voltarget.py`

**資料窗（釘死）：** 2024-07-02 -> 2026-07-02 (731 天 x 4 幣：BTC, ETH, SOL, HYPE)
**成本模型：** fee 5.0bps/side + slip 1.0bps/side = 6.0bps/side（單邊，換手時計）；G-A4 用 x1.5 = 9.00bps/side
**funding 缺洞天數**（有價格但無 funding 樣本的可交易日，缺洞以 0 計入）：BTC=0；ETH=0；SOL=0；HYPE=0；合計 0 天

## Gates 判定表

| Gate | 判準 | 結果 | 數字 |
|---|---|---|---|
| G-A1 | Sharpe>=0.5 且 總報酬>0 且 MDD<=20% | FAIL | sharpe=0.182, total_ret=3.1%, mdd=-20.0% |
| G-A2 | split-half 各半 sharpe>0 且 mdd<=25% | FAIL | 前半 sharpe=-0.096 mdd=-20.0%；後半 sharpe=0.411 mdd=-19.2% |
| G-A3 | PSR>=0.95（DSR） | FAIL | PSR=0.4652, SR=0.009536, SR*=0.012762 |
| G-A4 | 成本x1.5：sharpe>=0.4 且 mdd<=22% | FAIL | sharpe=0.133, mdd=-20.2% |

**綜合判定：NO-GO（至少一關不過，本線收檔，不再有下一輪 sizing 變體）**

## G-A1 主配置全窗數字

target=20%, lookback=20d, 槓桿上限=3x, entry_threshold=0.5, universe=['BTC', 'ETH', 'SOL', 'HYPE']

- Sharpe (ann., x19.1050) = 0.1822
- 總報酬 = 3.09%
- MDD = -19.96%

對照：原判 flat-3x（同一釘死窗，backtest.py 未改動、無 funding）：
- Sharpe = 0.2864, 總報酬 = -23.70%, MDD = -65.07%

## 敏感度組（僅呈報，不參與判定）

| target | lookback | Sharpe | 總報酬 | MDD | csv |
|---|---|---:|---:|---:|---|
| 15% | 20d | 0.155 | 2.2% | -17.5% | `sensitivity_target15_lb20d_daily_returns.csv` |
| 15% | 40d | 0.382 | 12.3% | -19.4% | `sensitivity_target15_lb40d_daily_returns.csv` |
| 25% | 20d | 0.218 | 4.6% | -22.1% | `sensitivity_target25_lb20d_daily_returns.csv` |
| 25% | 40d | 0.412 | 16.2% | -24.7% | `sensitivity_target25_lb40d_daily_returns.csv` |

## Split-half（G-A2）

| 半段 | 起訖 | Sharpe (ann.) | MDD（各半自己起點起算） |
|---|---|---:|---:|
| 前半 | 2024-07-02 -> 2025-07-01 | -0.096 | -20.0% |
| 後半 | 2025-07-02 -> 2026-07-02 | 0.411 | -19.2% |

## DSR 中間量（G-A3）

8 個試驗（日頻、未年化 SR = mean(r)/std(r, ddof=1)）：

| # | 試驗 | SR (daily) |
|---|---|---:|
| 1 | 原判 flat-3x（無 funding） | 0.014993 |
| 2 | vt20_lb20+funding（=主配置） | 0.009536 |
| 3 | vt15_lb20+funding | 0.008124 |
| 4 | vt25_lb20+funding | 0.011386 |
| 5 | vt30_lb20+funding | 0.012621 |
| 6 | vt20_lb10+funding | -0.009456 |
| 7 | vt20_lb40+funding | 0.020955 |
| 8 | 主配置（重複列入） | 0.009536 |

- V = var(8 個 SR, ddof=1) = 0.00007651
- N = 8, γ (Euler-Mascheroni) = 0.5772156649
- z(1-1/N) = 1.150349, z(1-1/(N·e)) = 1.685097
- SR* = sqrt(V) x [(1-γ)z(1-1/N) + γ·z(1-1/(N·e))] = 0.012762
- 主配置日報酬：n = 730, SR = 0.009536
- γ3（偏度，主配置日報酬）= 0.388834
- γ4（峰度，non-excess，主配置日報酬）= 10.974048
- PSR = Φ((SR-SR*)·sqrt(n-1) / sqrt(1-γ3·SR+((γ4-1)/4)·SR²)) = 0.465239
- **判準 PSR>=0.95：FAIL**

## G-A4 成本穩健性

成本 x1.5（fee 7.500bps + slip 1.500bps = 9.000bps/side）：
Sharpe = 0.133, 總報酬 = 0.7%, MDD = -20.2%

## 額外發現：主配置對窗口右端點極度敏感（非四關之一，但直接影響對本次 NO-GO 的解讀）

主配置（target=20%/lookback=20d/lev cap=3x + funding）之 Sharpe 在窗口右端點僅位移
10 天內劇烈跳動，且方向不一致——這不是本腳本的 bug（已用 repro 原函數在同一窗口
逐位元核對，數字完全吻合，見下方核對記錄），而是這個 sizing 方案本身對取樣窗邊界
極度敏感的直接證據：

| 窗口右端點 | 成本模型 | Sharpe | 總報酬 | 來源 |
|---|---|---:|---:|---|
| 2026-07-02（本協議釘死窗） | fee+slip 6bps | 0.182 | +3.1% | 本腳本主配置 |
| 2026-07-11（審計原log窗） | fee-only 5bps | 0.568 | +26.6% | `reports/audit/repro_momentum_sizing_funding.log:27` |
| 2026-07-12（今日重跑，核對用） | fee-only 5bps | 0.412 | +16.2% | 本次核對重跑，逐位元吻合 repro 原函數同窗結果 |
| 2026-07-12（今日重跑，核對用） | fee+slip 6bps | 0.396 | +15.3% | 同上，僅加回 slip 後 |

核對方法：把 `reports/audit/repro_momentum_sizing_funding.py` 當模組匯入，在同一窗口
（2026-07-12 收盤）分別呼叫其原始 `vol_target_with_funding`（fee-only 0.0005）與本腳本
的 `vol_target_backtest`（同一 funding panel、同一 cost_rate=0.0005），兩者 Sharpe 到小數點
第 10 位吻合（0.4116782421325865 vs 0.4116782421325871）——證明本腳本的引擎與審計原碼
行為一致，上表的落差 100% 來自「窗口右端點」與「成本模型微調（+1bp slip）」，且成本
微調的影響很小（0.412→0.396，同一窗口），窗口位移的影響才是主因（0.568→0.412，僅
差 1 天）。

**解讀：** 審計當初看到的「4/6 組過關」結論，其強度本身就坐在一個對取樣窗邊界極不
穩定的知識邊緣上——換一個只差幾天的收盤窗，同一組參數的 Sharpe 可以腰斬。這件事
本身就是本協議釘窗＋split-half＋DSR 三道機制想抓的問題，而釘死、預先註冊的窗口
（非審計當時「順手」用的窗口）算出來的主配置確實四關全不過，與這個窗口敏感性
觀察互相印證，而非互相矛盾。

## 誠實條款

- 本重測與原判/審計同窗，不構成樣本外證據；真 OOS 見協議 §5（paper/dry-run ≥4週）。
- funding 缺洞期以 0 計入（見上方缺洞天數統計），非零缺洞代表該期間的 funding PnL 被低估為 0（低估方向依當期真實費率正負而定，未逐一定向核實）。
- DSR 的試驗集（N=8）由本協議預先鎖定（原判 1＋審計變體 6＋主配置 1，含主配置與其一變體重複列入），非事後從更大候選集挑選最小方差組合。
- 敏感度組非判定依據，僅供解讀穩健性方向；判定看四個 Gate（G-A1~G-A4，G-A4 是四關之一）。

---
## 終審（2026-07-12）

**驗證**：fresh-context verifier 從逐日報酬 csv 獨立重算 G-A1/A2/A3（誤差 <0.1%，PSR 完美吻合）；
G-A4 初缺 csv，補檔後重跑對照吻合（Sharpe 0.1329/MDD -20.22%）。equity 曲線與報酬欄自洽至 1e-10。

**opus 二審（獨立、只看數字）**：NO-GO、收檔正確，判定收斂。要點採納入檔：
- 0/4 過關且非邊際：G-A2 前半 Sharpe 為負（-0.096）——全部正報酬靠後半單一 regime；
  G-A3 觀測 SR（0.0095/日）低於去膨脹門檻 SR*（0.0128），統計上無法拒絕「真 SR ≤ 0」。
- 「9 天端點位移使兩年 Sharpe 從 0.57 掉到 0.18」是**厚尾＋近零 edge 的指紋**
  （γ4=10.97：少數幾天主宰全部損益）；端點敏感性是 G-A3 的視覺版，兩者互相印證。
  審計窗多吃到的 2026-07 初那波是幸運端點，不是可重複訊號。
- 「等更多資料再測」＝window shopping，正是釘窗協議要防的行為；能被 9 天位移腰斬的
  結論，是更該 NO-GO 的理由。

**結論**：momentum 訊號在誠實 sizing 與成本下仍無統計上站得住的 edge。依協議 §3：
**維持 NO-GO，本線收檔，不再有 sizing 變體**。審計 item A 關閉。sizing 修正的唯一
遺產：MDD 從 -65% 收斂到 -20%，證明 vol-target overlay 本身有效——它值得成為未來
任何新策略的標配 sizing 層，但救不了沒有 edge 的訊號。

**制度回寫**：釘窗規則已入 `~/.claude/rules/judgment.md` §5（回測視窗硬編時間戳＋
端點敏感度檢查），2026-07-12。
