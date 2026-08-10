"""n8n「TM AI Agent」webhook 串接。

n8n 端不屬於本專案、也不會為了 Twitch 修改，所以 Bot 這側必須自己扛三件事：
把欄位送齊、把 Discord 風格的回覆洗乾淨、任何失敗都只給觀眾一句道歉語。
這裡全部離線驗證，不會真的打到 webhook。
"""

import asyncio

import pytest

from tm_twitch_bot.ai_actions import tm_ai_agent as agent
from tm_twitch_bot.svc_client import n8n_ai_agent as svc


class FakeResponse:
    def __init__(self, *, status_code=200, body=b"", json_data=None, text=None):
        self.status_code = status_code
        self._json = json_data
        self._explicit_text = text
        if json_data is not None:
            import json as _json

            self.content = _json.dumps(json_data).encode()
        else:
            self.content = body

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def text(self) -> str:
        if self._explicit_text is not None:
            return self._explicit_text
        return self.content.decode(errors="replace")

    def json(self):
        if self._json is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._json


@pytest.fixture
def webhook(monkeypatch):
    """攔截 HTTP，回傳 (設定回應的函式, 已送出的請求紀錄)。"""
    calls: list[dict] = []
    outcome: dict = {"response": FakeResponse(json_data={"reply": "安安好虎粉"})}

    class StubClient:
        async def post(self, url, *, json=None, headers=None, timeout=None):
            calls.append(
                {"url": url, "json": json, "headers": headers, "timeout": timeout}
            )
            result = outcome["response"]
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(svc, "get_async_client", lambda: StubClient())
    monkeypatch.setattr(svc.n8n_ai_agent_client, "_secret", "test-webhook-secret")

    def _respond(response):
        outcome["response"] = response

    return _respond, calls


class FakeMessage:
    def __init__(self, channel_name="tigermeowtw", display_name="好虎粉", user_id="u1"):
        self.author = type(
            "A", (), {"display_name": display_name, "id": user_id, "name": "fan"}
        )()
        self.channel = type("C", (), {"name": channel_name})()


# ===== Request body：規格說所有欄位都要給 =====


def test_payload_contains_every_required_field():
    payload = svc.N8nAiAgentClient.build_payload(
        text="你好", user_name="好虎粉", user_id="u1", channel_id="twitch:tigermeowtw"
    )

    assert set(payload) == {
        "text",
        "user_name",
        "user_id",
        "channel_id",
        "guild_id",
        "images",
        "stickers",
    }


def test_discord_only_fields_are_empty_not_omitted():
    payload = svc.N8nAiAgentClient.build_payload(
        text="你好", user_name="好虎粉", user_id="u1", channel_id="twitch:tigermeowtw"
    )

    assert payload["guild_id"] == ""
    assert payload["images"] == []
    assert payload["stickers"] == []


async def test_channel_id_carries_the_twitch_prefix(webhook):
    """記憶分組鍵少了前綴就會和 Discord 頻道共用同一份對話記憶。"""
    _, calls = webhook

    await agent.ask(raw_tail_text="你好", message=FakeMessage(channel_name="tigermeowtw"))

    assert calls[0]["json"]["channel_id"] == "twitch:tigermeowtw"


async def test_display_name_is_sent_so_the_ai_can_address_people(webhook):
    _, calls = webhook

    await agent.ask(
        raw_tail_text="你好", message=FakeMessage(display_name="老虎喵喵喵", user_id="359")
    )

    assert calls[0]["json"]["user_name"] == "老虎喵喵喵"
    assert calls[0]["json"]["user_id"] == "359"


async def test_secret_travels_in_the_header_only(webhook):
    _, calls = webhook

    await agent.ask(raw_tail_text="你好", message=FakeMessage())

    assert calls[0]["headers"]["x-webhook-secret"] == "test-webhook-secret"
    assert "test-webhook-secret" not in str(calls[0]["json"])


async def test_timeout_is_generous_enough_for_tool_calls(webhook):
    """AI 呼叫工具時要 10~25 秒，規格要求 timeout 設 120 秒。"""
    _, calls = webhook

    await agent.ask(raw_tail_text="你好", message=FakeMessage())

    assert calls[0]["timeout"].read >= 120


async def test_blank_question_is_filtered_before_calling(webhook):
    """空訊息送過去只會拿到「沒有文字內容」，白跑一趟還佔用對話記憶。"""
    _, calls = webhook

    result = await agent.ask(raw_tail_text="   ", message=FakeMessage())

    assert result == agent.NO_QUESTION_REPLY
    assert calls == []


