# 穩定幣對現貨交易成本調查報告
**查證日期**：2026-07-11  
**研究對象**：Binance、OKX、Bybit、Hyperliquid 穩定幣現貨對  
**交易對列表**：USDC/USDT、FDUSD/USDT、DAI/USDT、TUSD/USDT、USDP/USDT、PYUSD/USDT、USD1/USDT

---

## 查證結果

### 1. Binance

| 項目 | 費率 | 來源 | 查證日期 | 備註 |
|------|------|------|---------|------|
| **基礎現貨費率** | Maker 0.100% / Taker 0.100% | https://www.binance.com/en/fee/trading | 2026-07-11 | Regular User（交易量 <$1M，0 BNB） |
| **USDC 交易對** | Maker 0.095% / Taker 0.07125% | https://www.binance.com/en/fee/trading | 2026-07-11 | 查得但不確定是否現仍有效；頁面標註「[BNB 25% off]」 |
| **USDT/USDC、DAI/USDT、TUSD/USDT、USDP/USDT、PYUSD/USDT、USD1/USDT** | **未查證** | — | — | 官方費率表未列出穩定幣對逐一費率，需直接查詢交易對或聯絡支持 |
| **VIP 折扣** | VIP 9：Maker 0.011% / Taker 0.023% | https://www.binance.com/en/fee/trading | 2026-07-11 | 高交易量用戶可取得極低費率 |

**Binance 現況**：
- 基礎費率有交易量分級（Regular User 以上分 VIP 1-9）
- USDC 對有特殊較低費率，但其他穩定幣對未見明確列表
- 無法確認是否有時限促銷（零費活動的截止日期）

---

### 2. OKX

| 項目 | 費率 | 來源 | 查證日期 | 備註 |
|------|------|------|---------|------|
| **所有穩定幣對** | **未查證** | — | 2026-07-11 | 官方頁面 404 / 內容不可訪問 |

**OKX 查證失敗原因**：
- https://www.okx.com/help/what-are-the-fees-of-okx-spot-trading → 404 Not Found
- https://www.okx.com 首頁無直接費率鏈接
- Help center 返回的內容片段未包含費率表

**建議**：查詢 OKX 官方客服或使用 OKX API 文檔中的 fees endpoint

---

### 3. Bybit

| 項目 | 費率 | 來源 | 查證日期 | 備註 |
|------|------|------|---------|------|
| **所有穩定幣對** | **未查證** | — | 2026-07-11 | 官方頁面 timeout / Access Denied |

