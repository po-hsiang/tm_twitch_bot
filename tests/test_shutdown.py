"""關機收尾（CODE_REVIEW P1-13）。

過去 `close_async_client()` 定義了卻全專案零呼叫，Ctrl+C 時排程不會取消、
httpx 連線池不會關、bot 也不會 close，全靠直譯器結束時硬砍。

收尾程式最怕的是「第一步炸掉，剩下全部沒跑」，所以這裡盯得最緊的是
「任何一步失敗，後面的步驟仍然要跑完」。
"""

import pytest

from tm_twitch_bot import main as m


class Recorder:
    def __init__(self):
        self.calls: list[str] = []


@pytest.fixture
def calls():
    return Recorder().calls


@pytest.fixture(autouse=True)
def stub_http_close(monkeypatch):
    """攔截 httpx 連線池關閉，順便記錄它有沒有被呼叫。"""
    closed: list[str] = []

    async def _close():
        closed.append("httpx")

    monkeypatch.setattr(m, "close_async_client", _close)
    return closed


def make_bot(calls, *, with_eventsub=True, failing: str = ""):
    class FakeEventSub:
        async def stop(self):
            calls.append("eventsub")
            if failing == "eventsub":
                raise RuntimeError("EventSub 不在執行中")

    class FakeBot:
        def __init__(self):
            self.eventsub_ws = FakeEventSub() if with_eventsub else None
            self.scheduler = None

        async def close(self):
            calls.append("bot")
            if failing == "bot":
                raise RuntimeError("IRC 連線已經斷了")

    return FakeBot()


def make_twitch(calls, *, failing: str = ""):
    class FakeTwitch:
        async def close(self):
            calls.append("twitch")
            if failing == "twitch":
                raise RuntimeError("session 已關閉")

    return FakeTwitch()


def make_scheduler(calls, *, failing: str = ""):
    class FakeScheduler:
        def cancel_all(self):  # 同步方法，shutdown 要能同時吃同步與非同步
            calls.append("scheduler")
            if failing == "scheduler":
                raise RuntimeError("排程已經沒了")

    return FakeScheduler()


# ===== 順序 =====


async def test_everything_is_closed_in_the_right_order(calls, stub_http_close):
    await m.shutdown(
        bot=make_bot(calls),
        twitch=make_twitch(calls),
        scheduler=make_scheduler(calls),
    )

    # 先停「還會產生新工作的東西」，再關連線
    assert calls == ["scheduler", "eventsub", "bot", "twitch"]
    assert stub_http_close == ["httpx"]


async def test_eventsub_stops_before_the_irc_connection(calls):
    await m.shutdown(bot=make_bot(calls), twitch=make_twitch(calls))

    assert calls.index("eventsub") < calls.index("bot")


# ===== 容錯：這是整個收尾最重要的性質 =====


@pytest.mark.parametrize("broken", ["scheduler", "eventsub", "bot", "twitch"])
async def test_one_failing_step_never_blocks_the_rest(broken, calls, stub_http_close):
    await m.shutdown(
        bot=make_bot(calls, failing=broken),
        twitch=make_twitch(calls, failing=broken),
        scheduler=make_scheduler(calls, failing=broken),
    )

    assert calls == ["scheduler", "eventsub", "bot", "twitch"]
    assert stub_http_close == ["httpx"]  # 最後一步照樣要跑到


async def test_failures_are_logged_with_the_step_name(calls, caplog):
    await m.shutdown(bot=make_bot(calls, failing="bot"))

    assert "關閉 IRC 連線" in caplog.text


# ===== 還沒建立起來的東西要跳過 =====


async def test_shutdown_works_when_nothing_was_started(stub_http_close):
    """啟動階段就失敗時，bot / twitch 可能根本還不存在。"""
    await m.shutdown()

    assert stub_http_close == ["httpx"]  # 連線池仍然要關


async def test_eventsub_is_skipped_when_it_was_never_created(calls, stub_http_close):
    await m.shutdown(bot=make_bot(calls, with_eventsub=False))

    assert "eventsub" not in calls
    assert calls == ["bot"]
    assert stub_http_close == ["httpx"]
