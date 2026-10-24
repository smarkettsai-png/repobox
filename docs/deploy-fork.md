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

手機設定與分享收藏見下一節。

## 5.1 手機設定(PWA 分享捷徑)

網頁是 PWA,安裝後會出現在手機的分享選單:在 GitHub App 或瀏覽器的專案頁按「分享」→ 選 RepoBox,就會自動收藏,不用複製貼上。

### 設定步驟

1. **建這支手機專用的 PAT。** 照 4.2 的權限再建一把(只選 `repobox-library`、Contents: Read and write、不勾 Workflows、設到期日),名稱標明裝置,例如 `repobox-phone`。每台裝置各用一把,遺失時只撤銷該把。
2. 把 PAT 傳到手機時,使用密碼管理器或自己的加密備忘錄,不要透過聊天軟體或雲端公開文件。
3. 用手機瀏覽器開 `https://<你>.github.io/repobox/`。
4. 按頂部「尚未設定」標籤,填 `<你>/repobox-library` 與手機專用 PAT,按「儲存」。
5. **安裝成 App**(沒安裝就不會出現在分享選單):
   - Android Chrome:選單 →「安裝應用程式」或「加到主畫面」。
   - iPhone Safari:分享 →「加入主畫面」。
6. 到 GitHub App 或瀏覽器開一個專案頁,按分享,選 **RepoBox**。RepoBox 會開啟,顯示收到的專案並收藏。

### 運作方式

- `manifest.webmanifest` 宣告 `share_target`,接收分享的標題、文字、網址。
- 分享內容以 POST 送到網頁的 `/share`,由 service worker 暫存後導回首頁。
- 首頁從分享的文字中找出 GitHub 專案網址(會拆開常見的跳轉包裝連結),再用該裝置的 PAT 寫入 `inbox/`。
- 首頁底部「最後一次收到的分享內容」可展開,用來除錯。

### 限制與未驗證

- 每台裝置的 localStorage 各自獨立,每台都要設定一次。
- Android Chrome 支援分享目標。**iPhone Safari 是否支援尚未確認**;不行時改用首頁輸入框複製貼上。
- 以上只確認過程式與設定檔的寫法,**尚未在真機測試**。
- 分享選單沒出現 RepoBox 時:確認已安裝成 App(不是只開網頁),並重新開啟 App 一次。
- 收到分享但沒有收藏:展開「最後一次收到的分享內容」,看是否找得到 GitHub 專案網址;PAT 是否過期。

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
| 手機分享選單沒有 RepoBox | 是否已安裝成 App;見 5.1 |
| 網頁顯示尚未設定 | 是否在同一個瀏覽器、同一個 origin 設定;是否被清除網站資料 |
