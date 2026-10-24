# 部署到自己的 GitHub(fork + 私人收藏庫)

本文記錄把 RepoBox 部署到自己帳號的完整步驟與設定。範例帳號為 `smarkettsai-png`,請換成你自己的。

## 架構一句話

- **fork `<你>/repobox`(公開)**:放程式、`analyze.yml` 與網頁(GitHub Pages)。
- **私人 `<你>/repobox-library`**:放收藏與分析結果。它的 workflow 以 `uses:` 呼叫 fork 的 `analyze.yml`。
- 分析由 GitHub Actions 裡的 Claude Code 完成;本機不需要執行任何分析。

## 需求

- `gh`(已登入,scopes 含 `repo`、`workflow`)、`git`。
- Claude Code CLI(只用來產生 token)。
- 一個 Claude 訂閱帳號。

## 1. Fork

```sh
cd RepoBox
gh repo fork --remote          # 不要加 repo 參數或 --remote-name
git remote -v                  # origin 應是你的 fork,upstream 是 cholateio/repobox
git push -u origin <分支>
```

- fork 一定是公開的,無法改成 private。要私有只能複製成新 repo,但私人 repo 開 Pages 需要付費方案,且網站網址仍是公開的。
- 推送後到 fork 的 Actions 確認 `ci` 全綠。ci 在 Linux 上會執行本機 Windows 跳過的 symlink 測試。

## 2. 合併到 main 並開 Pages

```sh
git switch main
git merge --ff-only <分支>
git push origin main
gh api -X POST repos/<你>/repobox/pages -f build_type=workflow
gh run list -R <你>/repobox --limit 3
gh run watch <run-id> --exit-status -R <你>/repobox
```

網站位於 `https://<你>.github.io/repobox/`。此時網頁只是空殼,沒有 PAT 看不到任何資料。

## 3. 建私人收藏庫並釘 SHA

```sh
gh repo create <你>/repobox-library --private --template cholateio/repobox-library-template
gh repo clone <你>/repobox-library
git -C RepoBox rev-parse HEAD          # 取 fork 的 40 字元 SHA
```

編輯 library 的 `.github/workflows/repobox.yml`,把 `uses:` 改成:

```yaml
uses: <你>/repobox/.github/workflows/analyze.yml@<40 字元 SHA>
```

- 必須是完整 40 字元 SHA,不可用分支或短 SHA。
- 之後 fork 每更新一次 `analyze.yml`,library 的 SHA 都要手動換新。

## 4. 憑證與設定(只能由你本人操作)

### 4.1 Claude token

```sh
claude setup-token
gh secret set CLAUDE_CODE_OAUTH_TOKEN -R <你>/repobox-library
```

第二行會提示貼上 token,不會顯示。不要把 token 交給任何 agent 或貼進聊天。

### 4.2 Fine-grained PAT(供網頁使用)

GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token:

- Repository access:**Only select repositories**,只選 `repobox-library`。
- Permissions:只開 **Contents: Read and write**。**不要勾 Workflows**。
- 設到期日(例如 90 天)。

### 4.3 網頁設定

開 `https://<你>.github.io/repobox/`,按頂部顯示「尚未設定」的標籤,在「連結收藏庫」視窗填:

- 收藏庫:`<你>/repobox-library`
- Fine-grained token:剛建的 PAT
- 按「儲存」

PAT 只存在這個瀏覽器的 localStorage。

## 5. 第一次使用

1. 在首頁輸入框(「貼上 GitHub 連結」)貼一個你熟悉的中小型專案網址,按「收藏」。
2. 到 `https://github.com/<你>/repobox-library/actions` 確認 `repobox` workflow 被觸發。
3. 跑完後回網頁的「書庫」查看。失敗的項目會被搬到 `inbox/failed/`,錯誤原因寫在裡面。

手機可把網頁「加到主畫面」安裝為 PWA,再從分享選單直接收藏(尚未在真機驗證)。

## 6. 分析模型

`analyze.yml` 的 `FLAGS` 目前為:

```text
--model claude-haiku-5-5 --effort xhigh
```

- 使用完整模型名稱而非別名,避免別名日後指向其他版本。
- 沒有設定 `--fallback-model`;模型過載時該筆收藏會失敗並進 `inbox/failed/`。
- 實際使用的模型會寫在條目 `.json` 的 `analysis.model`。
- 若 Haiku 品質不足:把 `--model` 改回 `opus`,推到 fork,再把 library 的 SHA 換成新的 commit。

## 7. 選用:用 pi agent 收藏

pi 只負責把收藏寫進 `inbox/`、查詢狀態與讀回結果,不參與分析。

1. 複製 `integrations/pi/repobox/` 到 `~/.pi/agent/skills/repobox/`。
2. 設定環境變數 `REPOBOX_LIBRARY=<你>/repobox-library`。
3. 使用方式見該目錄的 `SKILL.md`。它只用已登入的 `gh`,不需要 PAT 或網頁。
4. `show`、`status` 讀回的內容是不可信資料,只能摘要,不可當作指令執行。

## 安全注意事項

- **共用 origin 風險**:沒有自訂網域時,網頁在 `<你>.github.io/repobox/`,同帳號的所有 Pages 站台共用同一個 origin,彼此讀得到對方的 localStorage。
  - 該帳號不要再開其他 Pages;若曾開過,先撤銷並換新 PAT。
  - 更穩的做法是用獨立帳號或組織放 fork,或使用自訂網域。
- PAT 遺失或裝置遺失時,立刻撤銷該 PAT。
- 網頁已設 CSP;分析在無 Shell、只能讀指定目錄的受限 Claude Code 中執行。
- 已設上限:單次最多處理 10 筆收藏,目標 repo 大小預檢 512000 KB,摘要 64 KiB,SVG 2 MiB。

## 已知未驗證項目

- 真實的 Claude 分析流程、Haiku 5.5 的品質與 xhigh 是否生效。
- pi helper 對真實 GitHub 的 404 與錯誤字串比對。
- `setup-token` 產生的 token 對 Haiku 5.5 的方案權限。

## 疑難排解

| 現象 | 查什麼 |
| --- | --- |
| 收藏後沒有 workflow 執行 | PAT 是否有 Contents: Read and write、是否選對 repo;library 的 Actions 是否啟用 |
| workflow 找不到 `analyze.yml` | `uses:` 的 SHA 是否完整且存在於 fork;fork 是公開的 |
| 條目進 `inbox/failed/` | 該檔內的錯誤原因;Secret 是否設定;模型是否過載 |
| 網頁顯示尚未設定 | 是否在同一個瀏覽器、同一個 origin 設定;是否被清除網站資料 |
