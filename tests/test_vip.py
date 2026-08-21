"""VIP 兌換的金流一致性。

這裡同時碰到 Twitch API（外部副作用）與兩個 collection，
最怕的就是「錢扣了但 VIP 沒給」或「VIP 給了但錢沒扣」。
"""

import pytest

from tm_twitch_bot.commands import vip as vs
from tm_twitch_bot.model.character import Character
from tm_twitch_bot.clients.mongo_atlas import mongo_atlas_client

COST = 100


@pytest.fixture
def char() -> Character:
    c = Character(user_id="u1", usernames=["tester"], display_names=["測試員"])
    c.gain_gold(500)
    return c


@pytest.fixture
def system(monkeypatch):
    """一個設定齊全、資料庫與 API 都被攔截的 VipSystem。"""
    sys_ = vs.VipSystem()
    monkeypatch.setattr(
        sys_,
        "cfg",
        vs.VipConfig(enabled=True, gold_cost=COST, vip_cap=10, days_per_redeem=31),
    )
    sys_.set_api_context(
        client_id="cid", broadcaster_id="bid", token_getter=lambda: "token"
    )

    async def find(collection, filter=None, projection=None, sort=None, limit=None):
        return []  # 尚未是 VIP，且目前沒有任何有效 VIP（名額未滿）

    async def update(collection, update, filter=None, upsert=False, many=False):
        return None

    monkeypatch.setattr(mongo_atlas_client, "find", find)
    monkeypatch.setattr(mongo_atlas_client, "update", update)
    return sys_


def stub_api(monkeypatch, result):
    """result 可為 (is_success, payload) 或要拋出的例外。"""

    async def add_channel_vip(token, client_id, broadcaster_id, user_id):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(vs.twitch_vips_api, "add_channel_vip", add_channel_vip)


async def test_successful_redeem_deducts_gold(system, char, monkeypatch):
    stub_api(monkeypatch, (True, None))

    result = await system.redeem_vip(char)

    assert "兌換成功" in result
    assert char.gold == 400


async def test_api_failure_refunds_the_gold(system, char, monkeypatch):
    stub_api(monkeypatch, (False, {"message": "使用者已是 VIP"}))

    result = await system.redeem_vip(char)

    assert "VIP 新增失敗" in result
    assert char.gold == 500  # 全額退還


async def test_api_exception_refunds_the_gold(system, char, monkeypatch):
    stub_api(monkeypatch, RuntimeError("Helix 無回應"))

    result = await system.redeem_vip(char)

    assert "已退還" in result
    assert char.gold == 500


# 這裡原本有一項 test_missing_api_context_refunds_the_gold，
# 用 monkeypatch.delattr 把 _token_getter 整個刪掉，驗「扣了錢要退回來」。
# P1-17 之後這個前提不成立了：__init__ 保證那三個屬性一定存在（值為 None），
# 而 redeem_vip 在扣款之前就會用 is_ready 擋掉，根本不會走到退款。
# 也就是說那項測試在模擬一個正式環境不可能出現的狀態。
# 取而代之的是下方「API context 尚未就緒（P1-17）」那一組，
# 驗的是真正會發生的情境：暖機中抵達的 !vip 完全不動到錢。


async def test_insufficient_gold_leaves_balance_untouched(system, char, monkeypatch):
    stub_api(monkeypatch, (True, None))
    poor = Character(user_id="u2", usernames=["poor"], display_names=["窮光蛋"])
    poor.gain_gold(COST - 1)

    result = await system.redeem_vip(poor)

    assert "Gold 不足" in result
    assert poor.gold == COST - 1


async def test_record_write_failure_still_reports_success(system, char, monkeypatch):
    """VIP 已授予、錢也扣了，紀錄寫入失敗不能讓觀眾以為兌換失敗。"""
    stub_api(monkeypatch, (True, None))

    calls: list[str] = []

    async def flaky_update(collection, update, filter=None, upsert=False, many=False):
        calls.append(collection)
        if collection == "tm_twitch_vips":
            raise RuntimeError("寫入失敗")

    monkeypatch.setattr(mongo_atlas_client, "update", flaky_update)

    result = await system.redeem_vip(char)

    assert "兌換成功" in result
    assert char.gold == 400
    assert "tm_twitch_vips" in calls


async def test_disabled_system_rejects_without_charging(char, monkeypatch):
    sys_ = vs.VipSystem()
    monkeypatch.setattr(
        sys_,
        "cfg",
        vs.VipConfig(enabled=False, gold_cost=COST, vip_cap=10, days_per_redeem=31),
    )

    result = await sys_.redeem_vip(char)

    assert "未啟用" in result
    assert char.gold == 500


# ===== API context 尚未就緒（P1-17）=====


@pytest.fixture
def unready_system(monkeypatch):
    """還沒被呼叫 set_api_context() 的 VipSystem——event_ready 之前的狀態。"""
    sys_ = vs.VipSystem()
    monkeypatch.setattr(
        sys_,
        "cfg",
        vs.VipConfig(enabled=True, gold_cost=COST, vip_cap=10, days_per_redeem=31),
    )
    monkeypatch.setattr(sys_, "_client_id", None)
    monkeypatch.setattr(sys_, "_broadcaster_id", None)
    monkeypatch.setattr(sys_, "_token_getter", None)
    return sys_


def test_a_fresh_instance_is_not_ready(monkeypatch):
    """三個屬性必須「存在但為 None」，不是「不存在」。

    不存在的話只能靠 AttributeError 兜底，而那個位置已經在扣款之後。
    """
    fresh = vs.VipSystem.__new__(vs.VipSystem)
    fresh.__init__()

    assert fresh.is_ready is False
    for name in ("_client_id", "_broadcaster_id", "_token_getter"):
        assert hasattr(fresh, name), f"{name} 應該在 __init__ 就存在"


def test_set_api_context_makes_it_ready(monkeypatch):
    fresh = vs.VipSystem.__new__(vs.VipSystem)
    fresh.__init__()

    fresh.set_api_context(client_id="cid", broadcaster_id="bid", token_getter=lambda: "t")

    assert fresh.is_ready is True


async def test_redeem_before_ready_does_not_charge(unready_system, char, monkeypatch):
    """暖機中抵達的 !vip 必須在扣款前就被擋掉。

    原本是靠取 token 時的 AttributeError 兜底，雖然會退款，
    卻多繞了「扣款→打 API 失敗→退款」一圈，log 還會留下誤導的 API 失敗紀錄。
    """
    called = []
    monkeypatch.setattr(
        vs.twitch_vips_api,
        "add_channel_vip",
        lambda *a, **k: called.append(a),
    )
    before = char.gold

    reply = await unready_system.redeem_vip(char)

    assert "暖機" in reply
    assert char.gold == before  # 完全沒動到錢，連退款都不需要
    assert called == []  # 也沒有打過 API


async def test_redeem_before_ready_says_nothing_internal(unready_system, char):
    """錯誤訊息不能夾帶內部細節（同 P1-11 的原則）。"""
    reply = await unready_system.redeem_vip(char)

    for leak in ("None", "AttributeError", "client_id", "broadcaster"):
        assert leak not in reply
