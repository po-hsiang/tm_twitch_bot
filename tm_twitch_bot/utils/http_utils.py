from tm_twitch_bot.utils.error_utils import StatusCodeError
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import asyncio
import httpx

RETRY_ATTEMPTS = 3  # 嘗試次數 (包含第一次)
BASE_BACKOFF_SECONDS = 0.5  # 指數退避基數：0.5 → 1 → 2 秒
MAX_BACKOFF_SECONDS = 8  # 退避上限，避免指數成長到荒謬的等待

CONNECT_TIMEOUT = 10  # 連線超時時間 (秒)
READ_TIMEOUT = 20  # 一般微服務的讀取超時 (秒)
LONG_READ_TIMEOUT = 120  # GPT 這類本來就慢的呼叫另外拉長

# 只有這些狀態碼值得重試——對方等於明說「現在不行，等等再來」。
# 400 / 401 / 403 / 404 重試幾次都是同樣結果，只會讓觀眾多等好幾秒才拿到錯誤。
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=CONNECT_TIMEOUT
)

# 給呼叫端指定用：本來就預期會跑很久的請求（例如 GPT 產生回覆）
LONG_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT,
    read=LONG_READ_TIMEOUT,
    write=LONG_READ_TIMEOUT,
    pool=CONNECT_TIMEOUT,
)

_client: Optional[httpx.AsyncClient] = None


def get_async_client() -> httpx.AsyncClient:
    """全專案共用一個 AsyncClient（連線池重用），惰性建立。"""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client


async def close_async_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


def _snippet(text: str, limit: int = 200) -> str:
    """把回應內容壓成一行短摘要，避免整包 HTML 灌進 log。"""
    text = (text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else f"{text[:limit]}…"


async def request_with_retries(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json: Optional[dict] = None,
    timeout: Optional[httpx.Timeout] = None,
) -> httpx.Response:
    """非同步請求，只對「等一下可能就會好」的失敗重試。

    這裡的重試策略刻意保守，因為它直接壓在觀眾的等待時間上：
      - 4xx（408 / 425 / 429 除外）代表請求本身有問題，重試沒有意義
      - 退避改為指數（0.5 → 1 秒），最壞情況的等待從原本的 15 秒降到約 1.5 秒
      - 讀取逾時從 600 秒降到 20 秒；單一微服務卡住不該讓一個指令懸置 10 分鐘
        （GPT 這類本來就慢的呼叫請傳入 LONG_TIMEOUT）
    """
    client = get_async_client()
    request_kwargs = {"params": params, "json": json}
    if timeout is not None:
        request_kwargs["timeout"] = timeout

    last_reason = "未知原因"
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = await client.request(method, url, **request_kwargs)
        except httpx.TransportError as e:
            # 連線層失敗（連不上、逾時、連線被切斷）——最值得重試的一類
            last_reason = f"{type(e).__name__}: {e}"
        else:
            if response.is_success:
                return response

            last_reason = f"HTTP {response.status_code}（{_snippet(response.text)}）"
            if response.status_code not in RETRYABLE_STATUS:
                logger.error(f"呼叫 {url} 失敗，不重試：{last_reason}")
                raise StatusCodeError(f"呼叫 {url} 失敗：{last_reason}")

        if attempt < RETRY_ATTEMPTS:
            delay = min(
                BASE_BACKOFF_SECONDS * 2 ** (attempt - 1), MAX_BACKOFF_SECONDS
            )
            logger.warning(
                f"呼叫 {url} 第 {attempt} 次失敗（{last_reason}），{delay} 秒後重試"
            )
            await asyncio.sleep(delay)

    logger.error(f"呼叫 {url} 已重試 {RETRY_ATTEMPTS} 次仍失敗：{last_reason}")
    raise StatusCodeError(
        f"呼叫 {url} 失敗，已嘗試 {RETRY_ATTEMPTS} 次：{last_reason}"
    )
