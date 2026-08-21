"""啟動時的 Google Sheets 設定載入（CODE_REVIEW P1-37）。

過去 main() 直接 await 兩個 Sheets 呼叫且沒有 try，
9091 沒開 Bot 就完全起不來 —— 而它偏偏是四個微服務裡最容易忘記開的一個，
只在啟動那一瞬間用到，開台途中完全不會再碰。

「整場開台沒有機器人」比「少了 ! 指令」嚴重得多，所以這裡驗證的是
「任何一項載入失敗，都只會被記錄與回報，不會擋住啟動」。
"""

import pytest

from tm_twitch_bot import sheet_config as m


@pytest.fixture
def loaders(monkeypatch):
    """用假的載入器取代真正會打 9091 的那兩個。"""
    called: list[str] = []

    def _make(names_that_fail=()):
        async def _ok(name):
            called.append(name)

        def _build(name):
            async def _loader():
                called.append(name)
                if name in names_that_fail:
                    raise RuntimeError(f"連不上微服務（{name}）")

            return _loader

        monkeypatch.setattr(
            m, "SHEET_LOADERS", {"指令集": _build("指令集"), "轉職表": _build("轉職表")}
        )
        return called

    return _make


async def test_everything_loads_and_nothing_is_reported(loaders):
    called = loaders()

    failed = await m.load_sheet_config()

    assert failed == []
    assert called == ["指令集", "轉職表"]


async def test_one_failure_never_stops_the_other(loaders):
    called = loaders(names_that_fail=["指令集"])

    failed = await m.load_sheet_config()

    assert failed == ["指令集"]
    assert "轉職表" in called  # 前一項炸掉也要繼續載入下一項


async def test_all_failing_still_returns_instead_of_raising(loaders):
    loaders(names_that_fail=["指令集", "轉職表"])

    failed = await m.load_sheet_config()  # 不該拋出任何例外

    assert failed == ["指令集", "轉職表"]


async def test_failures_are_logged_with_the_item_name(loaders, caplog):
    loaders(names_that_fail=["轉職表"])

    await m.load_sheet_config()

    assert "轉職表" in caplog.text


async def test_only_the_requested_items_are_reloaded(loaders):
    """重試時只需要重載當初失敗的那些，不必動已經好了的。"""
    called = loaders()

    await m.load_sheet_config(["轉職表"])

    assert called == ["轉職表"]


async def test_recovered_items_drop_out_of_the_failed_list(loaders, monkeypatch):
    """服務晚一點開起來，重試就要能把項目移出降級清單。"""
    state = {"broken": True}

    async def _loader():
        if state["broken"]:
            raise RuntimeError("還沒開")

    monkeypatch.setattr(m, "SHEET_LOADERS", {"指令集": _loader})

    assert await m.load_sheet_config() == ["指令集"]
    state["broken"] = False
    assert await m.load_sheet_config(["指令集"]) == []
