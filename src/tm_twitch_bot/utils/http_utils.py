from requests.exceptions import ConnectTimeout, ReadTimeout, RequestException
from tm_twitch_bot.utils.error_utils import StatusCodeError
from tm_twitch_bot.utils.log_utils import logger
import time

RETRY_ATTEMPTS = 3  # 嘗試次數 (包含第一次)
SLEEP_SECONDS = 5  # 重試間隔時間 (秒)
CONNECT_TIMEOUT = 10  # 連線超時時間 (秒)
READ_TIMEOUT = 600  # 讀取超時時間 (秒)


def request_with_retries(request_func, *args, **kwargs):
    attempts = 0
    while attempts < RETRY_ATTEMPTS:
        try:
            response = request_func(
                *args, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), **kwargs
            )
            if response.status_code == 200:
                return response
            else:
                debug_msg = f"狀態碼異常: {response.status_code}\nResponse 訊息為: {response.text}"
                attempts = handle_error(attempts, debug_msg)
        except (ConnectTimeout, ReadTimeout, RequestException) as e:
            error_type = type(e).__name__
            debug_msg = f"{error_type} 異常\n錯誤訊息: {e}"
            attempts = handle_error(attempts, debug_msg)
    raise StatusCodeError(f"打 API 給 {args[0]} 失敗，已嘗試了 {RETRY_ATTEMPTS} 次！")


def handle_error(attempts, debug_msg):
    attempts += 1
    logger.warning(f"第 {attempts} 次 Request {debug_msg}")
    time.sleep(SLEEP_SECONDS)
    return attempts
