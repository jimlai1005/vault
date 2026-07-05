# Compound（Bitfinex 放貸）併入 vault Monorepo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 compound（Bitfinex USD 自動放貸引擎＋研究成果）以快照方式併入 vault git，成為與 gridbot／CTA 並列的產品線，研究結論可從 vault 統一發現。

**Architecture:** compound 保持自包含子目錄（`compound/` 自帶 src／tests／scripts／reports／docs 與獨立 `.venv`），**不**併入 hlvault 套件；vault 根層 CLAUDE.md 負責路由（目錄地圖）與紅線（Bitfinex 實盤 key／引擎腳本）。git 歷史不匯入：快照 import，來源 repo 的 HEAD hash 記在 commit message，獨立 repo `~/projects/compound` 原地保留為冷檔案（處置權在使用者）。

**Tech Stack:** git（快照匯入）、Python 3.9 venv、pytest。

---

## 執行紅線（每個執行 task 的 subagent 都必須遵守，無例外）

1. **絕不執行** `compound/scripts/run_engine.py`（任何參數、任何模式）。Bitfinex 帳上現有真實放貸部位（328 USD，兩筆 2 天期約 2026-07-07 到期）；引擎已停止，本計畫不重啟它。
2. **絕不讀取或印出** `compound/.env`（兩個 repo 的複本皆然）——內含 Bitfinex 實盤 API key。唯一許可碰到真實 API 的動作是 Task 8 的 `scripts/status.py`（唯讀查詢，已向使用者揭露並隨計畫核准）。
3. **絕不修改** `~/projects/compound`（獨立 repo）——只允許唯讀比對。
4. 任何一步的實際輸出與「Expected」不符 → **停手回報**，不得自行放寬判準或跳過。
5. 不 push、不啟停任何服務、不刪除本計畫未列名的檔案。

## 已查證事實（2026-07-06 盤點，執行者不必重查）

- `vault/compound/` 已存在一份 compound 完整複本：自帶 `.git`，HEAD 與獨立 repo 同為 `9cc482c3e5ce95239de460a964bd3507d112dd4c`（23 commits、無 remote），排除 `.git/.venv/.pytest_cache/egg-info` 後內容零差異。兩邊 worktree 唯一的未 commit 變更都是 ` D .claude/scheduled_tasks.lock`（過期 session lock，不需要保留）。
- `.env` 從未進過任一 repo 的 git 歷史（以 `git log --all --diff-filter=A --name-only` 檔名層級查證）；程式碼無硬編碼 key。
- vault 根層 `.gitignore:5` 的 `.env` pattern（無斜線＝任意深度）與 `compound/.gitignore:1` 的 `.env` 都會忽略 `compound/.env`（Task 3 仍要實測 check-ignore）。
- `compound/data/` 只有 3 個小檔被 git 追蹤（README、book/ticker snapshot）；大 CSV（含 9MB funding_stats.csv）被 `compound/.gitignore` 的 `data/*.csv` 忽略，屬可重抓的 cache（`compound/scripts/fetch_history.py`），留在磁碟即可。
- compound 測試 56 個 test 函式、全離線：`compound/tests/conftest.py` autouse fixture 封鎖 `socket.connect` 並清空 `BFX_API_KEY/BFX_API_SECRET`。
- vault 的 pytest 設定 `testpaths = ["tests"]`（vault `pyproject.toml:31`）——不會收集 `compound/tests`。
- compound 憑證載入點：`src/compound/config.py:73` 從 `PROJECT_ROOT/.env` 讀（相對套件安裝位置，與 cwd 無關）。
- 研究腳本 `research_leverage_phases.py`／`research_market_regimes.py`／`research_strategy_phases.py` 用到 numpy/pandas，但 `compound/pyproject.toml` 未宣告（隱性依賴，Task 5 修）。

## 關鍵決策與理由

1. **快照匯入，不帶 git 歷史**：23 個 commit 全是 2026-07-04/05 兩天的自主開發紀錄、無 remote；獨立 repo 原地保留 → 歷史零損失。省去 subtree/filter-repo 的複雜度與 vault 歷史被無關 lineage 污染。
2. **compound 維持自包含（含獨立 .venv）**：不同交易所（Bitfinex vs Hyperliquid）、零程式碼相依（grep 證實無 import hlvault）、依賴極簡（requests）。不合併依賴 → 對 vault 現有三引擎零風險。
3. **研究報告留在 `compound/reports/`，由 CLAUDE.md 路由**：報告間互有引用，搬動會斷鏈；「共享」靠目錄地圖指路即可，跨產品資金配置 verdict（`compound/reports/cycle_allocation_verdict.md`）在地圖中單獨點名。

