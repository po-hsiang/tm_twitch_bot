"""進入點：驗 token、載入試算表設定、把 Bot 跑起來、收尾關乾淨。

    uv run python tm_twitch_bot/main.py

Bot 自己的事件處理在 bot.py，試算表載入在 sheet_config.py——這個檔案只回答
「怎麼開起來、怎麼關乾淨」。
"""

from twitchAPI.type import AuthScope
from twitchAPI.twitch import Twitch
from tm_twitch_bot.bot import MyBot
from tm_twitch_bot.config.loader import config
from tm_twitch_bot.sheet_config import load_sheet_config
from tm_twitch_bot.utils.http_utils import close_async_client
from tm_twitch_bot.utils.log_utils import logger
from tm_twitch_bot.utils.token_manager import token_manager
from typing import Tuple
import platform
import inspect
import asyncio
import signal
import httpx
import sys


if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


twitch_config = config["twitch"]
CID = twitch_config["client_id"]
CSECRET = twitch_config["client_secret"]
CHANNEL = twitch_config["channel"]

SHUTDOWN_TIMEOUT = 10  # 收尾的總時限（秒）。超過就放棄，不能讓關機卡住
SIGNAL_POLL_SECONDS = 0.5


# ---------- 工具 ----------
async def validate(token: str) -> Tuple[bool, str]:
    async with httpx.AsyncClient() as cli:
        resp = await cli.get(
            "https://id.twitch.tv/oauth2/validate",
            headers={"Authorization": f"OAuth {token}"},
        )
        resp_json = resp.json()
        logger.info(f"validate() 驗證結果: {resp_json}")
    if resp.status_code != 200:
        return False, ""
    return True, resp_json.get("client_id")


TOKEN_URL = "https://id.twitch.tv/oauth2/token"


async def refresh_access_token() -> Tuple[str, str]:
    """用 refresh_token 換新 access/refresh；失敗拋例外。"""
    payload = {
        "client_id": CID,
        "client_secret": CSECRET,
        "grant_type": "refresh_token",
        "refresh_token": token_manager.refresh_token,
    }
    async with httpx.AsyncClient(timeout=10) as cli:
        r = await cli.post(TOKEN_URL, params=payload)
    r.raise_for_status()
    j = r.json()
    return j["access_token"], j["refresh_token"]


# ---------- 收尾 ----------
async def shutdown(*, bot=None, twitch=None, scheduler=None) -> None:
    """依序關閉所有資源。

    順序是刻意的：先停掉「還會產生新工作的東西」（排程、EventSub），
    再關連線（IRC、Helix、httpx 連線池）。反過來的話，
    排程可能在連線關掉之後才醒來，留下一串沒有意義的錯誤。

    每一步各自 try —— 任何一步失敗都不能擋住後面的清理，
    收尾程式最怕的就是「第一步炸掉，剩下全部沒跑」。
    """
    steps: list[tuple[str, object]] = []
    if scheduler is not None:
        steps.append(("取消定時排程", scheduler.cancel_all))
    if bot is not None and getattr(bot, "eventsub_ws", None) is not None:
        steps.append(("關閉 EventSub WebSocket", bot.eventsub_ws.stop))
    if bot is not None:
        steps.append(("關閉 IRC 連線", bot.close))
    if twitch is not None:
        steps.append(("關閉 Twitch API", twitch.close))
    steps.append(("關閉 httpx 連線池", close_async_client))

    for label, action in steps:
        try:
            result = action()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.error(f"收尾步驟「{label}」失敗，繼續下一步: {type(e).__name__}: {e}")
        else:
            logger.info(f"收尾完成：{label}")


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """把 SIGINT／SIGTERM 轉成一個停止事件。

    刻意不用 loop.add_signal_handler()：Windows 的 asyncio 不支援它。
    第一次收到訊號就把處理器還原成預設值 —— 萬一收尾卡住，
    再按一次 Ctrl+C 仍然能強制結束，不會變成殺不掉的程序。
    """
    loop = asyncio.get_running_loop()

    def _request_stop(signum, _frame):
        logger.warning(f"收到訊號 {signum}，開始收尾（再按一次可強制結束）")
        try:
            signal.signal(signum, signal.SIG_DFL)
        except (ValueError, OSError):
            pass
        loop.call_soon_threadsafe(stop.set)

    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if sig is None:
            continue
        try:
            signal.signal(sig, _request_stop)
        except (ValueError, OSError, RuntimeError) as e:
            logger.warning(f"無法安裝 {sig!r} 的訊號處理器，略過: {e}")


