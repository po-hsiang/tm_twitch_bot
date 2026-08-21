"""`!YT`／`!找歌`：虎喵歌單。

原本這兩個指令函式住在 clients/youtube.py 裡，也就是 HTTP client 的檔案。
那讓 clients/ 這一層同時是「對外呼叫」和「指令實作」兩件事——挑歌、組回覆字串
都是業務決定，不屬於 client。搬到這裡之後 clients/youtube.py 只剩純粹的呼叫。

歌單在第一次使用時抓一次並快取，目前沒有失效機制（歌單更新要重開 Bot）。
"""

from tm_twitch_bot.clients.youtube import youtube_client


async def pick(*args, **kwargs):
    return await youtube_client.pick_random_song()


async def search_song(*args, **kwargs):
    keyword = kwargs.get("raw_tail_text", "")
    return await youtube_client.search(keyword)
