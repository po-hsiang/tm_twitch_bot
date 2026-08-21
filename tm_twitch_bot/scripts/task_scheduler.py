from tm_twitch_bot.games.guess_number_game import guess_number_game
from tm_twitch_bot.games.gold_rush_game import gold_rush_game
from tm_twitch_bot.utils.log_utils import logger
from tm_twitch_bot.utils.time_utils import now_tw
from typing import Iterable, Callable, Awaitable, Any
from dataclasses import dataclass
from functools import partial
import datetime as dt
import asyncio
import inspect
import random

AsyncFunc = Callable[..., Awaitable[None]] | Callable[..., None]

# 排程間隔與遊戲時長。抽成常數而不是散在呼叫處的裸數字，
# 營運要調整時只有這一區要看。
WATER_INTERVAL = 1800  # 定期喝水：30 分鐘
RANDOM_GAME_INTERVAL = 2700  # 隨機開一場小遊戲：45 分鐘
DAY_CHANGE_TIME = "23:59"  # 換日提醒
GOLD_RUSH_DURATION = 180  # 排程開的一桶金倒數：3 分鐘
# 終極密碼的流局倒數在 GuessNumberGame.TIMEOUT_SECONDS（30 分鐘），
# 因為那是遊戲自己的規則，管理員手動開局時也要生效。


def seconds_until(hour: int, minute: int, *, now: dt.datetime | None = None) -> float:
    """距離下一次 hh:mm（**台灣時間**）還有幾秒；已經過了就算到明天。

    原本這段內嵌在 _daily_worker 裡，用的是 naive 的 datetime.now()——
    也就是本機時區。搬到 UTC 機器上，23:59 的換日提醒會在台灣的早上八點才響
    （CODE_REVIEW P3-35）。

    now 可以注入，測試才不必真的等到午夜。
    固定偏移的時區讓 .replace(hour=...) 沒有 DST 邊界問題（見 time_utils）。
    """
    now = now or now_tw()
    next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if next_run <= now:
        next_run += dt.timedelta(days=1)
    return (next_run - now).total_seconds()


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
        # 必須在事件圈內建構。原本用 get_event_loop()，它在無執行中迴圈時
        # 只會發 DeprecationWarning 再拋錯，Python 3.14 起會直接拋錯；
        # 改用 get_running_loop() 讓誤用當場就看得出來。
        self.loop = loop or asyncio.get_running_loop()
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
        name = label or f"interval_{seconds}s"
        coro = self._interval_worker(
            funcs_list, seconds, run_now, args, kwargs or {}, name
        )
        return self._spawn(coro, name, label)

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
        name = label or f"daily_{time_str}"
        coro = self._daily_worker(funcs_list, hour, minute, args, kwargs or {}, name)
        return self._spawn(coro, name, label)

    # ---------- Internal Workers ---------- #

    def _spawn(self, coro, name: str, label: str | None) -> JobHandler:
        task = self.loop.create_task(coro, name=name)
        task.add_done_callback(partial(self._on_job_finished, name))
        handle = JobHandler(task, label)
        self._jobs.append(handle)
        return handle

    @staticmethod
    def _on_job_finished(name: str, task: asyncio.Task) -> None:
        """排程任務正常情況下永遠不會結束；真的結束了一定要留下痕跡。

        過去沒有任何人 await 這些 task，例外會被靜默吞掉，
        只在直譯器結束時才印出 "Task exception was never retrieved" ——
        排程默默死掉不會有人察覺。
        """
        if task.cancelled():
            logger.info(f"排程任務 {name} 已取消")
            return
        exc = task.exception()
        if exc is not None:
            logger.error(f"排程任務 {name} 意外終止: {type(exc).__name__}: {exc}")
        else:
            logger.warning(f"排程任務 {name} 意外結束（排程迴圈不應自行退出）")

    async def _interval_worker(
        self,
        funcs: list[AsyncFunc],
        seconds: int,
        run_now: bool,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        name: str,
    ):
        if run_now:
            await self._execute_safely(funcs, args, kwargs, name)
        while True:
            await asyncio.sleep(seconds)
            await self._execute_safely(funcs, args, kwargs, name)

    async def _daily_worker(
        self,
        funcs: list[AsyncFunc],
        hour: int,
        minute: int,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        name: str,
    ):
        while True:
            await asyncio.sleep(seconds_until(hour, minute))
            await self._execute_safely(funcs, args, kwargs, name)

    async def _execute_safely(
        self,
        funcs: list[AsyncFunc],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        name: str,
    ):
        """單次執行失敗不能拖垮整條排程，否則之後永遠不會再觸發。"""
        try:
            await self._execute(funcs, args, kwargs)
        except asyncio.CancelledError:
            raise  # 取消必須往外傳，不能被當成一般錯誤吃掉
        except Exception as e:
            logger.error(
                f"排程任務 {name} 本次執行失敗，下一輪仍會繼續: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )

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


def schedule_task(send_func) -> TaskScheduler:
    """建立所有定時任務，並把排程器交還給呼叫端。

    過去 TaskScheduler 只是這裡的區域變數，關機時沒有人能取消它，
    Ctrl+C 之後 task 只會被直譯器硬砍（見 CODE_REVIEW P1-13）。
    """
    task_scheduler = TaskScheduler()

    # 定期喝水
    task_scheduler.add_interval_job(
        water, seconds=WATER_INTERVAL, kwargs={"send_func": send_func}
    )

    # 開啟隨機遊戲
    task_scheduler.add_interval_job(
        random_game, seconds=RANDOM_GAME_INTERVAL, kwargs={"send_func": send_func}
    )

    # 提醒換日
    task_scheduler.add_daily_job(
        day_change, time_str=DAY_CHANGE_TIME, kwargs={"send_func": send_func}
    )

    return task_scheduler


async def water(*args, **kwargs):
    send_func = kwargs.get("send_func")
    await send_func("大家沒事多喝水 tigerm24HeartHeart ")


async def day_change(*args, **kwargs):
    send_func = kwargs.get("send_func")
    await send_func("23:59 囉！準備睡覺！")


async def random_game(*args, **kwargs):
    """隨機開一場小遊戲。

    兩個遊戲都要收下 send_func：它們的結算／流局公告是倒數結束後才送出的，
    那時已經沒有任何呼叫端在等回傳值（見 P1-15、P2-42）。

    用明確的啟動器，而不是原本靠 `__self__.__class__.__name__` 反射判斷
    是哪個遊戲再分支——那種寫法只要類別改名，兩個分支就都不成立，
    排程會靜靜地什麼都不做，而且不會有任何錯誤。
    """
    send_func = kwargs.get("send_func")
    starters = (
        lambda: guess_number_game.start(send_func),
        lambda: gold_rush_game.start(send_func, GOLD_RUSH_DURATION),
    )
    await send_func(random.choice(starters)())
