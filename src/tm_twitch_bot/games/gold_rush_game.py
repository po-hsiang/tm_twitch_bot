from tm_twitch_bot.utils.probability_utils import weighted_random_choice
from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.utils.yaml_utils import config
import threading
import asyncio


class _SingletonMeta(type):
    _instances: dict[type, "GoldRushGame"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class GoldRushGame(metaclass=_SingletonMeta):
    def __init__(self):
        self._active = False
        self._entries: dict[str, int] = {}
        self._timer: threading.Timer | None = None
        self.amount_max = 10

    def start(self, send_func, duration: int) -> None:
        if self._active:
            return "⚠️ 一桶金進行中"
        self._active = True
        self._entries.clear()
        loop = asyncio.get_running_loop()  # 取目前事件迴圈
        loop.call_later(
            duration,  # 幾秒後執行 lambda
            lambda: asyncio.create_task(self._end_game(send_func)),  # 把 message 帶進去
        )
        return f"💰 一桶金開始！倒數 {duration} 秒，輸入『 !投 <金額> 』每人投入上限 10 Gold"

    def add_entry(self, char: Character, raw_amount: str) -> None:
        if not self._active:
            return "⚠️ 目前沒有進行中的一桶金"
        elif not raw_amount.isdigit():
            return "⚠️ 請輸入正整數"

        amount = int(raw_amount)
        user_id = char.user_id

        if amount > self.amount_max:
            return f"⚠️ 一桶金的投入上限為 {self.amount_max}，您這次要投 {amount} nono"
        elif (
            user_id in self._entries
            and self._entries[user_id] + amount > self.amount_max
        ):
            return f"⚠️ 一桶金的投入上限為 {self.amount_max}，您目前已投 {self._entries[user_id]}"
        elif amount > char.gold:
            return f"⚠️ 餘額不足 {amount}，您目前只有 {char.gold} Gold"

        char.gold -= amount

        self._entries[user_id] = self._entries.get(user_id, 0) + amount
        total_gold = sum(self._entries.values())

        return f"投入 {amount}（個人累計 {self._entries[user_id]}，一桶金累計 {total_gold}，您餘額 {char.gold} Gold）"

    async def _end_game(self, send_func) -> None:
        self._active = False
        if not self._entries:
            return "⚠️ 沒有人參加一桶金遊戲"
        items, weights = zip(*self._entries.items())
        user_id = weighted_random_choice(list(items), list(weights))
        char = await Character.find_by_user_id(user_id)
        if not char:
            return "⚠️ 找不到參加者的資料，怪怪的"
        total_reward = sum(weights)
        original_gold = char.gold
        char.gold += total_reward
        await char.save()
        winner = char.display_names[-1]
        final_result = (
            f"@{winner} 🎊 恭喜您抱走一桶金 {total_reward} Gold！"
            f"原本 {original_gold} 現在 {char.gold} 🎊"
        )
        await send_func(final_result)


gold_rush_game = GoldRushGame()


def start(*args, **kwargs):
    char = kwargs.get("char")
    if char.user_id not in config["admin_user_id"]:
        return  # 只有虎喵能開啟遊戲
    duration = kwargs.get("raw_tail_text", "")
    message = kwargs.get("message")
    try:
        duration = int(duration)
        if duration <= 0:
            raise ValueError()
    except ValueError:
        return "⚠️ 倒數時間必須是正整數"
    return gold_rush_game.start(message.channel.send, duration)


def toss(*args, **kwargs):
    char = kwargs.get("char")
    amount = kwargs.get("raw_tail_text", "")
    return gold_rush_game.add_entry(char, amount)
