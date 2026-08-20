from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.sheet_utils import collect_cells
import random

_meme_pool: list[str] = []  # 惰性載入（過去在 import 階段抓表）
meme_cache = ""


async def _ensure_pool() -> None:
    if not _meme_pool:
        raw_meme_data = await google_sheets_client.get_sheet_data("酷酷的諧音梗")
        # 這張表**沒有**標題列（第 0 列是空的），跳過會把第 1 列的內容吃掉。
        # 三張內容表的實際形狀見 utils/sheet_utils.py。
        # 諧音梗是「問題換行答案」的格式，換行換成空白是刻意的排版選擇——
        # 交給 chat_sender.flatten 的話會變成 " / "。
        _meme_pool.extend(
            cell.replace("\n", " ")
            for cell in collect_cells(raw_meme_data, skip_header=False)
        )


async def pick(*args, **kwargs) -> str:
    global meme_cache
    if meme_cache:
        return meme_cache
    await _ensure_pool()
    meme_cache = random.choice(_meme_pool)
    return meme_cache
