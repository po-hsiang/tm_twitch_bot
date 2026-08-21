"""`!reload`：管理員限定，重新拉一次試算表，不必重開 Bot（CODE_REVIEW P2-26）。

實際的載入在 sheet_config——那份清單啟動時也要用，不能只屬於一個指令。
這裡只做兩件真正屬於「指令」的事：檢查權限、把結果講成一句人看得懂的話。

這也是全專案唯一硬寫在 dispatcher 裡的指令（見 chat/dispatcher.py 的
BUILTIN_COMMANDS）：它是修復工具，而「指令集沒載入成功」正是最需要它的時候，
放在試算表上就變成「要修的東西壞了，修它的工具也一起壞」。
"""

from tm_twitch_bot import sheet_config
from tm_twitch_bot.chat import dispatcher
from tm_twitch_bot.config.loader import config


async def reload(*, char=None) -> str:
    """簽章刻意寫明自己要什麼（P2-25 的「按參數名注入」）。

    這是第一個不用 `*args, **kwargs` 摸黑拿 context 的指令函式，
    也當作那個機制的示範。

    註：降級啟動時用了 !reload，那條五分鐘重試還是會再載一次並公告「已恢復」。
    多一句公告而已，不值得為它把 bot 實例傳進來。
    """
    if char is None or char.user_id not in config["admin_user_id"]:
        return ""  # 和兩個遊戲的開局指令一致：不是管理員就安靜不回應

    ok, failed = await sheet_config.reload_all()

    if failed:
        return (
            f"⚠️ 重新載入失敗：{'、'.join(failed)}"
            f"（成功：{'、'.join(ok) or '無'}）"
        )
    return (
        f"✅ 已重新載入 {len(ok)} 張表，指令集共 "
        f"{len(dispatcher.COMMAND_SET)} 筆"
    )
