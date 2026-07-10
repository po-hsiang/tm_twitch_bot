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


# ===== 共用呼叫橋樑 =====


async def _invoke(func, tail: list[str], raw_tail_text: str, context: dict):
    accepted_kw = {
        # 只挑函式簽章允收的名字，避免多餘 kwargs
        name: value
        for name, value in {
            "raw_tail_text": raw_tail_text,
            **context,
        }.items()
    }
    try:
        result = func(*tail, **accepted_kw)
        if inspect.isawaitable(result):  # 指令函數已全面 async 化，同步函數也相容
            result = await result
        return result
    except Exception as e:
        return f"⚠️ 執行 {func.__name__} 時發生錯誤：{e}"


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
            return str(e)
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

    if not COMMAND_SET:  # 保險：bootstrap 沒跑到時，第一次派發前補載入
        await load_command_set()

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
                if trigger in ["0", "87"] and normalized != trigger:
                    break

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
