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
