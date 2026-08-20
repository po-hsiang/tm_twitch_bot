"""試算表攤平工具，以及三張內容表「跳不跳第一列」的行為鎖定。

CODE_REVIEW P2-29：三支抽取器對第一列的處理不一樣，看起來像其中一支寫錯。
2026-08-21 直接打 9091 核對過實際的表，結論是**那個不一致才是對的**——
吃啥有分類標題列，酷酷的諧音梗與冒險台詞沒有。

這支測試存在的理由就是把那個結論鎖住：下一個人「順手把三支統一」時，
會有測試紅掉告訴他為什麼不能統一，而不是安靜地少掉一列內容。
"""

import pytest

from tm_twitch_bot.scripts import daily_food_picker, daily_meme_picker, greeter
from tm_twitch_bot.utils.sheet_utils import collect_cells


# ===== collect_cells 本身 =====


def test_header_row_is_dropped_when_asked():
    rows = [["分類A", "分類B"], ["滷肉飯", "拉麵"]]
    assert collect_cells(rows, skip_header=True) == ["滷肉飯", "拉麵"]


def test_header_row_is_kept_when_the_sheet_has_no_header():
    rows = [["第一句台詞"], ["第二句台詞"]]
    assert collect_cells(rows, skip_header=False) == ["第一句台詞", "第二句台詞"]


def test_blank_and_whitespace_only_cells_are_dropped():
    rows = [["有內容", "", "   "], ["\t", "也有內容"]]
    assert collect_cells(rows, skip_header=False) == ["有內容", "也有內容"]


def test_surrounding_whitespace_is_trimmed():
    """試算表很容易多打一個空白，那個空白會一路帶到聊天室。"""
    assert collect_cells([["  拉麵  "]], skip_header=False) == ["拉麵"]


def test_jagged_rows_do_not_raise():
    """Google Sheets 會把尾端空白儲存格截掉，每列長度不保證一致（見 P2-30）。"""
    rows = [["a", "b", "c"], ["d"], [], ["e", "f"]]
    assert collect_cells(rows, skip_header=False) == ["a", "b", "c", "d", "e", "f"]


@pytest.mark.parametrize("empty", [None, [], [[]], [["", "  "]]])
def test_nothing_usable_gives_an_empty_list(empty):
    """微服務回了沒有 data 的 JSON 時要回空 list，不能炸。

    抓內容表是在處理觀眾訊息的路徑上，炸掉會連招呼與獎勵一起沒有。
    池子留空則會讓下一次呼叫自己重抓一次。
    """
    assert collect_cells(empty, skip_header=False) == []
    assert collect_cells(empty, skip_header=True) == []


def test_skip_header_has_no_default():
    """這個決定必須看過那張表才能下，不該有人靠預設值帶過去。"""
    with pytest.raises(TypeError):
        collect_cells([["a"]])  # type: ignore[call-arg]


# ===== 三張表各自的決定 =====


@pytest.fixture(autouse=True)
def _reset_pools():
    """三支抽取器的池子與快取都是模組級狀態，測試之間必須隔離。"""

    def _clear():
        daily_food_picker.clear_pool()
        daily_food_picker.food_cache.clear()
        daily_meme_picker.clear_pool()
        daily_meme_picker.meme_cache = ""
        greeter.clear_pool()

    _clear()
    yield
    _clear()


class FakeChar:
    def __init__(self, user_id: str = "u1"):
        self.user_id = user_id


async def test_food_sheet_drops_its_category_header(monkeypatch, sheet_stub):
    """「吃啥」第 0 列是分類（飯／麵…），不是餐點——不跳的話會抽到分類名。"""
    get_sheet_data, _ = sheet_stub({"吃啥": [["飯", "麵"], ["滷肉飯", "拉麵"]]})
    monkeypatch.setattr(
        daily_food_picker.google_sheets_client, "get_sheet_data", get_sheet_data
    )

    await daily_food_picker._ensure_pool()

    assert daily_food_picker._food_pool == ["滷肉飯", "拉麵"]
    assert "飯" not in daily_food_picker._food_pool
    assert "麵" not in daily_food_picker._food_pool


