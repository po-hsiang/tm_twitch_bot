"""測試共用設定。

重點：這個模組會在任何 tm_twitch_bot 模組被 import 之前先跑，
在此塞入假的環境變數，讓測試永遠不會讀到真正的 .env 機敏值，
CI 上沒有 .env 也能直接跑。

（python-dotenv 的 load_dotenv 預設 override=False，
  所以本地即使有 .env，也不會蓋掉這裡先設好的假值。）
"""

import os
import tempfile

# log_utils 在 import 當下就會建立 logs/ 目錄，測試不該在專案裡留下檔案。
# 指向系統暫存目錄的固定位置（不用亂數，才不會每跑一次就多一個資料夾）。
os.environ.setdefault(
    "TM_BOT_LOG_DIR", os.path.join(tempfile.gettempdir(), "tm_twitch_bot_test_logs")
)

for _key, _value in {
    "TWITCH_CLIENT_ID": "test-client-id",
    "TWITCH_CLIENT_SECRET": "test-client-secret",
    "TWITCH_ACCESS_TOKEN": "test-access-token",
    "TWITCH_REFRESH_TOKEN": "test-refresh-token",
    "OPENAI_API_KEY": "test-openai-key",
}.items():
    os.environ.setdefault(_key, _value)


import pytest  # noqa: E402  （必須在環境變數設定之後）


@pytest.fixture
def collect_sends():
    """回傳 (async send_func, 已送出訊息 list)，用來取代 message.channel.send。"""
    sent: list[str] = []

    async def _send(content: str) -> None:
        sent.append(content)

    return _send, sent


@pytest.fixture
def sheet_stub():
    """產生一個假的 get_sheet_data，並記錄被呼叫次數（驗證快取用）。"""

    def _make(data_by_sheet: dict[str, list[list[str]]]):
        calls: list[str] = []

        async def _get_sheet_data(sheet_name: str):
            calls.append(sheet_name)
            return data_by_sheet[sheet_name]

        return _get_sheet_data, calls

    return _make
