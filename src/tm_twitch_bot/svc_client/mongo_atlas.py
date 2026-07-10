from tm_twitch_bot.utils.http_utils import request_with_retries
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import threading
import requests

mongo_config = config["mongodb_atlas"]


class _SingletonMeta(type):
    _instances: dict[type, "MongoAtlasClient"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class MongoAtlasClient(metaclass=_SingletonMeta):
    def __init__(self):
        self.base_url = f"{mongo_config['svc_url']}/mongo"

    def _req_for_mongo_atlas_svc(
        self,
        request_func,
        path,
        *,
        params: Optional[dict[str, any]] = None,
        json: Optional[dict[str, any]] = None,
    ):
        api_url = f"{self.base_url}{path}"
        resp = request_with_retries(request_func, api_url, params=params, json=json)
        resp.raise_for_status()
        resp_json = resp.json()
        # logger.info(f"[MongoAtlasClient] resp_json: {resp_json}")
        return resp_json

    def insert_one(self, collection: str, doc: dict):
        payload = {"collection": collection, "doc": doc}
        self._req_for_mongo_atlas_svc(requests.post, "/insert_one", json=payload)

    def insert_many(self, collection: str, docs: list):
        payload = {"collection": collection, "docs": docs}
        self._req_for_mongo_atlas_svc(requests.post, "/insert_many", json=payload)

    def find(
        self,
        collection: str,
        filter: dict = None,
        projection: dict = None,
        sort: dict = None,
        limit: int = None,
    ):
        payload = {
            "collection": collection,
            "filter": filter if filter else {},
            "projection": projection if projection else {},
            "sort": sort if sort else [],
            "limit": limit if limit else 0,
        }
        resp = self._req_for_mongo_atlas_svc(requests.post, "/find", json=payload)
        return resp.get("results")

    def update(
        self,
        collection: str,
        update: dict,
        filter: dict = {},
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
        self._req_for_mongo_atlas_svc(requests.post, "/update", json=payload)

    def create_index(self, collection: str, keys: dict):
        payload = {"collection": collection, "keys": keys}
        self._req_for_mongo_atlas_svc(requests.post, "/create_index", json=payload)


mongo_atlas_client = MongoAtlasClient()


if __name__ == "__main__":
    mongo_atlas_client.create_index(
        "tm_twitch_vips",
        keys={
            "user_id": 1,
        },
    )
    mongo_atlas_client.create_index(
        "tm_twitch_vips",
        keys={"active": 1, "expire_date": 1},
    )
