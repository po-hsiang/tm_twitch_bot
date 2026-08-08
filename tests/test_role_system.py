"""角色的升級與轉職邊界。

這段是純記憶體運算，不需要碰 MongoDB，很適合作為第一批回歸保護。
"""

import pytest

from tm_twitch_bot.scripts import level_and_job_system
from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.utils.yaml_utils import config

EXP_MULTIPLE = config["rpg_parameter"]["exp_req_multiple"]  # 升到下一級 = 目前等級 * 此值


@pytest.fixture
def char() -> Character:
    return Character(user_id="u1", usernames=["tester"], display_names=["測試員"])


@pytest.fixture(autouse=True)
def _reset_job_config():
    """JOB_CONFIG 是跨模組共用的同一個 dict 物件，只能就地修改。"""
    snapshot = dict(level_and_job_system.JOB_CONFIG)
    level_and_job_system.JOB_CONFIG.clear()
    yield
    level_and_job_system.JOB_CONFIG.clear()
    level_and_job_system.JOB_CONFIG.update(snapshot)


async def test_exp_below_threshold_does_not_level_up(char, collect_sends):
    send, sent = collect_sends
    await char.gain_exp(EXP_MULTIPLE - 1, send)

    assert char.level == 1
    assert char.exp == EXP_MULTIPLE - 1
    assert sent == []


async def test_exact_threshold_levels_up_once(char, collect_sends):
    send, sent = collect_sends
    await char.gain_exp(EXP_MULTIPLE, send)  # Lv.1 → Lv.2 剛好需要 1 * EXP_MULTIPLE

    assert char.level == 2
    assert char.exp == 0
    assert len(sent) == 1
    assert "升到 2 等" in sent[0]


async def test_large_exp_gain_levels_up_multiple_times(char, collect_sends):
    send, sent = collect_sends
    # Lv.1→2 需 10、Lv.2→3 需 20，共 30；給 35 應升到 Lv.3 並餘 5 點
    await char.gain_exp(EXP_MULTIPLE * 1 + EXP_MULTIPLE * 2 + 5, send)

    assert char.level == 3
    assert char.exp == 5
    assert len(sent) == 2


async def test_level_up_raises_exactly_one_attribute(char, collect_sends):
    send, _ = collect_sends
    before = sum(char.attributes.values())
    await char.gain_exp(EXP_MULTIPLE, send)

    assert sum(char.attributes.values()) == before + 1


async def test_job_change_fires_at_threshold_level(char, collect_sends):
    level_and_job_system.JOB_CONFIG.update({2: {"stage": "轉職", "jobs": ["劍士"]}})
    send, sent = collect_sends

    await char.gain_exp(EXP_MULTIPLE, send)

    assert char.job == "劍士"
    assert len(sent) == 2  # 升級一則 + 轉職一則
    assert "【初學者】轉職為【劍士】" in sent[1]


async def test_no_job_change_when_level_not_in_config(char, collect_sends):
    level_and_job_system.JOB_CONFIG.update({10: {"stage": "一轉", "jobs": ["劍士"]}})
    send, sent = collect_sends

    await char.gain_exp(EXP_MULTIPLE, send)

    assert char.job == "初學者"
    assert len(sent) == 1


def test_gain_gold_is_additive(char):
    char.gain_gold(3)
    char.gain_gold(7)
    assert char.gold == 10


def test_round_trip_through_dict(char):
    char.level, char.exp, char.gold, char.job = 5, 12, 300, "騎士"
    restored = Character.from_dict(char.to_dict())

    assert restored.to_dict() == char.to_dict()


def test_from_dict_fills_defaults_for_missing_fields():
    restored = Character.from_dict({"user_id": "u9"})

    assert restored.level == 1
    assert restored.gold == 0
    assert restored.job == "初學者"
    assert restored.usernames == []
    assert set(restored.attributes) == {"STR", "AGI", "VIT", "INT", "DEX", "LUK"}
