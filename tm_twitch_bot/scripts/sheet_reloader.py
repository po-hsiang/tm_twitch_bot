"""把 Google Sheets 上的營運內容重新拉一次，不必重開 Bot。

CODE_REVIEW P2-26：試算表是當 CMS 用的，但改完要重開 Bot 才會生效——
開台途中重開就是斷線一次，「隨時能改」這件事實際上做不到。

刻意只重載「資料」，不重載「程式」。
用 importlib.reload 把模組換掉聽起來更徹底，但這個專案有七個單例
（chat_sender、四個微服務 client、兩個遊戲），reload 會生出第二份類別與
第二個實例：進行中的終極密碼會憑空消失，其他模組手上的舊參考還指著舊類別，
之後所有 isinstance 都不成立。改了程式就重開 Bot，那才是誠實的做法。

清單刻意集中在這裡一份。main.py 的降級啟動與五分鐘重試吃的是同一份
SHEET_LOADERS——之前那份寫在 main.py，日後加第三張表很容易只改一邊。
"""

from tm_twitch_bot.scripts import command_dispatcher
from tm_twitch_bot.scripts import daily_food_picker
from tm_twitch_bot.scripts import daily_meme_picker
from tm_twitch_bot.scripts import greeter
from tm_twitch_bot.scripts import level_and_job_system
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Awaitable, Callable

# 啟動時就必須載入的表：沒有它們，對應功能整組不能用。
SHEET_LOADERS: dict[str, Callable[[], Awaitable[None]]] = {
    "指令集": command_dispatcher.load_command_set,
    "轉職表": level_and_job_system.load_job_config,
}

# 惰性載入的內容表：清掉快取就好，下一次用到時自己會抓。
# 這些刻意不進 SHEET_LOADERS——啟動時就抓它們只是把 9091 的風險提前，
# 沒有任何好處（見 P1-37 的降級設計）。
POOL_CLEARERS: dict[str, Callable[[], None]] = {
    "吃啥": daily_food_picker.clear_pool,
    "酷酷的諧音梗": daily_meme_picker.clear_pool,
    "冒險台詞": greeter.clear_pool,
}


async def reload_all() -> tuple[list[str], list[str]]:
    """重載所有試算表內容，回傳 (成功, 失敗) 兩份名單。

    每張表各自 try：一張掛掉不能連帶讓其他張也不重載。
    load_command_set 是先抓表、成功才 clear + update，所以抓表失敗時
    線上那份指令集完全不受影響——重載失敗不會讓 Bot 變成沒有指令。
    """
    ok: list[str] = []
    failed: list[str] = []

    for name, loader in SHEET_LOADERS.items():
        try:
            await loader()
            ok.append(name)
        except Exception as e:
            failed.append(name)
            logger.error(f"重新載入「{name}」失敗: {type(e).__name__}: {e}")

    # 清快取不會失敗，也不會打網路：下一次有人用到才會重抓。
    for name, clear in POOL_CLEARERS.items():
        clear()
        ok.append(name)

    command_dispatcher.clear_function_cache()
    logger.info(f"試算表重載完成，成功 {len(ok)} 張、失敗 {len(failed)} 張")
    return ok, failed


async def reload(*, char=None) -> str:
    """`!reload` 的入口，只有管理員能用。

    簽章刻意寫明自己要什麼（P2-25 的「按參數名注入」）：這是第一個不用
    `*args, **kwargs` 摸黑拿 context 的指令函式，也當作那個機制的示範。

    註：降級啟動時用了 !reload，main.py 那條五分鐘重試還是會再載一次
    並公告「已恢復」。多一句公告而已，不值得為它把 bot 實例傳進來。
    """
    if char is None or char.user_id not in config["admin_user_id"]:
        return ""  # 和兩個遊戲的開局指令一致：不是管理員就安靜不回應

    ok, failed = await reload_all()

    if failed:
        return (
            f"⚠️ 重新載入失敗：{'、'.join(failed)}"
            f"（成功：{'、'.join(ok) or '無'}）"
        )
    return (
        f"✅ 已重新載入 {len(ok)} 張表，指令集共 "
        f"{len(command_dispatcher.COMMAND_SET)} 筆"
    )
