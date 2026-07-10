from tm_twitch_bot.games.guess_number_game import guess_number_game
from tm_twitch_bot.games.gold_rush_game import gold_rush_game
from typing import Iterable, Callable, Awaitable, Any
from dataclasses import dataclass
import datetime as dt
import asyncio
import inspect
import random

AsyncFunc = Callable[..., Awaitable[None]] | Callable[..., None]


@dataclass
class JobHandler:
    task: asyncio.Task
    label: str | None = None

    def cancel(self) -> None:
        self.task.cancel()

    def done(self) -> bool:
        return self.task.done()


class TaskScheduler:
    def __init__(self, *, loop: asyncio.AbstractEventLoop | None = None):
        self.loop = loop or asyncio.get_event_loop()
        self._jobs: list[JobHandler] = []

    # ---------- Public API ---------- #

    def add_interval_job(
        self,
        funcs: AsyncFunc | Iterable[AsyncFunc],
        seconds: int,
        *,
        run_now: bool = False,
        label: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> JobHandler:
        funcs_list = list(funcs) if isinstance(funcs, Iterable) else [funcs]
        coro = self._interval_worker(funcs_list, seconds, run_now, args, kwargs or {})
        task = self.loop.create_task(coro, name=label or f"interval_{seconds}s")
        handle = JobHandler(task, label)
        self._jobs.append(handle)
        return handle

    def add_daily_job(
        self,
        funcs: AsyncFunc | Iterable[AsyncFunc],
        time_str: str,
        *,
        label: str | None = None,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> JobHandler:
        funcs_list = list(funcs) if isinstance(funcs, Iterable) else [funcs]
        hour, minute = map(int, time_str.split(":"))
        coro = self._daily_worker(funcs_list, hour, minute, args, kwargs or {})
        task = self.loop.create_task(coro, name=label or f"daily_{time_str}")
        handle = JobHandler(task, label)
        self._jobs.append(handle)
        return handle

    # ---------- Internal Workers ---------- #

    async def _interval_worker(
        self,
        funcs: list[AsyncFunc],
        seconds: int,
        run_now: bool,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ):
        if run_now:
            await self._execute(funcs, args, kwargs)
        while True:
            await asyncio.sleep(seconds)
            await self._execute(funcs, args, kwargs)

    async def _daily_worker(
        self,
        funcs: list[AsyncFunc],
        hour: int,
        minute: int,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ):
        while True:
            now = dt.datetime.now()
            next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += dt.timedelta(days=1)
            await asyncio.sleep((next_run - now).total_seconds())
            await self._execute(funcs, args, kwargs)

    async def _execute(
        self,
        funcs: list[AsyncFunc],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ):
        func = random.choice(funcs)
        if inspect.iscoroutinefunction(func):
            await func(*args, **kwargs)
        else:
            func(*args, **kwargs)

    # ---------- Utility ---------- #
    def cancel_all(self) -> None:
        for job in self._jobs:
            job.cancel()
        self._jobs.clear()


# ---------- 主程式呼叫過來的任務排程 ---------- #


def schedule_task(send_func):
    task_scheduler = TaskScheduler()

    # 定期喝水
    task_scheduler.add_interval_job(
        water, seconds=1200, kwargs={"send_func": send_func}
    )

    # 開啟隨機遊戲
    task_scheduler.add_interval_job(
        random_game, seconds=1800, kwargs={"send_func": send_func}
    )

    # 提醒換日
    task_scheduler.add_daily_job(
        day_change, time_str="23:59", kwargs={"send_func": send_func}
    )


async def water(*args, **kwargs):
    send_func = kwargs.get("send_func")
    await send_func("大家沒事多喝水 tigerm24HeartHeart ")


async def day_change(*args, **kwargs):
    send_func = kwargs.get("send_func")
    await send_func("23:59 囉！準備睡覺！")


async def random_game(*args, **kwargs):
    send_func = kwargs.get("send_func")
    games = [guess_number_game.start, gold_rush_game.start]
    game_start_func = random.choice(games)
    game_name = game_start_func.__self__.__class__.__name__
    if game_name == "GuessNumberGame":
        await send_func(game_start_func())
    elif game_name == "GoldRushGame":
        await send_func(game_start_func(send_func, 120))
