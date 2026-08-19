"""終極密碼（CODE_REVIEW P1-38、P1-39）。

這個遊戲會直接動玩家的金幣，卻長期沒有任何測試覆蓋。
"""

import pytest

from tm_twitch_bot.games import guess_number_game as gn


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
