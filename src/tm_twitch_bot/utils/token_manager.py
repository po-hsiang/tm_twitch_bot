from tm_twitch_bot.utils.yaml_utils import config, ENV_PATH
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
        set_key(str(ENV_PATH), "TWITCH_ACCESS_TOKEN", access_token)
        set_key(str(ENV_PATH), "TWITCH_REFRESH_TOKEN", refresh_token)
        logger.info("✅ 已更新 access / refresh token 並寫回 .env")
        self._notify(access_token, refresh_token)

    async def on_refresh(self, access_token: str, refresh_token: str) -> None:
        """twitchAPI 的 user_auth_refresh_callback 會 await 這個 callback。"""
        self.update(access_token, refresh_token)


token_manager = TokenManager()
