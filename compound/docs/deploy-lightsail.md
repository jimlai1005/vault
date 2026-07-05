# 部署到 AWS Lightsail

把 compound 引擎以 systemd 服務跑在 Lightsail 上。引擎是 IO-bound 的輕量服務
（每 5 分鐘一個 tick、幾個 REST 呼叫、寫幾行 JSONL），資源需求極低。

## 1. 實例規格

- **最小方案即可**：512 MB RAM / 1 vCPU（Lightsail 最便宜那檔）。CPU 與記憶體
  都遠夠用；唯一會慢慢長的是 journal/ 的 JSONL（每天一檔，見第 5 節）。
- OS：Ubuntu 22.04 LTS 或 Amazon Linux 2023 皆可，只要 `python3 --version` ≥ 3.9。
- **綁一個 Lightsail 靜態 IP**（Networking → Create static IP）。這不只是為了 SSH
  方便——下一節的 API key 要綁這個 IP。

## 2. API key（建議做法）

不要把本機開發用的 key 帶上去。到 Bitfinex 後台**另建一把新 key**：

- 權限最小化：只勾 margin funding 的讀＋寫（offers）；**不給提領、不給交易**。
- **IP whitelist 綁定 Lightsail 靜態 IP**——key 外洩也無法從其他機器使用。
- 部署驗證完成後，把舊的開發 key **輪替掉（撤銷）**。

## 3. 部署步驟

```bash
# SSH 進實例後
sudo apt-get update && sudo apt-get install -y python3-venv git   # Ubuntu

git clone <你的 repo 位址> ~/compound
cd ~/compound
python3 -m venv .venv
.venv/bin/pip install -e .

# .env 不進 git——從本機上傳（在本機執行）：
#   scp .env <user>@<static-ip>:~/compound/.env
chmod 600 ~/compound/.env

# 驗證順序（由淺入深）：
.venv/bin/python scripts/smoke_public.py          # 公開 API 通、解析正常
.venv/bin/python scripts/run_engine.py --dry-run --once   # 憑證通、帳戶讀得到、計畫合理
# dry-run 連續看兩次以上都合理，才進 live：
.venv/bin/python scripts/run_engine.py --live --once      # 會真的下單（live-test caps 生效）
```

## 4. systemd 服務

`/etc/systemd/system/compound.service`（`User`/路徑依實際帳號調整，下例為 Ubuntu 的 `ubuntu`）：

```ini
[Unit]
Description=compound - Bitfinex USD funding engine
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/compound
ExecStart=/home/ubuntu/compound/.venv/bin/python scripts/run_engine.py --live --daemon
Restart=on-failure
RestartSec=30
Environment=TZ=UTC
# 需要覆蓋參數時改用：
# ExecStart=/home/ubuntu/compound/.venv/bin/python scripts/run_engine.py --live --daemon --params /home/ubuntu/compound/params.json

[Install]
WantedBy=multi-user.target
```

注意：`WorkingDirectory` 必須是 repo 根目錄——`journal_dir` 預設是相對路徑
`journal/`，而 `.env` 是以套件安裝位置解析的（editable install 下即 repo 根目錄）。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now compound
systemctl status compound
journalctl -u compound -f          # 引擎的 stdout/stderr 日誌
```

先想觀察一陣子的話，把 `ExecStart` 的 `--live` 換成 `--dry-run` 跑常駐 dry-run，
看幾小時 journal 再切回來。

## 5. 監控

### JSONL journal（決策的真相來源）

引擎每 tick 在 `journal/YYYY-MM-DD.jsonl`（**UTC 日期**，每天自動換檔）追加一行
JSON，`kind` 欄位標示事件種類：

```bash
cd ~/compound
tail -f journal/$(date -u +%F).jsonl                     # 即時看
tail -1 journal/$(date -u +%F).jsonl | python3 -m json.tool   # 最近一個 tick 的完整快照
grep -h '"kind": "placed"' journal/*.jsonl               # 歷來所有真實下單
```

事件種類與該注意的程度：

| kind | 意義 | 注意程度 |
|---|---|---|
| `tick` | 每 tick 的完整快照：餘額、自有/外部掛單、FRR、目標單、計畫 | 正常心跳 |
| `placed` / `canceled` | 真實下單／撤單成功 | 正常 |
| `identity_mismatch` | **錢包餘額 ≠ 可用＋掛單＋貸出（差 >1 USD）**——帳對不上 | **立刻查**：可能是計帳 bug 或帳戶被外部動了 |
| `place_rejected` | 下單被交易所拒絕（semantic：參數、餘額）——不重試 | 查原因；反覆出現代表設定或策略有問題 |
| `place_failed` / `cancel_failed` | transient 失敗（可能已落地也可能沒有），本 tick 中止，下一 tick 對帳自癒 | 偶發可忽略；連續出現查網路/API 狀態 |
| `place_no_offer` | 下單回應沒帶 offer——下一 tick 對帳 | 偶發可忽略 |
| `tick_transient` / `tick_semantic` | 整個 tick 失敗（前者網路類、後者認證/設定類） | `tick_semantic` 連續出現要查 key 權限/IP 綁定 |

dry-run 模式沒有獨立事件：`tick` 記錄裡 `"dry_run": true`，計畫（`plan_cancels`/
`plan_places`）照記但不送出；擬執行的動作另以 `[dry]` 前綴印在 stdout（journalctl 可見）。

簡單的每日巡檢：

```bash
grep -hc '"kind": "identity_mismatch"\|"kind": "place_rejected"\|"kind": "tick_semantic"' \
  journal/$(date -u +%F).jsonl
# 期望是 0；非 0 就打開該檔細看
```

另外 `journal/owned.json` 是掛單所有權登記（引擎的記憶），**不要手動編輯**；
備份 journal/ 時把它一起帶上。

### 日誌輪替

JSONL 已按 UTC 日期自然分檔，不會單檔無限長；但檔案數會累積。二選一：

logrotate（`/etc/logrotate.d/compound`）——只壓縮、不改名（引擎永遠只寫「今天」的檔）：

```
/home/ubuntu/compound/journal/*.jsonl {
    weekly
    compress
    notifempty
    missingok
    rotate 26
    nocreate
    olddir /home/ubuntu/compound/journal/archive
    createolddir 0755 ubuntu ubuntu
}
```

或者更簡單的 cron（壓縮 7 天前的舊檔）：

```
0 3 * * * find /home/ubuntu/compound/journal -name '20*.jsonl' -mtime +7 -exec gzip {} \;
```

systemd 那側的 stdout 日誌交給 journald 自己管，必要時在
`/etc/systemd/journald.conf` 設 `SystemMaxUse=200M`。

## 6. 時區

**一切 UTC**：journal 檔名、記錄裡的 timestamp、Bitfinex API 的 mts、回測資料
全都是 UTC。建議實例系統時區也保持 UTC（`timedatectl set-timezone UTC`），
service 檔已設 `Environment=TZ=UTC`。對帳、查日誌時記得 `date -u`。

## 7. 升級與變更設定

```bash
cd ~/compound
sudo systemctl stop compound
git pull
.venv/bin/pip install -e .        # 相依有變時
.venv/bin/pytest                  # 全離線，機器上跑也安全
sudo systemctl start compound
```

改參數（如調 `capital_budget`）：編輯 `params.json` → `sudo systemctl restart compound`。
擴大資金的節奏與前提見 README「擴大資金的路徑」一節。
