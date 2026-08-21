"""排程器的容錯。

排程 task 沒有任何人 await，例外過去會被靜默吞掉、整條排程就此死亡，
而且不會有任何人察覺。這裡鎖定「單次失敗不影響下一輪」。
"""

import asyncio

import pytest

from tm_twitch_bot import scheduler as ts
from tm_twitch_bot.scheduler import TaskScheduler


@pytest.fixture
async def scheduler():
    """必須是 async fixture：TaskScheduler 要在事件圈內建構。"""
    sched = TaskScheduler()
    yield sched
    sched.cancel_all()


async def _wait_for(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), timeout=2)


async def test_interval_job_keeps_running_after_an_exception(scheduler):
    calls: list[int] = []
    reached_third = asyncio.Event()

    async def flaky(**kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise RuntimeError("第一次就爆炸")
        if len(calls) >= 3:
            reached_third.set()

    scheduler.add_interval_job(flaky, seconds=0, run_now=True, label="flaky")
    await _wait_for(reached_third)

    assert len(calls) >= 3  # 第一次爆炸沒有毒死整條排程


async def test_sync_function_is_supported(scheduler):
    calls: list[int] = []
    done = asyncio.Event()

    def sync_job(**kwargs):
        calls.append(1)
        done.set()

    scheduler.add_interval_job(sync_job, seconds=0, run_now=True, label="sync")
    await _wait_for(done)

    assert calls


async def test_sync_function_exception_is_also_contained(scheduler):
    calls: list[int] = []
    recovered = asyncio.Event()

    def flaky(**kwargs):
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise ValueError("同步函式也會爆")
        recovered.set()

    scheduler.add_interval_job(flaky, seconds=0, run_now=True, label="sync-flaky")
    await _wait_for(recovered)

    assert len(calls) >= 2


async def test_kwargs_are_forwarded(scheduler):
    received: list[str] = []
    done = asyncio.Event()

    async def job(**kwargs):
        received.append(kwargs["message"])
        done.set()

    scheduler.add_interval_job(
        job, seconds=0, run_now=True, kwargs={"message": "多喝水"}, label="kw"
    )
    await _wait_for(done)

    assert received[0] == "多喝水"


async def test_cancel_all_stops_the_job(scheduler):
    started = asyncio.Event()

    async def job(**kwargs):
        started.set()

    handle = scheduler.add_interval_job(job, seconds=0, run_now=True, label="cancel-me")
    await _wait_for(started)

    scheduler.cancel_all()
    await asyncio.sleep(0)  # 讓取消生效

    assert handle.done()


# ===== 排程間隔與遊戲時長 =====
#
# 這些是營運參數，抽成常數是為了「只有一處要改」。
# 測試把數值釘住，避免日後被別的改動順手動到。


def test_the_scheduled_intervals_match_the_operating_decision():
    assert ts.WATER_INTERVAL == 30 * 60  # 定期喝水：30 分鐘
    assert ts.RANDOM_GAME_INTERVAL == 45 * 60  # 隨機開遊戲：45 分鐘
    assert ts.GOLD_RUSH_DURATION == 3 * 60  # 一桶金倒數：3 分鐘
    assert ts.DAY_CHANGE_TIME == "23:59"


def test_the_game_interval_is_longer_than_both_games_last():
    """遊戲時長超過開局間隔的話，下一次排程會撞上「進行中」而白跑一場。"""
    from tm_twitch_bot.commands.games.guess_number import GuessNumberGame

    assert ts.GOLD_RUSH_DURATION < ts.RANDOM_GAME_INTERVAL
    assert GuessNumberGame.TIMEOUT_SECONDS < ts.RANDOM_GAME_INTERVAL


async def test_schedule_task_registers_with_those_intervals(monkeypatch):
    registered: list[tuple] = []

    def fake_interval(self, funcs, seconds, **kwargs):
        registered.append((getattr(funcs, "__name__", str(funcs)), seconds))
        return None

    def fake_daily(self, funcs, time_str, **kwargs):
        registered.append((getattr(funcs, "__name__", str(funcs)), time_str))
        return None

    monkeypatch.setattr(ts.TaskScheduler, "add_interval_job", fake_interval)
    monkeypatch.setattr(ts.TaskScheduler, "add_daily_job", fake_daily)

    async def _send(content):
        pass

    ts.schedule_task(_send)

    assert ("water", ts.WATER_INTERVAL) in registered
    assert ("random_game", ts.RANDOM_GAME_INTERVAL) in registered
    assert ("day_change", ts.DAY_CHANGE_TIME) in registered


# ===== 隨機開局要把 send_func 交給遊戲 =====


@pytest.mark.parametrize("game_index", [0, 1], ids=["終極密碼", "一桶金"])
async def test_random_game_hands_the_send_func_to_the_game(monkeypatch, game_index):
    """兩個遊戲的結算／流局公告都是倒數結束後才送出的。

    那時已經沒有任何呼叫端在等回傳值，所以遊戲必須自己拿到發話出口，
    否則訊息只會憑空消失（見 P1-15、P2-42）。
    """
    sent: list[str] = []
    got: dict = {}

    async def _send(content):
        sent.append(content)

    def fake_guess_start(send_func=None, timeout=None):
        got["guess_send_func"] = send_func
        return "終極密碼開始"

    def fake_rush_start(send_func, duration):
        got["rush_send_func"] = send_func
        got["rush_duration"] = duration
        return "一桶金開始"

    monkeypatch.setattr(ts.guess_number_game, "start", fake_guess_start)
    monkeypatch.setattr(ts.gold_rush_game, "start", fake_rush_start)
    monkeypatch.setattr(ts.random, "choice", lambda starters: starters[game_index])

    await ts.random_game(send_func=_send)

    if game_index == 0:
        assert got["guess_send_func"] is _send
        assert sent == ["終極密碼開始"]
    else:
        assert got["rush_send_func"] is _send
        assert got["rush_duration"] == ts.GOLD_RUSH_DURATION
        assert sent == ["一桶金開始"]
