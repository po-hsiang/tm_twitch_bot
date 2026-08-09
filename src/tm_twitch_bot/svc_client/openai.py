from tm_twitch_bot.utils.http_utils import request_with_retries, LONG_TIMEOUT
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional
import threading

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

    async def _req_for_openai_svc(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ):
        api_url = f"{self.base_url}{path}"
        # GPT 產生回覆本來就慢，用加長的讀取逾時，不受一般微服務的 20 秒限制
        resp = await request_with_retries(
            method, api_url, params=params, json=json, timeout=LONG_TIMEOUT
        )
        resp_json = resp.json()
        # logger.info(f"[OpenAIClient] resp_json: {resp_json}")
        return resp_json

    async def conversation(self, messages):
        data = {"api_key": self.api_key, "model": self.model, "messages": messages}
        resp_json = await self._req_for_openai_svc("POST", "/conversation", json=data)
        raw = resp_json.get("raw")
        logger.info(f"[OpenAIClient] conversation() raw: {raw}")
        return raw

    async def structured_output(self, system_prompt, prompt, schema):
        data = {
            "api_key": self.api_key,
            "system_prompt": system_prompt,
            "prompt": prompt,
            "schema": schema,
            "model": self.model,
        }
        resp_json = await self._req_for_openai_svc(
            "POST", "/structured_output", json=data
        )
        results = resp_json.get("results", [])
        # logger.info(f"[OpenAIClient] structured_output() results: {results}")
        return results[0].get("content_json", {})


openai_client = OpenAIClient()
