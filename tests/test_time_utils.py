"""時區統一（CODE_REVIEW P3-35）。

這一項的難處是「在台灣的機器上跑測試，看不出台北時間與本機時間的差別」。
所以測試不去比對時間值，而是驗**每個呼叫點真的走 time_utils**：
- 產出的字串帶不帶 `+08:00`
- 換日排程的預設時間來源是不是 now_tw

搬到 UTC 機器上就會壞掉的那些寫法（naive 的 datetime.now()、date.today()）
在這裡都會被抓到，不必真的搬一台機器。
"""

from datetime import datetime, timedelta, timezone

import pytest

from tm_twitch_bot.scripts import task_scheduler as ts
from tm_twitch_bot.scripts import vip_system as vs
from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.utils.time_utils import TW_TZ, now_tw, now_tw_iso, today_tw


# ===== 工具本身 =====


def test_the_offset_is_always_plus_eight():
    assert now_tw().utcoffset() == timedelta(hours=8)


def test_now_is_timezone_aware():
    """naive datetime 和 aware datetime 相減會拋 TypeError，混用遲早出事。"""
    assert now_tw().tzinfo is not None


def test_iso_string_carries_the_offset():
    """寫進 MongoDB 的時間戳要能看出時區——tm_twitch_vips 過去沒有偏移量。"""
    assert now_tw_iso().endswith("+08:00")


def test_today_matches_the_date_in_utc_plus_eight():
    """獨立算一次台灣的日期，驗 today_tw 不是拿本機時區充數。"""
    expected = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    assert today_tw() == expected


def test_taiwan_has_no_dst_so_the_offset_never_changes():
    """用固定 +08:00 而不是 zoneinfo 的前提：台灣 1979 年後沒有日光節約時間。

    這個前提一旦不成立（真的改制），這裡會提醒要改用 zoneinfo。
    """
    midsummer = datetime(2026, 7, 1, 12, tzinfo=TW_TZ)
    midwinter = datetime(2026, 1, 1, 12, tzinfo=TW_TZ)
    assert midsummer.utcoffset() == midwinter.utcoffset() == timedelta(hours=8)


# ===== 換日排程（task_scheduler.seconds_until）=====


@pytest.mark.parametrize(
    "now_hour, now_minute, target, expected_seconds",
    [
        (23, 0, (23, 59), 59 * 60),  # 今天還沒到
        (23, 59, (23, 59), 24 * 3600),  # 剛好到點 → 算明天，不要立刻再觸發一次
        (0, 1, (23, 59), 23 * 3600 + 58 * 60),  # 已經過了午夜
        (12, 0, (12, 30), 30 * 60),
    ],
)
def test_seconds_until_the_next_run(now_hour, now_minute, target, expected_seconds):
    now = datetime(2026, 8, 21, now_hour, now_minute, tzinfo=TW_TZ)
    assert ts.seconds_until(*target, now=now) == expected_seconds


def test_seconds_until_defaults_to_taiwan_time(monkeypatch):
    """預設的 now 必須來自 now_tw，不是 naive 的 datetime.now()。

    這是 P3-35 的核心：本機在台灣所以兩者相同，搬到 UTC 機器上，
    23:59 的換日提醒會在台灣的早上八點才響。
    """
    monkeypatch.setattr(
        ts, "now_tw", lambda: datetime(2026, 8, 21, 23, 0, tzinfo=TW_TZ)
    )

    assert ts.seconds_until(23, 59) == 59 * 60


def test_seconds_until_never_returns_a_negative_wait():
    """負數會讓 asyncio.sleep 立刻返回，排程就變成瘋狂空轉。"""
    for hour in range(24):
        now = datetime(2026, 8, 21, hour, 30, tzinfo=TW_TZ)
        assert ts.seconds_until(0, 0, now=now) > 0


# ===== 呼叫點真的走 time_utils =====


def test_character_timestamps_carry_the_offset():
    """tm_twitch_users 的 created_at / updated_at。"""
    assert Character._now_str().endswith("+08:00")


def test_vip_expiry_date_uses_taiwan_today():
    """VIP 到期日只存到「日」，時區差一天就是差一整天的權益。"""
    assert vs.VipSystem._today_iso() == today_tw().isoformat()
