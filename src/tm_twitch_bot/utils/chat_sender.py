"""統一的發話出口：長度截斷 + 速率保護。

Twitch 對一般帳號的限制是「30 秒 20 則」，超過會被伺服器靜音約 30 分鐘——
這是少數「錯一次整場開台都毀了」的地方，所以參數刻意抓得比官方上限保守。
一次尖峰就足以踩到：多人同時升級（每次升級 1～2 則）＋ 打招呼 ＋ 指令回覆。

單則訊息另有 500 字元上限，超過時 Twitch 是「整則丟掉」而不是截斷，
所以寧可自己先截，至少觀眾看得到前半段。

為什麼是「呼叫端等待」而不是背景佇列：
  - 送出時機與呼叫端一致，訊息順序與測試行為都好預測
  - 不必多養一個背景 task，也就少一個要 graceful shutdown 的東西
塞車時的保護改靠 MAX_WAITING —— 等待中的訊息過多就直接丟棄並記錄，
避免一堆 handle_message 全卡在這裡等好幾十秒。
"""

from tm_twitch_bot.utils.log_utils import logger
from typing import Awaitable, Callable, Optional
from collections import deque
from functools import partial
from time import monotonic
import asyncio

SendFunc = Callable[[str], Awaitable[None]]

MAX_MESSAGE_LENGTH = 500  # Twitch 單則訊息上限
TRUNCATE_SUFFIX = "…"
RATE_LIMIT = 18  # 官方上限 20，留 2 則餘裕給手動發言或 twitchio 內部訊息
WINDOW_SECONDS = 30.0
MAX_WAITING = 20  # 同時排隊等發話的訊息上限，超過就直接丟棄


def truncate(content: str) -> str:
    """超過 500 字元就截斷，並留下省略號讓觀眾知道還有後續。"""
    if len(content) <= MAX_MESSAGE_LENGTH:
        return content
    return content[: MAX_MESSAGE_LENGTH - len(TRUNCATE_SUFFIX)] + TRUNCATE_SUFFIX


class ChatSender:

    def __init__(
        self,
        *,
        rate_limit: int = RATE_LIMIT,
        window_seconds: float = WINDOW_SECONDS,
        max_waiting: int = MAX_WAITING,
        sleep: Optional[Callable[[float], Awaitable[None]]] = None,
        now: Optional[Callable[[], float]] = None,
    ):
        self._rate_limit = rate_limit
        self._window = window_seconds
        self._max_waiting = max_waiting
        # sleep / now 可注入，測試才不用真的等 30 秒
        self._sleep = sleep or asyncio.sleep
        self._now = now or monotonic
        self._sent_at: deque[float] = deque()  # 視窗內每則訊息的送出時間
        self._lock: Optional[asyncio.Lock] = None
        self._waiting = 0
        self.dropped = 0

    # ---------- 對外 ----------

    async def send(self, send_func: SendFunc, content: str) -> bool:
        """送出一則訊息，回傳是否真的送出（被丟棄時為 False）。

        send_func 由呼叫端提供（`channel.send`），不在這裡綁定：
        重連後 Channel 物件會換新，抓著舊物件會靜默失效。
        """
        if not content:
            return False

        if self._waiting >= self._max_waiting:
            # 已經塞到這種程度，再排進去只會讓每個人等更久，還不如直接放棄這一則
            self.dropped += 1
            logger.error(
                f"發話嚴重塞車（{self._waiting} 則等待中），本則直接丟棄："
                f"{content[:80]}"
            )
            return False

        content = truncate(content)
        self._waiting += 1
        try:
            # 上鎖是為了「一次只有一則在等額度」，順帶保證送出順序與呼叫順序一致
            async with self._serializer():
                await self._wait_for_slot()
                await send_func(content)
        finally:
            self._waiting -= 1
        return True

    def bind(self, send_func: SendFunc) -> SendFunc:
        """包成「只吃內容」的形式，方便往下層（role_system、遊戲）傳遞。"""
        return partial(self.send, send_func)

    def reset(self) -> None:
        """清空速率視窗與內部狀態。測試之間必須呼叫，正式環境不會用到。"""
        self._sent_at.clear()
        self._waiting = 0
        self.dropped = 0
        self._lock = None

    # ---------- 內部 ----------

    def _serializer(self) -> asyncio.Lock:
        """延後到第一次使用才建立 Lock。

        asyncio.Lock 會在第一次 acquire 時記住當下的事件圈，
        模組載入時就建好的話，換一個事件圈（例如每個測試各一個）就會炸。
        """
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _wait_for_slot(self) -> None:
        """等到速率視窗內有空位為止，取得空位後把這次的時間記進去。"""
        while True:
            now = self._now()
            while self._sent_at and now - self._sent_at[0] >= self._window:
                self._sent_at.popleft()

            if len(self._sent_at) < self._rate_limit:
                self._sent_at.append(now)
                return

            wait = self._window - (now - self._sent_at[0])
            logger.warning(
                f"已達自訂發話上限（{self._window:.0f} 秒 {self._rate_limit} 則），"
                f"延後 {wait:.1f} 秒再送"
            )
            await self._sleep(wait)


# 全專案共用一個，速率視窗才會是全域的——分開算等於沒有限制
chat_sender = ChatSender()
