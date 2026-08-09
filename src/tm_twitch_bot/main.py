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
from tm_twitch_bot.scripts import command_dispatcher
from tm_twitch_bot.scripts import level_and_job_system
from tm_twitch_bot.utils.chat_sender import chat_sender
from tm_twitch_bot.utils.token_manager import token_manager
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Tuple
import platform
import asyncio
import httpx


if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


twitch_config = config["twitch"]
CID = twitch_config["client_id"]
CSECRET = twitch_config["client_secret"]
CHANNEL = twitch_config["channel"]

# 開台／關台事件的 log 標記。刻意用純 ASCII，方便日後 grep：
#   grep STREAM-EVENT logs/tm_twitch_bot.log
STREAM_EVENT_TAG = "[STREAM-EVENT]"


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


# ---------- 子類別 Bot ----------
class MyBot(commands.Bot):

    def __init__(self, twitch: Twitch):
        super().__init__(
            token=f"oauth:{token_manager.access_token}",
            prefix="!",
            initial_channels=[CHANNEL],
        )
        self.twitch = twitch
        self.channel = None
        # 保留 EventSub WebSocket 的強參考。
        # 過去它只是 event_ready 的區域變數，方法一返回就沒有任何強參考撐著，
        # 隨時可能被 GC 回收 —— 很可能就是「別人兌換收不到事件」的主因。
        self.eventsub_ws: EventSubWebsocket | None = None
        # twitchio 每次成功連線（含斷線重連）都會觸發 event_ready，
        # 一次性初始化必須自行去重，否則排程與訂閱會隨重連次數倍增。
        self._bootstrapped = False
        # twitchio 在建構當下就把 token 複製進 REST client 與 IRC 連線，
        # 之後 twitchAPI 自動刷新時它並不知情，因此改為主動訂閱通知。
        token_manager.add_listener(self._on_token_refreshed)

    # ---------- Token 同步 ----------

    def _on_token_refreshed(self, access_token: str, _refresh_token: str) -> None:
        """token_manager 刷新後，把新 token 同步進 twitchio 並重連 IRC。

        twitchio 2.x 沒有公開的換 token API，token 被分別複製在兩處：
          - Client._http.token        → Helix REST 呼叫用
          - Client._connection._token → IRC 登入時送出的 PASS oauth:<token>
        只能直接寫入這兩個私有屬性。此處相依於 twitchio>=2.10,<3 的內部結構，
        升級 twitchio 時務必一併驗證。
        """
        self._http.token = access_token
        self._connection._token = access_token
        logger.info("已將新的 access_token 同步至 twitchio（REST + IRC）")

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 不在事件圈內（例如啟動階段的手動刷新），此時 IRC 還沒連線，不需重連
            return
        loop.create_task(self._reconnect_irc())

    async def _reconnect_irc(self) -> None:
        """以新 token 重建 IRC 連線，比照 twitchio 收到 RECONNECT 時的作法。"""
        conn = self._connection
        if not conn.is_alive:
            logger.info("IRC 尚未連線，略過重連（新 token 會在下次連線時生效）")
            return
        try:
            conn._reconnect_requested = True  # 讓現有 _keep_alive 迴圈停止
            if conn._keeper:
                conn._keeper.cancel()
            await conn._connect()
            logger.info("🔄  IRC 已使用新的 access_token 重新連線")
        except Exception as e:
            logger.error(f"IRC 以新 token 重連失敗: {e}")

    async def send_to_channel(self, content: str) -> None:
        """統一的發話入口。

        重連後 twitchio 會給出全新的 Channel 物件，
        排程器若抓著舊物件的 bound method 會靜默失效，因此一律晚綁定。
        """
        if self.channel is None:
            logger.error(f"channel 尚未就緒，訊息未送出：{content}")
            return
        # 統一走 chat_sender：截斷過長訊息，並確保不超過 Twitch 的速率限制
        await chat_sender.send(self.channel.send, content)

    async def event_ready(self):
        if not self.connected_channels:
            logger.error("event_ready 已觸發，但沒有任何已連線頻道")
            return

        # 重連後 Channel 物件會換新，這行每次都要更新
        self.channel = self.connected_channels[0]

        if self._bootstrapped:
            logger.warning(
                "event_ready 因 IRC 重連再次觸發，"
                "略過一次性初始化（EventSub 訂閱／VIP 掃描／定時排程／上線公告）"
            )
            return
        self._bootstrapped = True

        # 1) 取得頻道使用者 ID
        user = await first(self.twitch.get_users(logins=CHANNEL))
        if not user:
            logger.error("找不到頻道使用者，請確認 CHANNEL 名稱")
            self._bootstrapped = False  # 保留下次重連時重試的機會
            return

        # 2) 建立 WebSocket，先 start 再 listen
        self.eventsub_ws = EventSubWebsocket(self.twitch)
        self.eventsub_ws.start()  # 先建立 session
        await self.eventsub_ws.listen_channel_points_custom_reward_redemption_add(
            user.id, self.on_points
        )  # 再訂閱並帶 callback
        logger.info("🎧  忠誠點數 WebSocket 已連線並訂閱完成")

        # 3) 開台／關台事件——目前「只觀測、不改行為」。
        # 兩者都不需要額外 scope。這一步的用意是先累積實際資料：
        # EventSub 的 WebSocket 一斷線，訂閱會全部失效且事件不補發；
        # stream.offline 也可能因推流短暫中斷而抖動。
        # 先跑一陣子確認事件夠可靠，再決定要不要把 Bot 改成常駐服務。
        # 完整取捨見 docs/CODE_REVIEW.md 附錄 A。
        await self.eventsub_ws.listen_stream_online(user.id, self.on_stream_online)
        await self.eventsub_ws.listen_stream_offline(user.id, self.on_stream_offline)
        logger.info("📡  已訂閱開台／關台事件（僅記錄 log，不影響任何行為）")

        vip_system.set_api_context(
            client_id=CID,
            broadcaster_id=user.id,
            token_getter=token_manager.get_access,  # 永遠取得最新 token（含自動刷新後）
        )
        await vip_system.sweep_expired()

        if not config["is_test"]:
            await self.send_to_channel(f"Bot 已上線 tigerm24ThruFast ")
            await self.send_to_channel(
                f"指令集： https://docs.google.com/spreadsheets/d/1-UQ7KBWK09ZCHZKFycymk04BaB5oW6DJ0vi2N7x6qQE/edit?usp=sharing "
            )
        else:
            logger.info(f"【測試測試】Bot 已上線！")

        # === 這裡呼叫任務排程器 ===
        schedule_task(self.send_to_channel)

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

    # ---------- 開台／關台觀測 ----------
    #
    # 這兩個 handler 是刻意「唯讀」的：只寫 log，不碰任何狀態、不發任何訊息。
    # 觀察期要回答的問題是——事件會不會漏、offline 會不會抖、延遲多久。
    # 之後用 STREAM_EVENT_TAG 撈 logs/tm_twitch_bot.log 就能一次看完。

    async def on_stream_online(self, data) -> None:
        try:
            event = data.event
            logger.warning(
                f"{STREAM_EVENT_TAG} 開台 stream_id={event.id} type={event.type} "
                f"started_at={event.started_at} 頻道={event.broadcaster_user_name}"
            )
        except Exception as e:
            # 觀測用的程式碼絕不能反過來影響 Bot，欄位對不上就記下來就好
            logger.error(f"{STREAM_EVENT_TAG} 開台事件解析失敗: {e}")

    async def on_stream_offline(self, data) -> None:
        try:
            event = data.event
            logger.warning(
                f"{STREAM_EVENT_TAG} 關台 頻道={event.broadcaster_user_name}"
                f"（{event.broadcaster_user_id}）"
            )
        except Exception as e:
            logger.error(f"{STREAM_EVENT_TAG} 關台事件解析失敗: {e}")

    async def on_points(self, subscription_and_event):
        # TODO 待實測：過去有「其他人兌換收不到事件」的 Bug。
        # 已修正 EventSubWebsocket 沒有強參考、可能被 GC 回收的問題（見 CODE_REVIEW P0-3），
        # 但尚未於正式頻道實際驗證。若仍收不到，下一個懷疑對象是訂閱所用 token 的
        # scope 與 broadcaster_user_id 是否相符。
        event = subscription_and_event.event
        user_name = event.user_name

        reward = event.reward

        logger.info(f"【忠誠點數兌換】{user_name} 兌換了「{reward.title}」")
        if reward.title == "虎喵安安":
            logger.warning(f"{user_name} 打了招呼！")
        elif reward.title == "頭香，前來報到":
            logger.warning(f"{user_name} 換了頭香！")


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
    await command_dispatcher.load_command_set()
    await level_and_job_system.load_job_config()

    try:
        bot = MyBot(twitch)
        await bot.start()
    except Exception as e:
        logger.error(f"Bot 錯誤: {e}")
    finally:
        logger.warning(f"Bot finally 結束")
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
