"""角色存檔的並行安全（CODE_REVIEW P2-23）。

過去 `save()` 是全欄位 `$set`：拿手上的快照覆蓋整份文件。
只要有第二個流程在同一時間動到同一個角色，先寫的那筆就會被蓋掉 ——
最典型的是一桶金結算發完獎金，接著聊天 handler 用它載入時的舊快照存回去，
獎金直接消失。這裡驗證的是「送出去的是差額，不是絕對值」。
"""

import pytest

from tm_twitch_bot.model.character import Character, DEFAULT_ATTRIBUTES
from tm_twitch_bot.clients.mongo_atlas import mongo_atlas_client


@pytest.fixture
def updates(monkeypatch):
    """攔截所有 update 呼叫，直接檢查送出去的 payload。"""
    recorded: list[dict] = []

    async def _update(collection, update, filter=None, upsert=False, many=False):
        recorded.append(update)

    monkeypatch.setattr(mongo_atlas_client, "update", _update)
    return recorded


def make_char(**overrides) -> Character:
    """從一份資料庫文件載入角色，等同 load_or_create 走到既有角色的那條路。"""
    doc = {
        "user_id": "u1",
        "usernames": ["tester"],
        "display_names": ["測試員"],
        "level": 3,
        "exp": 20,
        "gold": 100,
        "job": "劍士",
        "attributes": DEFAULT_ATTRIBUTES.copy(),
    }
    doc.update(overrides)
    return Character.from_dict(doc)


# ===== 差額而不是絕對值 =====


async def test_gold_is_written_as_a_delta(updates):
    char = make_char()
    char.gain_gold(7)

    await char.save()

    assert updates[0]["$inc"] == {"gold": 7}
    assert "gold" not in updates[0]["$set"]  # 絕對值絕對不能再出現


async def test_spending_produces_a_negative_delta(updates):
    char = make_char(gold=100)
    char.spend_gold(30)

    await char.save()

    assert updates[0]["$inc"] == {"gold": -30}


async def test_unchanged_numbers_are_not_written_at_all(updates):
    char = make_char()
    char._maybe_append_name("tester2", "測試員2")  # 只動到名字

    await char.save()

    assert "$inc" not in updates[0]
    assert set(updates[0]["$set"]) == {"updated_at"}


async def test_level_up_writes_level_exp_and_attribute_deltas(updates, collect_sends):
    send, _ = collect_sends
    char = make_char(level=1, exp=9)

    await char.gain_exp(1, send)  # 1 等的門檻是 10，剛好升級
    await char.save()

    inc = updates[0]["$inc"]
    assert inc["level"] == 1
    assert inc["exp"] == -9  # 經驗歸零：從 9 變成 0
    # 升級加的那一點屬性要用點路徑，不能整包 attributes 覆蓋
    attribute_incs = {k: v for k, v in inc.items() if k.startswith("attributes.")}
    assert list(attribute_incs.values()) == [1]
    assert "attributes" not in updates[0]["$set"]


# ===== 字串欄位只在真的變了才寫 =====


async def test_job_is_not_written_when_it_did_not_change(updates):
    char = make_char(job="劍士")
    char.gain_gold(1)

    await char.save()

    assert "job" not in updates[0]["$set"]


async def test_job_is_written_when_it_changed(updates):
    char = make_char(job="劍士")
    char.job = "騎士"

    await char.save()

    assert updates[0]["$set"]["job"] == "騎士"


# ===== 這兩項是整個改動最容易出錯的地方 =====


async def test_saving_twice_does_not_double_count(updates):
    """vip_system 會先存一次扣款，message_controller 的 finally 再存一次。

    基準線沒有跟著推進的話，第二次會把同一筆差額再送一遍。
    """
    char = make_char(gold=100)
    char.spend_gold(50)

    await char.save()
    await char.save()

    assert updates[0]["$inc"] == {"gold": -50}
    assert "$inc" not in updates[1]  # 第二次已經沒有差額可寫


async def test_a_failed_save_keeps_the_delta_for_the_next_attempt(monkeypatch):
    """存檔失敗時基準線不能推進，否則那筆增減就憑空消失了。"""
    attempts: list[dict] = []
    fail_next = {"value": True}

    async def _update(collection, update, filter=None, upsert=False, many=False):
        attempts.append(update)
        if fail_next["value"]:
            fail_next["value"] = False
            raise RuntimeError("MongoDB 微服務無回應")

    monkeypatch.setattr(mongo_atlas_client, "update", _update)
    char = make_char(gold=100)
    char.gain_gold(25)

    with pytest.raises(RuntimeError):
        await char.save()
    assert char.is_dirty is True  # 還沒落地就仍然是髒的

    await char.save()

    assert attempts[1]["$inc"] == {"gold": 25}


async def test_a_concurrent_writer_no_longer_loses_the_other_update(updates):
    """P2-23 的原始情境：同一份文件被兩個流程各自載入、各自存檔。

    以前後寫的那筆會用舊快照整份蓋掉先寫的；
    現在兩邊都只送自己的差額，加總才是正確餘額。
    """
    chatting = make_char(gold=100)  # 聊天 handler 手上的快照
    settling = make_char(gold=100)  # 一桶金結算重新載入的同一個角色

    settling.gain_gold(50)  # 發獎金
    await settling.save()

    chatting.gain_gold(1)  # 打字獎勵，用的是「發獎金之前」的舊快照
    await chatting.save()

    total = sum(u["$inc"]["gold"] for u in updates)
    assert total == 51  # 50 + 1，一筆都沒有被蓋掉


# ===== 其餘欄位的行為不能被改壞 =====


async def test_names_are_still_merged_not_replaced(updates):
    char = make_char()
    char._maybe_append_name("newname", "新名字")

    await char.save()

    add_to_set = updates[0]["$addToSet"]
    assert "newname" in add_to_set["usernames"]["$each"]
    assert "新名字" in add_to_set["display_names"]["$each"]


async def test_updated_at_is_always_written(updates):
    char = make_char()

    await char.save()

    assert "updated_at" in updates[0]["$set"]


async def test_legacy_document_without_attributes_gets_them_created(updates):
    """舊文件缺 attributes 時，補上的預設值必須真的寫進去。

    基準線若也用補完後的預設值，差額會是 0，那六個屬性就永遠不會落地。
    """
    doc = {"user_id": "u1", "usernames": [], "display_names": [], "gold": 0}
    char = Character.from_dict(doc)
    char.gain_gold(1)  # 讓它有東西可存

    await char.save()

    inc = updates[0]["$inc"]
    for key in DEFAULT_ATTRIBUTES:
        assert inc[f"attributes.{key}"] == 1


def test_internal_bookkeeping_never_reaches_the_database():
    """_baseline 與 _dirty 都不是 dataclass field，不能被寫進文件。"""
    char = make_char()

    assert "_baseline" not in char.to_dict()
    assert "_dirty" not in char.to_dict()
