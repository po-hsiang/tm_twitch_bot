from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.log_utils import logger

# 啟動 bootstrap 時由 load_job_config() 填入（過去在 import 階段抓表）
# 注意：只做 in-place 更新，讓其他模組 `from ... import JOB_CONFIG` 的引用永遠有效
JOB_CONFIG: dict[int, dict] = {}


def parse_jobs_sheet(raw_data: list[list[str]]) -> dict[int, dict]:
    """
    raw_data 來自 google_sheets_client.get_sheet_data()
    第一列 → 中文序，第二列 → 等級門檻，其餘列 → 各職業
    """
    if len(raw_data) < 3:
        raise ValueError("資料格式不足，無法解析")

    stages = raw_data[0]
    levels_line = raw_data[1]  # ['10', '15', ...]
    job_rows = raw_data[2:]  # 之後每列都是職業
    job_config: dict[int, dict] = {}
    for idx, lvl in enumerate(levels_line):
        stage_name = stages[idx]
        jobs = [row[idx].strip() for row in job_rows if row[idx].strip()]
        job_config[int(lvl)] = {"stage": stage_name, "jobs": jobs}
    return job_config


async def load_job_config() -> None:
    raw_data = await google_sheets_client.get_sheet_data("轉職表")
    JOB_CONFIG.clear()
    JOB_CONFIG.update(parse_jobs_sheet(raw_data))
    logger.info(f"轉職表載入完成，門檻等級: {list(JOB_CONFIG.keys())}")


if __name__ == "__main__":
    import asyncio

    async def _demo():
        await load_job_config()
        print(f"JOB_CONFIG: {JOB_CONFIG}")

    asyncio.run(_demo())
