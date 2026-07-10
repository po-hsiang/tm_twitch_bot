from tm_twitch_bot.utils.yaml_utils import config, ENV_PATH
from tm_twitch_bot.utils.log_utils import logger
from dotenv import set_key


class TokenManager:
    """Twitch access / refresh token 的唯一來源。

    無論是啟動時手動刷新，或 twitchAPI 執行期自動刷新，
    都經過 update() 更新記憶體並寫回 .env，
    任何取用端（如 vip_system 的 token_getter）永遠拿到最新值。
    """

    def __init__(self):
        twitch_config = config["twitch"]
        self._access_token: str = twitch_config["access_token"]
        self._refresh_token: str = twitch_config["refresh_token"]

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

    async def on_refresh(self, access_token: str, refresh_token: str) -> None:
        """twitchAPI 的 user_auth_refresh_callback 會 await 這個 callback。"""
        self.update(access_token, refresh_token)


token_manager = TokenManager()
