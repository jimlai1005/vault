# CTA instance B1 部署教學（新錢包，vol-target sizing）

給 owner 的逐步上線教學。這份文件由 Claude 在 2026-07-14 準備，**只寫了檔案，
沒有執行任何部署、服務、下單操作**——見文末「Claude 已做/未做」。

## 0. 上線前必讀（已解決，留作記錄）：DOT 符號映射缺口

打包時發現宇宙 `BTC,ETH,SOL,DOGE,XRP,DOT` 中的 DOT 在 `config.py` 的
`BINANCE_SYMBOLS`（`data.py:206` 直接字典索引）沒有對應項，會導致 B1 實例
每個 cycle `KeyError: 'DOT'` 崩潰重啟。

**已於 2026-07-14 修復（與本 runbook 同一 commit）**：`config.py` 的
`BINANCE_SYMBOLS` 已加入 `"DOT": "DOTUSDT"`。這是純新增字典鍵——wallet A／B
的 `COIN_UNIVERSE` 皆不含 DOT，對運行中實例是死碼、零行為變化；全套
pytest（295）修復後全綠。Coinalyze 側本就是動態查詢（DOT＝`DOTUSDT_PERP.A`），
無需改動。此段保留，作為「共用檔案改動需審慎」的過程記錄。

## (a) 部署位置建議

**建議：同一顆現有 Lightsail**（目前跑 `hl-cta`／`hl-cta2` 的那台），理由：

- systemd 用 process 隔離：三個 service 是三個獨立進程，各自的 crash／重啟
  互不影響。
- state／cache 檔已經用 `INSTANCE_LABEL` 隔離（見下方「多實例機制」）：
  `.env.cta` → `cta_state.json`、`.env.cta2` → `cta2_state.json`、
  `.env.cta-b1` → `cta-b1_state.json`——三者不會互相覆蓋。
- 引擎是 IO-bound 輕量服務（4h 週期跑一次 rebalance），CPU/記憶體占用極小
  （`MemoryMax=256M`），加一個實例不會讓現有兩個吃緊。
- 省一台機器的月費，也省一輪金鑰搬遷／IP 白名單重建的麻煩。

**風險與緩解**：唯一的共同故障面是整機當機或斷網——三個引擎會同時停。
這屬於可接受風險（三個都是有 `MAX_DRAWDOWN_PCT` 熔斷器與獨立錢包的引擎，
整機當機不會造成部位失控，只是三者同時暫停決策，重開機後各自從交易所
重新對帳）。另一個共同資源是 Coinalyze 免費 key 的 40 req/min 額度——三個
實例若共用同一把 key 會互相排擠，見 `deploy/env.cta-b1.example` 裡的
Option A／B 說明（申請獨立 key，或三個實例的 throttle 一起調高）。

**若要完全隔離（新開一台 Lightsail）**：只有在 owner 認為「三引擎共機」的
故障面不可接受時才需要。步驟參考 `compound/docs/deploy-lightsail.md`
第 1-3 節的建機流程（最小方案 512MB/1vCPU 即可、Ubuntu 22.04、綁靜態 IP），
但要用這份 repo 的 `git clone` 與 `deploy/hl-cta-b1.service`（而非
compound 的）。這條路徑會多出一次 `git clone`＋`.venv` 建置＋（若要金鑰
IP 白名單）Hyperliquid 沒有 IP 白名單機制，故新機沒有額外的白名單步驟。

## (b) 逐步指令

以下每個指令塊都標明「在哪台機器、哪個使用者、碰不碰錢」。**碰錢／碰
實盤服務的步驟一律由 owner 親自執行**，Claude 沒有、也不會代為執行。

### 步驟 1：新錢包入金（本機或交易所網頁，owner 親自操作，**碰錢**）

在 Hyperliquid 開新錢包、轉入本金。這一步在交易所網頁／owner 自己的簽章
工具完成，不涉及這台 repo。

### 步驟 2：本機建立 `.env.cta-b1`（owner 的本機開發機，**碰錢：含私鑰**）

