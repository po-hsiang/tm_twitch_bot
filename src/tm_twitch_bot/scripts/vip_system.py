from tm_twitch_bot.svc_client.mongo_atlas import mongo_atlas_client
from tm_twitch_bot.svc_client import twitch_vips_api
from tm_twitch_bot.scripts.role_system import Character
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from tm_twitch_bot.utils.singleton import SingletonMeta
from tm_twitch_bot.utils.time_utils import now_tw_iso, today_tw
from datetime import timedelta
from dataclasses import dataclass
from typing import Optional
import asyncio


@dataclass(frozen=True)
class VipConfig:
    enabled: bool
    gold_cost: int
    vip_cap: int
    days_per_redeem: int


def _load_vip_config() -> VipConfig:
    c = config.get("vip_system", {})
    return VipConfig(
        enabled=c.get("enabled"),
        gold_cost=c.get("gold_cost"),
        vip_cap=c.get("vip_cap"),
        days_per_redeem=c.get("days_per_redeem"),
    )


class VipSystem(metaclass=SingletonMeta):
    def __init__(self):
        self.vips_col_name = "tm_twitch_vips"
        self.cfg = _load_vip_config()
        self._redeem_lock = asyncio.Lock()  # 全程式跑在單一事件圈上，改用 asyncio.Lock
        # 這三個要到 event_ready 才由 set_api_context() 填。
        # 明確初始化成 None，未就緒時才會是「值為 None」而不是
        # 「屬性不存在」——後者只能靠 AttributeError 兜底，
        # 而那要等到扣款之後才會爆（見 is_ready 與 redeem_vip）。
        self._client_id: Optional[str] = None
        self._broadcaster_id: Optional[str] = None
        self._token_getter = None

    def set_api_context(self, client_id: str, broadcaster_id: str, token_getter):
        self._client_id = client_id
        self._broadcaster_id = broadcaster_id
        self._token_getter = token_getter

    @property
    def is_ready(self) -> bool:
        """Twitch API 的呼叫條件是否已就緒。

        在 event_ready 之前抵達的 `!vip` 會走到這裡。
        """
        return all((self._client_id, self._broadcaster_id, self._token_getter))

    @staticmethod
    def _today_iso() -> str:
        """台灣的今天（YYYY-MM-DD）。

        到期日只存到「日」，而且是以字串比大小（$gte / $lt），所以回字串就好。
        用台灣時間是因為 date.today() 在 UTC 機器上會是「昨天」——兌換當下
        就少一天，過期掃描也會提早一天把人的 VIP 拔掉（CODE_REVIEW P3-35）。
        """
        return today_tw().isoformat()

    async def _get_vip_doc(self, user_id: str) -> Optional[dict]:
        docs = await mongo_atlas_client.find(
            self.vips_col_name, filter={"user_id": user_id}, limit=1
        )
        return docs[0] if docs else None

    async def _active_vip_count(self) -> int:
        docs = await mongo_atlas_client.find(
            self.vips_col_name,
            filter={"active": True, "expire_date": {"$gte": self._today_iso()}},
            projection={"_id": 1},
            limit=0,
        )
        return len(docs or [])

    async def redeem_vip(self, char: Character) -> str:

        if not self.cfg.enabled:
            return "⚠️ VIP 兌換功能未啟用。"

        # 在扣款之前就擋掉。原本這件事是靠取 token 時的 AttributeError 兜底，
        # 但那個位置已經在 spend_gold() 之後——雖然有退款，卻多繞了
        # 「扣款→打 API 失敗→退款」一圈，還會在 log 留下誤導的 API 失敗紀錄。
        if not self.is_ready:
            logger.error("!vip 在 set_api_context() 之前就被呼叫，Twitch API 尚未就緒")
            return "⚠️ VIP 兌換服務還在暖機，請稍等一下再試 tigerm24Love"

        user_id = getattr(char, "user_id", None)
        display_name = char.display_name
        username = char.username

        async with self._redeem_lock:
            today_iso = self._today_iso()
            vip_doc = await self._get_vip_doc(user_id)

            if (
                vip_doc
                and vip_doc.get("active")  # 已經是 VIP
                and vip_doc.get("expire_date") >= today_iso  # 還沒過期
            ):
                return f"⚠️ 您已是 VIP，過期後才能再次兌換。過期日：{vip_doc['expire_date']}！"

            # 剩餘 VIP 名額檢查
            if await self._active_vip_count() >= self.cfg.vip_cap:
                return f"⚠️ VIP 名額已滿，上限：{self.cfg.vip_cap}。"

            # 金幣檢查與扣款是同一步。
            # 先扣再打 API：避免「VIP 已授予但程式中途掛掉、錢卻沒扣」的白吃白喝，
            # API 失敗時再退款回去。
            cost = self.cfg.gold_cost
            current_gold = int(char.gold)
            if not char.spend_gold(cost):
                return f"⚠️ Gold 不足，需要 {cost}，您目前只有 {current_gold}。"

            # 固定效期 31 天（僅存 YYYY-MM-DD）
            expire_iso = (
                today_tw() + timedelta(days=self.cfg.days_per_redeem)
            ).isoformat()

            # 透過 API 設定 VIP。
            # 取 token 仍然包在 try 內：函式開頭的 is_ready 已經擋掉「還沒就緒」，
            # 但 token_getter 本身也可能拋例外（token 已失效、刷新失敗）。
            # 一旦讓它在 try 外拋出，就會變成「錢扣了、VIP 沒給、也沒退款」。
            try:
                token = self._token_getter()
                is_success, api_result = await twitch_vips_api.add_channel_vip(
                    token, self._client_id, self._broadcaster_id, user_id
                )
            except Exception as e:
                char.gain_gold(cost)  # 退款
                logger.error(f"呼叫 Twitch VIP API 失敗，已退還 {display_name} {cost} Gold: {e}")
                return "⚠️ VIP 兌換服務暫時無法使用，已退還您的 Gold，請稍後再試。"

            if not is_success:  # 新增失敗
                char.gain_gold(cost)  # 退款
                logger.warning(f"VIP 新增失敗，已退還 {display_name} {cost} Gold")
                return f"VIP 新增失敗，原因為 {api_result.get('message')}"
            logger.info(f"已經新增 {display_name} 的 VIP")

            # VIP 已實際授予，立刻把扣款落地，縮短「拿到 VIP 卻還沒付錢」的視窗。
            # 失敗也不中斷：char 仍是髒的，message_controller 的 finally 會再存一次。
            try:
                await char.save()
            except Exception as e:
                logger.error(f"VIP 扣款存檔失敗（稍後由訊息流程重試）: {e}")

            # 更新 tm_twitch_vips 表
            try:
                await mongo_atlas_client.update(
                    self.vips_col_name,
                    update={
                        "$set": {
                            "user_id": user_id,
                            "username": username,
                            "display_name": display_name,
                            "active": True,
                            "expire_date": expire_iso,  # YYYY-MM-DD
                            "updated_at": now_tw_iso(),
                        },
                        "$inc": {"redeemed_count": 1},
                        "$push": {
                            "history": {
                                "ts": now_tw_iso(),
                                "op": "redeem",
                                "days": self.cfg.days_per_redeem,
                                "gold_cost": cost,
                                "expire_date": expire_iso,
                            }
                        },
                    },
                    filter={"user_id": user_id},
                    upsert=True,
                    many=False,
                )
            except Exception as e:
                # VIP 已授予、錢也扣了，但沒有到期紀錄 → 過期掃描不會知道要移除他
                logger.error(
                    f"⚠️ VIP 兌換紀錄寫入失敗，{display_name}（{user_id}）的 VIP "
                    f"已授予但無到期紀錄（應於 {expire_iso} 到期），需要人工補登：{e}"
                )

            success_msg = f"🎊 VIP 兌換成功！原 {current_gold} Gold，兌換後 {current_gold - cost}。過期日：{expire_iso}！"
            return success_msg

    async def sweep_expired(self):

        if not self.cfg.enabled:
            logger.warning("VIP 兌換功能未啟用，略過過期掃描")
            return  # Bug fix：過去缺少 return，功能停用時仍會執行掃描

        today = self._today_iso()
        # find() 已保證回傳 list（見 svc_client/mongo_atlas.py），這裡不必再 `or []`
        expired_docs = await mongo_atlas_client.find(
            self.vips_col_name,
            filter={"active": True, "expire_date": {"$lt": today}},
            projection={
                "user_id": 1,
                "username": 1,
                "display_name": 1,
                "expire_date": 1,
            },
            limit=0,
        )
        logger.warning(f"哪些人要移除: {expired_docs}")

        for doc in expired_docs:

            user_id = doc.get("user_id")
            display_name = doc.get("display_name")
            token = self._token_getter()
            is_success, api_result = await twitch_vips_api.remove_channel_vip(
                token, self._client_id, self._broadcaster_id, user_id
            )
            if not is_success:  # 設定失敗
                logger.error(f"VIP 移除失敗，原因為 {api_result.get('message')}")
            logger.info(f"已經移除 {display_name} 的 VIP")

            await mongo_atlas_client.update(
                self.vips_col_name,
                update={
                    "$set": {
                        "active": False,
                        "updated_at": now_tw_iso(),
                    },
                    "$push": {
                        "history": {
                            "ts": now_tw_iso(),
                            "op": "revoke",
                            "reason": "expire_sweep",
                        }
                    },
                },
                filter={"user_id": doc["user_id"]},
                upsert=False,
                many=False,
            )


vip_system = VipSystem()


async def redeem(*args, **kwargs):
    char = kwargs.get("char")
    return await vip_system.redeem_vip(char)


if __name__ == "__main__":
    print(now_tw_iso())
    print(today_tw().isoformat())
