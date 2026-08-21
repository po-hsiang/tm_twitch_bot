"""終極密碼（CODE_REVIEW P1-38、P1-39）。

這個遊戲會直接動玩家的金幣，卻長期沒有任何測試覆蓋。
"""

import asyncio

import pytest

from tm_twitch_bot.commands.games import guess_number as gn


class FakeChar:
    def __init__(self, user_id: str = "u1", gold: int = 100):
        self.user_id = user_id
        self.gold = gold
        self.display_names = ["玩家"]

    @property
    def display_name(self) -> str:
        """比照真實 Character 的安全取名（見 model/character P2-40）。"""
        return self.display_names[-1] if self.display_names else self.user_id

    def gain_gold(self, amount: int) -> None:
        self.gold += amount

    def spend_gold(self, amount: int) -> bool:
        if self.gold < amount:
            return False
        self.gold -= amount
        return True


@pytest.fixture(autouse=True)
def fresh_game():
    """遊戲是模組級單例，測試之間必須歸零。"""
    game = gn.guess_number_game
    game.__init__()
    yield game
    game.__init__()


# ===== 開場訊息（P1-38）=====


def test_the_opening_message_is_a_single_line(fresh_game):
    """這則訊息會直接進 Twitch IRC，而 IRC 以換行作為一則訊息的結尾。

    原本用三引號多行字串，實際送出時後兩行會被當成另一行協定內容，
    觀眾只看到「@某人」後面空空的——遊戲開了卻沒人知道規則與範圍。
    """
    message = fresh_game.start()

    assert "\n" not in message
    assert "\r" not in message
    # 規則與範圍都必須真的在這一行裡，不能只剩開頭那句
    assert "!猜" in message
    assert str(fresh_game.high) in message


# ===== 數字解析（P1-39）=====


@pytest.mark.parametrize(
    "raw", ["五", "abc", "", " ", "-1", "1.5", "²"], ids=
    ["中文數字", "英文", "空字串", "空白", "負數", "小數", "上標2"]
)
def test_guess_rejects_non_numeric(fresh_game, raw):
    """「²」是關鍵案例：isdigit() 對它回 True，但 int("²") 會 ValueError。

    用 isdigit() 的話這裡不會被擋下來，而是一路走到 int() 才爆掉，
    最後被 message_controller 的通用錯誤處理接走——觀眾收到的是
    「系統忙碌」而不是「請輸入正整數」。
    """
    fresh_game.start()

    assert fresh_game.guess(FakeChar(), raw) == "⚠️ 請輸入正整數"


def test_a_rejected_guess_costs_nothing(fresh_game):
    """格式不對就不該扣錢。"""
    fresh_game.start()
    char = FakeChar(gold=100)

    fresh_game.guess(char, "²")

    assert char.gold == 100
    assert fresh_game.guess_counter == 0


def test_full_width_digits_are_accepted(fresh_game):
    """全形數字 int() 收得下，就不該擋——觀眾用中文輸入法很容易打出來。"""
    fresh_game.start()

    assert "請輸入正整數" not in fresh_game.guess(FakeChar(), "５００")


# ===== 開局 =====


def test_start_initialises_the_round(fresh_game):
    fresh_game.start()

    assert fresh_game._active is True
    assert (fresh_game.low, fresh_game.high) == (0, fresh_game.DEFAULT_MAX)
    assert 0 < fresh_game.answer < fresh_game.DEFAULT_MAX
    assert fresh_game.prize_pool == 0
    assert fresh_game.guess_counter == 0


def test_a_second_start_is_refused(fresh_game):
    fresh_game.start()
    fresh_game.answer = 500

    assert fresh_game.start() == "⚠️ 終極密碼進行中"
    assert fresh_game.answer == 500  # 不能把進行中的答案洗掉


def test_start_after_a_win_resets_the_prize_pool(fresh_game):
    """上一局的彩金池不能滾到下一局。"""
    fresh_game.start()
    fresh_game.answer = 500
    fresh_game.guess(FakeChar(), "500")  # 直接猜中，結束這局

    fresh_game.start()

    assert fresh_game.prize_pool == 0
    assert fresh_game.guess_counter == 0


