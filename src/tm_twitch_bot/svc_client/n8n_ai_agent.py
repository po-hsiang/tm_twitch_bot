"""n8n「TM AI Agent」工作流的 webhook client。

這條工作流是多客戶端共用的（Discord bot 也在用），n8n 端不屬於本專案、
也不需要為了 Twitch 做任何修改。因此這裡只負責「照規格把欄位送齊、
把回覆帶回來」，不做任何欄位推測，也不碰 prompt 與對話記憶——
那些都在 n8n 端。

與其他 svc_client 的三個差別都是刻意的：

  - **不重試。** 每次呼叫都會真的跑一輪 AI（模型還可能自行呼叫工具），
    重試等於重複計費；更糟的是逾時後重送，同一句話可能被寫進兩次對話記憶。
  - **逾時 120 秒。** 一般 3～5 秒，AI 呼叫工具時 10～25 秒，要留足餘裕。
  - **不拋例外。** 非 200、空 body、非 JSON 都可能發生（n8n 工作流執行失敗時
    webhook 會回空 body），一律收斂成 None，由呼叫端決定要對觀眾說什麼。
"""

from tm_twitch_bot.utils.http_utils import get_async_client, LONG_TIMEOUT
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import threading

agent_config = config["tm_ai_agent"]

# 對話記憶的分組鍵前綴。務必保留 ——
# 少了它 Twitch 就會和 Discord 頻道共用同一份記憶。
CHANNEL_ID_PREFIX = "twitch:"


class _SingletonMeta(type):
    _instances: dict[type, "N8nAiAgentClient"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class N8nAiAgentClient(metaclass=_SingletonMeta):
    def __init__(self):
        self.webhook_url = agent_config["webhook_url"]
        # secret 只從 .env 來，只出現在 request header，不進 log
        self._secret = agent_config["webhook_secret"]

    @property
    def is_configured(self) -> bool:
        return bool(self.webhook_url and self._secret)

    @staticmethod
    def build_payload(
        *, text: str, user_name: str, user_id: str, channel_id: str
    ) -> dict:
        """組出 request body。

        **所有欄位都要給**，Twitch 用不到的給空值 —— n8n 端不接受缺欄位。
        """
        return {
            "text": text,
            # user_name 會被 n8n 前綴成「名字：」餵給模型，
            # 同頻道靠它區分不同觀眾並自然稱呼對方，所以要傳 display name
            "user_name": user_name,
            "user_id": user_id,
            "channel_id": channel_id,
            "guild_id": "",  # Discord 專用
            "images": [],  # Discord 專用的圖片分析管線
            "stickers": [],  # Discord 專用的貼圖分析管線
        }

    async def ask(
        self, *, text: str, user_name: str, user_id: str, channel_id: str
    ) -> Optional[str]:
        """成功回傳 reply 文字；任何失敗都回傳 None，細節只進 log。"""
        if not self.is_configured:
            logger.error(
                "TM AI Agent 尚未設定完成（缺 webhook_url 或環境變數 TM_AI_AGENT_SECRET）"
            )
            return None

        payload = self.build_payload(
            text=text, user_name=user_name, user_id=user_id, channel_id=channel_id
        )
        try:
            resp = await get_async_client().post(
                self.webhook_url,
                json=payload,
                headers={
                    "x-webhook-secret": self._secret,
                    "Content-Type": "application/json",
                },
                timeout=LONG_TIMEOUT,
            )
        except Exception as e:
            # 連線層失敗（ngrok 掉了、n8n 沒開、逾時）都走這裡。
            # 刻意不重試：見模組開頭的說明。
            logger.error(f"[N8nAiAgent] 呼叫失敗: {type(e).__name__}: {e}")
            return None

        if not resp.is_success:
            logger.error(f"[N8nAiAgent] HTTP {resp.status_code}：{resp.text[:200]}")
            return None

        if not resp.content:
            # n8n 工作流執行失敗時，webhook 會回 200 但 body 是空的
            logger.error("[N8nAiAgent] 回應 body 為空，n8n 工作流可能執行失敗")
            return None

        try:
            data = resp.json()
        except Exception as e:
            logger.error(f"[N8nAiAgent] 回應不是 JSON（{type(e).__name__}）：{resp.text[:200]}")
            return None

        if not isinstance(data, dict):
            logger.error(f"[N8nAiAgent] 回應格式非預期：{data!r}")
            return None

        reply = data.get("reply")
        if not isinstance(reply, str) or not reply.strip():
            logger.error(f"[N8nAiAgent] 回應缺少可用的 reply：{data!r}")
            return None
        return reply


n8n_ai_agent_client = N8nAiAgentClient()
