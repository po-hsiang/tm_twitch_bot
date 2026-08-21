"""抽卡（CODE_REVIEW P2-19 補齊）。

這個模組會動玩家的金幣，卻長期沒有任何測試覆蓋。
抽卡的隨機性一律用 monkeypatch 固定，測試不靠機率碰運氣。
"""

import pytest

from tm_twitch_bot.commands import gacha as gh


class FakeChar:
    def __init__(self, gold: int = 100):
        self.gold = gold

    def gain_gold(self, amount: int) -> None:
        self.gold += amount

    def spend_gold(self, amount: int) -> bool:
        if self.gold < amount:
            return False
        self.gold -= amount
        return True


@pytest.fixture
def rigged(monkeypatch):
    """固定每一抽的結果，並記錄實際被抽了幾次。"""

    def _set(*results: str):
        sequence = list(results)
        calls: list[tuple] = []

        def _pick(items, weights):
            calls.append((tuple(items), tuple(weights)))
            return sequence[(len(calls) - 1) % len(sequence)]

        monkeypatch.setattr(gh, "weighted_random_choice", _pick)
        return calls

    return _set


# ===== 扣款 =====


def test_a_pull_costs_the_fee(rigged):
    rigged("tigerm24Black")
    char = FakeChar(gold=100)

    gh.gacha(char=char)

    assert char.gold == 100 - gh.PULL_COST


def test_an_insufficient_balance_pulls_nothing(rigged):
    """錢不夠時 spend_gold 不改變任何狀態，也不該真的去抽。"""
    calls = rigged("tigerm24Sharingan")
    char = FakeChar(gold=gh.PULL_COST - 1)

    reply = gh.gacha(char=char)

    assert f"不足 {gh.PULL_COST} Gold" in reply
    assert char.gold == gh.PULL_COST - 1
    assert calls == []  # 連抽都沒抽，不會出現「錢沒扣卻拿到獎品」


def test_a_pull_with_exactly_enough_gold_is_allowed(rigged):
    rigged("tigerm24Black")
    char = FakeChar(gold=gh.PULL_COST)

    reply = gh.gacha(char=char)

    assert "不足" not in reply
    assert char.gold == 0


# ===== 抽卡結果 =====


def test_every_pull_draws_exactly_ten_times(rigged):
    calls = rigged("tigerm24Black")

    gh.gacha(char=FakeChar())

    assert len(calls) == 10


def test_the_weights_match_the_item_list(rigged):
    """機率表與品項表長度一旦不一致，weighted_random_choice 的結果就沒意義。"""
    calls = rigged("tigerm24Black")

    gh.gacha(char=FakeChar())

    assert len(gh.ITEMS) == len(gh.WEIGHTS)
    assert calls[0] == (tuple(gh.ITEMS), tuple(gh.WEIGHTS))


def test_all_ten_results_appear_in_the_reply(rigged):
    rigged("tigerm24Rainbow")

    reply = gh.gacha(char=FakeChar())

    assert reply.count("tigerm24Rainbow") == 10


# ===== 獎金 =====


def test_a_full_miss_pays_nothing(rigged):
    rigged("tigerm24Black")
    char = FakeChar(gold=100)

    reply = gh.gacha(char=char)

    assert char.gold == 100 - gh.PULL_COST
    assert "什麼都沒有" in reply


def test_rewards_are_summed_across_all_ten_pulls(rigged):
    rigged("tigerm24Staring")
    char = FakeChar(gold=100)

    reply = gh.gacha(char=char)

    expected = 10 * gh.REWARD_MAP["tigerm24Staring"]
    assert char.gold == 100 - gh.PULL_COST + expected
    assert f"獲得 {expected} Gold" in reply


def test_mixed_results_only_count_the_paying_items(rigged):
    rigged("tigerm24Black", "tigerm24Sharingan")  # 交替：5 黑 5 寫輪眼
    char = FakeChar(gold=100)

    gh.gacha(char=char)

    expected = 5 * gh.REWARD_MAP["tigerm24Sharingan"]
    assert char.gold == 100 - gh.PULL_COST + expected


def test_every_rewarding_item_is_a_real_item(rigged):
    """獎金表裡出現不在品項表裡的名字，就是永遠發不出去的死設定。"""
    assert set(gh.REWARD_MAP) <= set(gh.ITEMS)


def test_the_jackpot_is_rarer_than_the_common_item():
    """權重與獎金必須同向：越稀有才越值錢，不然期望值會壞掉。"""
    weight_of = dict(zip(gh.ITEMS, gh.WEIGHTS, strict=True))
    rewards = sorted(gh.REWARD_MAP.items(), key=lambda kv: kv[1])

    for cheaper, dearer in zip(rewards, rewards[1:], strict=False):
        assert weight_of[cheaper[0]] > weight_of[dearer[0]]
