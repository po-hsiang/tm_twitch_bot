"""VIP 兌換的金流一致性。

這裡同時碰到 Twitch API（外部副作用）與兩個 collection，
最怕的就是「錢扣了但 VIP 沒給」或「VIP 給了但錢沒扣」。
"""

import pytest

from tm_twitch_bot.scripts import vip_system as vs
from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.svc_client.mongo_atlas import mongo_atlas_client

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


async def test_missing_api_context_refunds_the_gold(system, char, monkeypatch):
    """set_api_context() 沒被呼叫時（Bot 還沒 ready），不能扣了錢卻什麼都沒發生。"""
    stub_api(monkeypatch, (True, None))
    monkeypatch.delattr(system, "_token_getter", raising=False)

    result = await system.redeem_vip(char)

    assert "已退還" in result
    assert char.gold == 500


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
