"""`!pk` 對戰旁白的輸出驗證（CODE_REVIEW P2-41）。

`winner` 與 `battle_log` 都是模型自由生成的，而回覆會加上 `@` 直接進公開
聊天室。過去這兩個值是 `.get()` 拿了就內插——拿不到會送出字面的
「None 勝利者為: @None」，而模型幻想出一個名字時會去 @ 一個沒參戰的人。
"""

import pytest

from tm_twitch_bot.ai_actions import duel
from tm_twitch_bot.svc_client.openai import openai_client

PLAYERS = ("小虎", "阿喵")


@pytest.fixture
def model_returns(monkeypatch):
    """控制 structured_output 的回傳值，不碰 OpenAI 微服務。"""

    def _set(payload):
        async def _structured_output(system_prompt, user_content, schema):
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr(openai_client, "structured_output", _structured_output)

    return _set


# ===== 正常路徑 =====


async def test_a_valid_result_declares_the_winner(model_returns):
    model_returns({"winner": "小虎", "battle_log": "小虎一記暗器致勝 🗡️"})

    result = await duel.get_duel_result("（略）", PLAYERS)

    assert result == "小虎一記暗器致勝 🗡️ 勝利者為: @小虎"


# ===== 壞掉的輸出 =====


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "不是 dict",
        {},
        {"winner": "小虎"},
        {"winner": "小虎", "battle_log": ""},
        {"winner": "小虎", "battle_log": "   "},
        {"winner": "小虎", "battle_log": None},
    ],
    ids=["None", "list", "str", "空 dict", "缺 log", "空 log", "只有空白", "log 是 None"],
)
async def test_unusable_output_gives_the_generic_reply(model_returns, payload):
    model_returns(payload)

    result = await duel.get_duel_result("（略）", PLAYERS)

    assert result == duel.FAILURE_REPLY


async def test_the_literal_word_none_never_reaches_the_chat(model_returns):
    """最原始的症狀：觀眾看到「None 勝利者為: @None」。"""
    model_returns({})

    result = await duel.get_duel_result("（略）", PLAYERS)

    assert "None" not in result
    assert "@" not in result


# ===== 幻想出來的勝者 =====


@pytest.mark.parametrize(
    "hallucinated",
    ["不存在的人", "", "   ", None, 123, "小虎虎", "老虎喵喵喵"],
    ids=["別人", "空字串", "空白", "None", "數字", "近似名", "沒參戰的頻道主"],
)
async def test_a_winner_who_did_not_fight_is_not_mentioned(model_returns, hallucinated):
    """模型幻想一個名字時，絕不能加上 @ ——那會去標記一個無關的人。"""
    model_returns({"winner": hallucinated, "battle_log": "兩人打得精彩 🔥"})

    result = await duel.get_duel_result("（略）", PLAYERS)

    assert result == "兩人打得精彩 🔥"  # 旁白留著，勝者宣告省略
    assert "@" not in result


async def test_a_bogus_winner_is_logged(model_returns, caplog):
    model_returns({"winner": "路人甲", "battle_log": "打完了"})

    await duel.get_duel_result("（略）", PLAYERS)

    assert "路人甲" in caplog.text  # 要查得到模型到底回了什麼


# ===== 格式差異不該被當成幻想 =====


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  小虎  ", "小虎"),
        ("@小虎", "小虎"),
        ("阿喵", "阿喵"),
    ],
    ids=["前後空白", "多加了 @", "第二位玩家"],
)
async def test_minor_formatting_differences_still_resolve(model_returns, raw, expected):
    """模型偶爾會多空格或多帶一個 @，那是格式問題不是幻想，不該判定失敗。"""
    model_returns({"winner": raw, "battle_log": "精彩"})

    result = await duel.get_duel_result("（略）", PLAYERS)

    assert result == f"精彩 勝利者為: @{expected}"


async def test_case_differences_resolve_to_our_own_spelling(model_returns):
    """對回我們自己的名字，而不是沿用模型給的大小寫。"""
    model_returns({"winner": "TIGERFAN", "battle_log": "精彩"})

    result = await duel.get_duel_result("（略）", ("TigerFan", "阿喵"))

    assert result == "精彩 勝利者為: @TigerFan"


def test_resolve_winner_is_pure_and_returns_none_for_no_match():
    assert duel._resolve_winner("小虎", PLAYERS) == "小虎"
    assert duel._resolve_winner("誰啊", PLAYERS) is None
    assert duel._resolve_winner(None, PLAYERS) is None
