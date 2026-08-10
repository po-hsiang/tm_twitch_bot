from tm_twitch_bot.utils.log_utils import logger
from dotenv import load_dotenv
from pathlib import Path
import yaml
import os

CONFIG_COMMON_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "config_common.yaml"
)
# 專案根目錄的 .env（utils -> tm_twitch_bot -> src -> 專案根目錄）
ENV_PATH = Path(__file__).resolve().parents[3] / ".env"

load_dotenv(ENV_PATH)


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"缺少環境變數 {key}，請確認專案根目錄的 .env（可參考 .env.example）")
    return value


def load_yaml() -> dict:
    with CONFIG_COMMON_PATH.open("r", encoding="utf-8") as file:
        merged_config = yaml.safe_load(file)

    # 機敏資訊一律來自 .env，載入後合併進 config，讓既有取用方式（config["twitch"]["access_token"]）不變
    merged_config["twitch"]["client_id"] = _require_env("TWITCH_CLIENT_ID")
    merged_config["twitch"]["client_secret"] = _require_env("TWITCH_CLIENT_SECRET")
    merged_config["twitch"]["access_token"] = _require_env("TWITCH_ACCESS_TOKEN")
    merged_config["twitch"]["refresh_token"] = _require_env("TWITCH_REFRESH_TOKEN")
    merged_config["openai"]["api_key"] = _require_env("OPENAI_API_KEY")

    # n8n AI Agent 的 webhook secret 刻意「不」用 _require_env：
    # 少了它只會讓 AI 問答指令失效，不該讓整個 Bot 起不來（同 P1-37 的取捨）。
    merged_config["tm_ai_agent"]["webhook_secret"] = os.getenv("TM_AI_AGENT_SECRET", "")
    if not merged_config["tm_ai_agent"]["webhook_secret"]:
        logger.warning("缺少環境變數 TM_AI_AGENT_SECRET，AI 問答指令將無法使用")
    return merged_config


config = load_yaml()


if __name__ == "__main__":
    masked = {k: v for k, v in config.items()}
    print(f"\nconfig 載入成功，twitch keys: {list(config['twitch'].keys())}")
