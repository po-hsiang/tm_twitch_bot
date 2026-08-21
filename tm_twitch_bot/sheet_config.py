"""Google Sheets 上的營運內容：啟動時載入、失敗時重試、`!reload` 重新拉。

三個入口共用同一份清單，這就是這個模組存在的理由：

| 入口 | 呼叫 |
| --- | --- |
| 啟動 bootstrap | `load_sheet_config()`（失敗不中斷啟動，降級上線） |
| 降級後每五分鐘重試 | `load_sheet_config(還沒成功的那幾張)` |
| 管理員的 `!reload` | `reload_all()`（薄薄的指令外殼在 commands/reload.py） |

清單如果各自維護一份，日後加第三張表很容易只改到一邊。

**刻意只重載「資料」，不重載「程式」。** `importlib.reload` 聽起來更徹底，
但這個專案有八個 metaclass 單例（五個 client、VipSystem、兩個遊戲），再加上
`chat_sender` 那顆模組層實例；reload 會生出第二份類別與第二個實例——進行中的
終極密碼會憑空消失，其他模組手上的舊參考還指著舊類別，之後所有 isinstance
都不成立。改了程式就重開 Bot，那才是誠實的做法（CODE_REVIEW P2-26）。
"""

from tm_twitch_bot.chat import dispatcher
from tm_twitch_bot.chat import greeter
from tm_twitch_bot.commands import food
from tm_twitch_bot.commands import meme
from tm_twitch_bot.model import jobs
from tm_twitch_bot.utils.log_utils import logger
from typing import Awaitable, Callable

# 啟動時就必須載入的表：沒有它們，對應功能整組不能用。
# key 是給人看的名字，會直接出現在降級公告與 !reload 的回覆裡。
SHEET_LOADERS: dict[str, Callable[[], Awaitable[None]]] = {
    "指令集": dispatcher.load_command_set,
    "轉職表": jobs.load_job_config,
}

# 惰性載入的內容表：清掉快取就好，下一次用到時自己會抓。
# 這些刻意不進 SHEET_LOADERS——啟動時就抓它們只是把 9091 的風險提前，
# 沒有任何好處（見 P1-37 的降級設計）。
POOL_CLEARERS: dict[str, Callable[[], None]] = {
    "吃啥": food.clear_pool,
    "酷酷的諧音梗": meme.clear_pool,
    "冒險台詞": greeter.clear_pool,
}

SHEET_RETRY_SECONDS = 300  # 降級啟動後多久重試一次


async def load_sheet_config(names=None) -> list[str]:
    """載入啟動必需的試算表設定，回傳「失敗」的項目名稱。

    刻意不讓失敗中斷啟動。9091 是四個微服務裡最容易忘記開的一個——
    它只在啟動那一瞬間用到，開台途中完全不會再碰；而少了它，Bot 仍有一半以上
    的功能可用：打字給經驗值、升級、`!排行`、終極密碼、一桶金、VIP 掃描
    都不經過 Sheets。「整場開台沒有機器人」比「少了 ! 指令」嚴重得多。

    每個項目各自 try，一個失敗不影響另一個。
    """
    failed: list[str] = []
    for name in names or list(SHEET_LOADERS):
        try:
            await SHEET_LOADERS[name]()
        except Exception as e:
            failed.append(name)
            logger.error(f"載入「{name}」失敗: {type(e).__name__}: {e}")
    return failed


async def reload_all() -> tuple[list[str], list[str]]:
    """重載所有試算表內容（含惰性快取），回傳 (成功, 失敗) 兩份名單。

    每張表各自 try：一張掛掉不能連帶讓其他張也不重載。
    `load_command_set` 是先抓表、成功才 clear + update，所以抓表失敗時
    線上那份指令集完全不受影響——重載失敗不會讓 Bot 變成沒有指令。
    """
    ok: list[str] = []
    failed: list[str] = []

    for name, loader in SHEET_LOADERS.items():
        try:
            await loader()
            ok.append(name)
        except Exception as e:
            failed.append(name)
            logger.error(f"重新載入「{name}」失敗: {type(e).__name__}: {e}")

    # 清快取不會失敗，也不會打網路：下一次有人用到才會重抓。
    for name, clear in POOL_CLEARERS.items():
        clear()
        ok.append(name)

    dispatcher.clear_function_cache()
    logger.info(f"試算表重載完成，成功 {len(ok)} 張、失敗 {len(failed)} 張")
    return ok, failed
