from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.log_utils import logger

# 啟動 bootstrap 時由 load_job_config() 填入（過去在 import 階段抓表）
# 注意：只做 in-place 更新，讓其他模組 `from ... import JOB_CONFIG` 的引用永遠有效
JOB_CONFIG: dict[int, dict] = {}


def _cell(row: list[str], idx: int) -> str:
    """安全取格。

    Google Sheets API 會把每一列尾端的空白儲存格截掉，
    所以「列比表頭短」是常態而不是例外——直接 row[idx] 會 IndexError。
    這張表是在啟動 bootstrap 階段解析的，解析失敗等於 Bot 起不來。
    """
    return row[idx].strip() if idx < len(row) else ""


def _to_level(raw: str) -> int | None:
    """等級門檻必須是正整數；不是的話回傳 None 讓呼叫端略過該欄。"""
    try:
        level = int(raw.strip())
    except (AttributeError, ValueError):
        return None
    return level if level > 0 else None


def parse_jobs_sheet(raw_data: list[list[str]]) -> dict[int, dict]:
    """
    raw_data 來自 google_sheets_client.get_sheet_data()
    第一列 → 中文序，第二列 → 等級門檻，其餘列 → 各職業

    這張表可以被手動編輯，格式隨時可能歪掉，而它又是啟動時就要解析的。
    因此除了「整張表根本不成形」之外，一律容忍並記錄，不讓 Bot 起不來：
    少一個轉職階段只影響那一級的轉職，起不來則是整場開台都沒有機器人。
    """
    if len(raw_data) < 3:
        raise ValueError("資料格式不足，無法解析")

    stages = raw_data[0]
    levels_line = raw_data[1]  # ['10', '15', ...]
    job_rows = raw_data[2:]  # 之後每列都是職業
    job_config: dict[int, dict] = {}
    for idx, lvl in enumerate(levels_line):
        level = _to_level(lvl)
        if level is None:
            logger.error(
                f"轉職表第 {idx + 1} 欄的等級門檻「{lvl}」不是正整數，已略過該欄"
            )
            continue
        stage_name = _cell(stages, idx)
        jobs = [job for job in (_cell(row, idx) for row in job_rows) if job]
        job_config[level] = {"stage": stage_name, "jobs": jobs}
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
