"""n8n「TM AI Agent」webhook 串接。

n8n 端不屬於本專案，Bot 這側負責三件事：把欄位送齊、同頻道排隊、
任何失敗都只給觀眾一句道歉語。n8n 現在會偵測 twitch: 前綴並回純文字單行，
所以回覆處理只留下換行與長度兩道 Twitch 協定層的防線。
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


# ===== 回覆整形 =====
#
# n8n 端會偵測 twitch: 前綴，回覆保證是純文字單行、500 字元以內，
# 所以這裡只驗兩件事：該原樣通過的原樣通過，
# 以及兩道協定防線（換行、長度）在保證失效時仍然守得住。


@pytest.mark.parametrize(
    "raw",
    [
        "安安好虎粉 🐯 tigerm24Love",
        "答案是 12 * 34 = 408",
        "欄位叫 snake_case_name 喔",
        "圖表在這 https://quickchart.io/chart/render/zf-b0d974e6-a05b",
        "https://quickchart.io/chart?c={type:'bar',data:{labels:['a_b','c_d']}}&bkg=white",
    ],
    ids=["emoji-emote", "calculator", "identifier", "chart-url", "url-underscores"],
)
def test_plain_text_passes_through_untouched(raw):
    """n8n 給的已經是純文字，這裡不該再自作聰明去動它。

    列出來的每一項都是舊版剝 Markdown 時真的會弄壞的字串
    （`*` 與 `_` 被當成語法），拿掉那套之後正好變成迴歸保護。
    """
    assert agent.clean_reply(raw) == raw


def test_newlines_become_a_visible_separator():
    """IRC 以換行作為一則訊息的結尾，混進 \\n 會讓後半段變成另一行協定內容。

    n8n 保證不會有換行，但這是協定層的安全問題而不是排版問題，
    保證失效的代價太大，所以這道防線刻意留著。
    """
    cleaned = agent.clean_reply("1. 熱搜A\n2. 熱搜B\n3. 熱搜C")

    assert "\n" not in cleaned
    assert cleaned == "1. 熱搜A / 2. 熱搜B / 3. 熱搜C"


@pytest.mark.parametrize("break_char", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_a_lone_carriage_return_is_flattened_too(break_char):
    """split("\\n") 會漏掉單獨的 \\r，而 IRC 對 \\r 一樣敏感。"""
    cleaned = agent.clean_reply(f"前段{break_char}後段")

    assert cleaned == "前段 / 後段"


def test_blank_lines_do_not_produce_empty_segments():
    cleaned = agent.clean_reply("第一段\n\n\n第二段")

    assert cleaned == "第一段 / 第二段"


def test_over_length_reply_is_truncated_with_room_for_the_name_prefix():
    cleaned = agent.clean_reply("字" * 900)

    assert len(cleaned) == agent.MAX_REPLY_LENGTH
    assert cleaned.endswith(agent.TRUNCATE_SUFFIX)
    assert agent.MAX_REPLY_LENGTH < 500


def test_a_reply_at_n8n_max_still_fits_after_the_longest_prefix():
    """n8n 的上限剛好等於 Twitch 的上限，中間卻夾了一個前綴——這就是缺口。

    前綴是 message_controller 加的「@顯示名稱 」，n8n 不知道有這回事。
    Twitch 對超長訊息是整則丟掉而不是截斷，所以「剛好 500」等於整則消失。
    顯示名稱上限 25 字元，加上 @ 與空格共 27。
    """
    cleaned = agent.clean_reply("字" * 500)
    longest_prefix = "@" + "x" * 25 + " "

    assert len(longest_prefix + cleaned) <= 500


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
    respond(FakeResponse(json_data={"reply": "安安好虎粉\n今天過得好嗎 🐯"}))

    result = await agent.ask(raw_tail_text="你好", message=FakeMessage())

    assert result == "安安好虎粉 / 今天過得好嗎 🐯"
