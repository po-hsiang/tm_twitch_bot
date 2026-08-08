"""招呼語的惰性載入與降級行為。"""

import pytest

from tm_twitch_bot.scripts import greeter
from tm_twitch_bot.scripts.greeter import greet_user
from tm_twitch_bot.utils.yaml_utils import config

DIALOGUE_SHEET = {"冒險台詞": [["勇者出現了"]]}


@pytest.fixture(autouse=True)
def _reset_greeter_state():
    """who_arrived 與台詞池都是模組級狀態，測試之間必須隔離。"""
    greeter.adventure_dialogue_pool.clear()
    greeter.who_arrived.clear()
    greeter.who_arrived.add(config["tigermeowtw_id"])
    yield
    greeter.adventure_dialogue_pool.clear()
    greeter.who_arrived.clear()
    greeter.who_arrived.add(config["tigermeowtw_id"])


async def test_first_greeting_includes_adventure_dialogue(monkeypatch, sheet_stub):
    get_sheet_data, _ = sheet_stub(DIALOGUE_SHEET)
    monkeypatch.setattr(greeter.google_sheets_client, "get_sheet_data", get_sheet_data)

    result = await greet_user("u1")
    assert "聽說" in result
    assert result.endswith("勇者出現了")


async def test_second_message_from_same_user_is_not_greeted(monkeypatch, sheet_stub):
    get_sheet_data, _ = sheet_stub(DIALOGUE_SHEET)
    monkeypatch.setattr(greeter.google_sheets_client, "get_sheet_data", get_sheet_data)

    assert await greet_user("u1") != ""
    assert await greet_user("u1") == ""


async def test_bot_owner_is_never_greeted(monkeypatch, sheet_stub):
    get_sheet_data, calls = sheet_stub(DIALOGUE_SHEET)
    monkeypatch.setattr(greeter.google_sheets_client, "get_sheet_data", get_sheet_data)

    assert await greet_user(config["tigermeowtw_id"]) == ""
    assert calls == []  # 連台詞都不該去抓


async def test_dialogue_pool_is_fetched_only_once(monkeypatch, sheet_stub):
    get_sheet_data, calls = sheet_stub(DIALOGUE_SHEET)
    monkeypatch.setattr(greeter.google_sheets_client, "get_sheet_data", get_sheet_data)

    await greet_user("u1")
    await greet_user("u2")
    await greet_user("u3")
    assert calls == ["冒險台詞"]  # 惰性載入且只打一次 API


async def test_blank_cells_are_filtered_out(monkeypatch):
    async def get_sheet_data(sheet_name: str):
        return [["勇者出現了", "  "], ["", "魔王甦醒了"]]

    monkeypatch.setattr(greeter.google_sheets_client, "get_sheet_data", get_sheet_data)

    await greet_user("u1")
    assert greeter.adventure_dialogue_pool == ["勇者出現了", "魔王甦醒了"]


async def test_falls_back_to_plain_greeting_when_sheets_is_down(monkeypatch):
    """Sheets 服務掛掉時只能少一句台詞，不能讓整個訊息處理中斷。"""

    async def boom(sheet_name: str):
        raise RuntimeError("Sheets 服務無回應")

    monkeypatch.setattr(greeter.google_sheets_client, "get_sheet_data", boom)

    result = await greet_user("u1")
    assert result != ""
    assert "聽說" not in result
