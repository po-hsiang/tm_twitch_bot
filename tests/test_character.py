"""角色的升級與轉職邊界。

這段是純記憶體運算，不需要碰 MongoDB，很適合作為第一批回歸保護。
"""

import pytest

from tm_twitch_bot.model import jobs
from tm_twitch_bot.model.character import Character
from tm_twitch_bot.clients.mongo_atlas import mongo_atlas_client
from tm_twitch_bot.config.loader import config

EXP_MULTIPLE = config["rpg_parameter"]["exp_req_multiple"]  # 升到下一級 = 目前等級 * 此值


@pytest.fixture
def char() -> Character:
    return Character(user_id="u1", usernames=["tester"], display_names=["測試員"])


@pytest.fixture(autouse=True)
def _reset_job_config():
    """JOB_CONFIG 是跨模組共用的同一個 dict 物件，只能就地修改。"""
    snapshot = dict(jobs.JOB_CONFIG)
    jobs.JOB_CONFIG.clear()
    yield
    jobs.JOB_CONFIG.clear()
    jobs.JOB_CONFIG.update(snapshot)


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
    jobs.JOB_CONFIG.update({2: {"stage": "轉職", "jobs": ["劍士"]}})
    send, sent = collect_sends

    await char.gain_exp(EXP_MULTIPLE, send)

    assert char.job == "劍士"
    assert len(sent) == 2  # 升級一則 + 轉職一則
    assert "【初學者】轉職為【劍士】" in sent[1]


async def test_no_job_change_when_level_not_in_config(char, collect_sends):
    jobs.JOB_CONFIG.update({10: {"stage": "一轉", "jobs": ["劍士"]}})
    send, sent = collect_sends

    await char.gain_exp(EXP_MULTIPLE, send)

    assert char.job == "初學者"
    assert len(sent) == 1


def test_gain_gold_is_additive(char):
    char.gain_gold(3)
    char.gain_gold(7)
    assert char.gold == 10


# ===== 扣款（所有金幣支出的唯一入口） =====


def test_spend_gold_deducts_when_affordable(char):
    char.gain_gold(100)

    assert char.spend_gold(30) is True
    assert char.gold == 70


def test_spend_gold_allows_spending_exact_balance(char):
    char.gain_gold(20)

    assert char.spend_gold(20) is True
    assert char.gold == 0


def test_spend_gold_leaves_state_untouched_when_short(char):
    char.gain_gold(10)

    assert char.spend_gold(11) is False
    assert char.gold == 10  # 不能出現扣一半的中間狀態


def test_spend_gold_rejects_negative_cost(char):
    with pytest.raises(ValueError):
        char.spend_gold(-5)


# ===== 髒資料追蹤（決定 message_controller 要不要存檔） =====


def test_freshly_loaded_character_is_clean():
    restored = Character.from_dict({"user_id": "u9"})

    assert restored.is_dirty is False


def test_gold_changes_mark_dirty(char):
    char.gain_gold(1)
    assert char.is_dirty is True


def test_failed_spend_does_not_mark_dirty(char):
    char.spend_gold(999)
    assert char.is_dirty is False


async def test_exp_gain_marks_dirty(char, collect_sends):
    send, _ = collect_sends
    await char.gain_exp(1, send)

    assert char.is_dirty is True


def test_name_append_marks_dirty_only_when_new(char):
    char._maybe_append_name("tester", "測試員")  # 已存在
    assert char.is_dirty is False

    char._maybe_append_name("tester2", "測試員")  # 新的 username
    assert char.is_dirty is True


# 這裡原本有一項 test_dirty_flag_is_never_written_to_the_database，
# 只驗 `_dirty` 沒被寫進文件。P2-23 之後多了一個同性質的 `_baseline`，
# test_character_persistence.py 的 test_internal_bookkeeping_never_reaches_the_database
# 兩個都驗，是嚴格的超集，因此這裡就不重複一份。


async def test_save_clears_the_dirty_flag(char, monkeypatch):
    async def fake_update(*args, **kwargs):
        return None

    monkeypatch.setattr(mongo_atlas_client, "update", fake_update)
    char.gain_gold(1)

    await char.save()

    assert char.is_dirty is False


async def test_dirty_flag_survives_a_failed_save(char, monkeypatch):
    """存檔失敗時必須維持髒狀態，才有機會被重試。"""

    async def failing_update(*args, **kwargs):
        raise RuntimeError("寫入失敗")

    monkeypatch.setattr(mongo_atlas_client, "update", failing_update)
    char.gain_gold(1)

    with pytest.raises(RuntimeError):
        await char.save()

    assert char.is_dirty is True


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


# ===== 安全取名（P2-40）=====
#
# 直接寫 display_names[-1] 會對舊文件炸 IndexError：from_dict 用的是
# doc.get("display_names", [])，而 find_by_name / find_by_user_id 這兩條路
# 是直接撈文件、不補名字的（只有 get_or_create 會補）。


def test_display_name_uses_the_latest_name():
    char = Character(user_id="u1", usernames=["tester"], display_names=["舊名", "新名"])

    assert char.display_name == "新名"
    assert char.username == "tester"


def test_display_name_falls_back_to_username():
    """舊文件可能只有 usernames。名字醜一點都比整個指令炸掉好。"""
    char = Character(user_id="u1", usernames=["tester"], display_names=[])

    assert char.display_name == "tester"


def test_names_fall_back_all_the_way_to_the_user_id():
    char = Character(user_id="u1", usernames=[], display_names=[])

    assert char.display_name == "u1"
    assert char.username == "u1"


async def test_a_legacy_document_without_names_does_not_crash_on_level_up(
    collect_sends,
):
    """升級與轉職的廣播都會用到名字，是最容易踩到 IndexError 的地方。"""
    jobs.JOB_CONFIG.update({2: {"stage": "轉職", "jobs": ["劍士"]}})
    send, sent = collect_sends
    char = Character.from_dict({"user_id": "u1", "level": 1, "exp": 0})
    assert char.display_names == []  # 前提：這份舊文件真的沒有名字

    await char.gain_exp(EXP_MULTIPLE, send)  # 升級 + 轉職，兩則廣播

    assert len(sent) == 2
    assert all("u1" in message for message in sent)  # 退回 user_id，沒有炸掉


def test_the_name_properties_are_not_persisted():
    """它們是 property 而不是 dataclass field，不能被寫進文件。"""
    char = Character(user_id="u1", usernames=["tester"], display_names=["名字"])

    doc = char.to_dict()

    assert "display_name" not in doc
    assert "username" not in doc
    assert doc["display_names"] == ["名字"]
