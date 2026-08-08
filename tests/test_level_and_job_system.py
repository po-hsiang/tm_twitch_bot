"""轉職表解析。

這張表由 Google Sheets 提供，格式隨時可能被手動編輯弄壞，
而它是在啟動 bootstrap 階段解析的 —— 解析失敗等於 Bot 起不來。
"""

import pytest

from tm_twitch_bot.scripts.level_and_job_system import parse_jobs_sheet


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
    """role_system 用 JOB_CONFIG.get(self.level) 查表，型別錯了會永遠查不到。"""
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


@pytest.mark.xfail(
    raises=IndexError,
    strict=True,
    reason="CODE_REVIEW.md P2-30 待修：Sheets API 常截掉尾端空白儲存格，"
    "短列會讓 row[idx] 直接 IndexError，導致 Bot 啟動失敗",
)
def test_short_row_should_be_tolerated():
    raw = [
        ["一轉", "二轉"],
        ["10", "15"],
        ["劍士", "騎士"],
        ["魔法師"],  # 尾端空白被 Sheets API 截掉，這列只剩一欄
    ]
    parsed = parse_jobs_sheet(raw)

    assert parsed[10]["jobs"] == ["劍士", "魔法師"]
    assert parsed[15]["jobs"] == ["騎士"]
