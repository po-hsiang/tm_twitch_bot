"""專案內的固定路徑，集中在這一處。

`log_utils` 與設定載入器過去各自寫 `Path(__file__).resolve().parents[3]` 去猜
專案根目錄。那個 `3` 是「utils → tm_twitch_bot → src → 專案根」數出來的，
所以拿掉 `src/` 這一層時兩處會一起錯，**而且錯得很安靜**——
log 檔會寫到別的地方、`.env` 會找不到，程式不會拋任何例外。

集中之後，日後再搬目錄只要改這一個檔案。
這個模組刻意不 import 專案內任何東西，任何模組都可以安全地 import 它。
"""

from pathlib import Path

# tm_twitch_bot/ 套件本身
PACKAGE_ROOT = Path(__file__).resolve().parent

# 專案根目錄：.env、logs/、pyproject.toml 所在之處
PROJECT_ROOT = PACKAGE_ROOT.parent

ENV_PATH = PROJECT_ROOT / ".env"
LOG_DIR = PROJECT_ROOT / "logs"
CONFIG_COMMON_PATH = PACKAGE_ROOT / "config" / "config_common.yaml"
