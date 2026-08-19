# 外部服務清單

> 對應 [`CODE_REVIEW.md`](./CODE_REVIEW.md) 的 P3-32。
> 這份文件解決的問題很具體：`config_common.yaml` 裡只有 `http://localhost:9091` ~ `9094`，
> **沒有服務名稱、沒有 repo 位置、沒有「這一個負責什麼」**。容器設定確實都做好了，
> 但不在這個 repo，換機器或隔一陣子回來時只能靠記憶找。
>
> 最後核對：2026-08-20（以 `docker compose ls` 與各 repo 的實際內容為準，不是憑印象寫的）

## 一覽

| 服務 | Port | Container | 專案位置 | Compose 檔名 |
| --- | --- | --- | --- | --- |
| Google Sheets | 9091 | `google-sheets-svc` | `C:\Dev\GoProjects\google-sheets-svc` | `docker-compose.yaml` |
| OpenAI | 9092 | `openai-svc` | `C:\Dev\GoProjects\openai-svc` | `docker-compose.yaml` |
| MongoDB Atlas | 9093 | `mongo-atlas-svc` | `C:\Dev\GoProjects\mongo-atlas-svc` | `compose.yaml` |
| YouTube | 9094 | `youtube-svc` | `C:\Dev\GoProjects\youtube-svc` | `compose.yaml` |
| n8n（TM AI Agent） | 5678 | `n8n-main`、`n8n-runners` | `C:\Dev\Docker\n8n` | `compose.yaml` |

四個微服務都是 **Go 1.24.1**、各自獨立部署，並且都掛了 Swagger：`http://localhost:<port>/docs/index.html`。
根路徑 `/` 一律回 404（Go mux 的預設），所以「連得上但回 404」代表服務是活著的。

> ⚠️ Compose 檔名不一致（兩個 `docker-compose.yaml`、兩個 `compose.yaml`）。
> `docker compose up` 兩種都認得，所以不影響操作，但寫腳本時要注意。

## 各服務的職責與端點

### Google Sheets — 9091

指令集、轉職表、吃啥、諧音梗、冒險台詞等營運內容的來源（試算表當 CMS）。

| 端點 | Bot 有用嗎 |
| --- | --- |
| `GET /sheet_data` | ✅ 唯一用到的 |
| `GET /sheet_data_by_range` | ❌ |
| `GET /sheet_data_by_cell` | ❌ |

**掛掉的影響**：Bot 仍會啟動（降級模式），但所有 `!` 指令、打招呼詞、`!吃`、`!梗`、轉職都失效；
每 5 分鐘自動重試，服務起來後會在聊天室公告已恢復。詳見 CODE_REVIEW P1-37。

**這是四個裡最容易忘記開的一個**——只在啟動那一瞬間用到，開台途中完全不會再碰。

憑證：`credentials.json` 與 `the-signal-373210-d7ffa73e704d.json`（Google 服務帳戶）放在 repo 根目錄。

### OpenAI — 9092

| 端點 | Bot 有用嗎 |
| --- | --- |
| `POST /structured_output` | ✅ 唯一用到的（`!pk`） |
| `POST /conversation` | ❌ 已無呼叫端（第八輪移除 `gpt_chat_session`） |
| `GET /text_generate` | ❌ |
| `GET /text_generate_with_system` | ❌ |

**第八輪起只服務 `!pk` 一個指令。** AI 問答已全面改走 n8n，
留著這個服務的唯一理由是 `!pk` 需要模型回傳符合 JSON Schema 的欄位，
而 n8n 的 Agent 只回純文字。

**掛掉的影響**：`!pk` 回制式錯誤訊息，其餘一切正常。
`OPENAI_API_KEY` 也已從必填降為選填，缺少時 Bot 照常啟動。

設定：`config/config.yaml`（含 OpenAI API key 與模型名稱）。

### MongoDB Atlas — 9093

所有持久化資料的唯一出入口。

| 端點 | Bot 有用嗎 |
| --- | --- |
| `POST /mongo/find` | ✅ |
| `POST /mongo/update` | ✅ |
| `POST /mongo/insert_one` | ✅ |
| `POST /mongo/create_index` | ✅（手動維護用） |
| `POST /mongo/insert_many` | ❌ 有包但無呼叫端 |

Database：`tm_twitch_bot`。Collection：

| Collection | 內容 |
| --- | --- |
| `tm_twitch_users` | 觀眾角色資料（等級、經驗、金幣、職業、屬性、歷來暱稱、發言數） |
| `tm_twitch_vips` | VIP 兌換狀態（到期日、啟用狀態、兌換歷史） |

> `gpt_chat_sessions` 已於 2026-08-20 刪除（舊 `!gpt` 對話歷史，1 份文件 153 則訊息）。
> 刪除前有備份，`gpt_chat_session.py` 移除後就沒有任何程式讀寫它了。

**⚠️ 這個服務沒有任何刪除端點**（只有 insert / find / update / create_index）。
要刪資料得從 Atlas 後台或直接連線處理——這是刻意的保守設計，
但也意味著清理工作無法透過服務完成。