async def test_meme_sheet_keeps_its_first_row(monkeypatch, sheet_stub):
    """「酷酷的諧音梗」沒有標題列，跳過第 0 列就是少掉一整列的梗。"""
    get_sheet_data, _ = sheet_stub(
        {"酷酷的諧音梗": [["第一列的梗"], ["第二列的梗"]]}
    )
    monkeypatch.setattr(
        daily_meme_picker.google_sheets_client, "get_sheet_data", get_sheet_data
    )

    await daily_meme_picker._ensure_pool()

    assert daily_meme_picker._meme_pool == ["第一列的梗", "第二列的梗"]


async def test_meme_newlines_become_spaces(monkeypatch, sheet_stub):
    """梗的格式是「問題換行答案」，一格就是一則完整的梗。

    換行換成空白是刻意的排版選擇：交給 chat_sender.flatten 會變成 " / "。
    """
    get_sheet_data, _ = sheet_stub({"酷酷的諧音梗": [["為什麼？\n因為", ""]]})
    monkeypatch.setattr(
        daily_meme_picker.google_sheets_client, "get_sheet_data", get_sheet_data
    )

    await daily_meme_picker._ensure_pool()

    assert daily_meme_picker._meme_pool == ["為什麼？ 因為"]


async def test_adventure_sheet_keeps_its_first_row(monkeypatch, sheet_stub):
    """「冒險台詞」也沒有標題列，第 0 列就是第一句台詞。"""
    get_sheet_data, _ = sheet_stub({"冒險台詞": [["第一句"], ["第二句"]]})
    monkeypatch.setattr(
        greeter.google_sheets_client, "get_sheet_data", get_sheet_data
    )

    await greeter._ensure_dialogue_pool()

    assert greeter.adventure_dialogue_pool == ["第一句", "第二句"]


# ===== clear_pool 的界線（P2-26 的 !reload 會呼叫它們）=====


async def test_clearing_the_food_pool_does_not_reroll_anyone(monkeypatch, sheet_stub):
    """「一人一餐」是遊戲規則，不是試算表的快取。

    連 food_cache 一起清，!reload 就變成重骰按鈕了。
    """
    get_sheet_data, calls = sheet_stub({"吃啥": [["分類"], ["滷肉飯"]]})
    monkeypatch.setattr(
        daily_food_picker.google_sheets_client, "get_sheet_data", get_sheet_data
    )
    char = FakeChar()

    first = await daily_food_picker.pick(char=char)
    daily_food_picker.clear_pool()

    assert daily_food_picker._food_pool == []  # 表內容放掉了
    assert await daily_food_picker.pick(char=char) == first  # 但這個人的餐沒變
    assert calls == ["吃啥"]  # 而且不必再打一次 API


async def test_this_streams_meme_survives_a_reload(monkeypatch, sheet_stub):
    """「一場開台一則梗」是遊戲規則，重載不會換掉已經抽出來的那則。

    也就是說：這場抽過梗之後才新增的梗，要下一場才看得到。
    這是刻意的取捨——不然 !reload 就變成重抽按鈕了。
    """
    get_sheet_data, _ = sheet_stub({"酷酷的諧音梗": [["原本的梗"]]})
    monkeypatch.setattr(
        daily_meme_picker.google_sheets_client, "get_sheet_data", get_sheet_data
    )

    first = await daily_meme_picker.pick()
    assert first == "原本的梗"

    daily_meme_picker.clear_pool()

    assert daily_meme_picker._meme_pool == []  # 表內容放掉了
    assert await daily_meme_picker.pick() == first  # 但這場的梗沒變


def test_clearing_the_adventure_pool_does_not_re_greet_everyone():
    """who_arrived 是「一場開台跟每個人打一次招呼」的規則，不是表的快取。"""
    greeter.who_arrived.add("u1")

    greeter.clear_pool()

    assert greeter.adventure_dialogue_pool == []
    assert "u1" in greeter.who_arrived