```bash
# 在本機（不是伺服器）
cd /Users/jim/projects/vault
cp deploy/env.cta-b1.example .env.cta-b1
# 編輯 .env.cta-b1，填入：
#   WALLET_PRIVATE_KEY, WALLET_ADDRESS（新錢包）
#   TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
#   COINALYZE_API_KEY（若走 Option A 獨立 key）
#   確認 COIN_UNIVERSE / SIGMA_TARGET 等其餘欄位符合預期
chmod 600 .env.cta-b1
```

`.env.cta-b1` 已加進 `.gitignore`（本次打包已加入這一行，`git check-ignore
.env.cta-b1` 驗證過會印出 `.env.cta-b1`，即不會被 `git add` 誤收）。

### 步驟 3：把 `.env.cta-b1` 搬到伺服器（本機 → 伺服器，**碰錢：私鑰在傳輸中**）

```bash
# 在本機執行（換成實際 Lightsail 位址）
scp .env.cta-b1 ubuntu@<lightsail-ip>:~/vault/.env.cta-b1
ssh ubuntu@<lightsail-ip> 'chmod 600 ~/vault/.env.cta-b1'
```

### 步驟 4：更新伺服器上的 code（伺服器，`ubuntu` 使用者，**不碰錢**）

```bash
# 在伺服器上
cd ~/vault
git pull
```

`git pull` 本身不影響正在跑的 `hl-cta`／`hl-cta2`——**進程用的是已載入到
記憶體的舊 code，不會因為 working tree 更新就自動重啟或重讀**。這一步
**不要 restart 現有服務**（不需要，也不在本次任務範圍內；如果 pull 下來的
commit 動到 `src/hlvault/cta/` 共用邏輯且需要讓 A／B 也吃到新 code，那是
另一個決定，要照 CLAUDE.md 紅線另外走 owner 核准流程，不屬於這次 B1 上線
教學）。

### 步驟 5：安裝 B1 的 systemd unit（伺服器，`root`/`sudo`，**不碰錢，但需 sudo**）

```bash
# 在伺服器上
sudo cp deploy/hl-cta-b1.service /etc/systemd/system/
sudo systemctl daemon-reload
```

到這一步為止只是把 unit 檔登記進 systemd，**尚未 enable、尚未 start**。

### 步驟 6：dry-run 驗證（伺服器，`ubuntu` 使用者，**不碰錢——LIVE_TRADING=false 時是唯讀模擬**）

引擎的 `hl-cta` entrypoint 支援 `--dry-run --once`（`src/hlvault/cta/
live.py:570-588`）：`--dry-run` 強制 `live_trading=False`（不論
`.env.cta-b1` 裡怎麼設），`--once` 跑完一個 cycle 就結束，不進 loop。

```bash
# 在伺服器上
cd ~/vault
CTA_ENV_FILE=/home/ubuntu/vault/.env.cta-b1 .venv/bin/hl-cta --dry-run --once
```

**紅線提醒**：「勿在 live service 運行時對同一 state 檔跑 `--dry-run`」
指的是同一個 `.env`／同一個 state 檔的情況——B1 的 state 檔
（`data/cache/cta-b1_state.json`）是全新、獨立的，此刻沒有任何 service
在用它，所以對 `.env.cta-b1` 跑 dry-run 是安全的，不會干擾 wallet A／B。

（步驟 0 的 DOT 映射已隨本套件修復；若這一步仍看到 `KeyError: 'DOT'`，
代表伺服器上的 code 不是最新——確認 `git pull` 已到含修復的 commit。）

檢查 dry-run 輸出：
- 六個幣（BTC/ETH/SOL/DOGE/XRP/DOT）都跑過一輪 decision，沒有 exception。
- 看到 `SIGMA_TARGET`／`m=` 相關的 sizing log（B1 的 vol-target 開關生效
  的證據——若完全沒看到任何 `sigma=`／`m=` 字樣，代表 `SIGMA_TARGET` 沒讀
  到，回去檢查 `.env.cta-b1` 的這個變數有沒有設對）。
- `[DRY RUN]` 標記的下單意圖（若有訊號）而非真實委託回報。

