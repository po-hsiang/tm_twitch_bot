from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.utils.chat_sender import chat_sender
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
import threading
import asyncio
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
    # 沒人猜中就自動流局的秒數。
    # 沒有這個機制的話 _active 只會在「有人猜中」時歸零，
    # 沒人猜中就整場開台都開不了新局，只能重啟 Bot（CODE_REVIEW P2-42）。
    TIMEOUT_SECONDS = 1800  # 30 分鐘
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
        self._timeout_handle: asyncio.TimerHandle | None = None
        self._end_task: asyncio.Task | None = None
        # 每一局一個編號。用來擋掉「上一局的殘留倒數把新的一局判成流局」，
        # 光靠猜中時取消還不夠保險（見 _timeout_round）。
        self._round_id = 0

    def start(self, send_func=None, timeout: int | None = None) -> str:
        """開一局。

        `send_func` 是流局公告的出口，不給就沒有倒數（遊戲照常能玩）——
        測試不必為了無關的案例準備一個假的發話函式。
        """
        if self._active:
            return "⚠️ 終極密碼進行中"
        self._active = True
        self._round_id += 1
        self.low, self.high = 0, self.DEFAULT_MAX
        self.answer = random.randint(1, self.DEFAULT_MAX - 1)
        self.prize_pool = 0
        self.guess_counter = 0
        self._arm_timeout(send_func, self.TIMEOUT_SECONDS if timeout is None else timeout)
        # 刻意寫成單行：這則訊息會直接進 Twitch IRC，而 IRC 以換行作為
        # 一則訊息的結尾。原本是三引號多行字串，實際送出時後兩行會被當成
        # 另一行協定內容，觀眾只看得到「@某人」後面空空的（chat_sender 現在
        # 會兜住，但訊息本身就該是單行，不該依賴那道防線）。
        return (
            f"🎮 終極密碼開始！隨機產生數字於：{self.low} ~ {self.high}，"
            f"輸入『 !猜 <數字> 』每次猜測費 {self.GUESS_FEE}，"
            f"沒猜中灌注 {self.PRIZE_INC_PER_GUESS} 進彩金池"
        )

    # ---------- 流局倒數 ----------

    def _arm_timeout(self, send_func, timeout: int) -> None:
        """掛上流局倒數。送不出公告（沒有 send_func）就不掛。"""
        self._cancel_timeout()
        if send_func is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 不在事件圈內（例如手動跑腳本），沒有倒數但遊戲照常能玩
            logger.warning("終極密碼不在事件圈內啟動，本局沒有流局倒數")
            return
        self._timeout_handle = loop.call_later(
            timeout, self._schedule_timeout, send_func, self._round_id
        )

    def _cancel_timeout(self) -> None:
        if self._timeout_handle is not None:
            self._timeout_handle.cancel()
            self._timeout_handle = None

    def _schedule_timeout(self, send_func, round_id: int) -> None:
        """倒數到了，把流局公告丟成 task。

        必須留住強參考並掛上 done callback：create_task 的回傳值丟掉的話，
        例外會被靜默吞掉（同一桶金的 P1-15）。
        """
        self._end_task = asyncio.get_running_loop().create_task(
            self._timeout_round(send_func, round_id), name="guess_number_timeout"
        )
        self._end_task.add_done_callback(self._on_timeout_finished)

    @staticmethod
    def _on_timeout_finished(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(f"終極密碼流局公告失敗: {type(exc).__name__}: {exc}")

    async def _timeout_round(self, send_func, round_id: int) -> None:
        """時間到還沒人猜中就流局。

        round_id 不符代表這是上一局的殘留倒數（上一局已結束、新局已開始）。
        猜中時會取消倒數，但 call_later 的取消與 task 排入之間仍有空隙，
        少了這道檢查就可能把正在進行的新局誤判成流局。
        """
        if not self._active or round_id != self._round_id:
            return
        self._active = False
        self._timeout_handle = None
        await send_func(
            f"⏰ 終極密碼時間到，沒有人猜中！答案是 {self.answer}，"
            f"彩金池 {self.prize_pool} Gold 流局"
        )

    def guess(self, char: Character, raw_number: str) -> str:
        if not self._active:
            return "⚠️ 目前沒有進行中的終極密碼"
        elif self.GUESS_FEE > char.gold:
            return f"⚠️ 餘額不足 {self.GUESS_FEE}，您目前只有 {char.gold} Gold"
        # 用 isdecimal() 而不是 isdigit()：isdigit() 對「²」這種上標也回 True，
        # 但 int("²") 會 ValueError。isdecimal() 才與 int() 收的字元集一致。
        elif not raw_number.isdecimal():
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
            self._cancel_timeout()  # 已經有人猜中，流局倒數不該再響
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
    message = kwargs.get("message")
    channel = getattr(message, "channel", None)
    # 流局公告也要走速率保護，不然尖峰時剛好卡在上限就整則被 Twitch 吃掉。
    # 拿不到 channel 就不給 send_func（本局沒有倒數，但至少開得起來）。
    send_func = chat_sender.bind(channel.send) if channel is not None else None
    return guess_number_game.start(send_func)


def guess(*args, **kwargs):
    char = kwargs.get("char")
    number = kwargs.get("raw_tail_text", "")
    return guess_number_game.guess(char, number)


if __name__ == "__main__":
    while True:
        answer = random.randint(1, 3 - 1)
        print(f"answer: {answer}")
