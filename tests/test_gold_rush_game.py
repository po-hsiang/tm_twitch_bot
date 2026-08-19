"""一桶金的結算（CODE_REVIEW P1-15）。

`_end_game` 是被 `create_task` 丟出去的，回傳值沒有任何人接 ——
過去「沒有人參加」「找不到參加者的資料」這兩則是 return 出去的，
等於從來沒有觀眾看得到，體感上就是「遊戲開了但結束時毫無反應」。
"""

import asyncio

import pytest

from tm_twitch_bot.games import gold_rush_game as grg


def fresh_game() -> grg.GoldRushGame:
    """Singleton 會回傳同一顆實例，測試之間必須各自拿到乾淨狀態。"""
    game = grg.GoldRushGame.__new__(grg.GoldRushGame)
    game.__init__()
    return game


class FakeChar:
    def __init__(self, user_id: str = "u1", gold: int = 100):
        self.user_id = user_id
        self.gold = gold
        self.display_names = ["參加者"]
        self.saved = False

    def gain_gold(self, amount: int) -> None:
        self.gold += amount

    def spend_gold(self, amount: int) -> bool:
        if self.gold < amount:
            return False
        self.gold -= amount
        return True

    async def save(self) -> None:
        self.saved = True


@pytest.fixture
def game():
    return fresh_game()


@pytest.fixture
def found_char(monkeypatch):
    """控制 Character.find_by_user_id 的結果，避免碰到 MongoDB。"""

    def _set(result):
        async def _find(user_id):
            return result

        monkeypatch.setattr(grg.Character, "find_by_user_id", _find)
        return result

    return _set


# ===== 結算訊息真的送得出去 =====


async def test_empty_round_tells_the_chat(game, collect_sends):
    send, sent = collect_sends
    game._active = True

    await game._end_game(send)

    assert sent == ["⚠️ 沒有人參加一桶金遊戲"]
    assert game._active is False


async def test_missing_character_tells_the_chat(game, collect_sends, found_char):
    send, sent = collect_sends
    game._entries = {"u1": 5}
    found_char(None)

    await game._end_game(send)

    assert sent == ["⚠️ 找不到參加者的資料，怪怪的"]


async def test_winner_is_paid_saved_and_announced(game, collect_sends, found_char):
    send, sent = collect_sends
    game._entries = {"u1": 3, "u2": 7}
    char = found_char(FakeChar(gold=100))

    await game._end_game(send)

    assert char.gold == 110  # 3 + 7 全數入袋
    assert char.saved is True  # 得獎一定要落地，不能只在記憶體裡
    assert len(sent) == 1
    assert "10 Gold" in sent[0]


# ===== 丟出去的 task 不能靜默死掉 =====


async def test_settlement_failure_is_logged(game, collect_sends, monkeypatch, caplog):
    send, _ = collect_sends
    game._entries = {"u1": 5}

    async def boom(user_id):
        raise RuntimeError("MongoDB 微服務無回應")

    monkeypatch.setattr(grg.Character, "find_by_user_id", boom)

    game._schedule_end(send)
    await asyncio.gather(game._end_task, return_exceptions=True)
    await asyncio.sleep(0)  # done callback 是用 call_soon 排的

    assert "一桶金結算失敗" in caplog.text


async def test_settlement_task_is_kept_referenced(game, collect_sends):
    """沒有強參考的 task 可能被 GC 回收，事件就靜靜消失了。"""
    send, sent = collect_sends
    game._active = True

    game._schedule_end(send)
    assert game._end_task is not None

    await game._end_task
    assert sent == ["⚠️ 沒有人參加一桶金遊戲"]


# ===== 開局與投注 =====


async def test_start_announces_and_blocks_a_second_round(game, collect_sends):
    send, _ = collect_sends

    first = game.start(send, 120)
    second = game.start(send, 120)

    assert "一桶金開始" in first
    assert second == "⚠️ 一桶金進行中"


def test_add_entry_rejected_when_no_round_is_running(game):
    assert game.add_entry(FakeChar(), "5") == "⚠️ 目前沒有進行中的一桶金"


@pytest.mark.parametrize(
    "raw", ["五", "abc", "", " ", "-1", "1.5", "²"], ids=
    ["中文數字", "英文", "空字串", "空白", "負數", "小數", "上標2"]
)
def test_add_entry_rejects_non_numeric(game, raw):
    """「²」是關鍵案例：isdigit() 對它回 True，但 int("²") 會 ValueError。

    用 isdigit() 的話這裡不會被擋下來，而是一路走到 int() 才爆掉。
    """
    game._active = True
    assert game.add_entry(FakeChar(), raw) == "⚠️ 請輸入正整數"


def test_full_width_digits_are_accepted(game):
    """全形數字 int() 收得下，就不該擋——觀眾用中文輸入法很容易打出來。"""
    game._active = True
    assert "請輸入正整數" not in game.add_entry(FakeChar(gold=100), "５")


def test_add_entry_rejects_over_the_per_person_cap(game):
    game._active = True
    char = FakeChar(gold=100)

    result = game.add_entry(char, "11")

    assert "投入上限" in result
    assert char.gold == 100  # 被擋下就不該扣款


def test_add_entry_rejects_when_balance_is_short(game):
    game._active = True
    char = FakeChar(gold=2)

    result = game.add_entry(char, "5")

    assert "餘額不足" in result
    assert game._entries == {}  # 錢沒扣成功，注也不能下


def test_accumulated_entries_respect_the_cap(game):
    game._active = True
    char = FakeChar(gold=100)

    game.add_entry(char, "6")
    result = game.add_entry(char, "6")

    assert "投入上限" in result
    assert game._entries[char.user_id] == 6
    assert char.gold == 94  # 只扣掉第一次的 6
