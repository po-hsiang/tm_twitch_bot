from tm_twitch_bot.utils.http_utils import request_with_retries
from tm_twitch_bot.utils.yaml_utils import config
from typing import Any
import threading
import requests
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
        self.fetch_playlist()  # 啟動服務時先跑一次

    # ---------- 基礎呼叫 ---------- #
    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.base_url}{path}"
        resp = request_with_retries(requests.get, url, params=params)
        resp.raise_for_status()
        data = resp.json()  # ➟ dict / list
        return data

    # ---------- 公開方法 ---------- #
    def fetch_playlist(self, sort: str = "views") -> list[dict[str, Any]]:
        cache_key = f"{self.tm_playlist_id}:{sort}"
        if cache_key not in self._cache:
            data = self._get(
                "/playlist", {"playlist_id": self.tm_playlist_id, "sort": sort}
            )
            self._cache[cache_key] = data
        return self._cache[cache_key]

    def pick_random_song(self, sort: str = "views") -> str:
        songs = self.fetch_playlist(sort)
        song = random.choice(songs)
        return f"{song['channel']} | {song['title']} | {song['url']}"

    def search(self, keyword: str, sort: str = "views") -> int:
        keyword = keyword.strip()
        if len(keyword) < 2:
            return "搜尋關鍵字請大於等於 2 個字元"

        keyword_lower = keyword.lower()
        songs = self.fetch_playlist(sort)
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


def pick(*args, **kwargs):
    return youtube_client.pick_random_song()


def search_song(*args, **kwargs):
    keyword = kwargs.get("raw_tail_text", "")
    return youtube_client.search(keyword)


if __name__ == "__main__":
    print(youtube_client.fetch_playlist())
    # print(youtube_client.pick_random_song())
    # print(youtube_client.search("MJ116"))
