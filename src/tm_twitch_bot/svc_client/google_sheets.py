from tm_twitch_bot.utils.http_utils import request_with_retries
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import threading

gs_config = config["google_sheets"]


class _SingletonMeta(type):
    _instances: dict[type, "GoogleSheetsClient"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class GoogleSheetsClient(metaclass=_SingletonMeta):
    def __init__(self):
        self.base_url = gs_config["svc_url"]
        self.sheet_url = gs_config["sheet_url"]

    async def _req_for_google_sheets_svc(
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
        # logger.info(f"[GoogleSheetsClient] resp_json: {resp_json}")
        return resp_json

    async def get_sheet_data(self, sheet_name: str):
        params = {
            "url": self.sheet_url,
            "sheetName": sheet_name,
        }
        resp = await self._req_for_google_sheets_svc(
            "GET", "/sheet_data", params=params
        )
        return resp.get("data")

    async def get_sheet_data_by_cell(self, sheet_name, cell):
        params = {"url": self.sheet_url, "sheetName": sheet_name, "cell": cell}
        resp = await self._req_for_google_sheets_svc(
            "GET", "/sheet_data_by_cell", params=params
        )
        return resp.get("data")

    async def get_sheet_data_by_range(self, sheet_name, range_str):
        params = {"url": self.sheet_url, "sheetName": sheet_name, "range": range_str}
        resp = await self._req_for_google_sheets_svc(
            "GET", "/sheet_data_by_range", params=params
        )
        return resp.get("data")


google_sheets_client = GoogleSheetsClient()


if __name__ == "__main__":
    import asyncio

    async def _demo():
        raw_data = await google_sheets_client.get_sheet_data("轉職表")
        logger.info(f"raw_data: {raw_data}")

    asyncio.run(_demo())
