"""發話的速率與長度保護（CODE_REVIEW P1-14）。

Twitch 對超量發言的懲罰是整個帳號被靜音約 30 分鐘 ——
這是少數「錯一次就整場開台都毀了」的地方，所以測試盯得比較緊。
"""

import asyncio

import pytest

from tm_twitch_bot.utils import chat_sender as cs


class FakeClock:
    """假時鐘：sleep 不會真的等，只把時間往前推。"""

    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sender(clock):
    # 用小一點的視窗參數，測試才讀得懂
    return cs.ChatSender(
        rate_limit=3,
        window_seconds=30.0,
        max_waiting=5,
        sleep=clock.sleep,
        now=clock,
    )


@pytest.fixture
def recorder():
    sent: list[str] = []

    async def _send(content: str) -> None:
        sent.append(content)

    return _send, sent


# ===== 換行 =====
#
# IRC 以換行作為一則訊息的結尾，而 twitchio 的 check_content 只驗長度。
# 混進 \n 的話後半段會被當成另一行協定內容，觀眾只看到前半段就沒了。


async def test_multiline_message_is_flattened_to_one_line(sender, recorder):
    send, sent = recorder

    await sender.send(send, "第一行\n第二行\n第三行")

    assert sent == ["第一行 / 第二行 / 第三行"]
    assert "\n" not in sent[0]


