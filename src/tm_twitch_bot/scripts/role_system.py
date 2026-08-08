from tm_twitch_bot.svc_client.mongo_atlas import mongo_atlas_client
from tm_twitch_bot.scripts.level_and_job_system import JOB_CONFIG
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from datetime import datetime, timezone, timedelta
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

    # ---------- 髒資料追蹤 ----------

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
        return cls(
            user_id=doc["user_id"],
            usernames=doc.get("usernames", []),
            display_names=doc.get("display_names", []),
            level=doc.get("level", 1),
            exp=doc.get("exp", 0),
            gold=doc.get("gold", 0),
            job=doc.get("job", "初學者"),
            attributes=doc.get("attributes", DEFAULT_ATTRIBUTES.copy()),
        )

    # ---------- DB 相關 ----------

    @staticmethod
    def _now_str() -> str:
        return datetime.now(timezone(timedelta(hours=8))).isoformat()

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

        now = datetime.now(timezone(timedelta(hours=8))).isoformat()
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

    @classmethod
    async def get_tigermeow_char(cls) -> "Character":
        return await mongo_atlas_client.find(
            "tm_twitch_users", filter={"user_id": config["tigermeowtw_id"]}, limit=1
        )

    def _maybe_append_name(self, username: str, display_name: str):
        if username and username not in self.usernames:
            self.usernames.append(username)
            self._dirty = True
        if display_name and display_name not in self.display_names:
            self.display_names.append(display_name)
            self._dirty = True

    async def save(self):
        await mongo_atlas_client.update(
            "tm_twitch_users",
            update={
                "$set": {
                    "level": self.level,
                    "exp": self.exp,
                    "gold": self.gold,
                    "job": self.job,
                    "attributes": self.attributes,
                    "updated_at": self._now_str(),
                },
                "$addToSet": {
                    "usernames": {"$each": self.usernames},
                    "display_names": {"$each": self.display_names},
                },
            },
            filter={"user_id": self.user_id},
            many=False,
        )
        self._dirty = False

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
            f"恭喜 @{self.display_names[-1]} 升到 {self.level} 等，提升 {rand_attr} 1 點！"
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
            f"恭喜 @{self.display_names[-1]} 從【{old_job}】{cfg['stage']}為【{self.job}】！"
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


def check(*args, **kwargs):
    char = kwargs.get("char")
    return char.get_info()


if __name__ == "__main__":
    import asyncio

    async def _demo():
        char = await Character.load_or_create("35949794", "tigermeowtw", "老虎喵喵喵")
        logger.info(f"{await Character.find_by_user_id('35949794')}")
        logger.info(f"{await Character.find_by_name('老虎喵喵喵')}")
        logger.info(f"{char.get_info()}")

    asyncio.run(_demo())
