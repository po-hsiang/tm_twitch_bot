"""轉職表解析。

這張表由 Google Sheets 提供，格式隨時可能被手動編輯弄壞，
而它是在啟動 bootstrap 階段解析的 —— 解析失敗等於 Bot 起不來。
"""

import pytest

from tm_twitch_bot.model.jobs import parse_jobs_sheet


def test_parses_stages_levels_and_jobs():
    raw = [
        ["一轉", "二轉"],
        ["10", "15"],
        ["劍士", "騎士"],
        ["魔法師", "巫師"],
    ]
    assert parse_jobs_sheet(raw) == {
        10: {"stage": "一轉", "jobs": ["劍士", "魔法師"]},
        15: {"stage": "二轉", "jobs": ["騎士", "巫師"]},
    }


def test_level_keys_are_ints_not_strings():
    """model/character 用 JOB_CONFIG.get(self.level) 查表，型別錯了會永遠查不到。"""
    parsed = parse_jobs_sheet([["一轉"], ["10"], ["劍士"]])

    assert list(parsed) == [10]
    assert parsed.get(10) is not None


def test_blank_cells_are_dropped_and_values_stripped():
    raw = [
        ["一轉", "二轉"],
        ["10", "15"],
        ["劍士", "  騎士  "],
        ["", "巫師"],  # 一轉那欄留白，不該產生空字串職業
    ]
    parsed = parse_jobs_sheet(raw)

    assert parsed[10]["jobs"] == ["劍士"]
    assert parsed[15]["jobs"] == ["騎士", "巫師"]


def test_rejects_sheet_without_enough_rows():
    with pytest.raises(ValueError):
        parse_jobs_sheet([["一轉"], ["10"]])


# ===== 手動編輯造成的格式歪斜（P2-30）=====
#
# 這幾項的共同點：解析發生在啟動 bootstrap 階段，
# 只要拋例外，Bot 就整場開台都起不來。


def test_short_row_is_tolerated():
    raw = [
        ["一轉", "二轉"],
        ["10", "15"],
        ["劍士", "騎士"],
        ["魔法師"],  # 尾端空白被 Sheets API 截掉，這列只剩一欄
    ]
    parsed = parse_jobs_sheet(raw)

    assert parsed[10]["jobs"] == ["劍士", "魔法師"]
    assert parsed[15]["jobs"] == ["騎士"]


def test_short_stage_row_is_tolerated():
    """表頭那一列同樣可能被截短，不能因此掛掉。"""
    raw = [
        ["一轉"],  # 二轉的中文序沒填
        ["10", "15"],
        ["劍士", "騎士"],
    ]
    parsed = parse_jobs_sheet(raw)

    assert parsed[15]["stage"] == ""
    assert parsed[15]["jobs"] == ["騎士"]


def test_every_row_shorter_than_the_header_still_parses():
    raw = [
        ["一轉", "二轉", "三轉"],
        ["10", "15", "20"],
        ["劍士"],
        ["魔法師", "巫師"],
    ]
    parsed = parse_jobs_sheet(raw)

    assert parsed[10]["jobs"] == ["劍士", "魔法師"]
    assert parsed[15]["jobs"] == ["巫師"]
    assert parsed[20]["jobs"] == []  # 沒有職業，但不該讓整張表解析失敗


@pytest.mark.parametrize("bad_level", ["", "  ", "十五", "0", "-3"])
def test_unusable_level_column_is_skipped_not_fatal(bad_level, caplog):
    """等級門檻打錯只該少一個轉職階段，不該讓 Bot 起不來。"""
    raw = [
        ["一轉", "二轉"],
        ["10", bad_level],
        ["劍士", "騎士"],
    ]
    parsed = parse_jobs_sheet(raw)

    assert list(parsed) == [10]
    assert "已略過該欄" in caplog.text  # 壞掉的欄位必須留下痕跡
