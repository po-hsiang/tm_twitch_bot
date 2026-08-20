from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.sheet_utils import collect_cells
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from datetime import datetime, timezone, timedelta
from typing import Optional
import random

adventure_dialogue_pool: list[str] = []  # 冒險台詞：惰性載入（不可在 import 階段打 API）

who_arrived: set[str] = set()
who_arrived.add(config["tigermeowtw_id"])  # 機器人不用跟虎喵打招呼
# extension = " 好久不見 tigerm24Shy"  # 備用字尾（未使用，保留備忘）


async def _ensure_dialogue_pool() -> None:
    if not adventure_dialogue_pool:
        raw_adventure_dialogue = await google_sheets_client.get_sheet_data("冒險台詞")
        # 這張表**沒有**標題列（第 0 列就是第一句台詞），跳過會少一句。
        # 三張內容表的實際形狀見 utils/sheet_utils.py。
        adventure_dialogue_pool.extend(
            collect_cells(raw_adventure_dialogue, skip_header=False)
        )
        logger.info(f"冒險台詞載入完成，共 {len(adventure_dialogue_pool)} 句")


def clear_pool() -> None:
    """丟掉抓下來的台詞，下一次有人第一次發言時會重抓（!reload 會呼叫）。

    刻意不清 who_arrived：那是「一場開台跟每個人打一次招呼」的規則，
    不是試算表的快取。連它一起清，全場的人會被重新打一次招呼。
    """
    adventure_dialogue_pool.clear()


async def greet_user(user_id) -> Optional[str]:

    if user_id in who_arrived:
        return ""

    who_arrived.add(user_id)

    hour = datetime.now(timezone(timedelta(hours=8))).hour  # 台灣時區

    if 18 <= hour:
        greeting = "晚上好 tigerm24Hi"
    elif 6 <= hour <= 11:
        greeting = "早安 tigerm24Hi"
    elif 12 <= hour <= 17:
        greeting = "午安 tigerm24Hi"
    else:
        greeting = "嗨嗨 tigerm24Hi 這麼晚還沒睡 tigerm24Quest"

    try:
        await _ensure_dialogue_pool()
    except Exception as e:
        # Sheets 服務暫時不可用時退回純招呼，不讓整個訊息處理中斷
        logger.error(f"冒險台詞載入失敗，退回純招呼: {e}")
        return greeting

    # return f"{greeting} 要不要來台聚玩！"  # 舊版招呼語（保留備忘）
    return f"{greeting} 聽說{random.choice(adventure_dialogue_pool)}"