## File Structure

- Create（git 追蹤）: `compound/**`（整個子樹，約等於獨立 repo 的 tracked 清單減去 `.claude/scheduled_tasks.lock`）
- Modify: `compound/pyproject.toml`（補 research extras）、`CLAUDE.md`（目錄地圖＋紅線）
- Delete（磁碟上的匯入前清理，不進 git）: `compound/.git/`、`compound/.venv/`、`compound/.pytest_cache/`、`compound/src/compound.egg-info/`、`compound/.claude/`（已驗證為空）
- Create（不進 git）: `compound/.venv/`（重建，原 venv 的 shebang/路徑綁死在 `~/projects/compound`，複製過來的是壞的）

---

### Task 0: Commit 本計畫文件

**Files:**
- Create: `docs/superpowers/plans/2026-07-06-compound-integration.md`（已由規劃階段寫好）

- [ ] **Step 1: 確認檔案存在後 commit**

```bash
cd /Users/jim/projects/vault
git add docs/superpowers/plans/2026-07-06-compound-integration.md
git commit -m "docs: compound integration plan (sub-project import)"
```

Expected: commit 成功，`git status --short` 中該檔案消失。

### Task 1: 前置驗證（全唯讀；任何一步不符即停）

**Files:** 無（唯讀）

- [ ] **Step 1: 兩份複本 HEAD 一致**

```bash
git -C /Users/jim/projects/compound rev-parse HEAD
git -C /Users/jim/projects/vault/compound rev-parse HEAD
```

Expected: 兩行皆為 `9cc482c3e5ce95239de460a964bd3507d112dd4c`。

- [ ] **Step 2: 兩邊 worktree 無預期外變更**

```bash
git -C /Users/jim/projects/compound status --porcelain
git -C /Users/jim/projects/vault/compound status --porcelain
```

Expected: 每邊至多一行 ` D .claude/scheduled_tasks.lock`。出現任何其他行 → 停手回報該輸出。

- [ ] **Step 3: 內容零差異**

```bash
diff -rq /Users/jim/projects/compound /Users/jim/projects/vault/compound \
  -x .git -x .venv -x .pytest_cache -x "*.egg-info" -x __pycache__ -x .claude
```

Expected: 無輸出。有輸出 → 停手回報差異清單。

- [ ] **Step 4: 記錄 vault 測試基線**

```bash
cd /Users/jim/projects/vault && .venv/bin/pytest
```

Expected: 全綠；把 `N passed` 的 N 記下來，Task 6 要用同一個數字比對。若基線本來就有 fail，原樣記錄並在回報中標明「pre-existing」。

### Task 2: 清理匯入前的 artifacts（拆 gitlink 地雷）

**Files:**
- Delete: `compound/.git/`、`compound/.venv/`、`compound/.pytest_cache/`、`compound/src/compound.egg-info/`、`compound/.claude/`

- [ ] **Step 1: 刪除（只刪這五個路徑，一個字都不要多）**

```bash
cd /Users/jim/projects/vault
rm -rf compound/.git compound/.venv compound/.pytest_cache compound/src/compound.egg-info compound/.claude
```

- [ ] **Step 2: 確認 .git 已除、.env 仍在磁碟且被 ignore**

```bash
ls -d compound/.git 2>&1
ls compound/.env >/dev/null && echo "env-on-disk-ok"
git check-ignore -v compound/.env
```

Expected: 第一行 `No such file or directory`；第二行 `env-on-disk-ok`；第三行輸出一條命中規則（`.gitignore:5:.env` 或 `compound/.gitignore:1:.env`）。**check-ignore 無輸出＝.env 沒被忽略＝停手**。

### Task 3: 匯入 commit

**Files:**
- Create: `compound/**` 進入 vault git index

- [ ] **Step 1: Stage**

```bash
cd /Users/jim/projects/vault
git add compound/
```

- [ ] **Step 2: staged 清單 == 獨立 repo tracked 清單（減去 session lock）**

```bash
diff <(git -C /Users/jim/projects/compound ls-files | grep -v '^\.claude/scheduled_tasks\.lock$' | sort) \
     <(git diff --cached --name-only | sed 's|^compound/||' | sort)
```

Expected: 無輸出。有任何差異（多了 .env、CSV、cache，或少了檔案）→ `git reset` 後停手回報 diff 內容。

