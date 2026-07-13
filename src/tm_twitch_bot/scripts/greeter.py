from tm_twitch_bot.utils.yaml_utils import config
from datetime import datetime, timezone, timedelta
from typing import Optional

who_arrived: set[str] = set()
who_arrived.add(config["tigermeowtw_id"])  # 機器人不用跟虎喵打招呼
# extension = " 好久不見 tigerm24Shy"  # 備用字尾（未使用，保留備忘）


def greet_user(user_id) -> Optional[str]:

    if user_id in who_arrived:
        return ""

    who_arrived.add(user_id)

    hour = datetime.now(timezone(timedelta(hours=8))).hour  # 台灣時區

    if 18 <= hour:
        greeting = "晚上好 tigerm24Hi"
    elif 6 <= hour <= 11:
        greeting = "早安 tigerm24Hi"
    elif 12 <= hour <= 17:
        greeting = "午安 tigerm24Hi"
    else:
        greeting = "嗨嗨 tigerm24Hi 這麼晚還沒睡 tigerm24Quest"

    return f"{greeting} 要不要來台聚玩！"

    # 備用招呼語（保留備忘）：隨機接一句 Google Sheets「冒險台詞」
    # 若要啟用：台詞池需改為惰性載入（不可在 import 階段打 API），
    # 本函數改為 async 並在 message_controller 以 await greet_user(user_id) 呼叫
    # return f"{greeting} 聽說{random.choice(adventure_dialogue_pool)}"
