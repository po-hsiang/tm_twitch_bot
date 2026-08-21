# 這支檔案裡「活著」的只有下面那個 StatusCodeError。
# 其餘註解掉的是 Telegram 通報的舊碼（部分來自另一個專案），
# **刻意保留備忘、不是待清的死碼**。見 CODE_REVIEW P2-28。

# from tm_twitch_bot.utils.vault_utils import project_secret
# from tm_twitch_bot.config.loader import config
# from tm_twitch_bot.utils.log_utils import logger
# import traceback
# import requests
# import os

# # telegram bot token
# tg_secret = project_secret["telegram"]
# env = os.getenv("ENV", "dev").lower()
# user_notify_bot = tg_secret["token"][env]  # 使用者通報就用工作群組的那一隻機器人
# developer_notify_bot = tg_secret["token"][
#     "error_notification"
# ]  # 開發者通報會有自己的機器人

# # 指定群組或 Topic
# error_notification_group = config["telegram"]["sending_groups"]["error_notification"]

# # 單純組裝句子顯示用
# bot_name = config["telegram"]["bot_name"]
# developer_tg_user_id = "@tiger_meow11733"


class StatusCodeError(Exception):
    pass


# def notify(user_msg, e):
#     user_notify(
#         f"{bot_name} ({env}) 出現問題啦 QQ\n錯誤訊息為「{user_msg}」\n‼️請 {developer_tg_user_id} 趕緊查看‼️"
#     )

#     if e:
#         # 獲取錯誤類型
#         error_type = type(e).__name__
#         # 獲取錯誤訊息
#         error_message = str(e)
#         # 獲取詳細的錯誤追蹤
#         detailed_traceback = "".join(
#             traceback.format_exception(e, value=e, tb=e.__traceback__)
#         )
#         logger.error(f"詳細的錯誤追蹤: {detailed_traceback}")
#         tb = e.__traceback__
#         while tb.tb_next:
#             if (
#                 "vivy" in tb.tb_next.tb_frame.f_code.co_filename
#                 and ".venv" not in tb.tb_next.tb_frame.f_code.co_filename
#             ):
#                 # 有時候錯誤會追到第三方套件裡，這樣就會不知道從哪觸發，因此透過路徑來判斷是否是我自己的腳本
#                 tb = tb.tb_next
#             else:
#                 break
#         file_name = tb.tb_frame.f_code.co_filename
#         file_name = file_name.split("\\")[-1]
#         line_number = tb.tb_lineno
#         developer_msg = f"{bot_name} ({env}) 在\n{file_name} 的第 {line_number} 行\n發生了 {error_type}: {error_message}"
#         developer_notify(f"{developer_tg_user_id} \n{developer_msg}")


# def user_notify(message):
#     url = f"https://api.telegram.org/bot{user_notify_bot}/sendMessage"
#     data = {
#         "chat_id": error_notification_group["user"]["chat_id"],
#         "text": message,
#         "message_thread_id": error_notification_group["user"]["message_thread_id"],
#     }
#     response = requests.post(url, data=data)
#     response.raise_for_status()
#     return response


# def developer_notify(message):
#     url = f"https://api.telegram.org/bot{developer_notify_bot}/sendMessage"
#     data = {
#         "chat_id": error_notification_group["developer"]["chat_id"],
#         "text": message,
#     }
#     response = requests.post(url, data=data)
#     response.raise_for_status()
#     return response


# if __name__ == "__main__":
#     try:
#         print(1 / 0)
#     except Exception as e:
#         notify("使用者們安安！", e)
