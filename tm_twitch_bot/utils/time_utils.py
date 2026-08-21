"""全專案的「現在幾點」統一出口，一律台灣時間（UTC+8）。

CODE_REVIEW P3-35：原本三種寫法混在一起——

| 模組 | 原本的寫法 | 時區 |
| --- | --- | --- |
| greeter、role_system | `datetime.now(timezone(timedelta(hours=8)))` | 明確 UTC+8 |
| task_scheduler | `datetime.now()` | 本機 |
| vip_system | `date.today()`、`datetime.now()` | 本機 |

本機剛好就在台灣，所以現在看不出差別。搬到 UTC 機器上會有兩件事出錯，
而且都不會有任何錯誤訊息：

- 23:59 的換日提醒差 8 小時（review 原本只點到這一項）
- **VIP 的到期日整天算錯**——`date.today()` 在 UTC 的上午八點之前是「昨天」，
  兌換當下就少一天，過期掃描也會提早一天把人的 VIP 拔掉

順帶還有一致性問題：`tm_twitch_users` 的 `created_at` / `updated_at` 帶
`+08:00`，但 `tm_twitch_vips` 的 `updated_at` / `history[].ts` 完全沒有偏移量，
同一個資料庫裡兩種格式。改用這裡之後新寫入的都會帶 `+08:00`
（那些欄位程式從來不讀，所以舊資料不必回填）。

**用固定 +08:00 而不是 `zoneinfo.ZoneInfo("Asia/Taipei")`**：台灣自 1979 年起
沒有日光節約時間，兩者結果完全相同；而 zoneinfo 在 Windows 上還要多裝 tzdata
套件，為一個永遠不變的偏移多一個依賴不划算。固定偏移還讓 `.replace(hour=...)`
這種算法沒有 DST 的邊界問題（見 task_scheduler.seconds_until）。
"""

from datetime import date, datetime, timedelta, timezone

TW_TZ = timezone(timedelta(hours=8), "UTC+8")


def now_tw() -> datetime:
    """帶時區的現在時間。"""
    return datetime.now(TW_TZ)


def today_tw() -> date:
    """台灣的今天。VIP 到期日這種「以日為單位」的判斷用這個。"""
    return now_tw().date()


def now_tw_iso() -> str:
    """ISO 8601 字串，帶 `+08:00` 後綴。寫進資料庫的時間戳一律用這個。"""
    return now_tw().isoformat()