async def _keep_signals_responsive() -> None:
    """讓事件圈定期醒來，訊號處理器才有機會被執行。

    Windows 的 selector 事件圈閒置時會卡在 select()，Ctrl+C 不會把它叫醒；
    沒有這個心跳，關機可能要等到下一則聊天訊息進來才會生效。
    """
    while True:
        await asyncio.sleep(SIGNAL_POLL_SECONDS)


# ---------- 主協程 ----------
async def main():
    ok, cid_in_token = await validate(token_manager.access_token)
    if not ok or cid_in_token != CID:
        logger.warning("Access-Token 失效或非本 App，嘗試以 refresh_token 更新……")
        try:
            access_token, refresh_token = await refresh_access_token()
            token_manager.update(access_token, refresh_token)  # 更新記憶體並寫回 .env
            logger.info("🔄  取得新 access_token")
        except Exception as e:
            logger.error("自動刷新失敗：%s", e)
            raise RuntimeError("無法刷新 token，請重新授權") from e

    twitch = await Twitch(CID, CSECRET, authenticate_app=False)
    # twitchAPI 自動刷新後會 await 這個 callback，token_manager 同步更新記憶體與 .env
    twitch.user_auth_refresh_callback = token_manager.on_refresh
    await twitch.set_user_authentication(
        token_manager.access_token,
        [
            AuthScope.CHAT_READ,
            AuthScope.CHAT_EDIT,
            AuthScope.CHANNEL_READ_REDEMPTIONS,
            AuthScope.CHANNEL_MANAGE_VIPS,
            AuthScope.CHANNEL_READ_VIPS,
        ],
        refresh_token=token_manager.refresh_token,
    )
    logger.info("Twitch 物件建立完成")

    # === Bootstrap：啟動時載入 Google Sheets 設定（過去在 import 階段執行）===
    # 失敗不中斷啟動，改為降級上線並定期重試（見 load_sheet_config）
    degraded = await load_sheet_config()
    if degraded:
        logger.error(
            f"以降級模式啟動，未載入：{'、'.join(degraded)}。"
            f"請確認 Google Sheets 微服務（{config['google_sheets']['svc_url']}）是否已啟動"
        )

    bot = MyBot(twitch, degraded=degraded)
    stop = asyncio.Event()
    _install_signal_handlers(stop)

    bot_task = asyncio.create_task(bot.start(), name="twitchio_bot")
    stop_task = asyncio.create_task(stop.wait(), name="stop_signal")
    ticker = asyncio.create_task(_keep_signals_responsive(), name="signal_ticker")

    try:
        # 誰先結束都算：Bot 自己掛掉，或使用者按了 Ctrl+C
        await asyncio.wait({bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if bot_task.done() and not bot_task.cancelled():
            exc = bot_task.exception()
            if exc is not None:
                logger.error(f"Bot 意外終止: {type(exc).__name__}: {exc}")
            else:
                logger.warning("Bot 自行結束連線")
        else:
            logger.warning("收到停止指令，開始關閉 Bot")
    finally:
        stop_task.cancel()
        ticker.cancel()
        try:
            await asyncio.wait_for(
                shutdown(bot=bot, twitch=twitch, scheduler=bot.scheduler),
                timeout=SHUTDOWN_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(f"收尾超過 {SHUTDOWN_TIMEOUT} 秒仍未完成，直接結束")
        bot_task.cancel()
        # 這裡刻意不呼叫 sys.exit()：它會直接中止協程，
        # 讓上面剛寫好的收尾在某些路徑下反而跑不完。
        logger.warning("Bot 已完成收尾")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.error("主程式偵測到 KeyboardInterrupt")
    except Exception as e:
        logger.error(f"主程式錯誤: {e}")
    finally:
        logger.warning("主程式 finally 結束")
        sys.exit()