def test_guess_before_any_round_is_refused(fresh_game):
    assert fresh_game.guess(FakeChar(), "500") == "⚠️ 目前沒有進行中的終極密碼"


# ===== 範圍收斂 =====


def test_a_high_guess_lowers_the_ceiling(fresh_game):
    fresh_game.start()
    fresh_game.answer = 500

    reply = fresh_game.guess(FakeChar(), "800")

    assert fresh_game.high == 800
    assert fresh_game.low == 0
    assert "太大" in reply


def test_a_low_guess_raises_the_floor(fresh_game):
    fresh_game.start()
    fresh_game.answer = 500

    reply = fresh_game.guess(FakeChar(), "200")

    assert fresh_game.low == 200
    assert fresh_game.high == fresh_game.DEFAULT_MAX
    assert "太小" in reply


def test_a_guess_outside_the_range_is_refused_for_free(fresh_game):
    """超出範圍不扣錢也不算次數，否則玩家會因為手滑被懲罰。"""
    fresh_game.start()
    fresh_game.answer = 500
    fresh_game.low, fresh_game.high = 400, 600
    char = FakeChar(gold=100)

    reply = fresh_game.guess(char, "700")

    assert "400 ~ 600" in reply
    assert char.gold == 100
    assert fresh_game.guess_counter == 0
    assert fresh_game.prize_pool == 0


def test_the_range_always_still_contains_the_answer(fresh_game):
    """收斂邏輯不能把答案排除在範圍外，否則這局永遠猜不完。"""
    fresh_game.start()
    fresh_game.answer = 437
    char = FakeChar(gold=1000)

    for number in ("900", "100", "700", "300", "500", "400"):
        if fresh_game.low < int(number) < fresh_game.high:
            fresh_game.guess(char, number)

    assert fresh_game.low < fresh_game.answer < fresh_game.high


# ===== 金流 =====


def test_each_guess_costs_the_fee_and_feeds_the_pool(fresh_game):
    fresh_game.start()
    fresh_game.answer = 500
    char = FakeChar(gold=100)

    fresh_game.guess(char, "300")
    fresh_game.guess(char, "700")

    assert char.gold == 100 - 2 * fresh_game.GUESS_FEE
    assert fresh_game.prize_pool == 2 * fresh_game.PRIZE_INC_PER_GUESS
    assert fresh_game.guess_counter == 2


def test_a_guess_is_refused_when_the_balance_is_short(fresh_game):
    fresh_game.start()
    char = FakeChar(gold=fresh_game.GUESS_FEE - 1)

    reply = fresh_game.guess(char, "500")

    assert "餘額不足" in reply
    assert char.gold == fresh_game.GUESS_FEE - 1
    assert fresh_game.guess_counter == 0


def test_winning_pays_the_tier_reward_plus_the_pool(fresh_game):
    fresh_game.start()
    fresh_game.answer = 500
    char = FakeChar(gold=100)

    fresh_game.guess(char, "300")  # 第 1 次沒中，灌注彩金池
    reply = fresh_game.guess(char, "500")  # 第 2 次猜中

    expected = fresh_game.TIER_REWARDS[2] + 2 * fresh_game.PRIZE_INC_PER_GUESS
    assert char.gold == 100 - 2 * fresh_game.GUESS_FEE + expected
    assert str(expected) in reply
    assert fresh_game._active is False  # 猜中就結束這局


def test_a_very_late_win_still_pays_the_pool(fresh_game):
    """超過 TIER_REWARDS 的次數基礎獎為 0，但彩金池還是要給。

    注意猜中那一次本身也會先灌注彩金池再結算，所以贏家拿的是 40 + 2。
    """
    fresh_game.start()
    fresh_game.answer = 500
    fresh_game.guess_counter = 20
    fresh_game.prize_pool = 40
    char = FakeChar(gold=100)

    fresh_game.guess(char, "500")

    pool_at_win = 40 + fresh_game.PRIZE_INC_PER_GUESS
    assert char.gold == 100 - fresh_game.GUESS_FEE + pool_at_win


