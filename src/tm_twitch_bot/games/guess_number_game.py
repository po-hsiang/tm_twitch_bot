from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.utils.yaml_utils import config
import threading
import random


class _SingletonMeta(type):
    _instances: dict[type, "GuessNumberGame"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class GuessNumberGame(metaclass=_SingletonMeta):
    DEFAULT_MAX = 1000
    GUESS_FEE = 5
    PRIZE_INC_PER_GUESS = 2
    LOWEST_REWARD = 0
    TIER_REWARDS = {
        1: 5090,
        2: 2520,
        3: 1255,
        4: 600,
        5: 300,
        6: 150,
        7: 70,
        8: 30,
        9: 10,
        10: LOWEST_REWARD,
    }

    def __init__(self):
        self._active = False
        self.answer = None
        self.low = 0
        self.high = 0
        self.prize_pool = 0
        self.guess_counter = 0

    def start(self) -> str:
        if self._active:
            return "⚠️ 終極密碼進行中"
        self._active = True
        self.low, self.high = 0, self.DEFAULT_MAX
        self.answer = random.randint(1, self.DEFAULT_MAX - 1)
        self.prize_pool = 0
        self.guess_counter = 0
        # 刻意寫成單行：這則訊息會直接進 Twitch IRC，而 IRC 以換行作為
        # 一則訊息的結尾。原本是三引號多行字串，實際送出時後兩行會被當成
        # 另一行協定內容，觀眾只看得到「@某人」後面空空的（chat_sender 現在
        # 會兜住，但訊息本身就該是單行，不該依賴那道防線）。
        return (
            f"🎮 終極密碼開始！隨機產生數字於：{self.low} ~ {self.high}，"
            f"輸入『 !猜 <數字> 』每次猜測費 {self.GUESS_FEE}，"
            f"沒猜中灌注 {self.PRIZE_INC_PER_GUESS} 進彩金池"
        )

    def guess(self, char: Character, raw_number: str) -> str:
        if not self._active:
            return "⚠️ 目前沒有進行中的終極密碼"
        elif self.GUESS_FEE > char.gold:
            return f"⚠️ 餘額不足 {self.GUESS_FEE}，您目前只有 {char.gold} Gold"
        elif not raw_number.isdigit():
            return "⚠️ 請輸入正整數"

        number = int(raw_number)
        if not (self.low < number < self.high):
            return f"⚠️ 要猜 {self.low} ~ {self.high} 之間的數字喔！"

        # 上面已先做過餘額檢查，這裡是實際扣款；仍保留防呆，
        # 因為兩次檢查之間 char.gold 可能已被同一則訊息的其他指令改動
        if not char.spend_gold(self.GUESS_FEE):
            return f"⚠️ 餘額不足 {self.GUESS_FEE}，您目前只有 {char.gold} Gold"

        self.prize_pool += self.PRIZE_INC_PER_GUESS
        self.guess_counter += 1

        if number > self.answer:
            self.high = number
            return f"猜 {number} 太大！新範圍：{self.low} ~ {self.high}，下次猜中總獎金為 {self.TIER_REWARDS.get(self.guess_counter + 1, self.LOWEST_REWARD)} + {self.prize_pool + self.PRIZE_INC_PER_GUESS}"
        elif number < self.answer:
            self.low = number
            return f"猜 {number} 太小！新範圍：{self.low} ~ {self.high}，下次猜中總獎金為 {self.TIER_REWARDS.get(self.guess_counter + 1, self.LOWEST_REWARD)} + {self.prize_pool + self.PRIZE_INC_PER_GUESS}"
        else:
            self._active = False
            base_reward = self.TIER_REWARDS.get(self.guess_counter, self.LOWEST_REWARD)
            total_reward = base_reward + self.prize_pool
            original_gold = char.gold
            char.gain_gold(total_reward)
            return (
                f"🎊 恭喜您在第 {self.guess_counter} 次猜中 {number}！"
                f"基礎獎 {base_reward} + 彩金池 {self.prize_pool} = {total_reward} Gold！"
                f"原本 {original_gold} 現在 {char.gold} 🎊"
            )


guess_number_game = GuessNumberGame()


def start(*args, **kwargs):
    char = kwargs.get("char")
    if char.user_id not in config["admin_user_id"]:
        return  # 只有虎喵能開啟遊戲
    return guess_number_game.start()


def guess(*args, **kwargs):
    char = kwargs.get("char")
    number = kwargs.get("raw_tail_text", "")
    return guess_number_game.guess(char, number)


if __name__ == "__main__":
    while True:
        answer = random.randint(1, 3 - 1)
        print(f"answer: {answer}")
