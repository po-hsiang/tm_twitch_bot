"""指令入口：把觀眾的提問轉送到 n8n「TM AI Agent」，回覆貼回 Twitch 聊天室。

人設（虎喵小粉絲）、對話記憶（同 channel_id 共享最近 10 輪）與工具呼叫
（台灣熱搜／網路搜尋／維基／計算機／統計圖表／虎喵歌單）全都在 n8n 端，
這裡完全不管 prompt 也不存歷史。只負責兩件事：

  1. 把 Twitch 的欄位湊齊送出（見 clients/n8n_ai_agent.py）
  2. 同一頻道排隊送，避免共享記憶交錯

回覆不做任何後處理。n8n 端會偵測 channel_id 的 twitch: 前綴，
保證回純文字單行；而換行與長度這兩道 Twitch 協定防線本來就該由
唯一的出站瓶頸 chat/sender.py 負責，每個指令各做一份只會漏。

這是**唯一**的 AI 問答路徑。原本並存的 OpenAI 微服務路徑
（gpt_chat_session.py）已在觀察一段時間後移除——
n8n 端提供上下文記憶與工具呼叫，也不必為了換模型維護不同廠商的微服務。
clients/openai.py 只剩 !pk 還在用（它需要結構化輸出）。
"""

from tm_twitch_bot.clients.n8n_ai_agent import (
    n8n_ai_agent_client,
    CHANNEL_ID_PREFIX,
)
from tm_twitch_bot.config.loader import config
from tm_twitch_bot.utils.log_utils import logger
import asyncio

DEFAULT_CHANNEL = config["twitch"]["channel"]

# 同一頻道最多讓幾則排隊。再多就直接請他等一下 ——
# 每則最壞要等 120 秒，讓隊伍無上限成長只會讓所有人都等到懷疑人生。
MAX_WAITING_PER_CHANNEL = 2

NO_QUESTION_REPLY = "請於空格後加上您想問的話喔 tigerm24Love"
FAILURE_REPLY = "嗚嗚我剛剛恍神了一下，等等再問我一次好不好 tigerm24Cry"
BUSY_REPLY = "我還在想上一個問題，等我一下喔 tigerm24Love"


# ===== 同頻道排隊 =====

_locks: dict[str, asyncio.Lock] = {}
_waiting: dict[str, int] = {}


def _lock_for(channel_id: str) -> asyncio.Lock:
    """每個 channel_id 一把鎖，延後到第一次使用才建立。

    asyncio.Lock 會在第一次 acquire 時記住當下的事件圈，
    模組載入時就建好的話，換一個事件圈就會炸（測試每個 case 各一個）。
    """
    lock = _locks.get(channel_id)
    if lock is None:
        lock = _locks[channel_id] = asyncio.Lock()
    return lock


def reset() -> None:
    """清空排隊狀態。測試之間必須呼叫，正式環境不會用到。"""
    _locks.clear()
    _waiting.clear()


async def _ask_serialized(
    channel_id: str, text: str, user_name: str, user_id: str
) -> str:
    """同一頻道一次只送一則。

    n8n 端同一個 channel_id 共享最近 10 輪對話記憶，並行送出會讓記憶交錯，
    AI 就會把兩個人的話搞混、稱呼錯人。不同頻道各有各的鎖，可以並行。
    """
    if _waiting.get(channel_id, 0) >= MAX_WAITING_PER_CHANNEL:
        logger.warning(
            f"[TM AI Agent] {channel_id} 排隊已滿，請 {user_name} 稍後再問"
        )
        return BUSY_REPLY

    _waiting[channel_id] = _waiting.get(channel_id, 0) + 1
    try:
        async with _lock_for(channel_id):
            logger.info(
                f"[TM AI Agent] 送出 {user_name}（{user_id}）於 {channel_id} 的提問：{text}"
            )
            reply = await n8n_ai_agent_client.ask(
                text=text,
                user_name=user_name,
                user_id=user_id,
                channel_id=channel_id,
            )
    finally:
        _waiting[channel_id] -= 1

    if not reply:
        # 失敗細節只進 log。錯誤訊息會夾帶 ngrok 網址等內部資訊，
        # 不能進公開聊天室（同 CODE_REVIEW P1-11 的原則）。
        return FAILURE_REPLY

    logger.info(f"[TM AI Agent] 回覆：{reply}")
    return reply


# ===== 指令集入口 =====


async def ask(*args, **kwargs) -> str:
    """Google Sheets 指令集的「內容」欄指到這個函式即可。

    空訊息先在這裡擋掉：n8n 端雖然收得下，但只會回一句
    「訊息沒有文字內容」，白跑一趟還佔用對話記憶。
    """
    text = (kwargs.get("raw_tail_text") or "").strip()
    if not text:
        return NO_QUESTION_REPLY

    message = kwargs.get("message")
    author = getattr(message, "author", None)
    channel = getattr(message, "channel", None)

    # channel_id 是對話記憶的分組鍵，twitch: 前綴讓它和 Discord 的記憶分開
    channel_name = getattr(channel, "name", None) or DEFAULT_CHANNEL
    channel_id = f"{CHANNEL_ID_PREFIX}{channel_name}"

    return await _ask_serialized(
        channel_id=channel_id,
        text=text,
        user_name=getattr(author, "display_name", "") or "",
        user_id=getattr(author, "id", "") or "",
    )
