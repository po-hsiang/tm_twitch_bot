from tm_twitch_bot.clients.mongo_atlas import mongo_atlas_client
from tm_twitch_bot.model.jobs import JOB_CONFIG
from tm_twitch_bot.config.loader import config
from tm_twitch_bot.utils.log_utils import logger
from tm_twitch_bot.utils.time_utils import now_tw_iso
from dataclasses import dataclass, field, asdict
import random
import re

rpg_parameter = config["rpg_parameter"]

DEFAULT_ATTRIBUTES: dict[str, int] = {
    "STR": 1,
    "AGI": 1,
    "VIT": 1,
    "INT": 1,
    "DEX": 1,
    "LUK": 1,
}


@dataclass
class Character:
    user_id: str
    usernames: list[str]
    display_names: list[str]
    level: int = 1
    exp: int = 0
    gold: int = 0
    job: str = "初學者"
    attributes: dict[str, int] = field(
        default_factory=lambda: DEFAULT_ATTRIBUTES.copy()
    )

    def __post_init__(self):
        # 刻意「不」宣告成 dataclass field，asdict() 才不會把它一起寫進 MongoDB。
        # 用途：讓 message_controller 知道這次訊息有沒有改到角色，
        # 沒改到就不用白跑一次存檔，改到了就一定要存（即使中途出錯）。
        self._dirty = False
        # 同樣不是 dataclass field。存檔要送「差額」而不是絕對值，
        # 因此得記住載入當下的數值當作基準線（見 save()）。
        self._baseline = self._snapshot()

    def _snapshot(self) -> dict:
        """記下目前的數值欄位，作為下次存檔算差額的基準。"""
        return {
            "level": self.level,
            "exp": self.exp,
            "gold": self.gold,
            "job": self.job,
            "attributes": dict(self.attributes),
        }

    # ---------- 髒資料追蹤 ----------

    @property
    def display_name(self) -> str:
        """給觀眾看的名稱，保證取得到。

        直接寫 `display_names[-1]` 會對舊文件炸 IndexError：
        `from_dict` 用的是 `doc.get("display_names", [])`，而
        `find_by_name()` 與 `find_by_user_id()` 這兩條路是直接撈文件、
        **不補名字**的（只有 `get_or_create()` 會補）。
        所以 `!pk` 對上一份缺這個欄位的舊文件就會整個指令掛掉。
        依序退回 usernames、user_id——名字醜一點都比炸掉好。
        """
        if self.display_names:
            return self.display_names[-1]
        if self.usernames:
            return self.usernames[-1]
        return self.user_id

    @property
    def username(self) -> str:
        """登入帳號名，同樣保證取得到（理由見 display_name）。"""
        if self.usernames:
            return self.usernames[-1]
        if self.display_names:
            return self.display_names[-1]
        return self.user_id

    @property
    def is_dirty(self) -> bool:
        """自上次存檔以來是否有異動。"""
        return self._dirty

    def mark_dirty(self) -> None:
        self._dirty = True

    # ---------- 物件與 dict 轉換 ----------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, doc: dict) -> "Character":
        char = cls(
            user_id=doc["user_id"],
            usernames=doc.get("usernames", []),
            display_names=doc.get("display_names", []),
            level=doc.get("level", 1),
            exp=doc.get("exp", 0),
            gold=doc.get("gold", 0),
            job=doc.get("job", "初學者"),
            attributes=doc.get("attributes", DEFAULT_ATTRIBUTES.copy()),
        )
        # 基準線要對齊「資料庫裡實際有什麼」，而不是補完預設值之後的樣子：
        # 舊文件若缺 attributes，補上的預設值不能被當成已經寫進 DB，
        # 否則那六個屬性永遠不會有機會被寫入。
        char._baseline["attributes"] = dict(doc.get("attributes") or {})
        return char

    # ---------- DB 相關 ----------

    @staticmethod
    def _now_str() -> str:
        return now_tw_iso()

    @classmethod
    async def load_or_create(
        cls, user_id: str, username: str, display_name: str
    ) -> "Character":
        """
        從 Twitch 拿到的 username, display_name 是字串沒錯
        但因為這兩個值可以被使用者更換, 所以我想要存成 list, 後續有新的可以 Append
        """

        # 先找找看, 存在就轉為物件並補最新 username, display_name
        doc = await mongo_atlas_client.find(
            "tm_twitch_users", filter={"user_id": user_id}, limit=1
        )
        if doc:
            char = cls.from_dict(doc[0])
            char._maybe_append_name(username, display_name)
            return char

        # 不存在的話, 新建並寫入 DB
        char = cls(user_id=user_id, usernames=[username], display_names=[display_name])
        doc = char.to_dict()

        now = now_tw_iso()
        doc.update({"created_at": now, "updated_at": now})
        await mongo_atlas_client.insert_one("tm_twitch_users", doc)
        return char

    @classmethod
    async def find_by_user_id(cls, user_id: str) -> "Character | None":
        """
        透過 user_id 讀取角色資料
        """
        doc = await mongo_atlas_client.find(
            "tm_twitch_users", filter={"user_id": user_id}, limit=1
        )
        if doc:
            return cls.from_dict(doc[0])
        return None

    @classmethod
    async def find_by_name(cls, name: str) -> "Character | None":
        if not name:
            return None

        # 先嘗試大小寫不敏感的精確比對
        # ^ 與 $ 代表整段比對；'i' flag 代表 ignore-case
        #
        # name 是觀眾原始輸入，一定要 escape：
        #   未 escape 時 `!pk .*` 會匹配到隨機玩家，
        #   而 `!pk (a+)+$` 這種 catastrophic backtracking 能把 Atlas 的 CPU 打滿。
        escaped_name = re.escape(name)
        regex_filter = {
            # 先比對 display_names 看看
            "display_names": {"$regex": f"^{escaped_name}$", "$options": "i"}
        }

        doc = await mongo_atlas_client.find(
            "tm_twitch_users",
            filter=regex_filter,
            limit=1,  # 只要第一筆，理論上名稱應唯一
        )

        if not doc:
            username_filter = {
                # 再比對 usernames 看看
                "usernames": {"$regex": f"^{escaped_name}$", "$options": "i"}
            }
            doc = await mongo_atlas_client.find(
                "tm_twitch_users",
                filter=username_filter,
                limit=1,
            )

        if doc:
            return cls.from_dict(doc[0])
        return None

    def _maybe_append_name(self, username: str, display_name: str):
        if username and username not in self.usernames:
            self.usernames.append(username)
            self._dirty = True
        if display_name and display_name not in self.display_names:
            self.display_names.append(display_name)
            self._dirty = True

    def _pending_increments(self) -> dict[str, int]:
        """算出自上次存檔以來的數值差額。沒變的欄位不會出現在結果裡。"""
        increments: dict[str, int] = {}
        for field_name in ("level", "exp", "gold"):
            delta = getattr(self, field_name) - self._baseline[field_name]
            if delta:
                increments[field_name] = delta

        baseline_attributes = self._baseline["attributes"]
        for key, value in self.attributes.items():
            delta = value - baseline_attributes.get(key, 0)
            if delta:
                increments[f"attributes.{key}"] = delta
        return increments

    async def save(self):
        """把「差額」寫回資料庫，而不是用手上的快照覆蓋整份文件。

        全欄位 `$set` 會 lost update：
        某人正在聊天（handler 手上是載入當下的舊快照）時，一桶金結算重新讀取
        同一個角色、發完獎金存檔；接著聊天 handler 用舊快照把整份文件蓋回去
        —— 獎金就這樣消失了。改成 `$inc` 之後兩邊的增減都會被算進去，
        誰先寫誰後寫都不影響最後的餘額。

        `job` 是字串，沒有「差額」可言，因此只在真的變了才 `$set`；
        沒變就不寫，才不會用舊快照蓋掉別人剛改好的職業。

        代價要說清楚：兩個流程同時扣款時，餘額檢查各自看自己的快照，
        資料庫的 gold 仍有機會被扣成負數。但原本的 `$set` 是「其中一筆扣款
        整個消失」（等於白吃白喝），`$inc` 至少兩筆都算到。真正的解法要靠
        條件式更新，而目前的微服務 API 拿不到「有沒有更新到」的回應。
        """
        update: dict = {
            "$set": {"updated_at": self._now_str()},
            "$addToSet": {
                "usernames": {"$each": self.usernames},
                "display_names": {"$each": self.display_names},
            },
        }

        increments = self._pending_increments()
        if increments:
            update["$inc"] = increments
        if self.job != self._baseline["job"]:
            update["$set"]["job"] = self.job

        await mongo_atlas_client.update(
            "tm_twitch_users",
            update=update,
            filter={"user_id": self.user_id},
            many=False,
        )
        # 寫入成功之後才推進基準線。失敗時維持原樣，差額才不會憑空消失 ——
        # vip_system 正是靠這點：它存檔失敗後由 message_controller 的 finally 再存一次。
        self._dirty = False
        self._baseline = self._snapshot()

    # ---------- RPG 行為 ----------

    def gain_gold(self, gained: int):
        self.gold += gained
        self._dirty = True

    def spend_gold(self, cost: int) -> bool:
        """扣款。餘額不足時回傳 False 且完全不改變狀態。

        所有扣款都必須走這裡，不要在外部直接寫 char.gold -= x：
        統一入口才能保證「檢查餘額」與「實際扣款」是同一步，
        也才能正確標記髒資料、讓 message_controller 一定會存檔。
        """
        if cost < 0:
            raise ValueError(f"扣款金額不可為負數：{cost}")
        if self.gold < cost:
            return False
        self.gold -= cost
        self._dirty = True
        return True

    async def gain_exp(self, gained_exp: int, send_func):
        total_exp = self.exp + gained_exp
        while total_exp >= self._exp_to_next_level():
            total_exp -= self._exp_to_next_level()
            await self._on_level_up(send_func)
        self.exp = total_exp
        self._dirty = True

    def _exp_to_next_level(self) -> int:
        return self.level * rpg_parameter["exp_req_multiple"]

    async def _on_level_up(self, send_func):
        self.level += 1
        rand_attr = random.choice(list(DEFAULT_ATTRIBUTES.keys()))
        self.attributes[rand_attr] += 1
        self._dirty = True
        await send_func(
            f"恭喜 @{self.display_name} 升到 {self.level} 等，提升 {rand_attr} 1 點！"
        )
        await self._maybe_job_change(send_func)

    async def _maybe_job_change(self, send_func):
        cfg = JOB_CONFIG.get(self.level)
        if not cfg:
            return
        old_job = self.job
        new_job = random.choice(cfg["jobs"])
        self.job = new_job
        self._dirty = True
        await send_func(
            f"恭喜 @{self.display_name} 從【{old_job}】{cfg['stage']}為【{self.job}】！"
        )

    def get_info(self):
        parts = [
            f"Lv.{self.level} ",
            f"EXP {self.exp} ",
            f"Gold {self.gold} ",
            f"職業【{self.job}】",
        ]
        attr_str = " / ".join(f"{k} {v}" for k, v in self.attributes.items())
        parts.append(attr_str)
        return "| ".join(parts)


if __name__ == "__main__":
    import asyncio

    async def _demo():
        char = await Character.load_or_create("35949794", "tigermeowtw", "老虎喵喵喵")
        logger.info(f"{await Character.find_by_user_id('35949794')}")
        logger.info(f"{await Character.find_by_name('老虎喵喵喵')}")
        logger.info(f"{char.get_info()}")

    asyncio.run(_demo())