# ===== 錯誤處理：規格說這些都可能發生 =====


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status_code=500, text="Internal Server Error"),
        FakeResponse(status_code=401, text="unauthorized"),
        FakeResponse(status_code=200, body=b""),  # n8n 執行失敗會回 200 + 空 body
        FakeResponse(status_code=200, body=b"<html>not json</html>"),
        FakeResponse(json_data={"reply": ""}),
        FakeResponse(json_data={"error": "workflow failed"}),
        FakeResponse(json_data=["unexpected", "shape"]),
    ],
    ids=["500", "401", "empty-body", "not-json", "blank-reply", "no-reply", "not-dict"],
)
async def test_every_failure_mode_gives_the_same_apology(webhook, response):
    respond, _ = webhook
    respond(response)

    result = await agent.ask(raw_tail_text="你好", message=FakeMessage())

    assert result == agent.FAILURE_REPLY


async def test_connection_failure_gives_the_apology(webhook):
    """ngrok 掉了或 n8n 沒開都走這裡。"""
    respond, _ = webhook
    respond(RuntimeError("Connection refused"))

    result = await agent.ask(raw_tail_text="你好", message=FakeMessage())

    assert result == agent.FAILURE_REPLY


async def test_failure_details_never_reach_the_chat(webhook, caplog):
    respond, _ = webhook
    respond(FakeResponse(status_code=502, text="ngrok tunnel not found"))

    result = await agent.ask(raw_tail_text="你好", message=FakeMessage())

    for secret in ("ngrok", "502", "tunnel", "http"):
        assert secret not in result
    assert "502" in caplog.text  # 但 log 裡一定要查得到


async def test_missing_secret_does_not_call_the_webhook(webhook, monkeypatch):
    """沒設 TM_AI_AGENT_SECRET 時只該安靜失效，不是拿空 secret 去撞。"""
    _, calls = webhook
    monkeypatch.setattr(svc.n8n_ai_agent_client, "_secret", "")

    result = await agent.ask(raw_tail_text="你好", message=FakeMessage())

    assert result == agent.FAILURE_REPLY
    assert calls == []


# ===== 回覆清洗 =====


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("**粗體**", "粗體"),
        ("*斜體*", "斜體"),
        ("***又粗又斜***", "又粗又斜"),
        ("__底線__", "底線"),
        ("~~刪除線~~", "刪除線"),
        ("`程式碼`", "程式碼"),
        ("**_巢狀_**", "巢狀"),
        ("# 標題", "標題"),
        ("> 引言", "引言"),
        ("```python\nprint(1)\n```", "print(1)"),
    ],
)
def test_discord_markdown_is_removed(raw, expected):
    assert agent.clean_reply(raw) == expected


def test_newlines_become_a_visible_separator():
    """Twitch IRC 不支援換行，直接接起來會黏成一團。"""
    cleaned = agent.clean_reply("1. 熱搜A\n2. 熱搜B\n3. 熱搜C")

    assert "\n" not in cleaned
    assert cleaned == "1. 熱搜A / 2. 熱搜B / 3. 熱搜C"


def test_blank_lines_do_not_produce_empty_segments():
    cleaned = agent.clean_reply("第一段\n\n\n第二段")

    assert cleaned == "第一段 / 第二段"


def test_emoji_are_kept():
    assert "🐯" in agent.clean_reply("安安 🐯 好虎粉")


def test_twitch_emote_names_survive():
    assert "tigerm24Love" in agent.clean_reply("**安安** tigerm24Love")


def test_quickchart_urls_survive_untouched():
    """AI 畫統計圖會回 quickchart 網址，裡面的 _ 不能被當成斜體語法吃掉。"""
    url = "https://quickchart.io/chart?c={type:'bar',data:{labels:['a_b','c_d']}}&bkg=white"

    cleaned = agent.clean_reply(f"圖表在這 **請看**：{url}")

    assert url in cleaned


def test_markdown_links_keep_both_text_and_url():
    cleaned = agent.clean_reply("[虎喵頻道](https://twitch.tv/tigermeowtw)")

    assert "虎喵頻道" in cleaned
    assert "https://twitch.tv/tigermeowtw" in cleaned
    assert "[" not in cleaned and "](" not in cleaned


def test_over_length_reply_is_truncated_with_room_for_the_name_prefix():
    """message_controller 還會加上「@顯示名稱 」前綴，不能剛好貼滿 500。"""
    cleaned = agent.clean_reply("字" * 900)

    assert len(cleaned) == agent.MAX_REPLY_LENGTH
    assert cleaned.endswith(agent.TRUNCATE_SUFFIX)
    assert agent.MAX_REPLY_LENGTH < 500


