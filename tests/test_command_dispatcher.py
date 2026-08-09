"""指令派發器的行為鎖定測試。

這支是整個專案最值得優先覆蓋的模組：所有觀眾輸入都會經過它，
而它的比對邏輯（全形正規化、關鍵字掃描、函式動態載入）改動風險最高。
"""

import logging

import pytest

from tm_twitch_bot.scripts import command_dispatcher as cd
from tm_twitch_bot.scripts.command_dispatcher import dispatch_command
from tm_twitch_bot.utils.error_utils import StatusCodeError

HEADER = ["觸發字", "類型", "內容"]


@pytest.fixture(autouse=True)
def _isolate_dispatcher_state():
    """每個測試都從乾淨的 COMMAND_SET 與函式快取開始。"""
    cd.COMMAND_SET.clear()
    cd._load_function.cache_clear()
    cd._MODULE_CACHE.clear()
    yield
    cd.COMMAND_SET.clear()
    cd._load_function.cache_clear()
    cd._MODULE_CACHE.clear()


@pytest.fixture
def install_commands():
    """把指令列表灌進 COMMAND_SET，避免測試打到 Google Sheets。"""

    def _install(rows: list[list[str]]) -> None:
        cd.COMMAND_SET.update(cd._parse_sheet([HEADER, *rows]))

    return _install


# ===== 基本派發 =====


async def test_empty_input_returns_empty(install_commands):
    install_commands([["!英雄", "text", "英雄榜"]])
    assert await dispatch_command("") == ""


async def test_bang_text_command(install_commands):
    install_commands([["!英雄", "text", "英雄榜"]])
    assert await dispatch_command("!英雄") == "英雄榜"


async def test_unknown_command_returns_empty(install_commands):
    install_commands([["!英雄", "text", "英雄榜"]])
    assert await dispatch_command("!不存在的指令") == ""


async def test_command_matching_is_case_insensitive(install_commands):
    install_commands([["!yt", "text", "歌單"]])
    assert await dispatch_command("!YT") == "歌單"
    assert await dispatch_command("!Yt") == "歌單"


async def test_fullwidth_bang_is_normalized(install_commands):
    """中文輸入法很容易打出全形『！』，必須等同半形。"""
    install_commands([["!英雄", "text", "英雄榜"]])
    assert await dispatch_command("！英雄") == "英雄榜"


# ===== 關鍵字（無驚嘆號）掃描 =====


async def test_keyword_trigger_matches_substring(install_commands):
    install_commands([["帥", "text", "你最帥"]])
    assert await dispatch_command("虎喵今天好帥喔") == "你最帥"


async def test_numeric_trigger_requires_exact_match(install_commands):
    """『0』『87』這類 trigger 必須完全一致才觸發。"""
    install_commands([["0", "text", "零分"]])
    assert await dispatch_command("0") == "零分"
    assert await dispatch_command("這個要 100 元") == ""


async def test_numeric_trigger_does_not_abort_remaining_scan(install_commands):
    """回歸測試：關鍵字掃描過去誤用 break，會中斷整個 COMMAND_SET 走訪。

    只要訊息含有 0 或 87（網址、金額、時間都會命中），且該 trigger 在
    dict 走訪順序中排在前面，後面所有關鍵字指令就再也不會被比對到。
    """
    install_commands(
        [
            ["0", "text", "零分"],  # 先放，讓它在走訪順序中排前面
            ["帥", "text", "你最帥"],
        ]
    )
    assert await dispatch_command("這隻手錶要 30000 元 好帥") == "你最帥"


async def test_bang_command_does_not_fall_through_to_keywords(install_commands):
    """以 ! 開頭但查無此指令時，不應該再退回關鍵字比對。"""
    install_commands([["帥", "text", "你最帥"]])
    assert await dispatch_command("!帥") == ""


# ===== 分詞 =====


async def test_tail_text_is_passed_through(install_commands, monkeypatch):
    async def echo(*args, **kwargs):
        return f"收到:{kwargs.get('raw_tail_text')}"

    monkeypatch.setattr(cd, "echo", echo, raising=False)
    install_commands([["!gpt", "function", "echo"]])
    assert await dispatch_command("!gpt 我帥嗎") == "收到:我帥嗎"