- [ ] **Step 3: 機密與 gitlink 雙重保險**

```bash
git diff --cached --name-only | grep -iE '\.env|secret|\.pem'
git ls-files -s compound/ | awk '$1=="160000"'
```

Expected: 兩條命令皆無輸出（grep 以 exit 1 結束是正常的）。

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: import compound (Bitfinex USD lending) as a vault sub-project

Snapshot import of ~/projects/compound at HEAD 9cc482c3e5ce95239de460a964bd3507d112dd4c
(23 commits, no remote). Full history stays in the standalone repo, kept as
cold archive. Live engine is stopped; real positions remain on Bitfinex (~328
USD, two 2-day loans maturing ~2026-07-07) — importing files does not touch
them. Decisions & verification: docs/superpowers/plans/2026-07-06-compound-integration.md

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Expected: commit 成功。

- [ ] **Step 5: 匯入後 worktree 狀態檢查**

```bash
git status --short
```

Expected: 只剩本來就在的 `?? scripts/research_cta_crowd_ablation.py` 與 `?? scripts/tv_cta_strategy.pine`（不要動它們），沒有任何 `compound/` 相關行。

### Task 4: 補宣告 research 依賴

**Files:**
- Modify: `compound/pyproject.toml`

- [ ] **Step 1: 加 optional-dependencies**

把 `compound/pyproject.toml` 的

```toml
dependencies = ["requests"]
```

改為

```toml
dependencies = ["requests"]

[project.optional-dependencies]
research = ["numpy>=1.24", "pandas>=2.0"]
```

（`[project.optional-dependencies]` 段落緊接在 `dependencies` 行之後、`[tool.setuptools.packages.find]` 之前。）

- [ ] **Step 2: Commit**

```bash
cd /Users/jim/projects/vault
git add compound/pyproject.toml
git commit -m "chore(compound): declare research extras (numpy/pandas were undeclared imports)"
```

Expected: commit 成功。

### Task 5: 重建 venv、compound 測試全綠

**Files:**
- Create: `compound/.venv/`（gitignored，不進版控）

- [ ] **Step 1: 建 venv 並安裝**

```bash
cd /Users/jim/projects/vault/compound
python3 -m venv .venv
.venv/bin/pip install -q -e ".[research]"
```

Expected: exit 0。（機器 python3 為 3.9.6，滿足 `requires-python >= 3.9`。）

- [ ] **Step 2: 跑 compound 測試**

```bash
cd /Users/jim/projects/vault/compound && .venv/bin/pytest
```

Expected: 全綠、0 failed 0 error（56 個 test 函式；conftest 的 socket 封鎖保證離線，不會打真實 API）。

- [ ] **Step 3: 確認 venv 沒污染 git**

```bash
cd /Users/jim/projects/vault && git status --short | grep compound
```

Expected: 無輸出。

### Task 6: vault 測試迴歸確認

**Files:** 無

- [ ] **Step 1: 重跑 vault 測試**

```bash
cd /Users/jim/projects/vault && .venv/bin/pytest
```

Expected: 與 Task 1 Step 4 記錄的基線完全相同（同樣的 `N passed`）。

### Task 7: CLAUDE.md 更新（目錄地圖＋紅線加嚴）

**Files:**
- Modify: `CLAUDE.md`（vault 根層）

- [ ] **Step 1: 紅線——env 清單加入 compound/.env**

old_string:

```
- `.env.carry`、`.env.gridbot`、`.env.momentum` 是**實盤錢包的真實鑰匙**，`.env.research` 是真實 API key。
```

new_string:

```
- `.env.carry`、`.env.gridbot`、`.env.momentum` 是**實盤錢包的真實鑰匙**，`.env.research` 是真實 API key，
  `compound/.env` 是 **Bitfinex 實盤帳戶**的真實 API key。
```

- [ ] **Step 2: 紅線——碰真錢操作清單加入放貸引擎**

old_string:

```
  - `scripts/setup_carry_wallet.py` 及任何會送出交易、轉帳、下單的腳本
```

new_string:

```
  - `scripts/setup_carry_wallet.py` 及任何會送出交易、轉帳、下單的腳本
  - `compound/scripts/run_engine.py`（Bitfinex 放貸引擎，會送真實掛單／撤單）。注意：引擎停止
    不代表部位不存在——帳上可能仍有真實放貸；動引擎前先跑唯讀的 `compound/.venv/bin/python
    compound/scripts/status.py` 對帳
```

- [ ] **Step 3: 目錄地圖加入 compound**

old_string:

