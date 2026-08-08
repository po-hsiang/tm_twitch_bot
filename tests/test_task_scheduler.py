"""排程器的容錯。

排程 task 沒有任何人 await，例外過去會被靜默吞掉、整條排程就此死亡，
而且不會有任何人察覺。這裡鎖定「單次失敗不影響下一輪」。
"""

import asyncio

import pytest

from tm_twitch_bot.scripts.task_scheduler import TaskScheduler


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
