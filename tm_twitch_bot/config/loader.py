from tm_twitch_bot.utils.log_utils import logger
from tm_twitch_bot import paths
from dotenv import load_dotenv
import yaml
import os

# 兩個路徑都由 paths 統一提供（原本各自用 __file__ 數上層目錄，見 paths.py）
CONFIG_COMMON_PATH = paths.CONFIG_COMMON_PATH
ENV_PATH = paths.ENV_PATH

load_dotenv(ENV_PATH)


# ===== config_common.yaml 的形狀 =====
#
# CODE_REVIEW P2-22：config 過去完全沒有驗證。最實際的後果在 vip_system：
# `c.get("enabled")` ——key 打錯就是 None，`if not self.cfg.enabled` 讓整個
# VIP 功能靜默停用，沒有任何警告，只能等有人在聊天室回報。
#
# 刻意**不**導入 pydantic-settings（review 的原建議）：那要把全專案四十幾處
# `config["x"]["y"]` 改成型別化物件，而那些取用點多半只在開台時才真正執行到，
# 測試不一定攔得住改壞的地方。以「穩定 > 好維護 > 好擴充」來看，
# 「啟動時一次驗完、缺什麼就直接不啟動」已經拿到這一項要的東西。
#
# 這份 schema 只管 YAML；機敏值的必填規則在下面的 _require_env。
_SCHEMA: tuple[tuple[str, type], ...] = (
    ("is_test", bool),
    ("tigermeowtw_id", str),
    ("admin_user_id", list),
    ("bot_user_id", list),
    ("rpg_parameter.default_gained_exp", int),
    ("rpg_parameter.default_gainer_gold", int),
    ("rpg_parameter.exp_req_multiple", int),
    ("twitch.channel", str),
    ("twitch.redirect_uri", str),
    ("google_sheets.svc_url", str),
    ("google_sheets.sheet_url", str),
    ("openai.svc_url", str),
    ("openai.model", str),
    ("mongodb_atlas.svc_url", str),
    ("youtube.svc_url", str),
    ("youtube.tm_playlist_id", str),
    ("tm_ai_agent.webhook_url", str),
    ("vip_system.enabled", bool),
    ("vip_system.gold_cost", int),
    ("vip_system.vip_cap", int),
    ("vip_system.days_per_redeem", int),
)


def _lookup(cfg, path: str) -> tuple[bool, object]:
    """依 `a.b.c` 取值，回傳 (有沒有這條路徑, 值)。"""
    node = cfg
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def _leaf_paths(node, prefix: str = "") -> list[str]:
    """把巢狀 dict 攤成 `a.b.c` 清單。list 與純值都算葉節點。"""
    if not isinstance(node, dict):
        return [prefix]
    paths: list[str] = []
    for key, value in node.items():
        paths.extend(_leaf_paths(value, f"{prefix}.{key}" if prefix else key))
    return paths


def validate_config(cfg: dict) -> list[str]:
    """回傳所有問題的描述；空 list 代表通過。

    刻意一次列完所有問題，而不是遇到第一個就拋——啟動失敗的重試成本很高
    （改一個值、重跑 bootstrap、重連聊天室），一次看完才能一次改完。
    """
    problems: list[str] = []
    for path, expected in _SCHEMA:
        found, value = _lookup(cfg, path)
        if not found:
            problems.append(f"缺少 {path}")
            continue
        # bool 是 int 的子類別，isinstance(True, int) 會過。
        # 但 gold_cost: true 顯然是設定錯了，不能放過。
        if expected is int and isinstance(value, bool):
            problems.append(f"{path} 應該是 int，實際是 bool（{value!r}）")
            continue
        if not isinstance(value, expected):
            problems.append(
                f"{path} 應該是 {expected.__name__}，"
                f"實際是 {type(value).__name__}（{value!r}）"
            )
            continue
        # 有 key 但值是空的，跟沒有 key 一樣壞：空的 svc_url 只會讓
        # 每次呼叫都失敗，空的 admin_user_id 會讓管理員指令全數失效
        if expected in (str, list) and not value:
            problems.append(f"{path} 不能是空的")
    return problems


def unknown_config_keys(cfg: dict) -> list[str]:
    """YAML 裡有、但 schema 沒宣告的欄位。

    **要在合併 .env 之前呼叫。** 合併之後的 config 會多出六個機敏 key
    （client_id、client_secret、access_token、refresh_token、api_key、
    webhook_secret），那些刻意不在 schema 裡，事後呼叫會把它們全當成
    「未宣告」報出來。

    只記 warning、不擋啟動：多一個沒宣告的 key 不會讓任何功能壞掉，
    為它讓整場開台沒有機器人不成比例（同 P1-37 的取捨）。
    真正該擋住這種漂移的地方是 CI —— tests/test_config_loading.py
    會因為 schema 沒跟上而失敗，那時人還坐在電腦前。
    """
    declared = {path for path, _ in _SCHEMA}
    return sorted(path for path in _leaf_paths(cfg) if path not in declared)


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"缺少環境變數 {key}，請確認專案根目錄的 .env（可參考 .env.example）")
    return value


def load_yaml() -> dict:
    with CONFIG_COMMON_PATH.open("r", encoding="utf-8") as file:
        merged_config = yaml.safe_load(file)

    # 先驗 YAML 的形狀，再合併 .env 的機敏值。順序刻意是這樣：
    # schema 只描述 YAML，混進 env 之後就分不清「缺 key」是設定檔漏了
    # 還是 .env 漏了，而那兩件事的處理方式完全不同。
    problems = validate_config(merged_config)
    if problems:
        bullets = "\n  - ".join(problems)
        raise RuntimeError(f"config_common.yaml 設定有問題，請修正後再啟動：\n  - {bullets}")
    unknown = unknown_config_keys(merged_config)
    if unknown:
        logger.warning(
            f"config_common.yaml 有 schema 未宣告的欄位：{'、'.join(unknown)}"
            "（不影響啟動，但請到 config/loader.py 的 _SCHEMA 補上宣告）"
        )

    # 機敏資訊一律來自 .env，載入後合併進 config，讓既有取用方式（config["twitch"]["access_token"]）不變
    merged_config["twitch"]["client_id"] = _require_env("TWITCH_CLIENT_ID")
    merged_config["twitch"]["client_secret"] = _require_env("TWITCH_CLIENT_SECRET")
    merged_config["twitch"]["access_token"] = _require_env("TWITCH_ACCESS_TOKEN")
    merged_config["twitch"]["refresh_token"] = _require_env("TWITCH_REFRESH_TOKEN")
    # OPENAI_API_KEY 從 _require_env 降級為選填。
    # 它原本同時支撐 !gpt 與 !pk，硬性要求還算合理；但 AI 問答已全面改走
    # n8n（gpt_chat_session 已移除），現在只剩 !pk 一個指令用得到。
    # 為了一個娛樂指令讓整個 Bot 起不來，與 P1-37 的取捨相反。
    merged_config["openai"]["api_key"] = os.getenv("OPENAI_API_KEY", "")
    if not merged_config["openai"]["api_key"]:
        logger.warning("缺少環境變數 OPENAI_API_KEY，!pk 對戰指令將無法使用")

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
