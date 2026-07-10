from tm_twitch_bot.utils.error_utils import StatusCodeError
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import asyncio
import httpx

RETRY_ATTEMPTS = 3  # 嘗試次數 (包含第一次)
SLEEP_SECONDS = 5  # 重試間隔時間 (秒)
CONNECT_TIMEOUT = 10  # 連線超時時間 (秒)
READ_TIMEOUT = 600  # 讀取超時時間 (秒)

_TIMEOUT = httpx.Timeout(
    connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=READ_TIMEOUT, pool=CONNECT_TIMEOUT
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


async def request_with_retries(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json: Optional[dict] = None,
) -> httpx.Response:
    """非同步請求，狀態碼非 200 或連線異常時重試；重試等待不會阻塞事件圈。"""
    client = get_async_client()
    attempts = 0
    while attempts < RETRY_ATTEMPTS:
        try:
            response = await client.request(method, url, params=params, json=json)
            if response.status_code == 200:
                return response
            debug_msg = (
                f"狀態碼異常: {response.status_code}\nResponse 訊息為: {response.text}"
            )
            attempts = await handle_error(attempts, debug_msg)
        except httpx.HTTPError as e:
            error_type = type(e).__name__
            debug_msg = f"{error_type} 異常\n錯誤訊息: {e}"
            attempts = await handle_error(attempts, debug_msg)
    raise StatusCodeError(f"打 API 給 {url} 失敗，已嘗試了 {RETRY_ATTEMPTS} 次！")


async def handle_error(attempts: int, debug_msg: str) -> int:
    attempts += 1
    logger.warning(f"第 {attempts} 次 Request {debug_msg}")
    await asyncio.sleep(SLEEP_SECONDS)
    return attempts