**掛掉的影響**：該次訊息的獎勵存不了並記 log，其餘正常。
角色仍是「髒」的，下一次成功存檔會一起寫入。

設定：`config/config.yaml`（含 Atlas 連線字串與 database 名稱）。

### YouTube — 9094

代理虎喵歌單查詢。

| 端點 | Bot 有用嗎 |
| --- | --- |
| `GET /playlist` | ✅ 唯一的端點 |

**掛掉的影響**：`!YT` 與 `!找歌` 回制式錯誤訊息，其餘正常。
歌單在啟動時抓一次並快取，快取目前不會自動失效（CODE_REVIEW P2-15）。

設定：`config/config.yaml`。

### n8n（TM AI Agent） — 5678

自架 n8n 上的 AI Agent 工作流，**多客戶端共用**（Discord bot 也在用），
經 ngrok 靜態網域對外：`https://nemesis-ozone-credible.ngrok-free.dev/webhook/tm-ai-agent`。

人設「虎喵小粉絲」、對話記憶（同 `channel_id` 共享最近 10 輪）與工具呼叫
（台灣熱搜／頭條、網路搜尋、維基、計算機、日期計算、統計圖表、虎喵歌單）全都在 n8n 端。
Bot 這側只負責送齊欄位與同頻道排隊。

**掛掉的影響**：AI 問答回一句固定的道歉語，其餘正常。錯誤細節只進 log
（訊息會夾帶 ngrok 網址等內部資訊，不能進公開聊天室）。

認證：`x-webhook-secret` header，值來自 Bot 的 `.env`（`TM_AI_AGENT_SECRET`）。

> n8n 端不屬於本專案，也不會為了 Twitch 修改。它保證回覆是純文字單行、500 字元以內。

## 啟動

四份 compose 分散在四個資料夾，手動等於要開四個終端機。本 repo 提供：

```powershell
.\tools\start_services.ps1          # 啟動四個微服務並檢查是否真的活著
.\tools\start_services.ps1 -Check   # 只檢查，不啟動
```

n8n 刻意不在腳本內：它是多客戶端共用的服務，生命週期跟這個 Bot 無關。

手動的等價操作：

```powershell
cd C:\Dev\GoProjects\google-sheets-svc; docker compose up -d
cd C:\Dev\GoProjects\openai-svc;        docker compose up -d
cd C:\Dev\GoProjects\mongo-atlas-svc;   docker compose up -d
cd C:\Dev\GoProjects\youtube-svc;       docker compose up -d
```

### 平常不需要手動啟動

四個服務的 `restart` 政策都會讓它們在 Docker Desktop 起來後自動復原，
所以正常情況下開機就在跑了。腳本是給「重建機器」或「懷疑某個沒起來」時用的。

| 服務 | restart 政策 | 意義 |
| --- | --- | --- |
| google-sheets-svc | `unless-stopped` | 一直重啟直到手動停止 |
| mongo-atlas-svc | `unless-stopped` | 同上 |
| youtube-svc | `unless-stopped` | 同上 |
| **openai-svc** | **`on-failure:5`** | **失敗 5 次後放棄並保持停止** |

> ⚠️ `openai-svc` 的政策和其他三個不同。它連續失敗 5 次就不再嘗試，
> 而且不會有任何通知——某天 `!pk` 壞掉又「看起來服務都開著」的話，
> 先用 `docker ps -a` 確認它是不是已經放棄了。
> 另外它是唯一有記憶體上限（256M）的服務。

## 已知的營運風險

### 四個微服務都沒有版本控管

`google-sheets-svc`、`openai-svc`、`mongo-atlas-svc`、`youtube-svc`、`C:\Dev\Docker\n8n`
**都不是 git repo**（2026-08-20 核對）。這代表：

- 改壞一個 handler 沒有任何辦法還原，也看不出改了什麼
- 機器壞掉或資料夾誤刪，四個服務的原始碼就沒了——而 Bot 有四分之一的功能綁在它們身上
- Google 服務帳戶憑證、OpenAI API key、Atlas 連線字串都只存在那幾台機器上的單一副本

這比「缺一份服務清單」嚴重得多。**建議每個服務各建一個 private repo**，
並在第一次 commit 之前先寫好 `.gitignore`——那四個資料夾裡有憑證檔與含密鑰的
`config/config.yaml`，直接 `git add -A` 會把機敏資訊寫進歷史（歷史很難乾淨移除）。

參考本專案的做法：機敏值放 `.env`（gitignored），設定檔只留非機敏項目。

### 其他小事

- Compose 檔都寫 `version: '3.8'`，新版 Docker Compose 會警告這個欄位已廢棄，可以直接刪掉那一行
- 三個 Go 服務的 compose 帶 `NODE_ENV=production`，那是 Node 樣板的殘留，對 Go 沒有作用
- `openai-svc` 有四個端點，Bot 只用一個；`mongo-atlas-svc` 的 `insert_many` 也無呼叫端
