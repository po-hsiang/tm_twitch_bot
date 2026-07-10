from tm_twitch_bot.scripts.task_scheduler import TaskScheduler
from tm_twitch_bot.utils.log_utils import logger
import asyncio


async def func_a(name):
    logger.debug(f"每 30 秒呼叫 A, 參數: {name}")


async def func_b(name):
    logger.critical(f"每 60 秒被呼叫 B, 參數: {name}")


async def func_c():
    logger.warning("每 10 秒隨機呼叫 C 或 D")


async def func_d():
    logger.error("每 10 秒隨機呼叫 D 或 C")


async def func_e(name):
    logger.info(f"特定時間呼叫 E, 參數: {name}")


async def main():
    scheduler = TaskScheduler()

    scheduler.add_interval_job(func_a, 30, run_now=False, args=("Alice",))
    scheduler.add_interval_job(func_b, 60, run_now=True, args=("Health Check",))
    scheduler.add_interval_job([func_c, func_d], 5)
    scheduler.add_daily_job(func_e, time_str="17:40", args=("Daily summary",))

    while True:
        await asyncio.sleep(3600)  # 模擬主迴圈


if __name__ == "__main__":
    logger.info("開始執行定時任務...")
    asyncio.run(main())