再跑 `--status`（唯讀，只讀帳戶 equity 與 state，不下單）：

```bash
CTA_ENV_FILE=/home/ubuntu/vault/.env.cta-b1 .venv/bin/hl-cta --status
```

預期看到 `[cta-b1] equity $... | halted=False ...`。

### 步驟 7：正式啟動（伺服器，`root`/`sudo`，**碰錢：若 `.env.cta-b1` 的 `LIVE_TRADING=true` 會真的下單**）

確認 `.env.cta-b1` 的 `LIVE_TRADING` 已依 owner 決定設為 `true`（步驟 6
的 dry-run 只要求 code 跑得動，不會自動幫你把這個值改掉）：

```bash
# 在伺服器上，owner 親自執行
sudo systemctl enable --now hl-cta-b1
```

### 步驟 8：驗證清單（伺服器 + 交易所網頁，owner，**唯讀不碰錢**）

- `journalctl -u hl-cta-b1 -f`：看 decision log 有沒有 `m=`／`sigma=` 欄位
  （B1 sizing 生效的證據），六個幣都有被處理，沒有反覆 crash-restart。
- `CTA_ENV_FILE=/home/ubuntu/vault/.env.cta-b1 .venv/bin/hl-cta --status`：
  equity、`halted=False`、`open_entries` 合理。
- Hyperliquid 網頁：用新錢包地址登入，把網頁顯示的 Total Equity 與
  `--status` 的 equity 對帳（owner 既有慣例——equity 數字必須跟交易所網頁
  對得上）。
- `systemctl status hl-cta hl-cta2 hl-cta-b1 --no-pager`：確認三個服務都
  是 `active (running)`，wallet A／B 沒有因為這次操作被動到。

## (c) 回滾

```bash
# 伺服器上，owner 親自執行
sudo systemctl disable --now hl-cta-b1
```

**引擎停止不代表部位不存在**——`systemctl stop` 只是不再跑決策循環，
`.env.cta-b1` 對應的錢包上原本開的部位（若已有）仍然留著。回滾後務必到
Hyperliquid 網頁用新錢包地址確認持倉，需要的話手動平倉。B1 是全新錢包，
wallet A／B 完全獨立，這次回滾不影響它們。

## (d) 這份 runbook 中，Claude 已做／未做

**已做（只寫檔案）**：
- `deploy/env.cta-b1.example`（新檔案，env 範本，佔位符 `<FILL_ME>`，
  沒有任何真實金鑰）
- `deploy/hl-cta-b1.service`（新檔案，systemd unit 範本）
- `docs/runbooks/cta-b1-deploy.md`（本檔案）
- `.gitignore` 加了一行 `.env.cta-b1`（防止 owner 之後在本機建立真實檔案
  時被意外 `git add`——套用既有的 `.env.cta2` 先例，已用
  `git check-ignore .env.cta-b1` 驗證生效）

**未做（owner 親自執行的部分，一項都沒有代勞）**：
- 沒有建立、讀取、印出任何 `.env*` 真實檔案
- 沒有 `ssh`／`scp` 到任何伺服器
- 沒有跑 `systemctl`（daemon-reload／enable／start／stop 全部沒執行）
- 沒有跑 `git pull`、`sudo cp`、或任何會碰到 `/etc/systemd/system/` 的指令
- 沒有跑 `hl-cta` entrypoint（dry-run 或其他模式都沒有），因為那需要真實
  的 `.env.cta-b1` 才跑得起來，而這個檔案還不存在（owner 步驟 2 才會建立）
- **零觸碰現有 `hl-cta`／`hl-cta2` 服務**：沒有讀取、印出、複製
  `.env.cta`／`.env.cta2`，沒有對它們執行任何 systemctl 操作，也沒有修改
  `deploy/hl-cta.service`／`deploy/hl-cta2.service`／`deploy/setup-cta.sh`
  ／`deploy/setup-cta2.sh` 或任何其他既有 deploy／docs 檔案
- 沒有修改 `src/hlvault/cta/config.py`（步驟 0 的 DOT blocker 需要 owner
  核准後另外走修復流程，這次打包刻意沒有動它）
