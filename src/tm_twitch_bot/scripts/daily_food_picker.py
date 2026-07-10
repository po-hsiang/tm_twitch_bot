from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
import random

_food_pool: list[str] = []  # 惰性載入（過去在 import 階段抓表）

food_cache: dict[str, str] = {}


async def _ensure_pool() -> None:
    if not _food_pool:
        raw_food_data = await google_sheets_client.get_sheet_data("吃啥")
        _food_pool.extend(
            item for row in raw_food_data[1:] for item in row if item.strip()
        )


async def pick(*args, **kwargs) -> str:
    char = kwargs.get("char")

    if char.user_id in food_cache:
        return food_cache[char.user_id]

    await _ensure_pool()
    choice = random.choice(_food_pool)
    food_cache[char.user_id] = choice
    return choice
