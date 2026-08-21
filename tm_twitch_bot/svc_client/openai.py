"""OpenAI 微服務（localhost:9092）的 client。

**目前只剩 `!pk` 這一個呼叫端。** AI 問答已全面改走 n8n 的 TM AI Agent
（見 ai_actions/tm_ai_agent.py），連同 `ai_actions/gpt_chat_session.py`
與這裡的 `conversation()` 一起移除了——n8n 端提供上下文記憶與工具呼叫，
也不必為了換模型去維護不同廠商的微服務。

留下 `structured_output()` 的原因很單純：`!pk` 需要模型回傳符合
JSON Schema 的 `winner` / `battle_log` 兩個欄位，而 n8n 的 TM AI Agent
回的是純文字 `{"reply": ...}`，拿不到結構化輸出。
"""

from tm_twitch_bot.utils.http_utils import request_with_retries, LONG_TIMEOUT
from tm_twitch_bot.utils.yaml_utils import config
from tm_twitch_bot.utils.singleton import SingletonMeta
from typing import Optional

openai_config = config["openai"]


class OpenAIClient(metaclass=SingletonMeta):
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
