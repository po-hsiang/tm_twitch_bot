from tm_twitch_bot.svc_client.mongo_atlas import mongo_atlas_client
from tm_twitch_bot.scripts.command_dispatcher import dispatch_command
from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.scripts.greeter import greet_user
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from time import monotonic

rpg_parameter = config["rpg_parameter"]

CHAT_CD = 3
_last_cmd_ts: dict[str, float] = {}  # user_id -> 上次指令時間（秒）
_last_message: dict[str, str] = {}  # user_id -> 上一句訊息


async def handle_message(message):
    author = message.author
    user_id = author.id
    username = author.name
    display_name = author.display_name
    content = message.content.strip()

    # 機器人訊息不處理
    if user_id in config["bot_user_id"]:
        return

    # 取得角色 (若沒有則創角)
    char = await Character.load_or_create(
        user_id=user_id, username=username, display_name=display_name
    )

    # 增加真實聊天次數 (不論洗不洗頻都加一)
    await add_total_msgs_count(user_id)

    # 防 3 秒內輸入
    now = monotonic()
    if now - _last_cmd_ts.get(user_id, 0.0) < CHAT_CD:
        logger.warning(f"抓到 {display_name} 還在冷卻時間就講話")
        return
    _last_cmd_ts[user_id] = now

    # 防洗一樣的話
    if _last_message.get(user_id) == content:
        logger.warning(f"抓到 {display_name} 洗頻")
        return
    _last_message[user_id] = content

    # 第一次講話都會打招呼，獲得 3 點經驗值、3 金幣
    greet = await greet_user(user_id)
    if greet:
        await message.channel.send(f"@{display_name} {greet}")
        await char.gain_exp(3, message.channel.send)
        char.gain_gold(3)

    # 打字獲得 1 點經驗值、1 金幣
    await char.gain_exp(rpg_parameter["default_gained_exp"], message.channel.send)
    char.gain_gold(rpg_parameter["default_gainer_gold"])

    # 查看指令集
    cmd_reply = await dispatch_command(content, char=char, message=message)
    if cmd_reply:
        await message.channel.send(f"@{display_name} {cmd_reply}")

    # 存檔
    await char.save()


async def add_total_msgs_count(user_id):
    await mongo_atlas_client.update(
        "tm_twitch_users",
        update={"$inc": {"total_msgs": 1}},
        filter={"user_id": user_id},
        many=False,
        upsert=False,
    )