```
- `src/hlvault/` — 主套件。`carry/`、`gridbot/`、`momentum/` 是三個實盤引擎；`io/` 是外部呼叫邊界；`notify/` 是通知。
```

new_string:

```
- `src/hlvault/` — 主套件。`carry/`、`gridbot/`、`momentum/` 是三個實盤引擎；`io/` 是外部呼叫邊界；`notify/` 是通知。
- `compound/` — Bitfinex USD 自動放貸引擎（自包含子專案：自帶 src/tests/scripts/docs 與獨立
  `compound/.venv`，測試用 `compound/.venv/bin/pytest` 跑）。研究結論在 `compound/reports/`；
  跨產品（gridbot／CTA／放貸）四年週期資金配置 verdict：`compound/reports/cycle_allocation_verdict.md`。
```

- [ ] **Step 4: Commit**

```bash
cd /Users/jim/projects/vault
git add CLAUDE.md
git commit -m "docs: add compound (Bitfinex lending) to CLAUDE.md map + live-money red lines"
```

Expected: commit 成功。

### Task 8: 唯讀實跑驗證（新位置的引擎能載到憑證與帳戶）

**Files:** 無

- [ ] **Step 1: 跑唯讀 status（本計畫唯一許可的真實 API 呼叫）**

```bash
cd /Users/jim/projects/vault/compound && .venv/bin/python scripts/status.py
```

Expected: 印出 `wallet total ... | available ... | engine committed ... | budget 328`、own/foreign offers 計數與市場行情各一行；**不得**出現 key 內容。把輸出原文記進回報（它同時是使用者要的帳上現況快照）。若失敗：回報完整錯誤原文，最多重試一次，不得改跑其他腳本。

---

## 驗收（主對話派 fresh-context agent 執行，不給實作推理，只給下列清單）

1. `git log --oneline -5` 顯示四個新 commit：plan 文件、import、pyproject chore、CLAUDE.md docs。
2. 機密未入 git：`git ls-files | grep -c '^compound/\.env$'` 輸出 `0`；`git log --all --name-only | grep -c 'compound/\.env'` 輸出 `0`；`git check-ignore -q compound/.env; echo $?` 輸出 `0`。
3. 無 gitlink：`git ls-files -s compound/ | awk '$1=="160000"' | wc -l` 輸出 `0`。
4. 檔案完整性：`diff <(git -C /Users/jim/projects/compound ls-files | grep -v '^\.claude/scheduled_tasks\.lock$' | sort) <(git ls-files compound/ | sed 's|^compound/||' | sort)`——考慮 Task 4 改過 pyproject.toml，容許該檔內容不同但清單必須一致（此命令只比清單）。Expected: 無輸出。
5. 測試：`compound/.venv/bin/pytest`（在 compound/ 下跑）全綠；vault 根層 `.venv/bin/pytest` 等於 Task 1 基線。
6. CLAUDE.md 三處編輯落地：`grep -c 'compound/.env' CLAUDE.md` ≥ 1、`grep -c 'run_engine.py' CLAUDE.md` ≥ 1、`grep -c 'cycle_allocation_verdict' CLAUDE.md` ≥ 1。
7. 獨立 repo 未被動過：`git -C /Users/jim/projects/compound status --porcelain` 仍然只有 ` D .claude/scheduled_tasks.lock`。

## 不在本計畫內、留給使用者決策（執行者不得先做）

1. **Bitfinex API key 輪替**（建議優先）：`compound/reports/morning_report.md:120` 自陳這把 key 曾在對話中貼過。輪替後更新 `compound/.env`。
2. 獨立 repo `~/projects/compound` 的處置：建議至少保留到整併 commit 穩定之後，之後可刪或打 `git bundle` 冷存。
3. 引擎是否重啟＋資金搬遷級別（`compound/reports/morning_report.md` 第 6 節的 0→3 級路線）。帳上兩筆 2 天期放貸約 2026-07-07 到期回籠；屆時若無 daemon 在跑就不會複投（不虧錢，只是閒置）。
4. Lightsail 部署（`compound/docs/deploy-lightsail.md`，文件已備、未執行）。

## 執行備註（給主對話的派工建議）

- 建議分工：Agent A 做 Task 0-3（匯入鏈，順序敏感）、Agent B 做 Task 4-6（打包與測試）、Agent C 做 Task 7-8（文件與唯讀實跑）；驗收另派 fresh-context agent 跑上面的驗收清單。
- 每個 agent 的 prompt 都要原文附上「執行紅線」五條。
