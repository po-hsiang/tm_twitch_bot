from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.log_utils import logger
import random

_raw_food_data: list[list[str]] = google_sheets_client.get_sheet_data("吃啥")
_food_pool = [item for row in _raw_food_data[1:] for item in row if item.strip()]

food_cache: dict[str, str] = {}


def pick(*args, **kwargs) -> str:
    char = kwargs.get("char")

    if char.user_id in food_cache:
        return food_cache[char.user_id]

    choice = random.choice(_food_pool)
    food_cache[char.user_id] = choice
    return choice