async def test_unpaired_quote_falls_back_to_simple_split(install_commands, monkeypatch):
    """shlex 遇到不成對引號會拋 ValueError，必須退回簡單切割而不是整個炸掉。"""

    async def echo(*args, **kwargs):
        return f"收到:{kwargs.get('raw_tail_text')}"

    monkeypatch.setattr(cd, "echo", echo, raising=False)
    install_commands([["!gpt", "function", "echo"]])
    assert await dispatch_command('!gpt 這句有個 " 單引號') == '收到:這句有個 " 單引號'


# ===== 函式型指令 =====


async def test_async_function_command(install_commands, monkeypatch):
    async def ping(*args, **kwargs):
        return "pong-async"

    monkeypatch.setattr(cd, "ping", ping, raising=False)
    install_commands([["!ping", "function", "ping"]])
    assert await dispatch_command("!ping") == "pong-async"


async def test_sync_function_command(install_commands, monkeypatch):
    """指令函式已全面 async 化，但同步函式仍須相容（例如遊戲類的 start/guess）。"""

    def ping(*args, **kwargs):
        return "pong-sync"

    monkeypatch.setattr(cd, "ping", ping, raising=False)
    install_commands([["!ping", "function", "ping"]])
    assert await dispatch_command("!ping") == "pong-sync"


async def test_missing_function_replies_generically_and_logs_detail(
    install_commands, caplog
):
    """Sheets 設定打錯時，觀眾看到制式訊息，模組路徑只進 log。"""
    install_commands([["!nope", "function", "根本沒有這個函式"]])

    with caplog.at_level(logging.ERROR):
        result = await dispatch_command("!nope")

    assert result == cd.GENERIC_ERROR_REPLY
    assert "找不到函數" in caplog.text  # 設定錯誤的細節仍查得到


async def test_function_exception_is_contained(install_commands, monkeypatch, caplog):
    """指令函式拋例外時不能讓整個訊息處理中斷。"""

    async def boom(*args, **kwargs):
        raise RuntimeError("內部爆炸")

    monkeypatch.setattr(cd, "boom", boom, raising=False)
    install_commands([["!boom", "function", "boom"]])

    with caplog.at_level(logging.ERROR):
        result = await dispatch_command("!boom")

    assert result == cd.GENERIC_ERROR_REPLY
    assert "內部爆炸" in caplog.text


async def test_internal_details_never_reach_the_chat(install_commands, monkeypatch):
    """P1-11 的核心：微服務網址、模組路徑、例外型別都不該出現在回覆裡。

    StatusCodeError 的訊息長這樣——
    「呼叫 http://localhost:9093/mongo/find 失敗」，內部拓樸就這樣公開了。
    """

    async def leaky(*args, **kwargs):
        raise StatusCodeError("呼叫 http://localhost:9093/mongo/find 失敗：HTTP 500")

    monkeypatch.setattr(cd, "leaky", leaky, raising=False)
    install_commands([["!leak", "function", "leaky"]])

    result = await dispatch_command("!leak")

    for secret in ("localhost", "9093", "http", "StatusCodeError", "mongo"):
        assert secret not in result


# ===== 指令集沒載入成功時（P1-37 的降級路徑）=====


async def test_missing_command_set_returns_quietly_without_reloading(monkeypatch):
    """Google Sheets 微服務沒開時，派發只能安靜跳過。

    這裡刻意「不」補載入：重試是 main.py 排程的工作。
    壓在每一則訊息上的話，服務沒開時每則都要耗掉一輪重試與退避。
    """
    attempts: list[str] = []

    async def _should_not_be_called():
        attempts.append("load")

    monkeypatch.setattr(cd, "load_command_set", _should_not_be_called)

    assert await dispatch_command("!英雄") == ""
    assert attempts == []


async def test_missing_command_set_is_logged(caplog):
    with caplog.at_level(logging.WARNING):
        await dispatch_command("!英雄")

    assert "指令集尚未載入" in caplog.text


# ===== 設定檔解析 =====


def test_parse_sheet_skips_header_and_incomplete_rows():
    rows = [
        HEADER,
        ["!英雄", "text", "英雄榜"],
        ["!壞掉", "text"],  # 欄位不足，應被忽略
        ["  !空白  ", " text ", " 有空白 "],  # 前後空白應被 strip
    ]
    parsed = cd._parse_sheet(rows)
    assert parsed == {
        "!英雄": ("text", "英雄榜"),
        "!空白": ("text", "有空白"),
    }
