"""`!INFO`：把角色數值印出來。

只有兩行程式，但它是「按參數名注入」的一個活生生的樣本——
函式簽章寫 `kwargs.get("char")`，dispatcher 就得把 char 傳進來。
名字打錯的話會安靜地拿到 None，然後在聊天室變成一句「這個指令暫時出了點問題」。
"""

import pytest

from tm_twitch_bot.commands.profile import check


class FakeChar:
    def __init__(self):
        self.calls = 0

    def get_info(self) -> str:
        self.calls += 1
        return "Lv.7 | EXP 3 | Gold 120 | 職業【劍士】"


async def test_it_returns_the_characters_own_summary():
    char = FakeChar()

    assert check(char=char) == "Lv.7 | EXP 3 | Gold 120 | 職業【劍士】"
    assert char.calls == 1


async def test_the_context_key_is_named_char():
    """dispatcher 是按參數名注入的，這個名字就是契約。"""
    with pytest.raises(AttributeError):
        check(character=FakeChar())  # 拿不到 char → None.get_info()