def test_multiplication_in_calculator_output_is_not_eaten():
    """計算機工具的回覆含 * 號，加了空格就不該被當成斜體。"""
    assert agent.clean_reply("答案是 12 * 34 = 408") == "答案是 12 * 34 = 408"


def test_identifiers_with_underscores_are_not_eaten():
    """單一 _ 是 Discord 的斜體語法，但 snake_case 不該被當成斜體黏成一團。"""
    assert agent.clean_reply("欄位叫 snake_case_name 喔") == "欄位叫 snake_case_name 喔"


def test_bullet_markers_are_stripped():
    """Twitch 會把 * 原樣顯示，看起來像壞掉的 markdown。"""
    cleaned = agent.clean_reply("* 熱搜A\n* 熱搜B")

    assert cleaned == "熱搜A / 熱搜B"


# ===== 同頻道排隊 =====


async def test_same_channel_requests_are_serialized(webhook, monkeypatch):
    """n8n 端同 channel_id 共享記憶，並行送出會讓 AI 把兩個人的話搞混。"""
    order: list[str] = []

    async def _slow_ask(*, text, user_name, user_id, channel_id):
        order.append(f"start:{text}")
        await asyncio.sleep(0)
        order.append(f"end:{text}")
        return f"回覆 {text}"

    monkeypatch.setattr(svc.n8n_ai_agent_client, "ask", _slow_ask)

    await asyncio.gather(
        agent.ask(raw_tail_text="甲", message=FakeMessage(user_id="a")),
        agent.ask(raw_tail_text="乙", message=FakeMessage(user_id="b")),
    )

    # 沒有交錯：前一則收尾之後才會有下一則開頭
    assert order == ["start:甲", "end:甲", "start:乙", "end:乙"]


async def test_different_channels_run_in_parallel(webhook, monkeypatch):
    active = {"count": 0, "peak": 0}

    async def _slow_ask(*, text, user_name, user_id, channel_id):
        active["count"] += 1
        active["peak"] = max(active["peak"], active["count"])
        await asyncio.sleep(0)
        active["count"] -= 1
        return "回覆"

    monkeypatch.setattr(svc.n8n_ai_agent_client, "ask", _slow_ask)

    await asyncio.gather(
        agent.ask(raw_tail_text="甲", message=FakeMessage(channel_name="chan_a")),
        agent.ask(raw_tail_text="乙", message=FakeMessage(channel_name="chan_b")),
    )

    assert active["peak"] == 2


async def test_a_full_queue_asks_the_viewer_to_wait(webhook, monkeypatch):
    """每則最壞要等 120 秒，隊伍無上限成長會讓所有人都等到懷疑人生。"""
    gate = asyncio.Event()

    async def _blocking_ask(*, text, user_name, user_id, channel_id):
        await gate.wait()
        return "回覆"

    monkeypatch.setattr(svc.n8n_ai_agent_client, "ask", _blocking_ask)

    queued = [
        asyncio.create_task(agent.ask(raw_tail_text=f"問題{i}", message=FakeMessage()))
        for i in range(agent.MAX_WAITING_PER_CHANNEL)
    ]
    for _ in range(3):
        await asyncio.sleep(0)

    overflow = await agent.ask(raw_tail_text="插隊", message=FakeMessage())
    assert overflow == agent.BUSY_REPLY

    gate.set()
    await asyncio.gather(*queued)


async def test_queue_slot_is_released_after_a_failure(webhook, monkeypatch):
    """失敗也要把名額還回去，否則幾次錯誤之後就永遠卡在 BUSY。"""

    async def _boom(*, text, user_name, user_id, channel_id):
        raise RuntimeError("爆了")

    monkeypatch.setattr(svc.n8n_ai_agent_client, "ask", _boom)

    for _ in range(5):
        with pytest.raises(RuntimeError):
            await agent.ask(raw_tail_text="你好", message=FakeMessage())

    monkeypatch.setattr(
        svc.n8n_ai_agent_client,
        "ask",
        lambda **kwargs: _ok(),
    )

    async def _ok():
        return "還活著"

    assert await agent.ask(raw_tail_text="你好", message=FakeMessage()) == "還活著"


# ===== 成功路徑 =====


async def test_successful_reply_is_returned_cleaned(webhook):
    respond, _ = webhook
    respond(FakeResponse(json_data={"reply": "**安安**好虎粉\n今天過得好嗎 🐯"}))

    result = await agent.ask(raw_tail_text="你好", message=FakeMessage())

    assert result == "安安好虎粉 / 今天過得好嗎 🐯"