# ===== 管理員限制 =====


def test_only_the_admin_can_start_a_round(monkeypatch):
    monkeypatch.setitem(gn.config, "admin_user_id", ["359"])

    assert gn.start(char=FakeChar(user_id="路人")) is None
    assert gn.guess_number_game._active is False


def test_the_admin_can_start_a_round(monkeypatch):
    monkeypatch.setitem(gn.config, "admin_user_id", ["359"])

    reply = gn.start(char=FakeChar(user_id="359"))

    assert "終極密碼開始" in reply
    assert gn.guess_number_game._active is True


# ===== 流局倒數（P2-42）=====
#
# 沒有這個機制的話 _active 只會在「有人猜中」時歸零，
# 沒人猜中就整場開台都開不了新局，只能重啟 Bot。


def test_the_timeout_is_thirty_minutes():
    assert gn.GuessNumberGame.TIMEOUT_SECONDS == 30 * 60


async def test_a_round_nobody_wins_is_announced_and_released(fresh_game, collect_sends):
    send, sent = collect_sends
    fresh_game.start(send, timeout=0)
    fresh_game.answer = 777
    fresh_game.prize_pool = 12

    for _ in range(3):  # call_later(0) 要讓事件圈轉一圈才會排入
        await asyncio.sleep(0)
    await fresh_game._end_task

    assert fresh_game._active is False  # 名額釋放，可以開新的一局
    assert len(sent) == 1
    assert "時間到" in sent[0]
    assert "777" in sent[0]  # 答案要公布
    assert "12" in sent[0]  # 彩金池流局金額


async def test_a_new_round_can_start_after_a_timeout(fresh_game, collect_sends):
    send, _ = collect_sends
    fresh_game.start(send, timeout=0)
    for _ in range(3):
        await asyncio.sleep(0)
    await fresh_game._end_task

    assert "終極密碼開始" in fresh_game.start(send, timeout=0)


async def test_winning_cancels_the_timeout(fresh_game, collect_sends):
    """猜中之後倒數不該再響，否則會對一個已結束的局公告流局。"""
    send, sent = collect_sends
    fresh_game.start(send, timeout=0)
    fresh_game.answer = 500

    fresh_game.guess(FakeChar(), "500")
    for _ in range(5):
        await asyncio.sleep(0)

    assert fresh_game._timeout_handle is None
    assert not any("時間到" in m for m in sent)


async def test_a_stale_timeout_does_not_end_a_new_round(fresh_game, collect_sends):
    """上一局的殘留倒數不能把正在進行的新局判成流局。

    猜中時會取消倒數，但 call_later 的取消與 task 排入之間仍有空隙，
    所以另外用 round_id 把關。
    """
    send, sent = collect_sends
    fresh_game.start(send, timeout=999)
    stale_round = fresh_game._round_id
    fresh_game.answer = 500
    fresh_game.guess(FakeChar(), "500")  # 第一局結束
    fresh_game.start(send, timeout=999)  # 第二局開始

    fresh_game._schedule_timeout(send, stale_round)  # 硬叫上一局的回呼
    await fresh_game._end_task

    assert fresh_game._active is True  # 新的一局還活著
    assert not any("時間到" in m for m in sent)


def test_no_send_func_means_no_countdown(fresh_game):
    """送不出公告時就不掛倒數——掛了也只是靜默結束一局。"""
    fresh_game.start()

    assert fresh_game._timeout_handle is None
    assert fresh_game._active is True  # 遊戲照常能玩


async def test_the_timeout_announcement_is_a_single_line(fresh_game, collect_sends):
    """同 P1-38：直接進 IRC 的訊息不能有換行。"""
    send, sent = collect_sends
    fresh_game.start(send, timeout=0)
    for _ in range(3):
        await asyncio.sleep(0)
    await fresh_game._end_task

    assert "\n" not in sent[0]
