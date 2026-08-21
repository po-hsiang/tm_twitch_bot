"""試算表熱重載（CODE_REVIEW P2-26）。

要鎖住的性質有四個：
1. 只有管理員能重載（重載會打 9091，而且會換掉全頻道的指令集）
2. 一張表失敗不能連帶讓其他張也不重載
3. 重載失敗**不能**把線上那份指令集清空——那會比不重載嚴重得多
4. 內容表只清「表的快取」，不清「一人一次」那類遊戲規則
"""

import logging

import pytest

from tm_twitch_bot import sheet_config as sr
from tm_twitch_bot.chat import dispatcher as cd
from tm_twitch_bot.commands.reload import reload
from tm_twitch_bot.config.loader import config

ADMIN = "359"
COMMAND_SHEET = [
    ["觸發字", "類型", "內容"],
    ["!英雄", "text", "英雄榜"],
]


class FakeChar:
    def __init__(self, user_id: str = ADMIN):
        self.user_id = user_id


@pytest.fixture(autouse=True)
def _admin(monkeypatch):
    monkeypatch.setitem(config, "admin_user_id", [ADMIN])


@pytest.fixture
def spy_registry(monkeypatch):
    """把兩份登錄表換成間諜，驗「每一張表都真的被處理到」。"""
    called: list[str] = []

    def _make_loader(name: str, *, boom: bool = False):
        async def _loader():
            called.append(name)
            if boom:
                raise RuntimeError(f"{name} 抓不到")

        return _loader

    def _install(*, failing: tuple[str, ...] = ()):
        monkeypatch.setattr(
            sr,
            "SHEET_LOADERS",
            {
                name: _make_loader(name, boom=name in failing)
                for name in ("指令集", "轉職表")
            },
        )
        monkeypatch.setattr(
            sr,
            "POOL_CLEARERS",
            {
                name: (lambda n=name: called.append(n))
                for name in ("吃啥", "酷酷的諧音梗", "冒險台詞")
            },
        )
        return called

    return _install


# ===== 權限 =====


async def test_a_regular_viewer_cannot_reload(spy_registry):
    called = spy_registry()

    assert await reload(char=FakeChar(user_id="路人")) == ""
    assert called == []  # 連一張表都不該去抓


async def test_missing_char_cannot_reload(spy_registry):
    """context 拿不到 char（例如從排程呼叫）時一律當成沒權限。"""
    called = spy_registry()

    assert await reload() == ""
    assert called == []


# ===== 正常路徑 =====


async def test_the_admin_reloads_every_sheet(spy_registry):
    called = spy_registry()

    reply = await reload(char=FakeChar())

    assert sorted(called) == sorted(
        ["指令集", "轉職表", "吃啥", "酷酷的諧音梗", "冒險台詞"]
    )
    assert "已重新載入 5 張表" in reply


async def test_the_reply_reports_how_many_commands_are_live(spy_registry, monkeypatch):
    """回覆要帶指令筆數：那是「這次到底載到了什麼」唯一看得見的證據。"""
    spy_registry()
    monkeypatch.setitem(cd.COMMAND_SET, "!英雄", ("text", "英雄榜"))

    reply = await reload(char=FakeChar())

    assert f"{len(cd.COMMAND_SET)} 筆" in reply


async def test_stale_function_bindings_are_dropped(spy_registry, monkeypatch):
    """指令集換了新的一份，綁好的函式快取不能比它活得久。"""
    spy_registry()
    cd._load_function.cache_clear()
    cd._load_function("shlex.split")  # 隨便綁一個，讓快取裡有東西
    assert cd._load_function.cache_info().currsize == 1

    await reload(char=FakeChar())

    assert cd._load_function.cache_info().currsize == 0


# ===== 失敗路徑 =====


async def test_one_broken_sheet_does_not_block_the_others(spy_registry):
    called = spy_registry(failing=("指令集",))

    reply = await reload(char=FakeChar())

    assert "轉職表" in called  # 前一張炸掉了，後一張還是要載
    assert "⚠️" in reply
    assert "重新載入失敗：指令集" in reply
    assert "轉職表" in reply  # 成功的也要說，不然不知道哪些生效了


async def test_the_failure_reason_is_logged_not_replied(spy_registry, caplog):
    """例外訊息會夾帶微服務網址，只能進 log（P1-11）。"""
    spy_registry(failing=("轉職表",))

    with caplog.at_level(logging.ERROR):
        reply = await reload(char=FakeChar())

    assert "抓不到" in caplog.text
    assert "抓不到" not in reply
    assert "RuntimeError" not in reply


async def test_a_failed_reload_keeps_the_live_command_set(monkeypatch):
    """這是最重要的一條：重載失敗絕不能讓 Bot 變成沒有指令。

    load_command_set 是「先抓表、成功才 clear + update」，
    所以抓表失敗時線上那份完全不受影響。
    """
    cd.COMMAND_SET.clear()
    cd.COMMAND_SET.update(cd._parse_sheet(COMMAND_SHEET))
    before = dict(cd.COMMAND_SET)

    async def boom(sheet_name: str):
        raise RuntimeError("Sheets 服務無回應")

    monkeypatch.setattr(cd.google_sheets_client, "get_sheet_data", boom)
    monkeypatch.setattr(sr, "SHEET_LOADERS", {"指令集": cd.load_command_set})
    monkeypatch.setattr(sr, "POOL_CLEARERS", {})

    reply = await reload(char=FakeChar())

    assert cd.COMMAND_SET == before
    assert "指令集" in reply
    cd.COMMAND_SET.clear()


# ===== 登錄表本身 =====


async def test_startup_and_reload_read_the_same_list(spy_registry):
    """啟動載入與 !reload 必須吃同一份清單，不能各自維護。

    這一條靠「換掉 SHEET_LOADERS 之後兩個入口都跟著變」來驗：
    如果哪天有人在 main 或 bot 那邊自己複製一份清單，這裡就會紅。
    """
    called = spy_registry()

    await sr.load_sheet_config()
    assert sorted(called) == ["指令集", "轉職表"]

    called.clear()
    await sr.reload_all()
    assert "指令集" in called and "轉職表" in called


def test_lazy_content_sheets_are_not_loaded_at_startup():
    """啟動時就抓內容表只是把 9091 的風險提前，沒有任何好處（P1-37）。"""
    assert set(sr.SHEET_LOADERS) == {"指令集", "轉職表"}
    assert set(sr.POOL_CLEARERS) == {"吃啥", "酷酷的諧音梗", "冒險台詞"}
