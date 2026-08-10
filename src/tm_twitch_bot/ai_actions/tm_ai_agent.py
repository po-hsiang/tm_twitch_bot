"""指令入口：把觀眾的提問轉送到 n8n「TM AI Agent」，回覆貼回 Twitch 聊天室。

人設（虎喵小粉絲）、對話記憶（同 channel_id 共享最近 10 輪）與工具呼叫
（台灣熱搜／網路搜尋／維基／計算機／統計圖表／虎喵歌單）全都在 n8n 端，
這裡完全不管 prompt 也不存歷史。只負責三件事：

  1. 把 Twitch 的欄位湊齊送出（見 svc_client/n8n_ai_agent.py）
  2. 同一頻道排隊送，避免共享記憶交錯
  3. 把為 Discord 設計的回覆洗成 Twitch IRC 貼得出去的樣子

原本的 OpenAI 微服務路徑（ai_actions/gpt_chat_session.py）刻意保留不動，
兩條路可以並存，要切換只需要改 Google Sheets 指令集的「內容」欄。
"""

from tm_twitch_bot.svc_client.n8n_ai_agent import (
    n8n_ai_agent_client,
    CHANNEL_ID_PREFIX,
)
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
import asyncio
import re

DEFAULT_CHANNEL = config["twitch"]["channel"]

# Twitch 單則上限 500 字元，扣掉 message_controller 會加的「@顯示名稱 」前綴。
# n8n 端的回覆本來就控制在約 250 個中文字，這是保險而不是常態。
MAX_REPLY_LENGTH = 450
TRUNCATE_SUFFIX = "…"
LINE_SEPARATOR = " / "

# 同一頻道最多讓幾則排隊。再多就直接請他等一下 ——
# 每則最壞要等 120 秒，讓隊伍無上限成長只會讓所有人都等到懷疑人生。
MAX_WAITING_PER_CHANNEL = 2

NO_QUESTION_REPLY = "請於空格後加上您想問的話喔 tigerm24Love"
FAILURE_REPLY = "嗚嗚我剛剛恍神了一下，等等再問我一次好不好 tigerm24Cry"
BUSY_REPLY = "我還在想上一個問題，等我一下喔 tigerm24Love"


# ===== 回覆清洗 =====
#
# Twitch IRC 不渲染 markdown、不支援換行、單則上限 500 字元，
# 而 n8n 那條工作流的回覆是為 Discord 設計的。

_CODE_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n?")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
# 星號與波浪號：兩側都要緊貼非空白才算語法，所以「12 * 34」不會被誤吃
_STAR_EMPHASIS = re.compile(r"(\*{1,3}|~~)(?=\S)(.+?)(?<=\S)\1", re.S)
# 底線要多一層字元邊界限制，否則 snake_case_name 會被當成斜體而黏成一團
_UNDERSCORE_EMPHASIS = re.compile(r"(?<!\w)(_{1,3})(?=\S)(.+?)(?<=\S)\1(?!\w)", re.S)
# 引言的 >、標題的 #、以及會被 Twitch 原樣顯示的項目符號
_LINE_PREFIX = re.compile(r"^[ \t]*(?:>+|#{1,6}|[*•](?=[ \t]))[ \t]*", re.M)
_URL = re.compile(r"https?://\S+")
_SPACES = re.compile(r"[ \t　]+")

_URL_SLOT = "\x00{}\x00"


def clean_reply(reply: str) -> str:
    """把 Discord 風格的回覆洗成 Twitch 貼得出去的單行純文字。

    Emoji 刻意保留 —— 那是人設的一部分。
    網址也一定要留住原樣：AI 畫統計圖時會回 quickchart 的圖片網址，
    而那種網址又長又常含 `_`，直接洗 markdown 會把它吃掉，
    所以先把網址抽走、洗完再放回去。
    """
    text = _CODE_FENCE.sub("", reply)
    text = text.replace("`", "")
    text = _MD_LINK.sub(r"\1 \2", text)  # [文字](網址) → 文字 網址

    urls: list[str] = []

    def _stash(match: re.Match) -> str:
        urls.append(match.group(0))
        return _URL_SLOT.format(len(urls) - 1)

    text = _URL.sub(_stash, text)

    text = _LINE_PREFIX.sub("", text)
    for _ in range(3):  # 巢狀的 **_粗斜體_** 要一層一層剝
        text, star_hits = _STAR_EMPHASIS.subn(r"\2", text)
        text, underscore_hits = _UNDERSCORE_EMPHASIS.subn(r"\2", text)
        if not star_hits and not underscore_hits:
            break

    # 換行改成 /，連續空行只算一個分隔；其餘連續空白壓成一個空格
    lines = [line.strip() for line in text.splitlines()]
    text = LINE_SEPARATOR.join(line for line in lines if line)
    text = _SPACES.sub(" ", text).strip()

    for index, url in enumerate(urls):
        text = text.replace(_URL_SLOT.format(index), url)

    if len(text) > MAX_REPLY_LENGTH:
        text = text[: MAX_REPLY_LENGTH - len(TRUNCATE_SUFFIX)] + TRUNCATE_SUFFIX
    return text


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

    cleaned = clean_reply(reply)
    if not cleaned:
        logger.error(f"[TM AI Agent] 回覆清洗後變成空字串，原文：{reply!r}")
        return FAILURE_REPLY
    logger.info(f"[TM AI Agent] 回覆：{cleaned}")
    return cleaned


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
