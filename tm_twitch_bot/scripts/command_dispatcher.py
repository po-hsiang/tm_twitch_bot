from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional, Any
from functools import lru_cache
import importlib
import inspect
import shlex


"""
支援四大類指令：
1. 驚嘆號開頭、無參數      例：!英雄
2. 驚嘆號開頭、一參數     例：!gpt 我帥嗎
3. 無驚嘆號，句子含關鍵字   例：帥
4. 未來：多參數指令         例：!bet 虎喵贏 100
"""


# ===== 處理指令集設定檔 =====

COMMAND_SET: dict[str, tuple[str, str]] = {}


def _parse_sheet(rows: list[list[str]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for row in rows[1:]:
        if len(row) >= 3:
            trigger, resp_type, content = (c.strip() for c in row[:3])
            # 指令都正規化成大寫，函數則正規化成小寫
            result[trigger.upper()] = (resp_type, content)
    return result


async def load_command_set() -> None:
    """從 Google Sheets 載入指令集（啟動 bootstrap 時呼叫；過去在 import 階段執行）。"""
    raw_sheet = await google_sheets_client.get_sheet_data("指令集")
    COMMAND_SET.clear()
    COMMAND_SET.update(_parse_sheet(raw_sheet))
    logger.info(f"指令集載入完成，共 {len(COMMAND_SET)} 筆")


# ===== 硬寫在程式裡的指令 =====
#
# 全專案唯一一個不是從試算表來的指令。理由很具體：!reload 是修復工具，
# 而「指令集沒載入成功」正是最需要它的時候——把它放在試算表上，
# 就變成「要修的東西壞了，修它的工具也一起壞」。
#
# 值刻意寫成 qualname 字串而不是 import 進來的函式：sheet_reloader 必須
# import command_dispatcher（它要重載指令集），反過來 import 就成了循環。
# 走 _load_function 這條既有的路，順便連參數注入與例外收斂都是同一套。
BUILTIN_COMMANDS: dict[str, tuple[str, str]] = {
    "!RELOAD": ("function", "tm_twitch_bot.scripts.sheet_reloader.reload"),
}


# 給觀眾看的制式訊息。細節一律只進 log，不進聊天室——
# 內部例外訊息會夾帶微服務網址、模組路徑等資訊，那是不該公開的內部拓樸。
GENERIC_ERROR_REPLY = "⚠️ 這個指令暫時出了點問題，稍後再試試看 tigerm24Cry"


# ===== 共用呼叫橋樑 =====


@lru_cache(maxsize=256)
def _wanted_params(func) -> tuple[frozenset[str] | None, bool]:
    """看一次函式簽章，回傳 (願收的關鍵字名稱, 是否收位置參數)。

    關鍵字那一項為 None 代表它有 `**kwargs`，照舊全部給。
    簽章拿不到（C 實作的內建函式之類）時也回 None，保守維持舊行為。

    用 lru_cache 是因為每一則觸發指令的訊息都會走到這裡，
    而同一個函式的簽章不會變。
    """
    try:
        params = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return None, True

    takes_var_positional = any(
        p.kind is inspect.Parameter.VAR_POSITIONAL for p in params.values()
    )
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return None, takes_var_positional

    names = frozenset(
        name
        for name, p in params.items()
        if p.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )
    return names, takes_var_positional


async def _invoke(func, tail: list[str], raw_tail_text: str, context: dict):
    """把指令函式要的東西餵給它。

    這裡是「按參數名注入」：指令函式想要什麼就在簽章上寫什麼，
    沒寫的不會拿到。這讓新指令可以寫成明確的
    `async def foo(*, char, raw_tail_text)`，而不必再一律 `**kwargs`
    然後用 `kwargs.get("char")` 摸黑拿（拿錯名字會安靜地拿到 None）。

    現有 19 個指令函式全是 `*args, **kwargs`，在這個規則下行為完全不變，
    所以不需要一次性改寫它們。

    註：CODE_REVIEW P2-25 原本建議定義一個 CommandContext 型別。
    改用「按參數名注入」是刻意的取捨——它同樣讓函式的需求變明確、
    可標註型別，卻不必多一層物件包裝，也不必動到 19 個線上指令函式
    （那些只有開台時才會被真正執行到，改壞了測試不一定攔得住）。
    """
    available = {"raw_tail_text": raw_tail_text, **context}
    wanted, takes_var_positional = _wanted_params(func)
    accepted_kw = (
        available
        if wanted is None
        else {name: value for name, value in available.items() if name in wanted}
    )
    # 只有明確收 *args 的函式才拿得到訊息切出來的位置參數。
    # 目前沒有任何指令函式真的用它（都是從 raw_tail_text 取），
    # 但照給才不會讓既有的 `*args, **kwargs` 簽章行為改變。
    args = tuple(tail) if takes_var_positional else ()
    try:
        result = func(*args, **accepted_kw)
        if inspect.isawaitable(result):  # 指令函數已全面 async 化，同步函數也相容
            result = await result
        return result
    except Exception as e:
        # 例外訊息絕不能原樣回到公開聊天室：StatusCodeError 長這樣——
        # 「呼叫 http://localhost:9093/mongo/find 失敗」，內部拓樸就這樣公開了。
        logger.error(
            f"執行指令函數 {func.__name__}() 時發生錯誤: {type(e).__name__}: {e}",
            exc_info=True,
        )
        return GENERIC_ERROR_REPLY


# ===== 函數快取 =====

_MODULE_CACHE: dict[str, Any] = {}


@lru_cache(maxsize=128)
def _load_function(qualname: str):

    if not qualname:
        raise ValueError("Google Sheets 設定檔上的函數名稱空白")

    if "." not in qualname:  # 呼叫當前腳本內的函數
        try:
            return globals()[qualname]
        except KeyError as e:
            raise ValueError(
                f"command_dispatcher.py 腳本內找不到函數 {qualname}()"
            ) from e

    module_name, func_name = qualname.rsplit(".", 1)  # 從最右邊分割

    module = _MODULE_CACHE.get(module_name)
    if not module:
        try:
            module = importlib.import_module(module_name)  # 取得專案內特定腳本的模組
            _MODULE_CACHE[module_name] = module  # 可重複使用
        except ImportError as e:
            raise ValueError(f"無法導入模組 {module_name} error: {e}") from e

    try:
        return getattr(module, func_name)  # 取得模組內的函數
    except AttributeError as e:
        raise ValueError(f"模組 {module_name} 找不到函式 {func_name}()") from e


def clear_function_cache() -> None:
    """放掉已經綁好的指令函式（重載指令集時呼叫）。

    這**不是**為了讓改過的程式生效——那需要 importlib.reload，而這個專案
    有七個單例，reload 會生出第二份類別與第二個實例（見 sheet_reloader 的說明）。
    這裡要的是「快取不能比它建立時依據的那張表活得久」：從表上刪掉的指令，
    它綁住的函式與簽章也該一起放掉。
    """
    _load_function.cache_clear()
    _wanted_params.cache_clear()


# ===== 共通處理入口 (判別指令類型) =====


async def _handle_entry(
    resp_type: str, content: str, tail: list[str], raw_tail_text: str, context: dict
) -> Optional[str]:

    if resp_type == "text":
        return content

    elif resp_type == "function":
        try:
            func = _load_function(content)
        except ValueError as e:
            # 這是 Sheets 設定錯誤（函數名打錯、模組不存在），
            # 訊息會夾帶模組路徑，同樣不能直接回到聊天室
            logger.error(f"指令設定有誤，無法載入「{content}」：{e}")
            return GENERIC_ERROR_REPLY
        return await _invoke(func, tail, raw_tail_text, context)
    return ""


# ===== 對外主函數 =====


async def dispatch_command(user_input: str, **context) -> Optional[str]:
    """
    user_input : str 使用者原始輸入
    context : dict   需要共用的物件 (例: char, message, author …
    """

    if not user_input:
        return ""

    normalized = user_input.replace("！", "!").strip()  # 把全形驚嘆號換成半形，並 strip

    try:
        tokens = shlex.split(normalized)  # 把整句安全分割成 tokens
    except ValueError:  # 不成對的引號會讓 shlex 拋例外，退回簡單切割
        tokens = normalized.split()
    if not tokens:
        return ""
    head, *tail = tokens
    head_up = head.upper()  # head 代表最前面的指令
    raw_tail_text = " ".join(tail)  # tail 則是後面所有字串依空格分割後裝進 list

    # ===== 內建指令 =====
    # 刻意排在 COMMAND_SET 的檢查之前：指令集載入失敗時 !reload 仍然要能用。
    # 也刻意蓋過試算表上的同名列——修復工具不該被壞掉的那張表關掉。
    builtin = BUILTIN_COMMANDS.get(head_up)
    if builtin:
        return await _handle_entry(*builtin, tail, raw_tail_text, context)

    if not COMMAND_SET:
        # 指令集沒載入成功（多半是 Google Sheets 微服務沒開）。
        # 這裡刻意「不」補載入：重試是 main.py 排程的工作。
        # 壓在每一則訊息上的話，服務沒開時每則都要耗掉一輪重試與退避，
        # 整個聊天室都會變慢；失敗還會讓這則訊息連招呼與獎勵都拿不到。
        logger.warning(f"指令集尚未載入，略過這次派發：{user_input}")
        return ""

    # ===== 驚嘆號指令 =====
    if head.startswith("!"):
        entry = COMMAND_SET.get(head_up)
        if entry:
            return await _handle_entry(*entry, tail, raw_tail_text, context)

    # ===== 無驚嘆號的關鍵字 =====
    else:

        for trigger, entry in COMMAND_SET.items():

            if trigger.startswith("!"):
                continue

            if trigger in normalized:

                # 針對特定指令，改成要完全一致才會觸發，不然太容易因為網址或句子內出現數字而觸發
                # 注意：這裡必須是 continue。過去誤用 break 會中斷整個掃描，
                # 導致訊息只要含有 0 或 87（網址、金額、時間都會），後面所有關鍵字指令全部失效。
                if trigger in ["0", "87"] and normalized != trigger:
                    continue

                return await _handle_entry(*entry, tail, raw_tail_text, context)

    return ""


if __name__ == "__main__":
    import asyncio

    test_inputs = [
        "!vip"
        # "!英雄",
        # "!富翁",
        # "!找歌 Young & Dumb",
        # "!YT",
        # "!INFO",
        # "!吃",
        # "!梗",
        # "!抽",
        # "!gpt 妳是誰",
    ]

    async def _demo():
        await load_command_set()
        for input_text in test_inputs:
            print("\n")
            logger.info(f"測試輸入：『{input_text}』")
            result = await dispatch_command(input_text)
            if result:
                logger.info(f"回覆：『{result}』")

    asyncio.run(_demo())
