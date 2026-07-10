from pathlib import Path
import yaml
import os

CONFIG_COMMON_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "config_common.yaml"
)


def deep_merge(dict1, dict2):
    """
    遞歸合併兩個字典，對於重複的鍵：
    - 如果是字典，則進行遞歸合併
    - 否則，使用 dict2 的值覆蓋 dict1
    """
    for key, value in dict2.items():
        if key in dict1 and isinstance(dict1[key], dict) and isinstance(value, dict):
            dict1[key] = deep_merge(dict1[key], value)
        else:
            dict1[key] = value
    return dict1


def load_yaml():
    # env = os.getenv("ENV", "dev").lower()  # 預設使用 dev
    # env_path = Path(__file__).resolve().parent.parent / "config" / f"config_{env}.yaml"
    with CONFIG_COMMON_PATH.open("r", encoding="utf-8") as file:
        common_config = yaml.safe_load(file)
    # with env_path.open("r", encoding="utf-8") as file:
    # env_config = yaml.safe_load(file)
    # merged_config = deep_merge(common_config, env_config)
    merged_config = common_config
    return merged_config


config = load_yaml()


def save_tokens(access_token: str, refresh_token: str):
    current_config = load_yaml()
    if "twitch" not in current_config or not isinstance(current_config["twitch"], dict):
        current_config["twitch"] = {}
    current_config["twitch"]["access_token"] = access_token
    current_config["twitch"]["refresh_token"] = refresh_token

    with CONFIG_COMMON_PATH.open("w", encoding="utf-8") as file:
        yaml.safe_dump(
            current_config, file, allow_unicode=True, sort_keys=False, indent=2
        )

    global config
    config = current_config

    print("✅ 已成功更新 access_token 和 refresh_token 至 config_common.yaml")


if __name__ == "__main__":
    print(f"\nconfig: {config}")
