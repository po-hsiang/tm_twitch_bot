from tm_twitch_bot.utils.probability_utils import weighted_random_choice
from tm_twitch_bot.model.character import Character
from tm_twitch_bot.chat.sender import chat_sender
from tm_twitch_bot.config.loader import config
from tm_twitch_bot.utils.log_utils import logger
from tm_twitch_bot.utils.singleton import SingletonMeta
import asyncio


class GoldRushGame(metaclass=SingletonMeta):
    def __init__(self):
        self._active = False
        self._entries: dict[str, int] = {}
        self._end_task: asyncio.Task | None = None
        self.amount_max = 10

    def start(self, send_func, duration: int) -> str:
        if self._active:
            return "⚠️ 一桶金進行中"
        self._active = True
        self._entries.clear()
        loop = asyncio.get_running_loop()  # 取目前事件迴圈
        loop.call_later(duration, self._schedule_end, send_func)
        return f"💰 一桶金開始！倒數 {duration} 秒，輸入『 !投 <金額> 』每人投入上限 10 Gold"

    def _schedule_end(self, send_func) -> None:
        """倒數結束時把結算丟成 task。

        必須留住強參考並掛上 done callback：
        create_task 的回傳值丟掉的話，例外會被靜默吞掉，
        玩家只會看到「開了一桶金然後什麼都沒發生」。
        """
        self._end_task = asyncio.get_running_loop().create_task(
            self._end_game(send_func), name="gold_rush_end"
        )
        self._end_task.add_done_callback(self._on_end_finished)

    @staticmethod
    def _on_end_finished(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(f"一桶金結算失敗: {type(exc).__name__}: {exc}")

    def add_entry(self, char: Character, raw_amount: str) -> str:
        if not self._active:
            return "⚠️ 目前沒有進行中的一桶金"
        # 用 isdecimal() 而不是 isdigit()：isdigit() 對「²」這種上標也回 True，
        # 但 int("²") 會 ValueError。isdecimal() 才與 int() 收的字元集一致。
        elif not raw_amount.isdecimal():
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

        # 先扣款再記帳。扣款失敗就直接退出，避免出現「錢沒扣但注下了」
        if not char.spend_gold(amount):
            return f"⚠️ 餘額不足 {amount}，您目前只有 {char.gold} Gold"

        self._entries[user_id] = self._entries.get(user_id, 0) + amount
        total_gold = sum(self._entries.values())

        return f"投入 {amount}（個人累計 {self._entries[user_id]}，一桶金累計 {total_gold}，您餘額 {char.gold} Gold）"

    async def _end_game(self, send_func) -> None:
        """結算。

        這個協程是被 create_task 丟出去的，**沒有任何人接它的回傳值**——
        過去這裡的兩則錯誤訊息是 return 出去的，等於從來沒有觀眾看得到，
        體感上就是「遊戲開了但結束時毫無反應」（見 CODE_REVIEW P1-15）。
        所以一律改成主動送出。
        """
        self._active = False
        if not self._entries:
            await send_func("⚠️ 沒有人參加一桶金遊戲")
            return
        # strict=True：這裡每個元素都是 (user_id, 金額) 的二元組，長度本來就一致，
        # 寫明了才不會在未來換掉資料結構時默默丟掉尾巴
        items, weights = zip(*self._entries.items(), strict=True)
        user_id = weighted_random_choice(list(items), list(weights))
        char = await Character.find_by_user_id(user_id)
        if not char:
            await send_func("⚠️ 找不到參加者的資料，怪怪的")
            return
        total_reward = sum(weights)
        original_gold = char.gold
        char.gain_gold(total_reward)
        await char.save()
        winner = char.display_name
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
    # 結算訊息也要走速率保護，不然尖峰時剛好卡在上限就整則被 Twitch 吃掉
    return gold_rush_game.start(chat_sender.bind(message.channel.send), duration)


def toss(*args, **kwargs):
    char = kwargs.get("char")
    amount = kwargs.get("raw_tail_text", "")
    return gold_rush_game.add_entry(char, amount)
