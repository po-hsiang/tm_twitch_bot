from tm_twitch_bot.utils.http_utils import request_with_retries
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import threading
import requests

openai_config = config["openai"]


class _SingletonMeta(type):
    _instances: dict[type, "OpenAIClient"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class OpenAIClient(metaclass=_SingletonMeta):
    def __init__(self):
        self.base_url = openai_config["svc_url"]
        self.api_key = openai_config["api_key"]
        self.model = openai_config["model"]

    def _req_for_openai_svc(
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
        # logger.info(f"[OpenAIClient] resp_json: {resp_json}")
        return resp_json

    def conversation(self, messages):
        data = {"api_key": self.api_key, "model": self.model, "messages": messages}
        resp_json = self._req_for_openai_svc(requests.post, "/conversation", json=data)
        raw = resp_json.get("raw")
        logger.info(f"[OpenAIClient] conversation() raw: {raw}")
        return raw

    def structured_output(self, system_prompt, prompt, schema):
        data = {
            "api_key": self.api_key,
            "system_prompt": system_prompt,
            "prompt": prompt,
            "schema": schema,
            "model": self.model,
        }
        resp_json = self._req_for_openai_svc(
            requests.post, "/structured_output", json=data
        )
        results = resp_json.get("results", [])
        # logger.info(f"[OpenAIClient] structured_output() results: {results}")
        return results[0].get("content_json", {})


openai_client = OpenAIClient()
