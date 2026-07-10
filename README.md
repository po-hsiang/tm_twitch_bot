# tm_twitch_bot 🐯

為 Twitch 頻道 **tigermeowtw（虎喵）** 打造的聊天室機器人。以「聊天即遊戲」為核心概念：觀眾在聊天室發言即可獲得經驗值與金幣、升級轉職，並參與抽卡、終極密碼、一桶金等小遊戲，還能與 GPT 聊天、進行 AI 旁白的 RPG 對戰，或用金幣兌換頻道 VIP。

> 指令的觸發詞與回覆內容集中維護在 [Google Sheets 指令集](https://docs.google.com/spreadsheets/d/1-UQ7KBWK09ZCHZKFycymk04BaB5oW6DJ0vi2N7x6qQE/edit?usp=sharing)，不需改程式即可新增／調整指令。

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
├── pyproject.toml              # Poetry 專案定義（Python >= 3.13）
├── poetry.lock
├── src/tm_twitch_bot/
│   ├── main.py                 # 進入點：Token 驗證/刷新、Bot 啟動、事件註冊
│   ├── config/
│   │   └── config_common.yaml  # 全域設定（Twitch 憑證、各服務 URL、遊戲參數）
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
│       ├── yaml_utils.py           # 設定載入 / Token 寫回
│       ├── http_utils.py           # 帶重試的 HTTP 請求
│       ├── log_utils.py            # 彩色 Logger
│       ├── probability_utils.py    # 加權隨機
│       └── ...
└── tests/                      # （目前尚無測試）
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

1. **Python 3.13+** 與 **Poetry 2.x**
2. **四個本地微服務**已啟動（不在本 repo 內）：
   - Google Sheets 服務 → `localhost:9091`
   - OpenAI 服務 → `localhost:9092`
   - MongoDB Atlas 服務 → `localhost:9093`
   - YouTube 服務 → `localhost:9094`
3. Twitch 開發者應用程式（Client ID / Secret），Redirect URI 設定至你的 callback 網址。

### 安裝

```bash
poetry install
```

### 首次取得 Token

1. 啟動 OAuth callback 伺服器：

   ```bash
   poetry run python src/tm_twitch_bot/oauth/server.py
   ```

2. 於瀏覽器開啟授權網址（scope 需含 `chat:read chat:edit channel:read:redemptions channel:read:vips channel:manage:vips`），完成授權後從 callback 回應取得 `access_token` 與 `refresh_token`，填入 `config_common.yaml`。

### 啟動 Bot

```bash
poetry run python src/tm_twitch_bot/main.py
```

啟動流程：驗證 access token（失效時自動以 refresh token 換新並寫回設定檔）→ 建立 Twitch 物件 → 連線聊天室 → 訂閱忠誠點數 EventSub → 啟動排程任務。

### 測試模式

將 `config_common.yaml` 的 `is_test` 設為 `true`：Bot 不會發送上線公告，且只回應 `tigermeowtw_id` 指定帳號的訊息。

---

## 設定檔說明

`src/tm_twitch_bot/config/config_common.yaml`（敏感值以 `***` 表示）：

```yaml
is_test: false                # 測試模式開關
tigermeowtw_id: '***'         # 頻道主 user_id
admin_user_id: ['***']        # 管理員清單（可開遊戲）
bot_user_id: ['***']          # 機器人帳號（訊息忽略）
rpg_parameter:
  default_gained_exp: 1       # 每句話經驗
  default_gainer_gold: 1      # 每句話金幣
  exp_req_multiple: 10        # 升級所需經驗 = 等級 × 此值
twitch:
  access_token: '***'
  refresh_token: '***'
  client_id: '***'
  client_secret: '***'
  channel: tigermeowtw
  redirect_uri: https://***/callback
google_sheets: { svc_url: 'http://localhost:9091', sheet_url: '***' }
openai:        { svc_url: 'http://localhost:9092', api_key: '***', model: gpt-5-nano }
mongodb_atlas: { svc_url: 'http://localhost:9093' }
youtube:       { svc_url: 'http://localhost:9094', tm_playlist_id: '***' }
vip_system:
  enabled: true
  gold_cost: 100              # 兌換價格
  vip_cap: 51                 # VIP 名額上限
  days_per_redeem: 31         # 每次兌換天數
```

> ⚠️ **安全提醒**：此檔目前直接存放 access token、client secret 與 OpenAI API key 等明文機密。強烈建議改用環境變數或密鑰管理服務，並確保此檔不進入版本控制（見[注意事項](#注意事項)）。

---

## 資料儲存

MongoDB Atlas（經由 `:9093` 服務代理）使用的 Collections：

| Collection | 內容 |
|---|---|
| `tm_twitch_users` | 觀眾角色資料（等級、經驗、金幣、職業、屬性、歷來暱稱、發言數） |
| `tm_twitch_vips` | VIP 兌換狀態（到期日、啟用狀態、兌換歷史） |
| `gpt_chat_sessions` | `!gpt` 對話歷史（含 System Prompt） |

---

## 注意事項

- **機密管理**：`config_common.yaml` 內含明文憑證，請勿公開此檔或將其納入版本控制；外洩時請立即輪替（Twitch Client Secret、OpenAI API Key）。
- **啟動順序**：Bot 在模組載入階段就會呼叫 Google Sheets / YouTube 等服務拉取設定，因此**四個微服務必須先於 Bot 啟動**，否則 import 階段即失敗。
- **指令集熱更新限制**：指令集於啟動時載入一次，修改試算表後需重啟 Bot 才會生效。
- **已知問題**：忠誠點數兌換事件偶爾收不到其他使用者的兌換通知（見 `main.py` 中 `on_points` 的 TODO）。
- `tests/` 目前為空，尚未建立自動化測試。
