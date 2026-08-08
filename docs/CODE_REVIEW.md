# tm_twitch_bot 程式碼健檢報告

| 項目 | 內容 |
| --- | --- |
| 健檢日期 | 2026-08-09 |
| 基準版本 | `584821e`（健檢起點） |
| 最後更新 | 2026-08-09，第二輪修正後 |
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

測試總數 73 項（72 passed + 1 xfailed），全部離線。

剩餘 25 項待處理，內容如下。

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

### P0-8 ✅🧪 排程器的例外會靜默殺死整條排程

`scripts/task_scheduler.py`

`while True` 內的 `_execute` 一旦拋例外，該 task 直接結束，而且沒有任何人 `await` 它 → 例外被吞掉，只在程式結束時才印 `Task exception was never retrieved`。**喝水提醒某天默默不見了，不會有任何人知道。**

已修正：

- 新增 `_execute_safely()`：單次失敗只記錄，下一輪照常觸發；`CancelledError` 仍往外傳
- 新增 `_on_job_finished()` done callback：排程迴圈不該自行退出，真的結束一律留下 log
- `__init__` 改用 `get_running_loop()`，讓「在事件圈外建構」這種誤用當場暴露（原本的 `get_event_loop()` 在 Python 3.14 起會直接拋錯）

---

# P1｜穩定性與可維運性

### P1-9 🔲 日誌只有 stdout，沒有檔案、沒有輪替

`utils/log_utils.py`

Bot 半夜掛掉，隔天沒有任何線索可查。建議加 `RotatingFileHandler`。

同時有個潛在地雷：`ColoredFormatter.format`（:24）是**原地修改 `record.msg`**。目前只有一個 handler 所以沒事，但一加 FileHandler，log 檔就會塞滿 `\033[92m` 這類 ANSI 碼。應改為在 `format()` 內操作副本。

### P1-10 🔲 重試策略對 4xx 也重試，且 read timeout 600 秒

`utils/http_utils.py:10,47-52`

400/401/404 重試 3 次、每次等 5 秒 = 觀眾要等 15 秒才拿到錯誤。而 600 秒的 read timeout 意味著單一微服務卡住就能讓一個指令懸置 10 分鐘。

建議：只對 5xx 與連線類例外重試、加指數退避、read timeout 降到 15–30 秒（GPT 那條另外設定較長值）。

### P1-11 🔲 內部例外訊息會直接噴進公開聊天室

`scripts/command_dispatcher.py:60`

```python
return f"⚠️ 執行 {func.__name__} 時發生錯誤：{e}"
```

`StatusCodeError` 的訊息長這樣：`打 API 給 http://localhost:9093/mongo/find 失敗`。內部拓樸就這樣公開了。

建議：對觀眾回制式訊息，細節只進 log。（測試 `test_function_exception_is_contained` 目前鎖定的是「不會中斷」，修正時需一併更新該測試。）

### P1-12 🔲「每日」的快取其實不是每日，是「重啟才失效」

- `scripts/greeter.py:10` — `who_arrived` 永不清空 → 第二天起沒有人會被打招呼
- `scripts/daily_food_picker.py:6` — `food_cache` 永不清空 → `!吃` 一輩子同一個答案
- `scripts/daily_meme_picker.py:5` — `meme_cache` 是**單一全域字串** → 第一個打「梗」的人決定了全頻道所有人的梗，直到重啟

建議：掛一個每日 00:00 的清空 job。成本很低、體感差異很大。

### P1-13 🔲 沒有 graceful shutdown

`utils/http_utils.py:27`

`close_async_client()` 定義了但**全專案零呼叫**。Ctrl+C 時：排程 task 不會被 cancel、httpx 連線池不會關、bot 不會 close。

建議：`main()` 用 try/finally 收尾，並處理 SIGINT/SIGTERM。

### P1-14 🔲 沒有 Twitch 訊息速率與長度保護

IRC 限制是 30 秒 20 則。多人同時升級（`role_system.py:182` 每次升級都 send）加上招呼與指令回覆，尖峰很容易觸發靜音。單則 500 字元上限也沒有任何 guard。

建議：做一個統一的 `safe_send()` 包一層佇列與截斷。P0-4 已導入的 `send_to_channel()` 是很自然的落點。

### P1-15 🔲 一桶金的錯誤訊息永遠送不出去

`games/gold_rush_game.py:68,73`

`_end_game` 是被 `asyncio.create_task` 丟出去的，回傳值直接丟棄。所以「⚠️ 沒有人參加一桶金遊戲」「找不到參加者的資料」**從來沒有人看得到**。函式簽章寫 `-> None` 卻 return 字串，型別註記也對不上（`start` / `add_entry` 同樣問題）。

