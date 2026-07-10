from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
import random

_meme_pool: list[str] = []  # 惰性載入（過去在 import 階段抓表）
meme_cache = ""


async def _ensure_pool() -> None:
    if not _meme_pool:
        raw_meme_data = await google_sheets_client.get_sheet_data("酷酷的諧音梗")
        _meme_pool.extend(
            item.replace("\n", " ")
            for row in raw_meme_data
            for item in row
            if item.strip()
        )


async def pick(*args, **kwargs) -> str:
    global meme_cache
    if meme_cache:
        return meme_cache
    await _ensure_pool()
    meme_cache = random.choice(_meme_pool)
    return meme_cache
