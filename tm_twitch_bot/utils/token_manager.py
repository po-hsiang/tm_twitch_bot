from tm_twitch_bot.config.loader import config, ENV_PATH
from tm_twitch_bot.utils.log_utils import logger
from typing import Callable
from dotenv import set_key

# 訂閱者簽章：(access_token, refresh_token) -> None
TokenListener = Callable[[str, str], None]


class TokenManager:
    """Twitch access / refresh token 的唯一來源。

    無論是啟動時手動刷新，或 twitchAPI 執行期自動刷新，
    都經過 update() 更新記憶體並寫回 .env，
    任何取用端（如 vip_system 的 token_getter）永遠拿到最新值。

    有些取用端（例如 twitchio 的 IRC 連線）是在建構時就把 token 複製走的，
    沒辦法每次都來拿；這類對象改用 add_listener() 訂閱，在刷新當下被通知。
    """

    def __init__(self):
        twitch_config = config["twitch"]
        self._access_token: str = twitch_config["access_token"]
        self._refresh_token: str = twitch_config["refresh_token"]
        self._listeners: list[TokenListener] = []

    def add_listener(self, listener: TokenListener) -> None:
        """註冊 token 更新通知。listener 必須是同步函式，且自行處理例外成本。"""
        self._listeners.append(listener)

    def _notify(self, access_token: str, refresh_token: str) -> None:
        for listener in self._listeners:
            try:
                listener(access_token, refresh_token)
            except Exception as e:
                # 單一訂閱者失敗不能影響其他訂閱者，也不能讓刷新流程中斷
                logger.error(f"token 更新通知失敗（{getattr(listener, '__qualname__', listener)}）: {e}")

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def get_access(self) -> str:
        return self._access_token

    def update(self, access_token: str, refresh_token: str) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        # 同步 config dict，讓仍讀 config 的舊程式拿到新值
        config["twitch"]["access_token"] = access_token
        config["twitch"]["refresh_token"] = refresh_token

        # 寫檔順序是刻意的：refresh_token 先寫，access_token 後寫。
        #
        # dotenv 的 set_key 本身是原子的（寫暫存檔再 os.replace），
        # 但這裡有兩次呼叫，也就是兩個各自原子、彼此無關的操作。
        # 兩次之間崩潰（斷電、被強制關掉）就會留下不一致的一對，
        # 而 Twitch 的 refresh token 用過就輪替，所以哪一半留舊的差很多：
        #
        #   先寫 refresh（現在）：留下「新 refresh ＋ 舊 access」。
        #     下次啟動 validate() 發現 access 失效 → 用新的 refresh 換 → 自動復原。
        #   先寫 access（原本）：留下「新 access ＋ 舊 refresh」。
        #     下次啟動 validate() 通過，看起來一切正常，等到 access 過期要刷新時
        #     才發現 refresh 已經被輪替失效 —— 那時只能重跑一整輪 OAuth 授權。
        #
        # 換句話說，順序決定了「崩在中間」是自動復原還是要人工重新授權。
        set_key(str(ENV_PATH), "TWITCH_REFRESH_TOKEN", refresh_token)
        set_key(str(ENV_PATH), "TWITCH_ACCESS_TOKEN", access_token)
        logger.info("✅ 已更新 access / refresh token 並寫回 .env")
        self._notify(access_token, refresh_token)

    async def on_refresh(self, access_token: str, refresh_token: str) -> None:
        """twitchAPI 的 user_auth_refresh_callback 會 await 這個 callback。"""
        self.update(access_token, refresh_token)


token_manager = TokenManager()
