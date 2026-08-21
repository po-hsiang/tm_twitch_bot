"""`!YT` / `!找歌`：虎喵歌單。

這兩支是 clients/youtube.py 拆出來的指令外殼（第十一輪）。
要鎖的是「外殼有把參數正確轉給 client」——關鍵字是從 raw_tail_text 來的，
名字錯了會變成每次都搜尋空字串。
"""

from tm_twitch_bot.commands import songs


class FakeYouTube:
    def __init__(self):
        self.searched: list[str] = []
        self.picked = 0

    async def pick_random_song(self) -> str:
        self.picked += 1
        return "某頻道 | 某首歌 | https://youtu.be/xxxx"

    async def search(self, keyword: str) -> str:
        self.searched.append(keyword)
        return f"找到「{keyword}」"


async def test_pick_asks_the_client_for_a_random_song(monkeypatch):
    fake = FakeYouTube()
    monkeypatch.setattr(songs, "youtube_client", fake)

    result = await songs.pick()

    assert "youtu.be" in result
    assert fake.picked == 1


async def test_search_passes_the_keyword_through(monkeypatch):
    fake = FakeYouTube()
    monkeypatch.setattr(songs, "youtube_client", fake)

    assert await songs.search_song(raw_tail_text="Young & Dumb") == "找到「Young & Dumb」"
    assert fake.searched == ["Young & Dumb"]


async def test_a_missing_keyword_becomes_an_empty_search(monkeypatch):
    """沒帶關鍵字時交空字串給 client，長度檢查在 client 那一層。"""
    fake = FakeYouTube()
    monkeypatch.setattr(songs, "youtube_client", fake)

    await songs.search_song()

    assert fake.searched == [""]
