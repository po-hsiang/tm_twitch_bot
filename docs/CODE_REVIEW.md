# tm_twitch_bot 程式碼健檢報告

| 項目 | 內容 |
| --- | --- |
| 健檢日期 | 2026-08-09 |
| 基準版本 | `584821e`（健檢起點） |
| 最後更新 | 2026-08-09，第六輪修正後 |
| 範圍 | `src/tm_twitch_bot/` 全部模組、`pyproject.toml`、版控與部署設定 |
| 評估準則 | 依使用者指定的優先序：**穩定 > 好維護 > 好擴充** |

> 互動式架構圖與流程圖請見 [`project_report.html`](./project_report.html)。
> 本文件專注在缺陷清單與處置狀態。

## 狀態圖例

| 標記 | 意義 |
| --- | --- |
| ✅ | 已修正，附 commit |
| 🧪 | 已由自動化測試鎖定，回歸時會失敗 |
| ⏸️ | 已評估，決定不處理（附理由） |
| 🔲 | 待處理 |

## 處置摘要

### 第一輪

| 編號 | 項目 | 狀態 |
| --- | --- | --- |
| P0-1 | 關鍵字比對誤用 `break` | ✅ `6c895cf` 🧪 |
| P0-2 | Token 刷新後 IRC 仍用舊 token | ✅ `b67502d` |
| P0-3 | EventSub WebSocket 參考遺失 | ✅ `89ad915` |
| P0-4 | `event_ready` 重連時重複初始化 | ✅ `89ad915` |
| P2-19 | 零測試覆蓋 | ✅ `78dc68c` |

### 第二輪

| 編號 | 項目 | 狀態 |
| --- | --- | --- |
| P0-5 | `handle_message` 無例外保護 | ✅ `38e31c7` 🧪 |
| P0-6 | `find_by_name` regex 注入 | ✅ `57d333f` 🧪 |
| P0-7 | VIP 過期掃描只跑一次 | ⏸️ 不處理 |
| P0-8 | 排程例外靜默殺死整條排程 | ✅ `aaf6d95` 🧪 |
| P2-24 | 遊戲金流與持久化不一致 | ✅ `be6e28b` `a995fe3` 🧪 |

### 第三輪

| 編號 | 項目 | 狀態 |
| --- | --- | --- |
| P1-9 | 日誌只有 stdout，無檔案無輪替 | ✅ `fb4a341` 🧪 |
| P1-16 | Mongo `find` 回傳 `None` 沒有統一防護 | ✅ `9eda404` 🧪 |
| P2-20 | 沒有 CI | ✅ `e8c8c3b` |
| P1-12 | 「每日」快取其實是「重啟才失效」 | ⏸️ 經確認為刻意設計，結案 |

### 第四輪

| 編號 | 項目 | 狀態 |
| --- | --- | --- |
| P1-10 | 重試策略對 4xx 也重試、逾時 600 秒 | ✅ `0754132` 🧪 |
| P1-11 | 內部例外訊息噴進公開聊天室 | ✅ `e4867e6` 🧪 |
| — | 開台／關台事件觀測（附錄 A 第 1 步） | ✅ `3833b57` |

### 第五輪

| 編號 | 項目 | 狀態 |
| --- | --- | --- |
| P2-30 | `parse_jobs_sheet` 對短列會 IndexError | ✅ `bb47474` 🧪 |
| P1-14 | 沒有 Twitch 訊息速率與長度保護 | ✅ `b452cd9` 🧪 |
| P1-15 | 一桶金的錯誤訊息永遠送不出去 | ✅ `3daa235` 🧪 |
| P1-13 | 沒有 graceful shutdown | ✅ `2830418` 🧪 |
| P3-32 | 沒有部署設定 | ⏸️ 大部分為誤判，重寫如下 |
| P1-37 | Google Sheets 服務沒開就啟動失敗 | 🔲 本輪查證時新發現 |

測試總數 149 項，全部離線，執行時間 0.6 秒。

### 第六輪

| 編號 | 項目 | 狀態 |
| --- | --- | --- |
| P1-37 | Google Sheets 服務沒開就啟動失敗 | ✅ `087306b` 🧪 |
| P2-23 | `Character.save()` 全欄位 `$set` 會 lost update | ✅ `788b500` 🧪 |

測試總數 170 項，全部離線，執行時間 0.65 秒。

