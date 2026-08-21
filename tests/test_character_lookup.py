"""名稱查詢的 regex 逸出。

find_by_name 會把觀眾輸入直接組成 MongoDB 的 $regex，
未逸出時 `!pk .*` 能匹配到隨機玩家，
`!pk (a+)+$` 這種 catastrophic backtracking 能把 Atlas 的 CPU 打滿。
"""

import pytest

from tm_twitch_bot.model.character import Character
from tm_twitch_bot.clients.mongo_atlas import mongo_atlas_client


@pytest.fixture
def captured_filters(monkeypatch):
    captured: list[dict] = []

    async def find(collection, filter=None, projection=None, sort=None, limit=None):
        captured.append(filter)
        return []

    monkeypatch.setattr(mongo_atlas_client, "find", find)
    return captured


async def test_wildcard_is_escaped(captured_filters):
    await Character.find_by_name(".*")

    assert captured_filters[0]["display_names"]["$regex"] == r"^\.\*$"


async def test_redos_payload_is_escaped(captured_filters):
    await Character.find_by_name("(a+)+$")

    regex = captured_filters[0]["display_names"]["$regex"]
    assert "(" not in regex.replace(r"\(", "")  # 括號都被逸出了
    assert regex.startswith("^") and regex.endswith("$")


async def test_plain_names_remain_usable(captured_filters):
    """逸出不能破壞正常的中文與英數名稱。"""
    await Character.find_by_name("老虎喵喵喵")

    assert captured_filters[0]["display_names"]["$regex"] == "^老虎喵喵喵$"


async def test_falls_back_to_usernames_with_escaping(captured_filters):
    await Character.find_by_name("drowsy5566")

    assert len(captured_filters) == 2  # display_names 沒中，再查 usernames
    assert captured_filters[1]["usernames"]["$regex"] == "^drowsy5566$"


async def test_empty_input_short_circuits(captured_filters):
    assert await Character.find_by_name("") is None
    assert captured_filters == []
