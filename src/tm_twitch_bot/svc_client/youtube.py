from tm_twitch_bot.utils.http_utils import request_with_retries
from tm_twitch_bot.utils.yaml_utils import config
from typing import Any
import threading
import random

yt_cofig = config["youtube"]


class _SingletonMeta(type):
    _instances: dict[type, "YouTubeClient"] = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class YouTubeClient(metaclass=_SingletonMeta):
    def __init__(self):
        self.base_url = yt_cofig["svc_url"]
        self.tm_playlist_id = yt_cofig["tm_playlist_id"]
        self._cache: dict[str, list[dict[str, Any]]] = {}

    # ---------- 基礎呼叫 ---------- #
    async def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        resp = await request_with_retries("GET", url, params=params)
        data = resp.json()  # ➟ dict / list
        return data

    # ---------- 公開方法 ---------- #
    async def fetch_playlist(self, sort: str = "views") -> list[dict[str, Any]]:
        # 惰性載入：第一次使用時才抓歌單（過去在 import 階段抓，服務沒開 Bot 會直接掛）
        cache_key = f"{self.tm_playlist_id}:{sort}"
        if cache_key not in self._cache:
            data = await self._get(
                "/playlist", {"playlist_id": self.tm_playlist_id, "sort": sort}
            )
            self._cache[cache_key] = data
        return self._cache[cache_key]

    async def pick_random_song(self, sort: str = "views") -> str:
        songs = await self.fetch_playlist(sort)
        song = random.choice(songs)
        return f"{song['channel']} | {song['title']} | {song['url']}"

    async def search(self, keyword: str, sort: str = "views") -> str:
        keyword = keyword.strip()
        if len(keyword) < 2:
            return "搜尋關鍵字請大於等於 2 個字元"

        keyword_lower = keyword.lower()
        songs = await self.fetch_playlist(sort)
        matches = [
            s
            for s in songs
            if keyword_lower in s["title"].lower()
            or keyword_lower in s["channel"].lower()
        ]
        if not matches:
            return f"虎喵歌單中的頻道和標題都沒有符合「{keyword}」的歌唷"

        song = random.choice(matches)
        result = f"找到符合「{keyword}」的有 {len(matches)} 首，幫您隨機挑出：{song['title']} | {song['url']}"
        return result


youtube_client = YouTubeClient()


async def pick(*args, **kwargs):
    return await youtube_client.pick_random_song()


async def search_song(*args, **kwargs):
    keyword = kwargs.get("raw_tail_text", "")
    return await youtube_client.search(keyword)


if __name__ == "__main__":
    import asyncio

    async def _demo():
        print(await youtube_client.fetch_playlist())
        # print(await youtube_client.pick_random_song())
        # print(await youtube_client.search("MJ116"))

    asyncio.run(_demo())