@pytest.mark.parametrize("break_char", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
async def test_a_lone_carriage_return_is_flattened_too(sender, recorder, break_char):
    """split("\\n") 會漏掉單獨的 \\r，而 IRC 對 \\r 一樣敏感。"""
    send, sent = recorder

    await sender.send(send, f"前段{break_char}後段")

    assert sent == ["前段 / 後段"]


async def test_blank_lines_do_not_produce_empty_segments(sender, recorder):
    send, sent = recorder

    await sender.send(send, "第一段\n\n\n第二段")

    assert sent == ["第一段 / 第二段"]


async def test_a_message_of_only_newlines_is_never_sent(sender, recorder):
    """整平後變成空字串，送空的 PRIVMSG 沒有意義。"""
    send, sent = recorder

    assert await sender.send(send, "\n\n  \n") is False
    assert sent == []


async def test_flatten_happens_before_truncation(sender, recorder):
    """分隔符會佔字數，先截再整平就可能又超過上限。"""
    send, sent = recorder
    # 每行 200 字元共 3 行，整平後 600 + 分隔符，一定要截到 500
    await sender.send(send, "\n".join(["字" * 200] * 3))

    assert len(sent[0]) == cs.MAX_MESSAGE_LENGTH
    assert "\n" not in sent[0]


def test_flatten_leaves_single_line_content_untouched():
    """絕大多數訊息本來就是單行，不該被動到。"""
    for text in ["大家沒事多喝水", "答案是 12 * 34 = 408", "https://a.com/b_c"]:
        assert cs.flatten(text) == text


# ===== 長度 =====


async def test_normal_message_passes_through_untouched(sender, recorder):
    send, sent = recorder

    assert await sender.send(send, "大家沒事多喝水") is True
    assert sent == ["大家沒事多喝水"]


async def test_message_exactly_at_the_limit_is_untouched(sender, recorder):
    send, sent = recorder
    content = "字" * cs.MAX_MESSAGE_LENGTH

    await sender.send(send, content)

    assert sent == [content]


async def test_over_length_message_is_truncated_not_dropped(sender, recorder):
    """Twitch 對超長訊息是整則丟掉，自己先截至少還看得到前半段。"""
    send, sent = recorder

    await sender.send(send, "字" * 900)

    assert len(sent) == 1
    assert len(sent[0]) == cs.MAX_MESSAGE_LENGTH
    assert sent[0].endswith(cs.TRUNCATE_SUFFIX)


async def test_empty_message_is_never_sent(sender, recorder):
    send, sent = recorder

    assert await sender.send(send, "") is False
    assert sent == []


# ===== 速率 =====


async def test_within_the_limit_nothing_waits(sender, recorder, clock):
    send, sent = recorder

    for i in range(3):
        await sender.send(send, f"訊息{i}")

    assert len(sent) == 3
    assert clock.slept == []  # 沒踩到上限就不該有任何延遲


async def test_exceeding_the_limit_waits_for_the_window(sender, recorder, clock):
    send, sent = recorder

    for i in range(4):  # rate_limit=3，第 4 則必須等
        await sender.send(send, f"訊息{i}")

    assert len(sent) == 4  # 是「延後送出」而不是丟棄
    assert clock.slept == [30.0]


async def test_window_slides_so_old_messages_free_up_slots(sender, recorder, clock):
    send, sent = recorder

    for i in range(3):
        await sender.send(send, f"舊訊息{i}")
    clock.advance(31)  # 整個視窗都過去了
    await sender.send(send, "新訊息")

    assert clock.slept == []
    assert sent[-1] == "新訊息"


async def test_rate_window_is_shared_across_different_send_targets(sender, clock):
    """限制是綁在帳號上的，不是綁在頻道物件上。"""
    a_sent, b_sent = [], []

    async def send_a(content):
        a_sent.append(content)

    async def send_b(content):
        b_sent.append(content)

    for i in range(2):
        await sender.send(send_a, f"a{i}")
    for i in range(2):
        await sender.send(send_b, f"b{i}")

    assert clock.slept == [30.0]  # 第 4 則（不論由誰送）就該等


# ===== 塞車 =====


async def test_backlog_is_dropped_instead_of_piling_up(sender, clock):
    """等待中的訊息滿了就直接丟棄，避免一堆 handle_message 全卡在這裡。"""
    gate = asyncio.Event()
    sent: list[str] = []

    async def blocking_send(content: str) -> None:
        await gate.wait()
        sent.append(content)

    tasks = [
        asyncio.create_task(sender.send(blocking_send, f"訊息{i}"))
        for i in range(5)  # max_waiting=5，正好塞滿
    ]
    for _ in range(3):
        await asyncio.sleep(0)  # 讓每個 task 都跑到等待點

    assert await sender.send(blocking_send, "第六則") is False
    assert sender.dropped == 1

    gate.set()
    await asyncio.gather(*tasks)
    assert "第六則" not in sent


async def test_waiting_counter_is_released_after_a_failed_send(sender, clock):
    """送出失敗也要把名額還回去，否則幾次錯誤之後就永遠塞車。"""

    async def boom(content: str) -> None:
        raise RuntimeError("Twitch 拒絕發言")

    for _ in range(10):
        with pytest.raises(RuntimeError):
            await sender.send(boom, "會炸的訊息")

    ok: list[str] = []

    async def fine(content: str) -> None:
        ok.append(content)

    assert await sender.send(fine, "還活著") is True


async def test_send_errors_reach_the_caller(sender):
    """呼叫端有自己的錯誤處理，這裡不該偷偷吞掉例外。"""

    async def boom(content: str) -> None:
        raise RuntimeError("Twitch 拒絕發言")

    with pytest.raises(RuntimeError):
        await sender.send(boom, "訊息")


# ===== 順序與介面 =====


async def test_messages_keep_the_order_they_were_queued_in(sender):
    sent: list[str] = []

    async def slow_send(content: str) -> None:
        await asyncio.sleep(0)
        sent.append(content)

    await asyncio.gather(
        *(sender.send(slow_send, f"訊息{i}") for i in range(3))
    )

    assert sent == ["訊息0", "訊息1", "訊息2"]


async def test_bind_produces_a_single_argument_sender(sender, recorder):
    send, sent = recorder

    bound = sender.bind(send)
    await bound("透過 bind 送出")

    assert sent == ["透過 bind 送出"]


async def test_reset_clears_the_window(sender, recorder, clock):
    send, _ = recorder

    for i in range(3):
        await sender.send(send, f"訊息{i}")
    sender.reset()
    await sender.send(send, "重置之後")

    assert clock.slept == []


def test_default_settings_stay_under_the_official_limit():
    """官方是 30 秒 20 則；預設值必須留餘裕，不能剛好貼著。"""
    assert cs.RATE_LIMIT < 20
    assert cs.WINDOW_SECONDS >= 30
    assert cs.MAX_MESSAGE_LENGTH == 500
