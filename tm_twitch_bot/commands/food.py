from tm_twitch_bot.clients.google_sheets import google_sheets_client
from tm_twitch_bot.utils.sheet_utils import collect_cells
import random

_food_pool: list[str] = []  # 惰性載入（過去在 import 階段抓表）

food_cache: dict[str, str] = {}


async def _ensure_pool() -> None:
    if not _food_pool:
        raw_food_data = await google_sheets_client.get_sheet_data("吃啥")
        # 這張表第 0 列是分類標題（飯／飯糰／燴飯…），不是餐點，所以要跳過。
        # 另兩張內容表不跳——三張表的實際形狀見 utils/sheet_utils.py。
        _food_pool.extend(collect_cells(raw_food_data, skip_header=True))


def clear_pool() -> None:
    """丟掉抓下來的表內容，下一次 !吃 會重抓一次（!reload 會呼叫）。

    刻意不清 food_cache：「一人一餐」是遊戲規則，不是試算表的快取。
    連它一起清，!reload 就變成重骰按鈕了。
    """
    _food_pool.clear()


async def pick(*args, **kwargs) -> str:
    char = kwargs.get("char")

    if char.user_id in food_cache:
        return food_cache[char.user_id]

    await _ensure_pool()
    choice = random.choice(_food_pool)
    food_cache[char.user_id] = choice
    return choice
