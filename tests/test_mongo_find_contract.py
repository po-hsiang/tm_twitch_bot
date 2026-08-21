"""`mongo_atlas_client.find()` 的回傳契約：永遠是 list，永遠不是 None。

過去這個保證是「每個呼叫端各自負責」，而 commands/ranking.py 就漏掉了：
微服務一異常，`!排行` 就會 `enumerate(None)` 直接 TypeError。
契約收斂到 client 層之後，這裡同時鎖定契約本身與最容易漏的呼叫端。
"""

import pytest

from tm_twitch_bot.commands import ranking
from tm_twitch_bot.clients.mongo_atlas import mongo_atlas_client


@pytest.fixture
def svc_response(monkeypatch):
    """攔截對 MongoDB 微服務的 HTTP 呼叫，直接指定它回傳的 JSON。"""

    def _set(payload):
        async def _fake_req(method, path, *, params=None, json=None):
            return payload

        monkeypatch.setattr(
            mongo_atlas_client, "_req_for_mongo_atlas_svc", _fake_req
        )

    return _set


# ===== 契約本身 =====


async def test_normal_results_pass_through(svc_response):
    svc_response({"results": [{"user_id": "u1"}]})

    assert await mongo_atlas_client.find("c") == [{"user_id": "u1"}]


async def test_null_results_become_empty_list(svc_response):
    """微服務異常時 results 是 null，不能讓 None 流到呼叫端。"""
    svc_response({"results": None})

    assert await mongo_atlas_client.find("c") == []


async def test_missing_results_key_becomes_empty_list(svc_response):
    svc_response({"error": "collection not found"})

    assert await mongo_atlas_client.find("c") == []


async def test_non_dict_response_becomes_empty_list(svc_response):
    """回傳格式完全跑掉時也不能拋 AttributeError。"""
    svc_response(["unexpected"])

    assert await mongo_atlas_client.find("c") == []


# ===== 最容易漏防護的呼叫端 =====


async def test_rank_survives_empty_results(svc_response):
    svc_response({"results": None})

    assert await ranking.top_heroes() == "目前沒有資料…"
    assert await ranking.top_richest() == "目前沒有資料…"


async def test_rank_formats_real_results(svc_response):
    svc_response(
        {
            "results": [
                {"display_names": ["甲"], "level": 9, "job": "騎士", "gold": 300},
                {"display_names": ["乙"], "level": 5, "job": "劍士", "gold": 100},
            ]
        }
    )

    heroes = await ranking.top_heroes()

    assert "1. 甲 | Lv.9 | 騎士" in heroes
    assert "2. 乙 | Lv.5 | 劍士" in heroes
