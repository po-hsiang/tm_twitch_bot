"""Token 寫回 .env 的順序（CODE_REVIEW P1-18）。

`update()` 會呼叫兩次 dotenv 的 set_key。單次是原子的，但兩次之間崩潰
會留下不一致的一對，而 Twitch 的 refresh token 用過就輪替 ——
哪一半留舊的，決定了下次啟動是自動復原還是要人工重跑 OAuth。
"""

import pytest

from tm_twitch_bot.utils import token_manager as tm


@pytest.fixture
def writes(monkeypatch):
    """攔下 set_key，記錄寫入順序。"""
    recorded: list[tuple[str, str]] = []

    def _set_key(path, key, value):
        recorded.append((key, value))

    monkeypatch.setattr(tm, "set_key", _set_key)
    return recorded


@pytest.fixture
def manager():
    """每個測試一顆乾淨的 TokenManager（正式環境是模組級單例）。

    `update()` 會順手改寫全域的 config dict，用完要還原，
    否則假 token 會漏到其他測試去。
    """
    original = dict(tm.config["twitch"])
    instance = tm.TokenManager()
    instance._access_token = "舊access"
    instance._refresh_token = "舊refresh"
    instance._listeners = []
    yield instance
    tm.config["twitch"].update(original)


def test_refresh_token_is_written_before_access_token(manager, writes):
    """順序反了的話，崩在中間會留下「新 access ＋ 已失效的舊 refresh」。

    那個狀態最陰險：下次啟動 validate() 會通過，看起來一切正常，
    等到 access 過期要刷新時才發現 refresh 已經不能用，只能重跑授權。
    """
    manager.update("新access", "新refresh")

    assert [key for key, _ in writes] == [
        "TWITCH_REFRESH_TOKEN",
        "TWITCH_ACCESS_TOKEN",
    ]


def test_a_crash_between_the_two_writes_stays_recoverable(manager, monkeypatch):
    """只寫成第一個就崩掉時，留在 .env 裡的必須是新的 refresh_token。

    這樣下次啟動 validate() 發現 access 失效，還能用它換到新的一對。
    """
    written: dict[str, str] = {}

    def _set_key(path, key, value):
        if key == "TWITCH_ACCESS_TOKEN":
            raise OSError("模擬寫檔中途斷電")
        written[key] = value

    monkeypatch.setattr(tm, "set_key", _set_key)

    with pytest.raises(OSError):
        manager.update("新access", "新refresh")

    assert written == {"TWITCH_REFRESH_TOKEN": "新refresh"}


def test_memory_is_updated_before_any_write(manager, writes):
    """執行中的程序不該受寫檔結果影響。"""
    manager.update("新access", "新refresh")

    assert manager.access_token == "新access"
    assert manager.refresh_token == "新refresh"
    assert tm.config["twitch"]["access_token"] == "新access"
    assert tm.config["twitch"]["refresh_token"] == "新refresh"


def test_listeners_are_notified_after_the_write(manager, writes):
    seen: list[tuple[str, str]] = []
    manager.add_listener(lambda a, r: seen.append((a, r)))

    manager.update("新access", "新refresh")

    assert seen == [("新access", "新refresh")]


def test_one_failing_listener_does_not_block_the_others(manager, writes):
    """單一訂閱者失敗不能影響其他訂閱者，也不能讓刷新流程中斷。"""
    seen: list[str] = []

    def _boom(a, r):
        raise RuntimeError("這個訂閱者壞了")

    manager.add_listener(_boom)
    manager.add_listener(lambda a, r: seen.append("第二個有跑到"))

    manager.update("新access", "新refresh")

    assert seen == ["第二個有跑到"]
