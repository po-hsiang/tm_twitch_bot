"""訊息處理管線的容錯與存檔保證。

這條管線上任何一步失敗（微服務暫時不可用、Twitch 拒絕發言…），
都不能讓玩家已經到手的經驗與金幣蒸發。
"""

import pytest

from tm_twitch_bot.scripts import message_controller as mc
from tm_twitch_bot.svc_client.mongo_atlas import mongo_atlas_client
from tm_twitch_bot.utils.yaml_utils import config


class FakeAuthor:
    def __init__(self, user_id: str, name: str, display_name: str):
        self.id = user_id
        self.name = name
        self.display_name = display_name


class FakeChannel:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class FakeMessage:
    def __init__(self, content: str, user_id: str = "u1"):
        self.author = FakeAuthor(user_id, "tester", "測試員")
        self.channel = FakeChannel()
        self.content = content


@pytest.fixture(autouse=True)
def _reset_module_state():
    """冷卻與洗頻紀錄都是模組級 dict，測試之間必須隔離。"""
    mc._last_cmd_ts.clear()
    mc._last_message.clear()
    yield
    mc._last_cmd_ts.clear()
    mc._last_message.clear()


@pytest.fixture
def fake_mongo(monkeypatch):
    """攔截所有 MongoDB 存取，回傳可檢查的呼叫紀錄。"""
    store: dict[str, list] = {"docs": [], "updates": [], "inserts": []}

    async def find(collection, filter=None, projection=None, sort=None, limit=None):
        return store["docs"]

    async def update(collection, update, filter=None, upsert=False, many=False):
        store["updates"].append(update)

    async def insert_one(collection, doc):
        store["inserts"].append(doc)

    monkeypatch.setattr(mongo_atlas_client, "find", find)
    monkeypatch.setattr(mongo_atlas_client, "update", update)
    monkeypatch.setattr(mongo_atlas_client, "insert_one", insert_one)
    return store


@pytest.fixture(autouse=True)
def _quiet_greeter(monkeypatch):
    """預設不打招呼，避免測試碰到 Google Sheets。"""

    async def _no_greeting(user_id):
        return ""

    monkeypatch.setattr(mc, "greet_user", _no_greeting)


def saves_of(store) -> list[dict]:
    """從所有 update 中挑出角色存檔，排除發言計數。

    角色存檔一定帶 $set（至少有 updated_at），發言計數只有 $inc，
    因此看有沒有 $set 就分得出來。金額本身則走 $inc（見 P2-23）。
    """
    return [u for u in store["updates"] if "$set" in u]


# ===== 正常流程 =====


async def test_new_user_is_created_and_saved(fake_mongo, monkeypatch):
    async def no_command(*args, **kwargs):
        return ""

    monkeypatch.setattr(mc, "dispatch_command", no_command)

    await mc.handle_message(FakeMessage("安安"))

    assert len(fake_mongo["inserts"]) == 1  # 創角
    assert len(saves_of(fake_mongo)) == 1  # 存檔一次
    assert saves_of(fake_mongo)[0]["$inc"]["gold"] == 1  # 發言得 1 金幣（差額）


async def test_command_reply_is_sent_to_channel(fake_mongo, monkeypatch):
    async def reply(*args, **kwargs):
        return "英雄榜"

    monkeypatch.setattr(mc, "dispatch_command", reply)
    message = FakeMessage("!英雄")

    await mc.handle_message(message)

    assert message.channel.sent == ["@測試員 英雄榜"]


async def test_bot_messages_are_ignored(fake_mongo):
    bot_id = config["bot_user_id"][0]

    await mc.handle_message(FakeMessage("我是機器人", user_id=bot_id))

    assert fake_mongo["updates"] == []
    assert fake_mongo["inserts"] == []


# ===== 容錯：這幾項是 P0-5 的核心 =====


async def test_rewards_are_saved_even_when_command_raises(fake_mongo, monkeypatch):
    """指令函式炸掉時，本次發言已賺到的經驗與金幣仍要落地。"""

    async def boom(*args, **kwargs):
        raise RuntimeError("MongoDB 微服務無回應")

    monkeypatch.setattr(mc, "dispatch_command", boom)

    await mc.handle_message(FakeMessage("!壞掉的指令"))

    saves = saves_of(fake_mongo)
    assert len(saves) == 1
    assert saves[0]["$inc"]["gold"] == 1
    assert saves[0]["$inc"]["exp"] == 1


async def test_greeting_failure_does_not_abort_the_pipeline(fake_mongo, monkeypatch):
    async def boom(user_id):
        raise RuntimeError("Sheets 服務無回應")

    async def no_command(*args, **kwargs):
        return ""

    monkeypatch.setattr(mc, "greet_user", boom)
    monkeypatch.setattr(mc, "dispatch_command", no_command)

    await mc.handle_message(FakeMessage("安安"))  # 不應拋出例外

    # 招呼失敗發生在給獎之前，本次沒有異動就不會有存檔
    assert saves_of(fake_mongo) == []


async def test_no_exception_escapes_even_when_saving_fails(fake_mongo, monkeypatch):
    """存檔本身失敗也只能記錄，不能往外拋——否則會蓋掉原本真正的錯誤。"""

    async def failing_update(*args, **kwargs):
        raise RuntimeError("寫入失敗")

    async def no_command(*args, **kwargs):
        return ""

    monkeypatch.setattr(mongo_atlas_client, "update", failing_update)
    monkeypatch.setattr(mc, "dispatch_command", no_command)

    await mc.handle_message(FakeMessage("安安"))  # 不應拋出例外


# ===== 不必要的存檔要避免 =====


async def test_cooldown_blocked_message_is_not_saved(fake_mongo, monkeypatch):
    async def no_command(*args, **kwargs):
        return ""

    monkeypatch.setattr(mc, "dispatch_command", no_command)

    await mc.handle_message(FakeMessage("第一句"))
    before = len(saves_of(fake_mongo))
    fake_mongo["docs"] = [{"user_id": "u1", "usernames": ["tester"], "display_names": ["測試員"]}]

    await mc.handle_message(FakeMessage("三秒內的第二句"))

    # 被冷卻擋下、角色沒有任何異動，就不該再白跑一次 DB 寫入
    assert len(saves_of(fake_mongo)) == before


async def test_repeated_message_is_not_saved(fake_mongo, monkeypatch):
    async def no_command(*args, **kwargs):
        return ""

    monkeypatch.setattr(mc, "dispatch_command", no_command)
    monkeypatch.setattr(mc, "CHAT_CD", 0)  # 排除冷卻干擾，只驗洗頻

    await mc.handle_message(FakeMessage("一樣的話"))
    before = len(saves_of(fake_mongo))
    fake_mongo["docs"] = [{"user_id": "u1", "usernames": ["tester"], "display_names": ["測試員"]}]

    await mc.handle_message(FakeMessage("一樣的話"))

    assert len(saves_of(fake_mongo)) == before