**Bybit 查證失敗原因**：
- 直接 HTTP 訪問返回 "Access Denied" (Reference #18.24f93dd2)
- WebFetch 超時（60s 連接失敗）
- 無法取得官方費率表

**建議**：查詢 Bybit 官方支持或通過 Bybit 移動應用查看實時費率

---

### 4. Hyperliquid

| 項目 | 費率 | 來源 | 查證日期 | 備註 |
|------|------|------|---------|------|
| **穩定幣對基礎費率** | Taker: 0.014% (基礎費率 × 0.2，80% 折扣) | https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees | 2026-07-11 | Spot pairs between two stable quote assets |
| **支持的穩定幣對** | USDT/USDC 等穩定幣對 | https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees | 2026-07-11 | 現貨市場支持穩定幣對；Maker rebates 同樣享 80% 折扣 |
| **分級費率** | Base tier (0 volume): 0.014% taker | https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees | 2026-07-11 | 高交易量用戶費率可能更低（未查詳細分級） |

**Hyperliquid 現況**：
- 穩定幣對費率固定為基礎費率的 20%（0.014% taker）
- 無時限促銷，為永久政策
- 結構上是所有穩定幣對統一費率（不分 USDC/DAI/TUSD 等）

---

## 穩定幣對典型 Spread 寬度（bps）

| 交易所 | 交易對 | Spread（bps） | 來源 | 備註 |
|------|------|-------|------|------|
| **Binance** | USDT/USDC 等 | **未查證** | — | 官方未列公開數據；需實盤觀察或查 API |
| **OKX** | — | **未查證** | — | 官方頁面無法訪問 |
| **Bybit** | — | **未查證** | — | 官方頁面無法訪問 |
| **Hyperliquid** | USDT/USDC 等 | **未查證** | — | 文檔未公開 spread 數據 |

*說明：Spread 宽度（買賣價差）是実盤數據，各交易對各時刻不同，通常需實時監控而非事前查詢。*

---

## 結論

### 💚 明確可行的成本

**最便宜的選項**：
- **Hyperliquid** 穩定幣對：**0.014% taker fee**（固定，無時限）
- **Binance** 基礎費率：**0.100% taker**（Regular User）；如持 BNB 或交易量大可更低

**成本差異**：Hyperliquid vs Binance ≈ 86 bps/side（0.100% - 0.014% ≈ 0.086%）

### ⚠️ 無法確認的項目

1. **OKX 穩定幣對費率**：官方頁面無法訪問（404）
2. **Bybit 穩定幣對費率**：官方頁面無法訪問（Access Denied）
3. **Binance DAI/TUSD/USDP/PYUSD/USD1 具體費率**：官方費率表未逐一列出
4. **所有交易所穩定幣對 spread 寬度**：需實盤數據
5. **Binance USDC 特殊費率（0.095%/0.07125%）的有效期**：頁面未標註截止日期

### 🔍 建議後續驗證方式

1. **查詢 OKX 與 Bybit 費率**：
   - 方式 A：聯絡官方客服（24/7）
   - 方式 B：查詢各交易所 REST API 的 `/fees` endpoint
   - 方式 C：在官方移動應用或交易介面直接檢查實時費率

2. **驗證 Binance 穩定幣對全列表**：
   - 訪問 Binance 交易頁面，逐一檢查各穩定幣對的買賣手續費
   - 或使用 Binance API：https://api.binance.com/api/v1/exchangeInfo

3. **確認 spread 寬度**：
   - 通過各交易所的 WebSocket market data feed 實時監控
   - 或使用 Coinalyze/Glassnode 等專業數據服務

---

## 查證過程總結

| 嘗試方法 | 結果 | 時間戳 |
|---------|------|--------|
| WebFetch: https://www.binance.com/en/fee/trading | ✅ 部分成功（基礎費率+USDC） | 2026-07-11 |
| WebFetch: OKX 官方頁面 | ❌ 404 Not Found | 2026-07-11 |
| WebFetch: Bybit 官方頁面 | ❌ timeout / Access Denied | 2026-07-11 |
| WebFetch: https://hyperliquid.gitbook.io | ✅ 成功 | 2026-07-11 |
| Bash curl: Binance/OKX/Bybit | ⚠️ 限制（過大 HTML、拒絕訪問、timeout） | 2026-07-11 |
| WebFetch: CoinGecko 交易所排名 | ❌ 無詳細費率 | 2026-07-11 |
| WebFetch: Binance 公告頁面 | ⚠️ 找不到費率公告 | 2026-07-11 |

**限制原因**：Web scraper 容易被 CDN/WAF 限流；需 JavaScript 渲染或認證訪問的動態頁面無法通過靜態 fetch 獲得。

---

## 檔案元數據

- **報告版本**：Ground Truth v1.0
- **查證日期**：2026-07-11
- **查證人**：Claude Code
- **驗收判準**：每個數字附來源 URL；無法查證的項明確標註；反面證據交代
- **置信度**：
  - Hyperliquid：**高**（官方文檔明確，穩定幣費率無時限變化）
  - Binance 基礎費率：**高**（官方費率表，但穩定幣對逐一費率未列）
  - OKX/Bybit：**無法評估**（頁面無法訪問）

---

## 使用方式

本報告為「穩定幣均值回歸策略」的成本基線查詢結果。**策略可行性判定前必須**：

1. 確認 OKX 與 Bybit 的實際費率（見建議驗證方式）
2. 在實盤環境測試穩定幣對的實際 spread（不同時段、幣種、流動性等級不同）
3. 考慮隱含成本：滑點、資金費率（perp）、借貸成本（margin 對）

**邊界條件**：本查詢僅涵蓋 taker/maker 掛牌費率，不含其他交易成本。
