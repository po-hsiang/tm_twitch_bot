# tm_twitch_bot 🐯

為 Twitch 頻道 **tigermeowtw（虎喵）** 打造的聊天室機器人。以「聊天即遊戲」為核心概念：觀眾在聊天室發言即可獲得經驗值與金幣、升級轉職，並參與抽卡、終極密碼、一桶金等小遊戲，還能與 GPT 聊天、進行 AI 旁白的 RPG 對戰，或用金幣兌換頻道 VIP。

> 指令的觸發詞與回覆內容集中維護在 [Google Sheets 指令集](https://docs.google.com/spreadsheets/d/1-UQ7KBWK09ZCHZKFycymk04BaB5oW6DJ0vi2N7x6qQE/edit?usp=sharing)，不需改程式即可新增／調整指令。

### 📄 相關文件

| 文件 | 內容 |
|---|---|
| [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md) | 程式碼健檢報告：缺陷清單、優先序與處置狀態 |
| [`docs/project_report.html`](docs/project_report.html) | 互動式專案報告：架構圖、訊息流程圖、指令總表 |

---

## 目錄

- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [專案結構](#專案結構)
- [訊息處理流程](#訊息處理流程)
- [指令一覽](#指令一覽)
- [安裝與執行](#安裝與執行)
- [設定檔說明](#設定檔說明)
- [資料儲存](#資料儲存)
- [測試](#測試)
- [注意事項](#注意事項)

---

## 功能特色

### 🎮 聊天 RPG 養成（role_system / level_and_job_system）
- 每位觀眾第一次發言自動建立角色（`Character`），欄位含等級、經驗、金幣、職業與六維屬性（STR / AGI / VIT / INT / DEX / LUK）。
- 發言即獲得經驗與金幣；升級時隨機提升一項屬性。
- 到達門檻等級（10 等一轉、15 等二轉）自動隨機轉職，職業表由 Google Sheets「轉職表」維護。
- `!英雄`、`!富翁` 查看等級榜與財富榜（rank_system）。

### 🎰 小遊戲（games / gacha_handler）
| 遊戲 | 說明 |
|---|---|
| 終極密碼（guess_number_game） | 猜 0~1000 之間的數字，每次猜測收費並灌注彩金池，越早猜中基礎獎金越高 |
| 一桶金（gold_rush_game） | 限時投注，每人上限 10 Gold，結束後依投入比例加權抽出得主獨得全池 |
| 抽卡（gacha_handler） | 20 Gold 十連抽，抽中稀有表情符號可獲得對應 Gold 回饋 |

### 🤖 AI 互動（ai_actions）
- `!gpt <問題>`：具人設（虎喵粉絲）的 GPT 聊天，對話歷史存於 MongoDB，超過 token 上限自動裁切最舊問答。
- `!pk @對象`：取雙方角色數值，由 GPT 以結構化輸出（JSON Schema）生成戲劇化對戰旁白並判定勝負。

### 👑 VIP 系統（vip_system）
- 用 100 Gold 兌換 31 天頻道 VIP（透過 Twitch Helix API 實際授予徽章）。
- 名額上限 51 人；到期後由過期掃描（sweep）移除 VIP 並更新資料庫紀錄。

### ⏰ 排程任務（task_scheduler）
- 每 20 分鐘提醒喝水、每 30 分鐘隨機開啟一場小遊戲、每日 23:59 換日提醒。
- 通用的 `TaskScheduler` 支援 interval / daily 兩種任務型態，可註冊多個函數隨機執行其一。

### 💬 聊天品質控管（message_controller）
- 3 秒發言冷卻、重複訊息（洗頻）過濾、機器人帳號忽略。
- 首次發言依台灣時區給予早安／午安／晚安招呼並贈送獎勵。

### 📊 其他日常指令
- `!吃`：隨機推薦吃什麼（每人每次啟動記憶一次結果）。
- `!梗`：隨機諧音梗。
- `!YT` / `!找歌 <關鍵字>`：從虎喵歌單隨機推薦或搜尋歌曲。
- 忠誠點數兌換事件：透過 EventSub WebSocket 接收頻道點數兌換通知。

---

## 系統架構

本專案採 **Bot 主程式 + 本地微服務** 的架構，所有外部資源（Google Sheets、OpenAI、MongoDB Atlas、YouTube）都透過獨立的本地 HTTP 服務代理，Bot 端僅保留輕量的 HTTP Client（`svc_client/`）。

```
                         ┌──────────────────────────────┐
                         │        Twitch 平台            │
                         │  IRC Chat / EventSub / Helix  │
                         └──────┬────────────┬───────────┘
                                │            │
                     twitchio(chat)    twitchAPI(EventSub/VIP)
                                │            │
┌───────────────────────────────▼────────────▼──────────────────┐
│                     main.py (MyBot)                            │
│  Token 驗證/刷新 → 事件監聽 → message_controller → dispatcher   │
└──────┬──────────────┬──────────────┬──────────────┬────────────┘
       │              │              │              │
   svc_client     svc_client     svc_client     svc_client
       │              │              │              │
┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐
│GoogleSheets│ │  OpenAI    │ │ MongoDB    │ │  YouTube   │
│  svc :9091 │ │  svc :9092 │ │ Atlas svc  │ │  svc :9094 │
│(指令/文案) │ │ (GPT/對戰) │ │   :9093    │ │  (歌單)    │
└────────────┘ └────────────┘ └────────────┘ └────────────┘
```

- **twitchio**（2.x）：負責 IRC 聊天訊息的收發。
- **twitchAPI**（4.x）：負責 EventSub WebSocket（忠誠點數兌換）與 Helix API（VIP 授予/移除）。
- **oauth/server.py**：FastAPI 撰寫的 OAuth callback 伺服器（port 8096），用於首次取得 access / refresh token。
- **Google Sheets 作為 CMS**：指令集、轉職表、吃啥、諧音梗、冒險台詞等內容皆存放於試算表，營運人員可直接編輯。

---

## 專案結構

```
tm_twitch_bot/
├── pyproject.toml              # 專案定義（uv 管理，Python >= 3.13）
├── uv.lock
├── .env                        # 機敏資訊（token / secret / api key），不進版控
├── .env.example                # .env 範本
├── docs/
│   ├── CODE_REVIEW.md          # 程式碼健檢報告（缺陷清單與處置狀態）
│   └── project_report.html     # 互動式專案報告（架構圖／流程圖／指令表）
├── src/tm_twitch_bot/
│   ├── main.py                 # 進入點：Token 驗證/刷新、bootstrap、Bot 啟動
│   ├── config/
│   │   └── config_common.yaml  # 非機敏設定（各服務 URL、遊戲參數）
│   ├── oauth/
│   │   └── server.py           # FastAPI OAuth callback（首次授權用）
│   ├── scripts/                # 核心業務邏輯
│   │   ├── message_controller.py   # 訊息處理管線（冷卻/洗頻/獎勵/派發）
│   │   ├── command_dispatcher.py   # 指令派發器（Sheets 設定 + 動態載入函數）
│   │   ├── role_system.py          # Character 資料模型與 RPG 行為
│   │   ├── level_and_job_system.py # 轉職表解析
│   │   ├── rank_system.py          # 排行榜
│   │   ├── vip_system.py           # VIP 兌換與到期掃描
│   │   ├── gacha_handler.py        # 抽卡
│   │   ├── greeter.py              # 首次發言招呼
│   │   ├── daily_food_picker.py    # !吃
│   │   ├── daily_meme_picker.py    # !梗
│   │   ├── task_scheduler.py       # 通用排程器 + 排程任務定義
│   │   └── call_timer.py           # 排程器使用範例
│   ├── games/
│   │   ├── guess_number_game.py    # 終極密碼
│   │   └── gold_rush_game.py       # 一桶金
│   ├── ai_actions/
│   │   ├── gpt_chat_session.py     # !gpt 聊天 Session
│   │   └── duel.py                 # !pk AI 對戰旁白
│   ├── svc_client/             # 對本地微服務/外部 API 的 HTTP Client
│   │   ├── google_sheets.py
│   │   ├── openai.py
│   │   ├── mongo_atlas.py
│   │   ├── youtube.py
│   │   └── twitch_vips_api.py      # 直接呼叫 Twitch Helix VIP API
│   └── utils/
│       ├── yaml_utils.py           # 設定載入（YAML + .env 合併）
│       ├── token_manager.py        # Token 唯一來源（刷新後同步記憶體與 .env）
│       ├── http_utils.py           # 帶重試的非同步 HTTP 請求（httpx.AsyncClient）
│       ├── log_utils.py            # 彩色 Logger
│       ├── probability_utils.py    # 加權隨機
│       └── ...
└── tests/                      # pytest 測試（全離線，不需啟動微服務）
    ├── conftest.py                 # 假環境變數與共用 fixture
    ├── test_command_dispatcher.py
    ├── test_greeter.py
    ├── test_role_system.py
    └── test_level_and_job_system.py
```

---

## 訊息處理流程

每則聊天訊息經過以下管線（`message_controller.handle_message`）：

```
訊息進入
  → 機器人帳號？──是──▶ 忽略
  → 載入或建立角色（MongoDB）
  → 累計發言次數 total_msgs +1
  → 3 秒冷卻中？──是──▶ 忽略
  → 與上一句重複（洗頻）？──是──▶ 忽略
  → 首次發言？──是──▶ 招呼 + 贈送 3 EXP / 3 Gold
  → 發言獎勵 +1 EXP / +1 Gold（可能觸發升級/轉職廣播）
  → command_dispatcher 比對指令集
       ├─ text 類型：直接回覆文字
       └─ function 類型：動態 import 並執行對應函數
  → 回覆結果（若有）
  → 角色存檔（MongoDB）
```

指令派發規則（`command_dispatcher`）：
1. `!指令`（無參數），例：`!英雄`
2. `!指令 參數`，例：`!gpt 我帥嗎`
3. 無驚嘆號關鍵字（句子包含即觸發），例：`帥`
4. 全形驚嘆號自動正規化為半形；指令大小寫不敏感。

---

## 指令一覽

實際觸發詞以 Google Sheets「指令集」工作表為準，以下為程式內對應的功能：

| 指令 | 功能 | 對應模組 |
|---|---|---|
| `!INFO` | 查看自己的角色資訊 | `role_system.check` |
| `!英雄` | 等級排行榜 Top 3 | `rank_system.top_heroes` |
| `!富翁` | 財富排行榜 Top 3 | `rank_system.top_richest` |
| `!抽` | 20 Gold 十連抽 | `gacha_handler.gacha` |
| `!猜 <數字>` | 終極密碼猜數字 | `guess_number_game.guess` |
| `!投 <金額>` | 一桶金投注 | `gold_rush_game.toss` |
| `!gpt <問題>` | 與 AI 聊天 | `gpt_chat_session.ask` |
| `!pk @對象` | AI 旁白 RPG 對戰 | `duel.pk` |
| `!vip` | 100 Gold 兌換 31 天 VIP | `vip_system.redeem` |
| `!吃` | 隨機推薦食物 | `daily_food_picker.pick` |
| `!梗` | 隨機諧音梗 | `daily_meme_picker.pick` |
| `!YT` | 隨機推薦歌單歌曲 | `youtube.pick` |
| `!找歌 <關鍵字>` | 搜尋歌單 | `youtube.search_song` |

管理員（`admin_user_id`）限定：手動開啟終極密碼／一桶金（`guess_number_game.start`、`gold_rush_game.start`）。

---

## 安裝與執行

### 前置需求

1. **Python 3.13+** 與 **[uv](https://docs.astral.sh/uv/)**
2. **四個本地微服務**已啟動（不在本 repo 內）：
   - Google Sheets 服務 → `localhost:9091`
   - OpenAI 服務 → `localhost:9092`
   - MongoDB Atlas 服務 → `localhost:9093`
   - YouTube 服務 → `localhost:9094`
3. Twitch 開發者應用程式（Client ID / Secret），Redirect URI 設定至你的 callback 網址。

### 安裝

```bash
uv sync
```

### 設定機敏資訊

複製 `.env.example` 為 `.env`，填入 Twitch 憑證與 OpenAI API Key：

```bash
cp .env.example .env
```

### 首次取得 Token

1. 啟動 OAuth callback 伺服器：

   ```bash
   uv run python src/tm_twitch_bot/oauth/server.py
   ```

2. 於瀏覽器開啟授權網址（scope 需含 `chat:read chat:edit channel:read:redemptions channel:read:vips channel:manage:vips`），完成授權後從 callback 回應取得 `access_token` 與 `refresh_token`，填入 `.env`。

### 啟動 Bot

```bash
uv run python src/tm_twitch_bot/main.py
```

啟動流程：驗證 access token（失效時自動以 refresh token 換新並寫回 `.env`）→ 建立 Twitch 物件 → bootstrap 載入指令集與轉職表 → 連線聊天室 → 訂閱忠誠點數 EventSub → 啟動排程任務。

### 測試模式

將 `config_common.yaml` 的 `is_test` 設為 `true`：Bot 不會發送上線公告，且只回應 `tigermeowtw_id` 指定帳號的訊息。

---

## 設定檔說明

設定分成兩層：

### `.env`（機敏資訊，已列入 .gitignore）

```env
TWITCH_CLIENT_ID=...
TWITCH_CLIENT_SECRET=...
TWITCH_ACCESS_TOKEN=...
TWITCH_REFRESH_TOKEN=...
OPENAI_API_KEY=...
```

Token 由 `utils/token_manager.py` 集中管理：無論啟動時手動刷新或 twitchAPI 執行期自動刷新，都會同步更新記憶體並寫回 `.env`。

### `src/tm_twitch_bot/config/config_common.yaml`（非機敏設定，可入版控）

```yaml
is_test: false                # 測試模式開關
tigermeowtw_id: '...'         # 頻道主 user_id
admin_user_id: ['...']        # 管理員清單（可開遊戲）
bot_user_id: ['...']          # 機器人帳號（訊息忽略）
rpg_parameter:
  default_gained_exp: 1       # 每句話經驗
  default_gainer_gold: 1      # 每句話金幣
  exp_req_multiple: 10        # 升級所需經驗 = 等級 × 此值
twitch:
  channel: tigermeowtw
  redirect_uri: https://***/callback
google_sheets: { svc_url: 'http://localhost:9091', sheet_url: '...' }
openai:        { svc_url: 'http://localhost:9092', model: gpt-5-nano }
mongodb_atlas: { svc_url: 'http://localhost:9093' }
youtube:       { svc_url: 'http://localhost:9094', tm_playlist_id: '...' }
vip_system:
  enabled: true
  gold_cost: 100              # 兌換價格
  vip_cap: 51                 # VIP 名額上限
  days_per_redeem: 31         # 每次兌換天數
```

程式載入時（`utils/yaml_utils.py`）會把 `.env` 的機敏值合併進 config dict，既有的 `config["twitch"]["access_token"]` 取用方式不變。

---

## 資料儲存

MongoDB Atlas（經由 `:9093` 服務代理）使用的 Collections：

| Collection | 內容 |
|---|---|
| `tm_twitch_users` | 觀眾角色資料（等級、經驗、金幣、職業、屬性、歷來暱稱、發言數） |
| `tm_twitch_vips` | VIP 兌換狀態（到期日、啟用狀態、兌換歷史） |
| `gpt_chat_sessions` | `!gpt` 對話歷史（含 System Prompt） |

---

## 測試

```bash
uv run pytest
```

測試全部離線執行，不需要啟動任何微服務、也不會讀到真正的 `.env`——`tests/conftest.py` 會在 import 任何專案模組之前塞入假的環境變數。

目前覆蓋 `command_dispatcher`（指令派發與分詞）、`greeter`（惰性載入與降級）、`role_system`（升級與轉職邊界）、`level_and_job_system`（轉職表解析）。尚未覆蓋的部分與補齊順序列在 [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md) 的 P2-19。

---

## 注意事項

- **機密管理**：所有憑證存於 `.env`（已列入 `.gitignore`）。請勿把 `.env` 分享給任何人；懷疑外洩時請立即輪替 Twitch Client Secret 與 OpenAI API Key。
- **啟動順序**：Google Sheets 的指令集與轉職表在 Bot 啟動的 bootstrap 階段載入（其餘資料為首次使用時惰性載入），因此**啟動 Bot 時微服務需在線**；單純 import 模組（開發、測試）則不需要。
- **非同步 HTTP**：所有對微服務與 Twitch Helix 的請求都走共用的 `httpx.AsyncClient`，重試等待不會阻塞事件圈。
- **指令集熱更新限制**：指令集於啟動時載入一次，修改試算表後需重啟 Bot 才會生效。
- **twitchio 版本相依**：`main.py` 的 token 同步機制寫入了 twitchio 的私有屬性（`_http.token`、`_connection._token`）。套件已釘選 `twitchio>=2.10,<3`，升級時務必一併驗證。
- **待實測**：忠誠點數兌換偶爾收不到其他使用者事件的問題，已修正 EventSub 物件被 GC 回收的疑似成因（CODE_REVIEW P0-3），但**尚未於正式頻道驗證**，上線後請實際請他人兌換一次確認。
- **待處理缺陷**：完整清單與優先序見 [`docs/CODE_REVIEW.md`](docs/CODE_REVIEW.md)。
