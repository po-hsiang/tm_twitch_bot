from pathlib import Path
import sys

parent_path = Path(__file__).resolve().parent.parent
sys.path.append(str(parent_path))

from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.type import AuthScope
from twitchAPI.twitch import Twitch
from twitchAPI.helper import first
from twitchio.ext import commands
from tm_twitch_bot.scripts.message_controller import handle_message
from tm_twitch_bot.scripts.task_scheduler import schedule_task
from tm_twitch_bot.scripts.vip_system import vip_system
from tm_twitch_bot.utils.yaml_utils import config, save_tokens
from tm_twitch_bot.utils.dump_obj_utils import dump_obj
from tm_twitch_bot.utils.log_utils import logger
from typing import Tuple
import platform
import asyncio
import httpx
import sys


if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


twitch_config = config["twitch"]
ACCESS = twitch_config["access_token"]
REFRESH = twitch_config["refresh_token"]
CID = twitch_config["client_id"]
CSECRET = twitch_config["client_secret"]
CHANNEL = twitch_config["channel"]


# ---------- 工具 ----------
async def validate(token: str) -> str:
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


def refresh_access_token() -> Tuple[str, str]:
    """用 refresh_token 換新 access/refresh；失敗拋例外。"""
    payload = {
        "client_id": CID,
        "client_secret": CSECRET,
        "grant_type": "refresh_token",
        "refresh_token": REFRESH,
    }
    r = httpx.post(TOKEN_URL, params=payload, timeout=10)
    r.raise_for_status()
    j = r.json()
    return j["access_token"], j["refresh_token"]


# ---------- 子類別 Bot ----------
class MyBot(commands.Bot):

    def __init__(self, twitch: Twitch):
        super().__init__(
            token=f"oauth:{ACCESS}", prefix="!", initial_channels=[CHANNEL]
        )
        self.twitch = twitch
        self.channel = None

    async def event_ready(self):
        # 1) 取得頻道使用者 ID
        user = await first(self.twitch.get_users(logins=CHANNEL))
        if not user:
            logger.error("找不到頻道使用者，請確認 CHANNEL 名稱")
            return

        # 2) 建立 WebSocket，先 start 再 listen
        ws = EventSubWebsocket(self.twitch)
        ws.start()  # 先建立 session :contentReference[oaicite:3]{index=3}
        await ws.listen_channel_points_custom_reward_redemption_add(
            user.id, self.on_points
        )  # 再訂閱並帶 callback
        logger.info("🎧  忠誠點數 WebSocket 已連線並訂閱完成")

        self.channel = self.connected_channels[0]

        vip_system.set_api_context(
            client_id=CID,
            broadcaster_id=user.id,
            token_getter=lambda: ACCESS,  # 你刷新 ACCESS 後，lambda 取到的就是最新 token
        )
        vip_system.sweep_expired()

        if not config["is_test"]:
            await self.channel.send(f"Bot 已上線 tigerm24ThruFast ")
            await self.channel.send(
                f"指令集： https://docs.google.com/spreadsheets/d/1-UQ7KBWK09ZCHZKFycymk04BaB5oW6DJ0vi2N7x6qQE/edit?usp=sharing "
            )
        else:
            logger.info(f"【測試測試】Bot 已上線！")

        # === 這裡呼叫任務排程器 ===
        schedule_task(self.channel.send)

    async def event_message(self, message):
        if message.echo:
            return

        # 測試期間只有虎喵能打通指令
        if config["is_test"]:
            if message.author.id == config["tigermeowtw_id"]:
                await handle_message(message)
            return

        # 正式時走這段
        await handle_message(message)

    async def on_points(self, subscription_and_event):
        # TODO 目前有其他人兌換而收不到事件的 Bug
        # logger.info(f"tpye(subscription_and_event): {type(subscription_and_event)}")
        # logger.info(f"to_dict(): {subscription_and_event.to_dict()}")

        event = subscription_and_event.event
        user_id = event.user_id
        user_login = event.user_login
        user_name = event.user_name
        user_input = event.user_input

        reward = event.reward

        logger.info(f"【忠誠點數兌換】{user_name} 兌換了「{reward.title}」")
        if reward.title == "虎喵安安":
            logger.warning(f"{user_name} 打了招呼！")
        elif reward.title == "頭香，前來報到":
            logger.warning(f"{user_name} 換了頭香！")


# ---------- 主協程 ----------
async def main():
    global ACCESS, REFRESH  # 若刷新需更新全域

    ok, cid_in_token = await validate(ACCESS)
    if not ok or cid_in_token != CID:
        logger.warning("Access-Token 失效或非本 App，嘗試以 refresh_token 更新……")
        try:
            ACCESS, REFRESH = refresh_access_token()
            save_tokens(ACCESS, REFRESH)  # 寫回 YAML 或檔案
            logger.info(
                "🔄  取得新 access_token，剩餘 %s 秒過期",
                twitch_config.get("expires_in", "240*60"),
            )
        except Exception as e:
            logger.error("自動刷新失敗：%s", e)
            raise RuntimeError("無法刷新 token，請重新授權") from e

    twitch = await Twitch(CID, CSECRET, authenticate_app=False)
    twitch.user_auth_refresh_callback = save_tokens
    await twitch.set_user_authentication(
        ACCESS,
        [
            AuthScope.CHAT_READ,
            AuthScope.CHAT_EDIT,
            AuthScope.CHANNEL_READ_REDEMPTIONS,
            AuthScope.CHANNEL_MANAGE_VIPS,
            AuthScope.CHANNEL_READ_VIPS,
        ],
        refresh_token=REFRESH,
    )
    logger.info("Twitch 物件建立完成")

    try:
        bot = MyBot(twitch)
        await bot.start()
    except Exception as e:
        logger.error(f"Bot 錯誤: {e}")
    finally:
        logger.warning(f"Bot finally 結束")
        sys.exit()
    sys.exit()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.error(f"主程式偵測到 KeyboardInterrupt")
    except Exception as e:
        logger.error(f"主程式錯誤: {e}")
    finally:
        logger.warning(f"主程式 finally 結束")
        sys.exit()
    sys.exit()
