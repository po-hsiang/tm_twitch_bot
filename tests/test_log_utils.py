"""日誌落檔與著色。

核心風險：ColoredFormatter 過去是「就地」把 ANSI 色碼寫進 record.msg。
只有一個 handler 時看不出問題，一加上檔案 handler，log 檔就會被控制碼汙染——
而汙染程度還取決於 handler 的順序，是那種上線後才會發現的坑。
"""

import logging

import pytest

from tm_twitch_bot.utils import log_utils

ANSI_PREFIX = "\033["


def make_record(level=logging.INFO, msg="測試訊息", args=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )


@pytest.fixture
def colored() -> log_utils.ColoredFormatter:
    return log_utils.ColoredFormatter(log_utils.LOG_FORMAT, datefmt=log_utils.DATE_FORMAT)


@pytest.fixture
def plain() -> logging.Formatter:
    return logging.Formatter(log_utils.LOG_FORMAT, datefmt=log_utils.DATE_FORMAT)


# ===== 著色不得汙染 record 本身 =====


def test_console_output_is_colored(colored):
    output = colored.format(make_record())

    assert log_utils.GREEN in output
    assert output.endswith(log_utils.RESET)


def test_record_is_not_mutated_by_formatting(colored):
    record = make_record()

    colored.format(record)

    assert record.msg == "測試訊息"  # 原始 record 必須毫髮無傷


def test_file_handler_output_stays_clean_after_console_formatting(colored, plain):
    """這就是 P1-9 真正要防的回歸：同一個 record 先給主控台、再給檔案。"""
    record = make_record()

    colored.format(record)
    file_output = plain.format(record)

    assert ANSI_PREFIX not in file_output
    assert "測試訊息" in file_output


def test_repeated_formatting_does_not_stack_colors(colored):
    record = make_record()

    first = colored.format(record)
    second = colored.format(record)

    assert first == second
    assert first.count(log_utils.RESET) == 1


def test_percent_style_args_are_interpolated(colored):
    """main.py 有 logger.error("自動刷新失敗：%s", e) 這種寫法。"""
    record = make_record(level=logging.ERROR, msg="失敗：%s", args=("timeout",))

    output = colored.format(record)

    assert "失敗：timeout" in output
    assert "%s" not in output


def test_unmapped_level_is_not_colored(colored):
    output = colored.format(make_record(level=logging.NOTSET + 5))

    assert ANSI_PREFIX not in output


# ===== 檔案 handler =====


def test_file_handler_is_rotating_and_utf8(tmp_path):
    handler = log_utils.build_file_handler(tmp_path)
    try:
        assert handler.maxBytes > 0
        assert handler.backupCount > 0
        # Windows 預設 cp950，寫繁中或 emoji 會直接 UnicodeEncodeError
        assert handler.encoding == "utf-8"
    finally:
        handler.close()


def test_file_handler_writes_cjk_and_emoji(tmp_path):
    handler = log_utils.build_file_handler(tmp_path)
    try:
        handler.emit(make_record(msg="🎧 忠誠點數 WebSocket 已連線"))
        handler.flush()
        written = (tmp_path / log_utils.LOG_FILE_NAME).read_text(encoding="utf-8")
    finally:
        handler.close()

    assert "🎧 忠誠點數 WebSocket 已連線" in written
    assert ANSI_PREFIX not in written


def test_file_handler_creates_missing_directory(tmp_path):
    target = tmp_path / "不存在" / "logs"
    handler = log_utils.build_file_handler(target)
    handler.close()

    assert target.is_dir()


def test_logger_wires_console_and_file_with_the_right_formatters():
    # 以 formatter 而非 handler 型別來辨識：
    # RotatingFileHandler 本身就是 StreamHandler 的子類，而 pytest 也會塞自己的
    # 擷取用 handler 進來，單純數 StreamHandler 的數量並不可靠。
    handlers = log_utils.logger.handlers
    files = [h for h in handlers if isinstance(h, log_utils.RotatingFileHandler)]
    console = [h for h in handlers if isinstance(h.formatter, log_utils.ColoredFormatter)]

    assert len(files) == 1
    assert len(console) == 1
    assert files[0] not in console  # 顏色絕不能套到檔案上