### P1-16 🔲 Mongo `find` 回傳 `None` 沒有統一防護

`scripts/rank_system.py:5`

`mongo_atlas_client.find` 回傳 `resp.get("results")`，服務異常時是 `None`。`vip_system` 有 `or []` 擋、`role_system` 有 `if doc:` 擋，**但 `_format_rank_list` 沒有** → `enumerate(None)` 直接 TypeError。

建議：在 client 層就統一 `return resp.get("results") or []`。

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

- `conftest.py` 在 import 任何專案模組前塞入假環境變數，測試永遠不會讀到真正的 `.env`，CI 上沒有 `.env` 也能直接跑
- 73 項測試全部離線，`uv run pytest` 約 0.3 秒完成
- 覆蓋 `command_dispatcher`、`greeter`、`role_system`、`level_and_job_system`、`message_controller`、`task_scheduler`、`vip_system`

尚未覆蓋（後續補齊建議順序）：`gold_rush` / `guess_number` 的金幣邊界、`http_utils` 的重試策略（適合搭配 `respx`）、`rank_system` 的空結果處理。

### P2-20 🔲 沒有 CI

repo 已建立（`po-hsiang/tm_twitch_bot`）。一個 GitHub Actions（`uv sync` + `uv run pytest`）就能擋掉大部分回歸。

### P2-21 🔲 `_SingletonMeta` 被複製了 8 份

`svc_client/google_sheets.py`、`svc_client/mongo_atlas.py`、`svc_client/openai.py`、`svc_client/youtube.py`、`ai_actions/gpt_chat_session.py`、`scripts/vip_system.py`、`games/gold_rush_game.py`、`games/guess_number_game.py`

建議抽到 `utils/singleton.py`。另外它用的是 `threading.Lock`，但整個程式跑在單一事件圈上——語意上並不需要這把鎖。

### P2-22 🔲 Config 沒有 schema 驗證

`scripts/vip_system.py:21-28`

`c.get("enabled")` 沒有 default，key 打錯就是 `None` → `if not self.cfg.enabled` → **整個 VIP 功能靜默停用，沒有任何警告**。

建議：導入 `pydantic-settings`，讓 `.env` + YAML 在啟動時就驗完型別，錯了就 fail fast。

### P2-23 🔲 `Character.save()` 是全欄位 `$set` 覆寫，會 lost update

`scripts/role_system.py:142`

情境：某人正在聊天（handler 已載入 char 快照），同時 `gold_rush._end_game` 重新讀 char、發獎金、存檔；接著聊天 handler 用它手上的舊快照覆蓋回去 → **獎金消失**。

建議：金幣類欄位改用 `$inc` 增量更新。

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

### P2-30 🔲 `parse_jobs_sheet` 對短列會 IndexError

`scripts/level_and_job_system.py:23`

`row[idx]` 假設每一列都有足夠欄位。Google Sheets API 常會把尾端空白儲存格截掉 → 某列變短 → **啟動時直接掛掉**。

建議：`row[idx] if idx < len(row) else ""`。

> 已用 `tests/test_level_and_job_system.py::test_short_row_should_be_tolerated` 的 `xfail(strict=True)` 標記。修好之後該測試會自動轉綠並提示移除標記。

---

# P3｜工程品質

### P3-31 🔲 沒有 lint / format 工具鏈

建議加 `ruff` + `black` + `pre-commit`，並在 `pyproject.toml` 的 dev group 一併宣告。

### P3-32 🔲 沒有部署設定

四個 localhost 微服務（9091 Google Sheets / 9092 OpenAI / 9093 MongoDB / 9094 YouTube）的啟動方式完全沒有被文件或程式碼記錄，換一台機器等於重新考古。建議補 `Dockerfile` / `compose.yaml`，至少補一份服務清單文件。

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

P0 已全數結案（P0-7 為評估後決定不處理）。剩下的依投報率排序：

1. **P2-20**（CI）——兩輪修正已累積 73 項測試，接上 GitHub Actions 才能真正發揮回歸保護的價值
2. **P1-12**（每日快取重置）——成本最低、觀眾體感差異最大；`!梗` 目前全頻道共用同一則直到重啟
3. **P1-16 + P1-9**（Mongo 空結果防護、日誌落檔）——兩者都是「出事時查得到、不會二次爆炸」的基本盤
4. **P1-10 + P1-11**（重試策略、錯誤訊息不外洩）——都在 HTTP 與指令回覆路徑上，適合一起做
5. **P2-23**（`$inc` 增量更新）——與已完成的 P2-24 是同一主題的下半場，解決並行寫入的 lost update
6. **P2-30**（Sheets 短列）——已有 `xfail` 測試等著轉綠，修起來只有一行