同場加映：釐清了「開台／關台事件偵測」與營運架構的取捨，
結論見 [附錄 A](#附錄-a營運架構手動啟動-vs-常駐服務)——**維持手動啟動，並已上線只寫 log 的事件觀測**。
這個決策同時影響 P0-7、P1-12、P1-13、P3-32。

剩餘 15 項待處理，內容如下。

---

# P0｜會造成功能錯誤或資料遺失

### P0-1 ✅🧪 關鍵字指令會被「0 / 87」整串中斷

`scripts/command_dispatcher.py`

無驚嘆號的關鍵字掃描中，「0」「87」這兩個需要完全一致才觸發的指令，在不符合時執行了 `break` 而非 `continue`，直接中斷整個 `COMMAND_SET` 走訪。實務上只要觀眾訊息含有 `0` 或 `87`（網址、金額、時間都會命中），且該 trigger 在 dict 走訪順序中排在前面，**後面所有關鍵字指令就再也不會被比對到**。

已修正並加上回歸測試 `test_numeric_trigger_does_not_abort_remaining_scan`（已驗證：還原修正即失敗）。

### P0-2 ✅ Token 自動刷新後，IRC 連線仍用舊 token

`main.py` · `utils/token_manager.py`

`MyBot.__init__` 在建構當下就把 `access_token` 固定寫進 twitchio。twitchAPI 之後自動刷新時只更新了 `token_manager` 與 Helix 那條線，twitchio 的 IRC 完全不知情，跑滿 token 效期（約 4 小時）後聊天會斷線且重連失敗。

作法：`TokenManager` 新增 `add_listener()` / `_notify()`，讓「建構時複製 token」這類無法每次重取的對象在刷新當下被通知；`MyBot` 訂閱後同步寫入 `Client._http.token` 與 `Client._connection._token`，並比照 twitchio 收到 `RECONNECT` 的流程重建 IRC 連線，尚未連線時安全略過。

> ⚠️ **維護提醒**：twitchio 2.x 沒有公開的換 token API，此處相依其內部私有屬性。`pyproject.toml` 已將 twitchio 釘選在 `>=2.10,<3`；升級時務必一併驗證 `_http.token`、`_connection._token`、`_keeper`、`_connect()` 是否仍存在。

### P0-3 ✅ EventSub WebSocket 物件沒有被持有

`main.py`

`ws = EventSubWebsocket(self.twitch)` 過去是 `event_ready` 的區域變數，方法一返回就沒有任何強參考撐著，隨時可能被 GC 回收。**這很可能就是 `on_points` 那則 TODO 所述「其他人兌換收不到事件」的根因。** 已改為 `self.eventsub_ws`。

> 上線後請實測：請他人兌換一次忠誠點數，確認 `on_points` 有收到事件。若仍未收到，下一個懷疑對象是 EventSub 訂閱所用 token 的 scope 與 `broadcaster_user_id` 是否相符。

### P0-4 ✅ `event_ready` 在重連時會再次觸發

`main.py`

twitchio 2.x 每次成功連線都會呼叫 `event_ready`。原本每次都會再建一個 `EventSubWebsocket`、再跑一次 `schedule_task()`——網路抖一次，喝水提醒就變兩則、兩個隨機遊戲排程互相打架。已加 `_bootstrapped` 旗標做一次性初始化去重。

順帶修正：排程器過去抓的是 `self.channel.send` 這個 bound method，重連後 twitchio 會給出全新的 `Channel` 物件，舊物件會靜默失效。改以 `send_to_channel()` 晚綁定。

### P0-5 ✅🧪 `handle_message` 全程沒有 try/except

`scripts/message_controller.py`

`load_or_create`、`add_total_msgs_count`、`greet_user`、`dispatch_command` 全都在任何保護之外。MongoDB 或 Google Sheets 微服務一有閃失就丟 `StatusCodeError`，該則訊息中斷、**最後的 `await char.save()` 不會執行**，玩家經驗值與金幣直接蒸發。

已修正：

- 整條管線包 try/except，未預期錯誤只記錄不外拋
- 存檔移到 `finally`，任何路徑（含提早 return）都會執行
- 只在 `char.is_dirty` 時才寫入，被冷卻或洗頻擋下的訊息不再白跑一次 DB
- 存檔本身失敗也只記錄，避免蓋掉原本真正的錯誤

> 仍有無法消除的殘餘風險：若 `char.save()` 當下 MongoDB 不可用，該次異動終究會遺失。要根治需要 write-ahead log 或本地暫存佇列，屬於獨立工程。

### P0-6 ✅🧪 `find_by_name` 有 regex 注入

`scripts/role_system.py`

```python
{"display_names": {"$regex": f"^{name}$", "$options": "i"}}
```

`name` 是觀眾原始輸入。`!pk .*` 會匹配到隨機玩家；`!pk (a+)+$` 這種 catastrophic backtracking 可以直接把 Atlas 的 CPU 打滿。已改用 `re.escape()`；中文與英數名稱不受影響，已由測試覆蓋。

### P0-7 ⏸️ VIP 過期掃描只在啟動時跑一次

`main.py`（`event_ready` 內）· `scripts/vip_system.py`

`sweep_expired()` 只在 bootstrap 呼叫，Bot 連續執行期間到期的 VIP 不會被移除。

**經評估後決定維持現狀**（2026-08-09，頻道主決定）：VIP 權限只在開台時才有實際作用，而開台時本來就會重啟 Bot、觸發一次掃描。多留幾天 VIP 不構成問題，不值得為此增加一條常駐排程。

> 若未來改成 Bot 常駐不重啟，或 VIP 具備離線也生效的權益，此項需要重新評估。
> 這個「常駐 vs 手動啟動」的取捨已完整分析於 [附錄 A](#附錄-a營運架構手動啟動-vs-常駐服務)，結論是暫時維持手動啟動。

### P0-8 ✅🧪 排程器的例外會靜默殺死整條排程

`scripts/task_scheduler.py`

`while True` 內的 `_execute` 一旦拋例外，該 task 直接結束，而且沒有任何人 `await` 它 → 例外被吞掉，只在程式結束時才印 `Task exception was never retrieved`。**喝水提醒某天默默不見了，不會有任何人知道。**

已修正：

- 新增 `_execute_safely()`：單次失敗只記錄，下一輪照常觸發；`CancelledError` 仍往外傳
- 新增 `_on_job_finished()` done callback：排程迴圈不該自行退出，真的結束一律留下 log
- `__init__` 改用 `get_running_loop()`，讓「在事件圈外建構」這種誤用當場暴露（原本的 `get_event_loop()` 在 Python 3.14 起會直接拋錯）

---

# P1｜穩定性與可維運性

### P1-9 ✅🧪 日誌只有 stdout，沒有檔案、沒有輪替

`utils/log_utils.py`

Bot 半夜掛掉，隔天沒有任何線索可查——關掉終端機就什麼都不剩。

同時有個潛在地雷：`ColoredFormatter.format` 是**原地修改 `record.msg`**。只有一個 handler 時看不出問題，但同一個 `LogRecord` 會依序交給每一個 handler，一加 FileHandler，log 檔就會塞滿 `\033[92m` 這類 ANSI 碼，而且汙染程度還取決於 handler 的註冊順序。

已修正：

- 加上 `RotatingFileHandler`（`logs/tm_twitch_bot.log`，5 MB × 5 份），可用 `TM_BOT_LOG_DIR` 覆寫位置
- `encoding` 寫死 `utf-8`：Windows 預設 cp950，log 裡的繁中與 emoji（🎧 🔄 ⚠️）會直接 `UnicodeEncodeError`
- 落檔失敗只警告不中斷——不能讓 Bot 因為寫不了 log 就起不來
- `ColoredFormatter` 改為對 record 副本上色，原始 record 保持乾淨；檔案端用純 `Formatter`
- `propagate = False`，避免第三方套件呼叫 `basicConfig()` 導致 log 變兩份

> 回歸測試 `test_file_handler_output_stays_clean_after_console_formatting` 直接模擬「同一個 record 先給主控台、再給檔案」，已驗證還原修正即失敗。

### P1-10 ✅🧪 重試策略對 4xx 也重試，且 read timeout 600 秒

`utils/http_utils.py` · `svc_client/openai.py`

400/401/404 重試 3 次、每次等 5 秒 = 觀眾要等 15 秒才拿到一個「查無此人」。而 600 秒的 read timeout 意味著單一微服務卡住就能讓一個指令懸置 10 分鐘。

已修正：

- 只對 `408 / 425 / 429 / 5xx` 與連線層例外（`httpx.TransportError`）重試，其餘立刻失敗
- 退避改為指數（0.5 → 1 秒，上限 8 秒），最壞情況等待從 15 秒降到約 1.5 秒
- 讀取逾時 600 → 20 秒；GPT 這條改傳 `LONG_TIMEOUT`（120 秒），慢的呼叫不必拖累所有人
- **順帶修掉一個潛在缺陷**：成功條件原本寫死 `status_code == 200`，微服務若回 201／204 會被當成失敗而重試三次。已放寬為 2xx
- 回應內容截斷後才進 log 與例外訊息，避免整包 HTML 灌進 log 檔

### P1-11 ✅🧪 內部例外訊息會直接噴進公開聊天室

`scripts/command_dispatcher.py`

```python
return f"⚠️ 執行 {func.__name__} 時發生錯誤：{e}"
```

`StatusCodeError` 的訊息長這樣：`呼叫 http://localhost:9093/mongo/find 失敗`。指令一出錯，內部拓樸就這樣公開在聊天室裡。

已修正：觀眾一律看到制式訊息 `GENERIC_ERROR_REPLY`，細節（例外型別、堆疊、模組路徑）只進 log。

`_handle_entry` 的 Sheets 設定錯誤走同一條路——它的訊息會夾帶模組路徑（`無法導入模組 tm_twitch_bot.scripts.xxx`）。原本這份 review 只點名了 `_invoke`，但兩處是同一個問題，一併處理。

> 測試 `test_function_exception_is_contained` 已更新（原本鎖定的是「不會中斷」），並新增 `test_internal_details_never_reach_the_chat` 直接斷言回覆中不得出現 `localhost`、`9093`、`http`、`mongo`、`StatusCodeError`。

### P1-12 ⏸️「每日」的快取其實不是每日，是「重啟才失效」

`scripts/greeter.py` · `scripts/daily_food_picker.py` · `scripts/daily_meme_picker.py`

**原本的判斷有誤，此處更正。** 我把「重啟才失效」當成缺陷，但在目前「開台才手動啟動 Bot」的營運架構下，進程生命週期本來就等於一場直播，因此：

- `who_arrived` → 每場開台每人被招呼一次。**正確，且正是預期行為**
- `food_cache` → 每人每場一道菜（`dict[user_id]`，是分人的）。**正確**
- `meme_cache` → 每場一則梗。**隨開台變動的部分正確**

**經確認為刻意設計**（2026-08-09，頻道主決定）：這三項內容都應該「隨每次開台變動、該場固定」，而不是隨日曆日變動。原本建議的「每日 00:00 清空 job」與此設計衝突，**撤回**。

連粒度的不對稱也是刻意的（2026-08-09 再次確認）：

| | 快取結構 | 粒度 | 理由 |
| --- | --- | --- | --- |
| `!吃` | `dict[user_id, str]` | 每人各自一道菜 | 食物種類非常多元，夠分 |
| `!梗` | 單一全域字串 | 全頻道每場共用一則 | 諧音梗素材有限，分人會一場就消耗光 |

**本項結案，無待辦。**

> 若未來改成常駐服務（見附錄 A），這三個快取就必須改由 `stream.online` 事件觸發清空——目前由進程重啟免費提供的語意會消失。

### P1-13 ✅🧪 沒有 graceful shutdown

`main.py` · `scripts/task_scheduler.py`

`close_async_client()` 定義了但**全專案零呼叫**。Ctrl+C 時：排程 task 不會被 cancel、httpx 連線池不會關、bot 不會 close，全靠直譯器結束時硬砍。

已修正（`2830418`）。收尾順序是刻意的：

| 順序 | 步驟 | 為什麼在這個位置 |
| --- | --- | --- |
| 1 | 取消定時排程 | 先停掉「還會產生新工作的東西」 |
| 2 | 關閉 EventSub WebSocket | 同上，避免事件在連線關掉後才進來 |
| 3 | 關閉 IRC 連線 | 開始關連線 |
| 4 | 關閉 Twitch API | Helix 的 aiohttp session |
| 5 | 關閉 httpx 連線池 | 四個微服務共用的那一個 |

反過來的話，排程可能在連線關掉之後才醒來，只會留下一串沒有意義的錯誤。
**每一步各自 try**——收尾程式最怕的就是第一步炸掉、剩下全部沒跑，這也是測試盯最緊的一點。

配套修正：

- `schedule_task()` 過去把 `TaskScheduler` 當區域變數丟掉，關機時根本沒有人拿得到它。改為回傳並存進 `bot.scheduler`。
- 拿掉 `main()` finally 裡的 `sys.exit()`：它會直接中止協程，讓收尾在某些路徑下反而跑不完。

> 訊號處理刻意用 `signal.signal()` 而不是 `loop.add_signal_handler()`——後者 Windows 的 asyncio 不支援。
> 兩個細節值得記著：
> ① 收到第一次訊號就把處理器還原成 `SIG_DFL`，萬一收尾卡住，再按一次 Ctrl+C 仍然殺得掉；
> ② 另外掛一個 0.5 秒心跳協程——Windows 的 selector 事件圈閒置時會卡在 `select()`，Ctrl+C 叫不醒它，
> 沒有心跳的話關機可能要等到下一則聊天訊息進來才生效。

### P1-14 ✅🧪 沒有 Twitch 訊息速率與長度保護

`utils/chat_sender.py`（新增）· `main.py` · `scripts/message_controller.py`

IRC 限制是 30 秒 20 則，超過會被伺服器靜音約 30 分鐘。多人同時升級（`role_system` 每次升級都 send，轉職還會再一則）加上招呼與指令回覆，尖峰很容易觸發。單則 500 字元上限也沒有任何 guard，而 Twitch 對超長訊息是**整則丟掉**而不是截斷。

已修正（`b452cd9`），新增 `utils/chat_sender.py` 作為唯一出口：

| 保護 | 設定 | 超過時的行為 |
| --- | --- | --- |
| 長度 | 500 字元 | 自行截斷並補省略號，至少看得到前半段 |
| 速率 | 30 秒 18 則（官方 20，留 2 則餘裕） | 滑動視窗，滿了就等 |
| 塞車 | 同時等待 20 則 | 直接丟棄並記 `error` |

**刻意採「呼叫端等待」而不是背景佇列。** 佇列雖然更漂亮，但代價是多養一個背景 task，
而它的生命週期又得綁進剛做好的 graceful shutdown（P1-13）。呼叫端等待則讓送出時機與呼叫順序一致，
測試行為也好預測；塞車的保護改用「等待中的訊息過多就丟棄」，避免一堆 `handle_message` 全卡在這裡等好幾十秒。

`message_controller` 的三處 `message.channel.send` 全部換成 `chat_sender.bind()`，
升級／轉職訊息也一路傳進 `role_system`——那才是尖峰的主要來源。
`send_to_channel()`（排程用）與一桶金的結算訊息同樣走這裡。

> 速率視窗是**全域單例**。分開算等於沒有限制——Twitch 的限制是綁在帳號上，不是綁在 Channel 物件上。

### P1-15 ✅🧪 一桶金的錯誤訊息永遠送不出去

`games/gold_rush_game.py`

`_end_game` 是被 `asyncio.create_task` 丟出去的，回傳值直接丟棄。所以「⚠️ 沒有人參加一桶金遊戲」「找不到參加者的資料」**從來沒有人看得到**，體感上就是「遊戲開了但結束時毫無反應」。函式簽章寫 `-> None` 卻 return 字串，型別註記也對不上（`start` / `add_entry` 同樣問題）。

已修正（`3daa235`）。兩則訊息改為主動 `await send_func()` 送出，型別註記一併更正為 `-> str`。

同時處理這個 task 本身的另外兩個問題（review 原本沒點名，但屬於同一個「射後不理」的根因）：

- `create_task()` 的回傳值也被丟掉，**沒有強參考撐著隨時可能被 GC 回收**——與 P0-3 的 `EventSubWebsocket` 是完全同一類問題。
- 結算途中拋例外會被靜默吞掉（例如 MongoDB 微服務無回應）。改為掛 done callback 記 `error`，不再默默消失。

### P1-16 ✅🧪 Mongo `find` 回傳 `None` 沒有統一防護

`svc_client/mongo_atlas.py` · `scripts/rank_system.py`

`mongo_atlas_client.find` 回傳 `resp.get("results")`，服務異常時是 `None`。`vip_system` 有 `or []` 擋、`role_system` 有 `if doc:` 擋，**但 `_format_rank_list` 沒有** → `enumerate(None)` 直接 TypeError，觀眾打 `!排行` 只會看到內部錯誤訊息。

已修正：把契約收斂到 client 層——`find()` 永遠回傳 `list`，呼叫端只要判斷「有沒有資料」。回應格式整個跑掉（非 dict）時也記錄並視為空結果。`vip_system` 原本的 `or []` 隨之移除，避免留下「find 可能回傳 None」的錯誤暗示。

> 順帶記錄一個**尚未處理**的相鄰風險：`_format_rank_list` 對 `doc['level']`、`doc['job']`、`doc['gold']` 是硬括號存取。目前所有角色文件都經 `Character.to_dict()` 產生，必定含這些欄位，因此暫不處理；但若日後有其他來源寫入 `tm_twitch_users`，這裡會 KeyError。

### P1-17 🔲 `vip_system` 的 API context 未初始化

`scripts/vip_system.py`

`_client_id` / `_broadcaster_id` / `_token_getter` 只在 `set_api_context()` 建立。任何在 `event_ready` 之前抵達的 `!vip` 都會 AttributeError。

**已部分緩解**（P2-24 一併處理）：取 token 現在包在 try 內，未初始化時會退款並回覆友善訊息，不會出現「錢扣了什麼都沒發生」。

仍待處理：`__init__` 應把三個屬性初始化為 `None`，並在進入兌換流程前就明確檢查，而不是靠例外兜底。

### P1-18 🔲 `.env` 的 token 寫回不是原子操作

`utils/token_manager.py`

`set_key` 是 read-modify-write 整個檔案。若寫入當下崩潰，**`refresh_token` 可能整個遺失，就得重新走完整 OAuth 授權流程**。

建議：寫暫存檔再 `os.replace()`，或把 token 移到獨立的 `.tokens.json`。

---

# P2｜可維護性與擴充性

### P2-19 ✅ 零測試覆蓋

已建立 pytest 骨架（`tests/`）：

- `conftest.py` 在 import 任何專案模組前塞入假環境變數，測試永遠不會讀到真正的 `.env`，CI 上沒有 `.env` 也能直接跑；同時把 log 目錄導到系統暫存區，測試不會在專案裡留下檔案
- 107 項測試全部離線，`uv run pytest` 約 0.5 秒完成
- 覆蓋 `command_dispatcher`、`greeter`、`role_system`、`level_and_job_system`、`message_controller`、`task_scheduler`、`vip_system`、`mongo_atlas` + `rank_system`、`log_utils`、`http_utils`（重試策略）

尚未覆蓋（後續補齊建議順序）：`gold_rush` / `guess_number` 的金幣邊界。

### P2-20 ✅ 沒有 CI

`.github/workflows/ci.yml`

兩輪修正累積了 73 項測試，卻沒有任何機制自動執行它們，回歸保護實際上只在本機生效。

已建立 GitHub Actions：`push`（master／main）、`pull_request`、手動觸發三種時機，跑 `uv sync --locked --dev` → `compileall` → `pytest`。

- `--locked` 讓「`uv.lock` 與 `pyproject.toml` 不同步」直接失敗，避免 CI 偷偷解析出跟本地不一樣的版本
- 加跑 `compileall`：測試只會載入被用到的模組，沒被 import 到的檔案語法壞掉不會被發現
- 不需要任何 secrets——測試全部離線
- `concurrency` 設定會取消同分支上還在跑的舊流程

> Private repo 的 CI 徽章對未登入者無法顯示，因此 README 以文字說明取代徽章。

### P2-21 🔲 `_SingletonMeta` 被複製了 8 份

`svc_client/google_sheets.py`、`svc_client/mongo_atlas.py`、`svc_client/openai.py`、`svc_client/youtube.py`、`ai_actions/gpt_chat_session.py`、`scripts/vip_system.py`、`games/gold_rush_game.py`、`games/guess_number_game.py`

建議抽到 `utils/singleton.py`。另外它用的是 `threading.Lock`，但整個程式跑在單一事件圈上——語意上並不需要這把鎖。

### P2-22 🔲 Config 沒有 schema 驗證

`scripts/vip_system.py:21-28`

`c.get("enabled")` 沒有 default，key 打錯就是 `None` → `if not self.cfg.enabled` → **整個 VIP 功能靜默停用，沒有任何警告**。

建議：導入 `pydantic-settings`，讓 `.env` + YAML 在啟動時就驗完型別，錯了就 fail fast。

### P2-23 ✅🧪 `Character.save()` 是全欄位 `$set` 覆寫，會 lost update

`scripts/role_system.py`

情境：某人正在聊天（handler 已載入 char 快照），同時 `gold_rush._end_game` 重新讀 char、發獎金、存檔；接著聊天 handler 用它手上的舊快照覆蓋回去 → **獎金消失**。

已修正（`788b500`）。`Character` 在載入當下記一條基準線，存檔時只送差額：

| 欄位 | 過去 | 現在 |
| --- | --- | --- |
| `level` / `exp` / `gold` | `$set` 絕對值 | `$inc` 差額 |
| `attributes` | `$set` 整包覆蓋 | `$inc attributes.STR` 逐項差額 |
| `job` | 每次都 `$set` | 只在真的變了才 `$set` |
| `usernames` / `display_names` | `$addToSet`（本來就安全） | 不變 |

`job` 是字串，沒有「差額」可言。沒變就不寫，才不會用舊快照蓋掉別人剛改好的職業。

**兩個最容易寫錯的地方已用測試鎖住：**

1. 基準線必須在寫入**成功之後**才推進——否則存兩次會重複計算。這條路徑真的存在：`vip_system` 會先存一次扣款（縮短「拿到 VIP 卻還沒付錢」的視窗），`message_controller` 的 `finally` 再存一次。
2. 存檔**失敗時基準線不能推進**——否則那筆增減會憑空消失。`vip_system` 正是靠這點：它存檔失敗只記 log，靠後面的 `finally` 重試。

> **代價要說清楚。** 兩個流程同時扣款時，餘額檢查各自看自己的快照，資料庫的 `gold` 仍有機會被扣成負數。
> 但原本的 `$set` 是「其中一筆扣款整個消失」，等於白吃白喝——`$inc` 至少兩筆都算到，是嚴格的改善。
> 真正的解法要靠條件式更新（`filter` 帶 `gold: {$gte: cost}`），而目前的微服務 `update` API 拿不到「有沒有更新到」的回應，做不了。若日後微服務願意回傳 `matched_count`，這一項可以再收緊。

### P2-24 ✅🧪 遊戲狀態與金幣持久化不一致

`scripts/role_system.py`、`games/gold_rush_game.py`、`games/guess_number_game.py`、`scripts/gacha_handler.py`、`scripts/vip_system.py`

這些模組都直接改 in-memory `char.gold`，靠呼叫端 `handle_message` 最後那行 `save()`。中間任何一步炸掉，就會出現「錢沒扣但注下了」或「VIP 給了但錢沒扣」。

已修正：

- `Character.spend_gold()` 成為所有支出的唯一入口，把「檢查餘額」與「實際扣款」綁成同一步；餘額不足時回傳 `False` 且完全不改變狀態
- `Character.is_dirty` 追蹤異動（刻意不宣告成 dataclass field，`asdict()` 才不會把它寫進 MongoDB），搭配 P0-5 的 `finally` 保證存檔
- 四個呼叫端全部改走 `spend_gold()` / `gain_gold()`，不再直接寫 `char.gold`
- `vip_system.redeem_vip` 改為先扣款再打 Twitch API，取 token 或 API 失敗時退款；授予成功後立刻存檔以縮短「拿到 VIP 卻還沒付錢」的視窗；兌換紀錄寫入失敗時明確記錄需人工補登

> 跨系統（Twitch API + 兩個 collection）的真正原子性做不到，這裡採取的是「縮短不一致視窗 + 失敗時明確留痕」。

### P2-25 🔲 `_invoke` 的參數過濾是假的

`scripts/command_dispatcher.py:46-53`

註解寫「只挑函式簽章允收的名字」，但那個 dict comprehension **沒有做任何過濾**。要做就用 `inspect.signature` 濾一遍；不做就把註解拿掉，別留誤導。

更好的方向：給指令函式定義一個明確的 `CommandContext` 型別，取代現在滿場飛的 `*args, **kwargs`。**這對「好擴充」的幫助最大。**

### P2-26 🔲 指令集無法熱重載

改了 Google Sheets 就得重啟 Bot。建議加一個 admin 專用的 `!reload`，或掛定時重新拉表。

注意：`_load_function` 上的 `lru_cache` 會讓函式綁定黏住，重載時要一併 `cache_clear()`。

### P2-27 🔲 GPT session 是全頻道共用單一上下文

`ai_actions/gpt_chat_session.py:23`

所有觀眾共用 `session_id = "tm_twitch"` 一份歷史，彼此可以污染上下文，prompt injection 面很大（system prompt 第 9 條有防，但共用歷史仍是弱點）。而且沒有鎖，並發 `!gpt` 會交錯 append。

另外 `_pop_oldest_pair`（:91）在 `len <= 3` 時 log 寫「移除最前面的問答」卻直接 return 沒移除，訊息與行為不符。

### P2-28 🔲 死碼與未宣告依賴

- `utils/dump_obj_utils.py:1` — `import attr`，但 **`attrs` 沒有宣告在 `pyproject.toml`**，現在能跑純粹是靠 twitchAPI 的傳遞依賴。而且這個模組零呼叫端。
- `scripts/role_system.py:131` — `get_tigermeow_char()` 宣告回傳 `Character`，實際回傳 mongo 的 raw list，零呼叫端。
- `tttest.py`、`GoldRushGame._timer`（宣告了 `threading.Timer` 但從未使用）。
- `utils/vault_utils.py`、`utils/asset_file_utils.py`、`utils/error_utils.py` 有大量註解掉的舊碼。**這部分不會擅自刪除**，但建議決定去留：要留就移到 `docs/` 或獨立分支，留在 `utils/` 會讓人誤以為是活的。

### P2-29 🔲 表頭處理不一致

`scripts/daily_food_picker.py:13` 用 `raw_food_data[1:]` 跳過標題列，但 `scripts/daily_meme_picker.py:12` 與 `scripts/greeter.py:19` 都沒跳。

請確認「酷酷的諧音梗」與「冒險台詞」兩張表的第一列是否為標題——是的話目前會被當成內容抽出來。

### P2-30 ✅🧪 `parse_jobs_sheet` 對短列會 IndexError

`scripts/level_and_job_system.py`

`row[idx]` 假設每一列都有足夠欄位。Google Sheets API 常會把尾端空白儲存格截掉 → 某列變短 → **啟動時直接掛掉**。

已修正（`bb47474`），取格改走 `_cell()`，越界回空字串。原本的 `xfail(strict=True)` 標記隨之移除。

**順帶多修了一項 review 沒列到的**：同一個迴圈裡的 `int(lvl)`，等級門檻被打成空白或中文字時一樣是 `ValueError` → 一樣起不來。改為記 `error` 並略過該欄。

這兩處的取捨是同一個：**少一個轉職階段只影響那一級的轉職，起不來卻是整場開台都沒有機器人。**
所以除了「整張表根本不成形」（少於三列）之外一律容忍並記錄。

---

# P3｜工程品質

### P3-31 🔲 沒有 lint / format 工具鏈

建議加 `ruff` + `black` + `pre-commit`，並在 `pyproject.toml` 的 dev group 一併宣告。

### P3-32 ⏸️ 沒有部署設定 —— **原判斷大部分是誤判**

原本寫的是「四個微服務的啟動方式完全沒有被記錄，建議補 `Dockerfile` / `compose.yaml`」。

**經頻道主澄清：四個服務都是自己開發的，且都已容器化，各自的專案資料夾裡有自己的 `Dockerfile` 與 `compose.yaml`。**
也就是說「補容器設定」這件事早就做完了，只是從 bot 這個 repo 看不到而已。附錄 A-5 把 P3-32 稱為「唯一真正嚴重的風險」，那個結論建立在錯誤的前提上，**現予撤回**。

也一併確認頻道主的另一個說法是對的：微服務的網址並沒有寫死在程式裡，四個都讀 `config_common.yaml` 的 `svc_url`，換 port 或搬到別的網段只要改設定檔。

扣掉誤判之後，真正還缺的只剩兩件，而且都不嚴重：

| 缺什麼 | 嚴重度 | 成本 |
| --- | --- | --- |
| **這個 repo 裡沒有那四個服務的線索** | 低 | 15 分鐘 |
| **沒有一鍵啟動** | 低（純方便性） | 30 分鐘 |

第一項：`config_common.yaml` 裡只有 `http://localhost:9091` ~ `9094`，
沒有服務名稱、沒有 repo 位置、沒有「這一個負責什麼」。容器設定確實存在，但**不在這裡**，
換機器時仍然要靠記憶找出那四個專案資料夾。補一份 `docs/SERVICES.md`（名稱／port／repo 位置／一行職責／啟動指令）就結案。

第二項：四份 compose 分散在四個資料夾，開台前等於要開四個終端機。
可以在本 repo 放一份 compose 用 `include:` 引用那四份（Compose v2.20+），或一支五行的 `start.ps1`。這是方便性，不是風險。

> **但查證過程中發現一個真正的問題**，而且正好推翻「微服務掛掉不該影響主體」這個前提——見 P1-37。

### P1-37 ✅🧪 Google Sheets 微服務沒開，Bot 就啟動失敗

`main.py` · `scripts/command_dispatcher.py`

```python
await command_dispatcher.load_command_set()   # → 9091
await level_and_job_system.load_job_config()  # → 9091
```

這兩行沒有任何 try，`StatusCodeError` 會一路往上拋穿 `main()`。
**9091 沒開 → Bot 根本起不來**，而且要先耗掉重試與退避才會失敗。

這直接牴觸頻道主提出的原則：「微服務掛掉不應該影響主體聊天機器人服務」。查證後的實際狀況是：

| 服務 | port | 掛掉時的實際影響 | 攔在哪 |
| --- | --- | --- | --- |
| Google Sheets | 9091 | **Bot 完全起不來** | 無 |
| OpenAI | 9092 | `!gpt` 回制式錯誤訊息，其餘正常 | `command_dispatcher._invoke` |
| MongoDB | 9093 | 該次訊息的獎勵存不了，記 log，其餘正常 | `message_controller` |
| YouTube | 9094 | `!找歌` 回制式錯誤訊息，其餘正常 | `command_dispatcher._invoke` |

**只有 9091 是硬相依**，另外三個的防護在前幾輪（P0-5、P1-11）都已經補好了。
而 9091 偏偏是四個裡最容易忘記開的一個——它只在啟動那一瞬間用到，開台途中完全不會再碰。

剛修好的 P2-30 讓「表格式歪掉」不再讓 Bot 起不來，但「服務沒開」這條路徑還是會掛，兩者是不同的失敗點。

**降級啟動之後還剩什麼？** 值得先看清楚再決定要不要做：

| 還能用 | 不能用 |
| --- | --- |
| 打字給經驗值與金幣、升級 | 所有 `!` 指令（指令集在 Sheets） |
| `!排行`（Mongo）、終極密碼、一桶金 | 打招呼詞、`!吃`、`!梗`（都在 Sheets） |
| VIP 掃描、開台／關台事件觀測 | 轉職（`JOB_CONFIG` 會是空的，但不會拋例外） |

一半以上的功能還在，所以**建議降級啟動**：bootstrap 包 try，失敗時記 `error`、發一則「指令功能暫時無法使用」到聊天室，然後照常上線。
已修正（`087306b`）。改為 `load_sheet_config()`：每項各自 try，回傳失敗的項目名稱，**啟動一定會繼續走下去**。

| 狀況 | 行為 |
| --- | --- |
| 全部載入成功 | 一切照舊，不會多任何排程 |
| 有項目失敗 | 記 `error`、照常上線、`event_ready` 告知觀眾「這次沒載入到 ⋯」 |
| 降級後 | 每 5 分鐘重試一次失敗的項目，成功就再公告一次「已恢復」 |

**順帶拿掉 `dispatch_command` 裡的 `if not COMMAND_SET: await load_command_set()`。**
原本它是「bootstrap 沒跑到」的保險，但在降級情境下反而有害：9091 沒開時**每一則訊息**都要耗掉一輪重試與退避，整個聊天室都會變慢；而它拋出的例外還會讓那則訊息連招呼與獎勵都拿不到。重試集中由排程負責，這裡改成安靜跳過。

> 附帶好處：這行拿掉之後，測試再也沒有機會真的打到 9091。
> 回歸驗證時把它還原回去，測試 log 裡當場就冒出「指令集載入完成，共 71 筆」——
> 那是真的連上了本機的 Google Sheets 微服務。

### P3-33 🔲 `main.py` 的 `sys.path` hack

`main.py:4-5` 的 `sys.path.append` 已經沒有必要（uv 已將套件正式安裝進環境）。

### P3-34 🔲 OAuth 工具的殘留與缺漏

`oauth/server.py`

- docstring（:9,:17）內嵌了真實 `client_id` 與個人網域
- callback **沒有驗證 `state`**（CSRF），且直接把 token 明文回在 HTTP response body
- `host="0.0.0.0"`

雖然只是本地一次性工具，風險不高（`client_id` 在 OAuth 流程中本來就是半公開值，且 repo 為 private），但值得清理。

### P3-35 🔲 時區處理不一致

`scripts/task_scheduler.py:91` 用的是 naive `datetime.now()`（本機時區），但 `greeter` 與 `role_system` 都明確用 UTC+8。部署到 UTC 機器上，23:59 的換日提醒會差 8 小時。建議全專案統一。

### P3-36 🔲 硬編碼的指令集網址

`main.py` 的上線公告內嵌 Google Sheets 網址，但 `config_common.yaml` 已有 `google_sheets.sheet_url`。建議改讀 config，避免兩處不同步。

---

## 建議的下一批處理順序

**P0、P1、P2 的高風險項目已全數結案**（P0-7、P1-12 為評估後決定不處理，P3-32 為誤判撤回）。
剩下的 15 項都不會造成資料錯誤或服務中斷，依投報率排序：

1. **P3-32**（服務清單）——15 分鐘的文件工作：四個微服務的名稱／port／repo 位置／啟動指令
2. **P3-31**（lint / format 工具鏈）——CI 已經在跑了，加 `ruff` 幾乎是免費的
3. **P2-25 ~ P2-29**——`_SingletonMeta` 重複六份、VIP 名額全表撈、快取無 TTL 等，都是維護性議題
4. **P3-35**（時區不一致）——`task_scheduler` 用本機時區，其餘用 UTC+8；目前都在同一台機器上所以看不出來
5. **P3-33、P3-34、P3-36**——`sys.path` hack、OAuth 工具殘留、硬編碼的指令集網址

> 目前唯一還「知道有問題但沒解」的是 P2-23 的並行扣款：兩個流程同時扣款仍可能把 `gold` 扣成負數。
> 要解需要微服務端支援條件式更新並回傳 `matched_count`，那是微服務那邊的工程。

---

# 附錄 A｜營運架構：手動啟動 vs 常駐服務

> 起因：頻道主希望「**確保機器人只在開台期間運作**」，因此目前刻意採用本機手動啟動、不容器化、不上雲。
> 問題是：Twitch 抓不抓得到開台／關台？如果抓得到，架構要不要改？

## A-1 事實查核：開台與關台都抓得到

已核對 [Twitch EventSub 官方文件](https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/) 與本機安裝的 twitchAPI 4.5.0：

| 項目 | `stream.online` | `stream.offline` |
| --- | --- | --- |
| 版本 | 1 | 1 |
| 需要的 scope | **不需要** | **不需要** |
| condition | `broadcaster_user_id` | `broadcaster_user_id` |
| 傳輸方式 | Webhook／WebSocket 皆可 | Webhook／WebSocket 皆可 |
| 事件內容 | 含 `type`、`started_at` | 僅頻道識別資訊 |
| twitchAPI 對應方法 | `listen_stream_online()` | `listen_stream_offline()` |

**結論：兩個都抓得到，而且完全不需要新增 scope。** 本專案已經有一個 `EventSubWebsocket`（訂閱忠誠點數兌換），加兩行 `listen_*` 就能同時收到開台與關台事件。

### 但有四個必須先知道的限制

1. **WebSocket 只吃 user access token。** 官方文件明講「用 app access token 訂閱會失敗」。本專案本來就是 user token，這點沒有影響。
2. **斷線等於訂閱全滅，而且事件不補發。** WebSocket 一斷，該 session 的所有訂閱自動停用；重連後必須重新訂閱，**斷線期間的事件永久遺失，沒有 replay**。這是常駐架構最關鍵的風險：半夜 WS 斷了沒人發現，隔天開台的 `stream.online` 可能根本收不到，機器人就整場不會醒來。
3. **`stream.offline` 會抖。** 推流短暫中斷（拔網路線、OBS 重連）有機會產生一對 offline → online 事件。若把「關台」直接當成停止服務的訊號，一次網路抖動就會讓機器人誤判下台。
4. **事件有延遲**，不是即時的。

> 第 3、4 點屬於實務上的普遍觀察，官方文件並未承諾具體的延遲上限或抖動行為。因此若真的要依賴這兩個事件，**必須搭配 Helix `Get Streams` 定期對帳**，用「當下的真實狀態」而不是「收到的事件」作為單一事實來源。

## A-2 先釐清：需求其實有兩層

「確保機器人只在開台期間運作」可以拆成兩件事：

- **(a) 進程要不要一直活著**
- **(b) 機器人要不要一直回應**

目前的手動啟動架構把這兩件事綁在一起——用「進程不存在」來保證「不會回應」。但它們是可以脫鉤的，於是實際上有三個選項：

| | 進程 | 回應 | 評價 |
| --- | --- | --- | --- |
| **A** 手動啟動 | 只在開台期間 | 只在開台期間 | 現況 |
| **B** 常駐 + 開關台閘門 | 24 小時 | 只在開台期間 | 需要新邏輯 |
| **C** 常駐、永遠回應 | 24 小時 | 24 小時 | **與需求衝突，直接排除** |

C 就是頻道主明確不要的「大家一直洗錢、洗經驗值，但我都看不到」。所以真正要比較的是 A 與 B。

## A-3 A：手動啟動（現況）

**優勢**

1. **需求由架構天然保證，零信任成本。** 進程不在，就不可能有人洗錢——不依賴任何判斷邏輯的正確性。這是最強的一種保證。
2. **「每場開台固定內容」是免費的。** `!吃`、`!梗`、招呼名單的快取隨進程生死，語意剛好就是「本場」。這是刻意設計，不是缺陷（見 P1-12 的更正）。
3. **除錯最直接。** 終端機就在眼前，出事當場看得到；現在也有 log 檔可以事後追。
4. **零基礎設施、零常態成本。** 不用 Docker、不用開機自啟、不用監控；不開台就不吃電、不佔 Atlas 連線。
5. **改版即生效。** 改完程式，下次開台就是新版，沒有部署流程。

**劣勢**（已依 2026-08-09 頻道主補充的實際習慣重新評估）

1. ~~要記得手動開~~ → **不成立**。頻道主開台前一定會開 Bot，忘了觀眾也會提醒。
2. ~~中途掛掉沒有人救~~ → **影響可接受**。家用電腦每天重開機，且頻道主明確表示「當次開台沒有機器人可用就算了」。supervisor 仍是加分項，但不是必要投資。
3. ~~**綁在一台機器上。**~~ → **影響比原本評估的小很多。** 原本寫「四個微服務的啟動方式完全沒有被記錄」，
   但經頻道主澄清，四個服務都已各自容器化（詳見改寫後的 P3-32），這一點大部分是誤判。
   真正還缺的只是「這個 repo 裡沒有那四個服務的清單」，補一份文件即可。
4. **長期任務無處可掛。** 「VIP 到期當天移除」「每日凌晨統計」這類需求做不了。
5. **開台前幾分鐘有空窗。** 觀眾比機器人早到。

> 頻道主的使用習慣（每日重開機、一定會記得開、單次故障可接受）等於免費消化掉了 A 的兩項劣勢。這讓 A 比原本評估的更划算。

## A-4 B：常駐 + 開關台閘門

**優勢**

1. **不會忘記開**，而且開台當下就已經在線，沒有空窗。
2. **可以自動重啟。** Docker restart policy 或 Windows 服務，掛掉自己爬起來。
3. **長期排程有地方掛。** VIP 每日到期掃描（P0-7）、每日 00:00 的各種重置都變成自然的事。
4. **可以在關台後做事。** 例如結算當日排行、產出當場數據。
5. **順便解掉 P3-32。** 容器化會強迫把四個微服務的啟動方式寫下來，換機器不再是考古。

**劣勢**

1. **「只在開台期間運作」從架構保證退化成邏輯保證。** 閘門有 bug、狀態判斷錯誤，就會出現「沒開台卻在發經驗值」——而這件事**頻道主看不到**，正是最在意的失效模式。以「穩定 > 好維護 > 好擴充」的優先序衡量，這是往後退。
2. **狀態偵測有一整圈邊界情況要處理。** WS 斷線不補發、offline 抖動、事件延遲，都要靠 Helix 定期對帳兜底。多了一塊需要維護與測試的邏輯。
3. **「每場固定內容」得自己實作。** 現在由進程重啟免費提供的語意會消失，必須改成監聽 `stream.online` 時清快取（好處是這個行為從隱性變顯性、變得可測試）。
4. **持續佔用資源。** 電、記憶體、Atlas 連線、token 刷新迴圈都要 24 小時跑。
5. **改版要重新部署**，不能再靠「下次開台自然生效」。
6. **新增基礎設施維護面。** Docker、開機自啟、要不要監控告警。

## A-5 結論與建議

**決定：維持 A 手動啟動**（2026-08-09，頻道主拍板）。

A 的五項劣勢裡，前兩項已被頻道主的使用習慣消化掉（每天重開機、一定會記得開、單次故障可接受），
第 3 點（綁在一台機器上）經澄清後大部分是誤判——四個微服務都已容器化，只差一份服務清單，
第 4、5 項則是能接受的取捨。**這條路線目前沒有未解的嚴重風險。**

> 2026-08-09 補記：P1-13 的 graceful shutdown 雖然已從「必要」降為加分項，仍在第五輪一併做掉了（`2830418`）。
> 真正剩下的是本輪新發現的 **P1-37**——它跟營運架構無關，是 bootstrap 的硬相依。

反過來，B 的劣勢第 1 點正好打在頻道主最在意的地方。用「進程不存在」保證需求是零成本、零 bug 的；換成程式邏輯，就換成了需要測試與維運的保證。在還沒有出現非常駐不可的需求之前，不值得做這個交換。

### 什麼時候該重新評估

- 想要「VIP 到期當天就移除」，或出現任何**離線也生效**的權益（這正好就是 P0-7 記載的重新評估條件）
- 開台頻率變高，或有其他人代管，忘記開的成本上升
- 想累積跨場次的數據（每日／每週統計）

### 若真的要切換，建議的最小順序

1. ✅ **先訂閱 `stream.online` / `stream.offline`，但只寫 log、不改任何行為。** 跑幾週，確認事件真的可靠、觀察抖動頻率 —— **已實作**（`3833b57`），詳見下方 A-6
2. **加上 Helix `Get Streams` 定期對帳**（例如每 5 分鐘），確立「真實開台狀態」的單一事實來源
3. **才把閘門接到 `message_controller` 最前面**（未開台就直接 return），並把 `!吃`／`!梗`／招呼名單的清空改由 `stream.online` 觸發
4. **最後才容器化與開機自啟**

重點是**先觀測、後信任**：在確認事件可靠之前，就把服務行為押在它身上，是最容易出事的做法。

### 還有一個折衷方案

**拆成兩個進程**：一個常駐的小型 worker（只負責 VIP 到期掃描、每日統計這類維運工作），一個仍然手動啟動的聊天 Bot。

這樣既拿到常駐的好處，又完整保留「進程不存在＝絕對不會回應」的強保證——閘門邏輯根本不需要存在。以目前的專案規模，這很可能是投報率最高的路。

## A-6 觀察期：已上線的開台／關台觀測（`3833b57`）

已在 `main.py` 的 `event_ready` 訂閱 `stream.online` 與 `stream.offline`，**只寫 log、不改變任何行為**。

- handler：`MyBot.on_stream_online()` / `on_stream_offline()`
- log 標記：`[STREAM-EVENT]`（刻意用純 ASCII，方便 grep）
- 兩個 handler 都各自包 try/except——觀測用的程式碼絕不能反過來影響 Bot

### 怎麼看結果

```bash
grep STREAM-EVENT logs/tm_twitch_bot.log
```

開台會記錄 `stream_id`、`type`、`started_at`；關台記錄頻道識別資訊。

### 觀察期要回答的三個問題

| 問題 | 怎麼判斷 |
| --- | --- |
| 事件會不會漏？ | 每場開台是否都有對應的 `開台` 一行；有沒有只有關台沒有開台的情況 |
| `offline` 會不會抖？ | 同一場直播中途是否出現 `關台` → `開台` 的成對事件；`stream_id` 是否改變 |
| 延遲多久？ | 比對 log 的時間戳與事件裡的 `started_at`，以及自己實際按下開台的時間 |

若這三題的答案都令人滿意，才有資格進行 A-5 的第 2 步（Helix 對帳）。若發現會漏、會抖，就代表 B 架構的成本比預估更高，維持 A 的決定更加穩固。
