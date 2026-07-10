from tm_twitch_bot.svc_client.openai import openai_client
from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.utils.log_utils import logger

system_prompt = """
# 角色與任務
您是一位充滿戲劇張力的臺灣繁體中文 RPG 對戰旁白，熟悉 Twitch 文化與 Emoji。
每次將收到兩名玩家的角色狀態 (`duel_info`)。
請依下列規則產出 **唯一且有效的 JSON**：
1. `winner`：請填寫獲勝者的「玩家名稱」字串，不會有「平手」的狀況。勝負需綜合考量等級、職業與角色數值，但必須保有隨機性；同樣輸入需要不同結果。
2. `battle_log`：大約 25 個中文字以內，描述精采對戰過程；可加入 1 – 3 個 Emoji 增添情緒。內容須引用玩家職業或關鍵屬性作亮點。

# 輸入格式
按此格式一次提供兩行：
<玩家名稱> | Lv. <等級> | 職業【<職業>】| STR <數> / AGI <數> / VIT <數> / INT <數> / DEX <數> / LUK <數>

# 輸出規範
1. 英數字元與中文字符之間務必留一個半形空白，例如：揮舞長劍 🗡️，卻被瞬間冰霜 🧊 封住。
2. 文字語言必須為「臺灣繁體中文」，並完整保留所有專有名詞原文
3. 嚴禁使用任何 Markdown 或 HTML 標記
4. 勝負需綜合考量等級、職業與角色數值

# 範例
[input]
小虎 | Lv. 11 | 職業【忍者】| STR 1 / AGI 11 / VIT 1 / INT 1 / DEX 1 / LUK 1
阿喵 | Lv. 12 | 職業【跆拳】| STR 12 / AGI 1 / VIT 1 / INT 1 / DEX 1 / LUK 1
[output]
{"winner":"小虎", "battle_log":"阿喵攻勢猛烈，又是重拳又是旋風踢 🐾，但小虎速度更勝一籌，使用影分身閃過最後一記重踢，回身來個暗器致勝！"}
"""

schema = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "description": "勝利者玩家名稱"},
        "battle_log": {"type": "string", "description": "約 25 字對戰敘述，含 emoji"},
    },
    "required": ["winner", "battle_log"],
}


async def pk(*args, **kwargs) -> str:
    challenger: Character = kwargs["char"]  # 說話者自己為挑戰者
    raw_tail_text: str = kwargs.get(
        "raw_tail_text", ""
    )  # 扣除掉指令，空格後的字串，這裡指 pk 對象

    if "老虎喵喵喵" in raw_tail_text or "tigermeowtw" in raw_tail_text:
        return "tigerm24Zombie 你打不贏 GM 啦"

    target_display_name = raw_tail_text.lstrip().lstrip("@").strip()
    if not target_display_name:
        return "⚠️ 要輸入 !pk @對方顯示名稱"

    opponent = await Character.find_by_name(target_display_name)
    if not opponent:
        return f"⚠️ 找不到 {target_display_name} 的角色資料"

    if opponent.user_id == challenger.user_id:
        return "⚠️ 您不能和自己 PK"

    duel_info = "\n".join([format_for_duel(challenger), format_for_duel(opponent)])
    result = await get_duel_result(duel_info)
    logger.info(f"對戰資訊:\n{duel_info}\n對戰結果: {result}")
    return result


def format_for_duel(char: Character) -> str:
    attr_str = " / ".join(f"{k} {v}" for k, v in char.attributes.items())
    return (
        f"{char.display_names[-1]} | "
        f"Lv. {char.level} | 職業【{char.job}】| {attr_str}"
    )


async def get_duel_result(duel_info: str) -> str:
    content_json = await openai_client.structured_output(
        system_prompt, duel_info, schema
    )
    winner = content_json.get("winner")
    battle_log = content_json.get("battle_log")
    return f"{battle_log} 勝利者為: @{winner}"


if __name__ == "__main__":
    import asyncio

    async def _demo():
        challenger = await Character.find_by_name("老虎喵喵喵")
        opponent = await Character.find_by_name("drowsy5566")
        if opponent.user_id == challenger.user_id:
            print("⚠️ 您不能和自己 PK")
            return
        duel_info = "\n".join([format_for_duel(challenger), format_for_duel(opponent)])
        result = await get_duel_result(duel_info)
        logger.info(f"對戰資訊:\n{duel_info}\n對戰結果: {result}")

    asyncio.run(_demo())
