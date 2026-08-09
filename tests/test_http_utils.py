"""HTTP 重試策略。

這段程式直接壓在觀眾的等待時間上：舊版對 404 也重試 3 次、每次固定等 5 秒，
等於觀眾要等 15 秒才拿得到一個「查無此人」。這裡鎖定的就是「什麼該重試、
什麼該立刻放棄、等多久」。
"""

import httpx
import pytest

from tm_twitch_bot.utils import http_utils
from tm_twitch_bot.utils.error_utils import StatusCodeError

URL = "http://localhost:9093/mongo/find"


class _SleepRecorder:
    """只替換 http_utils 眼中的 asyncio，不去動全域的 asyncio.sleep。"""

    def __init__(self, slept: list[float]):
        self._slept = slept

    async def sleep(self, seconds: float) -> None:
        self._slept.append(seconds)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    """把退避等待記錄下來而不是真的睡，測試才能秒完。"""
    slept: list[float] = []
    monkeypatch.setattr(http_utils, "asyncio", _SleepRecorder(slept))
    return slept


class _StubClient:
    """request_with_retries 只用到 client.request()。

    刻意不建真的 httpx.AsyncClient——它會初始化 SSL context，
    每個測試多花約 0.25 秒，而這裡完全用不到。
    """

    def __init__(self, results):
        self.results = results
        self.calls: list[str] = []

    async def request(self, method, url, **kwargs):
        self.calls.append(url)
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def responder(monkeypatch):
    """依序回傳指定的結果；元素可以是 httpx.Response 或要拋出的例外。"""

    def _install(*results):
        client = _StubClient(results)
        monkeypatch.setattr(http_utils, "get_async_client", lambda: client)
        return client.calls

    return _install


def resp(status: int, text: str = "") -> httpx.Response:
    return httpx.Response(status_code=status, text=text)


# ===== 成功路徑 =====


async def test_success_returns_immediately(responder):
    calls = responder(resp(200, '{"results": []}'))

    result = await http_utils.request_with_retries("POST", URL)

    assert result.status_code == 200
    assert len(calls) == 1


async def test_non_200_success_codes_are_accepted(responder):
    """舊版只認 200，201 / 204 會被當成失敗而重試。"""
    calls = responder(resp(204))

    result = await http_utils.request_with_retries("POST", URL)

    assert result.status_code == 204
    assert len(calls) == 1


# ===== 不該重試的失敗 =====


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_client_errors_fail_fast(responder, no_real_sleep, status):
    calls = responder(resp(status, "not found"))

    with pytest.raises(StatusCodeError):
        await http_utils.request_with_retries("POST", URL)

    assert len(calls) == 1, "4xx 重試幾次都是同樣結果，不該讓觀眾多等"
    assert no_real_sleep == []


# ===== 該重試的失敗 =====


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_retryable_statuses_are_retried(responder, status):
    calls = responder(resp(status, "boom"))

    with pytest.raises(StatusCodeError):
        await http_utils.request_with_retries("POST", URL)

    assert len(calls) == http_utils.RETRY_ATTEMPTS


async def test_transport_errors_are_retried(responder):
    calls = responder(httpx.ConnectError("連不上"))

    with pytest.raises(StatusCodeError):
        await http_utils.request_with_retries("POST", URL)

    assert len(calls) == http_utils.RETRY_ATTEMPTS


async def test_recovers_when_a_later_attempt_succeeds(responder):
    calls = responder(resp(503), resp(200, "ok"))

    result = await http_utils.request_with_retries("POST", URL)

    assert result.status_code == 200
    assert len(calls) == 2


# ===== 退避與逾時 =====


async def test_backoff_is_exponential_and_bounded(responder, no_real_sleep):
    responder(resp(503))

    with pytest.raises(StatusCodeError):
        await http_utils.request_with_retries("POST", URL)

    # 最後一次失敗後不再等待，所以睡眠次數比嘗試次數少一
    assert len(no_real_sleep) == http_utils.RETRY_ATTEMPTS - 1
    assert no_real_sleep == [0.5, 1.0]
    assert sum(no_real_sleep) < 5, "舊版固定 5 秒 × 3 次，觀眾要等 15 秒"


def test_read_timeout_is_short_enough_for_a_chat_command():
    assert http_utils.READ_TIMEOUT <= 30, "單一微服務卡住不該讓指令懸置十分鐘"
    assert http_utils.LONG_TIMEOUT.read > http_utils.READ_TIMEOUT


# ===== 錯誤訊息 =====


async def test_error_message_is_truncated(responder):
    responder(resp(500, "X" * 5000))

    with pytest.raises(StatusCodeError) as excinfo:
        await http_utils.request_with_retries("POST", URL)

    assert len(str(excinfo.value)) < 500, "整包回應不該灌進例外訊息與 log"
