"""共用的 SingletonMeta（CODE_REVIEW P2-21）。

八份複製合併成一份，最需要鎖住的不是「回傳同一顆實例」——那八份本來就對——
而是**合併帶來的新風險**：八把鎖變成一把，非可重入的鎖會讓「單例的 __init__
裡建立另一個單例」直接死鎖。那種故障沒有錯誤訊息，只是整個程式停住。
"""

import threading

import pytest

from tm_twitch_bot.games.gold_rush_game import GoldRushGame, gold_rush_game
from tm_twitch_bot.games.guess_number_game import GuessNumberGame, guess_number_game
from tm_twitch_bot.scripts.vip_system import VipSystem, vip_system
from tm_twitch_bot.svc_client.google_sheets import GoogleSheetsClient, google_sheets_client
from tm_twitch_bot.svc_client.mongo_atlas import MongoAtlasClient, mongo_atlas_client
from tm_twitch_bot.svc_client.n8n_ai_agent import N8nAiAgentClient, n8n_ai_agent_client
from tm_twitch_bot.svc_client.openai import OpenAIClient, openai_client
from tm_twitch_bot.svc_client.youtube import YouTubeClient, youtube_client
from tm_twitch_bot.utils.singleton import SingletonMeta

# 八個真的在用它的類別，以及各模組匯出的那顆實例。
# 新增第九個單例時請一起加進來——這份清單就是「哪些東西是單例」的答案。
LIVE_SINGLETONS = [
    (GoogleSheetsClient, google_sheets_client),
    (MongoAtlasClient, mongo_atlas_client),
    (OpenAIClient, openai_client),
    (YouTubeClient, youtube_client),
    (N8nAiAgentClient, n8n_ai_agent_client),
    (VipSystem, vip_system),
    (GoldRushGame, gold_rush_game),
    (GuessNumberGame, guess_number_game),
]


@pytest.mark.parametrize(
    "cls, instance", LIVE_SINGLETONS, ids=lambda v: getattr(v, "__name__", "")
)
def test_constructing_again_returns_the_module_level_instance(cls, instance):
    """再 `Cls()` 一次不能生出第二顆——模組層那顆才是全專案共用的狀態。"""
    assert cls() is instance
    assert cls() is cls()


def test_every_live_singleton_uses_the_shared_metaclass():
    """有人自己再貼一份 metaclass 的話，這裡會抓到。"""
    for cls, _ in LIVE_SINGLETONS:
        assert type(cls) is SingletonMeta, f"{cls.__name__} 沒有用共用的 SingletonMeta"


def test_the_shared_lock_is_reentrant():
    """一把共用的鎖必須可重入，否則巢狀建立單例就是死鎖。

    直接驗鎖的型別，而不是靠下面那個「真的巢狀建立」的測試——
    那個測試若失敗會是整個 pytest 卡住（沒有錯誤訊息、沒有 timeout），
    debug 起來比一行 assert 痛苦得多。
    """
    assert isinstance(SingletonMeta._lock, type(threading.RLock()))


def test_a_singleton_can_build_another_singleton_in_its_init():
    """P2-21 合併八把鎖之後唯一真正的新風險。

    八份各有自己的鎖時這樣寫是安全的；共用一把非可重入的鎖就會死鎖。
    這個測試若壞掉，症狀是整個測試程序停在這裡不動。
    """

    class Inner(metaclass=SingletonMeta):
        pass

    class Outer(metaclass=SingletonMeta):
        def __init__(self):
            self.inner = Inner()

    outer = Outer()

    assert outer.inner is Inner()
    assert Outer() is outer


def test_each_class_gets_its_own_instance():
    """`_instances` 是共用的一份 dict，以類別為 key——不能互相蓋掉。"""

    class A(metaclass=SingletonMeta):
        pass

    class B(metaclass=SingletonMeta):
        pass

    assert A() is not B()
    assert isinstance(A(), A)
    assert isinstance(B(), B)


def test_init_runs_exactly_once():
    """單例的 __init__ 只跑一次，不會每次 `Cls()` 又重置一遍狀態。"""
    calls = []

    class Counter(metaclass=SingletonMeta):
        def __init__(self):
            calls.append(1)

    Counter()
    Counter()
    Counter()

    assert len(calls) == 1


def test_concurrent_construction_from_threads_gives_one_instance():
    """鎖真正要防的情境：兩條執行緒同時第一次呼叫 `Cls()`。"""
    seen: list[object] = []
    start = threading.Barrier(4)

    class Racy(metaclass=SingletonMeta):
        pass

    def build():
        start.wait()
        seen.append(Racy())

    threads = [threading.Thread(target=build) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(seen) == 4
    assert len(set(id(obj) for obj in seen)) == 1
