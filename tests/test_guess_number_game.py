"""終極密碼（CODE_REVIEW P1-38、P1-39）。

這個遊戲會直接動玩家的金幣，卻長期沒有任何測試覆蓋。
"""

import pytest

from tm_twitch_bot.games import guess_number_game as gn


class FakeChar:
    def __init__(self, user_id: str = "u1", gold: int = 100):
        self.user_id = user_id
        self.gold = gold
        self.display_names = ["玩家"]

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
