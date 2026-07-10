from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.log_utils import logger
import random

_raw_meme_data: list[list[str]] = google_sheets_client.get_sheet_data("酷酷的諧音梗")

_meme_pool = [
    item.replace("\n", " ") for row in _raw_meme_data for item in row if item.strip()
]
meme_cache = ""


def pick(*args, **kwargs) -> str:
    global meme_cache
    if meme_cache:
        return meme_cache
    meme_cache = random.choice(_meme_pool)
    return meme_cache


if __name__ == "__main__":
    logger.info(f"{pick()}")
