from tm_twitch_bot.utils.http_utils import request_with_retries
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import threading
import requests

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

    def _req_for_google_sheets_svc(
        self,
        request_func,
        path: str,
        *,
        params: Optional[dict[str, any]] = None,
        json: Optional[dict[str, any]] = None,
    ):
        api_url = f"{self.base_url}{path}"
        resp = request_with_retries(request_func, api_url, params=params, json=json)
        resp.raise_for_status()
        resp_json = resp.json()
        # logger.info(f"[GoogleSheetsClient] resp_json: {resp_json}")
        return resp_json

    def get_sheet_data(self, sheet_name: str):
        params = {
            "url": self.sheet_url,
            "sheetName": sheet_name,
        }
        resp = self._req_for_google_sheets_svc(
            requests.get, "/sheet_data", params=params
        )
        return resp.get("data")

    def get_sheet_data_by_cell(self, sheet_name, cell):
        params = {"url": self.sheet_url, "sheetName": sheet_name, "cell": cell}
        resp = self._req_for_google_sheets_svc(
            requests.get, "/sheet_data_by_cell", params=params
        )
        return resp.get("data")

    def get_sheet_data_by_range(self, sheet_name, range_str):
        params = {"url": self.sheet_url, "sheetName": sheet_name, "range": range_str}
        resp = self._req_for_google_sheets_svc(
            requests.get, "/sheet_data_by_range", params=params
        )
        return resp.get("data")


google_sheets_client = GoogleSheetsClient()


if __name__ == "__main__":
    raw_data = google_sheets_client.get_sheet_data("轉職表")
    logger.info(f"raw_data: {raw_data}")
    # raw_data = google_sheets_client.get_sheet_data_by_cell("指令集", "A2")
    # logger.info(f"cell: {raw_data}")
    # raw_data = google_sheets_client.get_sheet_data_by_range("指令集", "A1:B2")
    # logger.info(f"range: {raw_data}")
