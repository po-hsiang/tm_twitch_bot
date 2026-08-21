# 這一整支是註解掉的舊碼（Vault 取密鑰），**刻意保留備忘、不是待清的死碼**。
# 現行做法：機敏值走 .env（見 utils/yaml_utils.py），設定檔只留非機敏項目。
# 見 CODE_REVIEW P2-28。

# from tm_twitch_bot.utils.yaml_utils import config
# import requests

# vault_config = config["vault"]


# def get_secret():
#     params = {
#         "token": vault_config["token"],
#         "project": vault_config["project"],
#         "path": vault_config["path"],
#     }
#     response = requests.get(vault_config["api_url"], params=params)
#     return response.json()


# project_secret = get_secret()

# if __name__ == "__main__":
#     print(f"\nproject_secret：{project_secret}")
