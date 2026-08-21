from tm_twitch_bot import paths
from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging
import copy
import os

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
PURPLE = "\033[95m"
CYAN = "\033[96m"
RESET = "\033[0m"

LOG_COLORS_MAPPING = {
    logging.CRITICAL: PURPLE,
    logging.ERROR: RED,
    logging.WARNING: YELLOW,
    logging.INFO: GREEN,
    logging.DEBUG: CYAN,
}

LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 專案根目錄：src/tm_twitch_bot/utils/log_utils.py → 往上四層
# 專案根目錄由 paths 統一提供：這裡原本自己數 parents[3]（utils → tm_twitch_bot
# → src → 專案根），拿掉 src/ 那層時會安靜地把 log 寫到別的地方（見 paths.py）
DEFAULT_LOG_DIR = Path(os.getenv("TM_BOT_LOG_DIR") or paths.LOG_DIR)
LOG_FILE_NAME = "tm_twitch_bot.log"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5  # 連同當前檔案，最多留 30 MB


class ColoredFormatter(logging.Formatter):
    """主控台專用：把訊息本體套上 ANSI 顏色。

    注意：同一個 LogRecord 物件會依序交給每一個 handler，
    所以絕對不能就地改 `record.msg`——後面的檔案 handler 拿到的就是被
    汙染過的訊息，log 檔會塞滿 `\\033[92m` 這類控制碼。這裡改為對副本上色。
    """

    def format(self, record: logging.LogRecord) -> str:
        color = LOG_COLORS_MAPPING.get(record.levelno)
        if not color:
            return super().format(record)

        colored = copy.copy(record)
        # getMessage() 已經把 args 帶入，因此副本要清掉 args，避免再格式化一次
        colored.msg = f"{color}{record.getMessage()}{RESET}"
        colored.args = None
        return super().format(colored)


def build_console_handler() -> logging.StreamHandler:
    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    return handler


def build_file_handler(log_dir: Path = None) -> RotatingFileHandler:
    """輪替式檔案 handler，讓「半夜掛掉、隔天沒線索」不再發生。

    encoding 一定要寫死 utf-8：Windows 的預設編碼是 cp950，
    而本專案的 log 大量使用繁體中文與 emoji（🎧 🔄 ⚠️），
    不指定會在寫入當下拋 UnicodeEncodeError。

    刻意用純 Formatter 而非 ColoredFormatter——顏色只對終端機有意義。
    """
    log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / LOG_FILE_NAME,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    return handler


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# 不往 root 傳遞：任何第三方套件呼叫 basicConfig() 都不該讓我們的 log 變兩份
logger.propagate = False

if not logger.handlers:  # 模組若被重複載入，不要疊加 handler
    logger.addHandler(build_console_handler())
    try:
        logger.addHandler(build_file_handler())
    except OSError as e:
        # 落檔失敗（唯讀目錄、權限不足…）不該讓整個 Bot 起不來，主控台仍有輸出
        logger.warning(f"無法建立 log 檔（{e}），本次只輸出到主控台")


if __name__ == "__main__":
    logger.critical("這是一個致命錯誤訊息")
    logger.error("這是一個錯誤訊息")
    logger.warning("這是一個警告訊息")
    logger.info("這是一個資訊訊息")
    logger.debug("這是一個除錯訊息")
    logger.info(f"log 檔位置：{DEFAULT_LOG_DIR / LOG_FILE_NAME}")
