from tm_twitch_bot.utils.http_utils import request_with_retries
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from tm_twitch_bot.utils.singleton import SingletonMeta
from typing import Optional

mongo_config = config["mongodb_atlas"]


class MongoAtlasClient(metaclass=SingletonMeta):
    def __init__(self):
        self.base_url = f"{mongo_config['svc_url']}/mongo"

    async def _req_for_mongo_atlas_svc(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ):
        api_url = f"{self.base_url}{path}"
        resp = await request_with_retries(method, api_url, params=params, json=json)
        resp_json = resp.json()
        # logger.info(f"[MongoAtlasClient] resp_json: {resp_json}")
        return resp_json

    async def insert_one(self, collection: str, doc: dict):
        payload = {"collection": collection, "doc": doc}
        await self._req_for_mongo_atlas_svc("POST", "/insert_one", json=payload)

    async def insert_many(self, collection: str, docs: list):
        payload = {"collection": collection, "docs": docs}
        await self._req_for_mongo_atlas_svc("POST", "/insert_many", json=payload)

    async def find(
        self,
        collection: str,
        filter: dict = None,
        projection: dict = None,
        sort: dict = None,
        limit: int = None,
    ) -> list[dict]:
        """查詢結果一律回傳 list，永遠不會是 None。

        微服務異常時 results 可能缺席或為 null，過去會原封不動往上丟，
        由每個呼叫端各自防護 —— 而 rank_system 就漏了，`enumerate(None)` 直接 TypeError。
        統一在這一層收斂成 []，呼叫端只要判斷「有沒有資料」即可。
        """
        payload = {
            "collection": collection,
            "filter": filter if filter else {},
            "projection": projection if projection else {},
            "sort": sort if sort else [],
            "limit": limit if limit else 0,
        }
        resp = await self._req_for_mongo_atlas_svc("POST", "/find", json=payload)
        if not isinstance(resp, dict):
            logger.error(f"[MongoAtlasClient] find 回傳非預期格式，已視為空結果：{resp!r}")
            return []
        return resp.get("results") or []

    async def update(
        self,
        collection: str,
        update: dict,
        filter: dict = None,
        upsert: bool = False,
        many: bool = False,
    ):
        payload = {
            "collection": collection,
            "update": update,
            "filter": filter if filter else {},
            "upsert": upsert,
            "many": many,
        }
        await self._req_for_mongo_atlas_svc("POST", "/update", json=payload)

    async def create_index(self, collection: str, keys: dict):
        payload = {"collection": collection, "keys": keys}
        await self._req_for_mongo_atlas_svc("POST", "/create_index", json=payload)


mongo_atlas_client = MongoAtlasClient()


if __name__ == "__main__":
    import asyncio

    async def _demo():
        await mongo_atlas_client.create_index("tm_twitch_vips", keys={"user_id": 1})
        await mongo_atlas_client.create_index(
            "tm_twitch_vips", keys={"active": 1, "expire_date": 1}
        )

    asyncio.run(_demo())
