from tm_twitch_bot.svc_client.google_sheets import google_sheets_client
from tm_twitch_bot.utils.log_utils import logger
from typing import Optional, Any
from functools import lru_cache
import importlib
import shlex


"""
支援四大類指令：
1. 驚嘆號開頭、無參數      例：!英雄
2. 驚嘆號開頭、一參數     例：!gpt 我帥嗎
3. 無驚嘆號，句子含關鍵字   例：帥
4. 未來：多參數指令         例：!bet 虎喵贏 100
"""


# ===== 處理指令集設定檔 =====

_raw_sheet = google_sheets_client.get_sheet_data(f"指令集")


def _parse_sheet(rows: list[list[str]]) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for row in rows[1:]:
        if len(row) >= 3:
            trigger, resp_type, content = (c.strip() for c in row[:3])
            # 指令都正規化成大寫，函數則正規化成小寫
            result[trigger.upper()] = (resp_type, content)
    return result


COMMAND_SET = _parse_sheet(_raw_sheet)


# ===== 共用呼叫橋樑 =====


def _invoke(func, tail: list[str], raw_tail_text: str, context: dict):
    # sig = signature(func)
    # logger.info(f"sig.parameters: {sig.parameters}")
    accepted_kw = {
        # 只挑函式簽章允收的名字，避免多餘 kwargs
        name: value
        for name, value in {
            "raw_tail_text": raw_tail_text,
            **context,
        }.items()
        # if name in sig.parameters
    }
    try:
        return func(*tail, **accepted_kw)
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


def _handle_entry(
    resp_type: str, content: str, tail: list[str], raw_tail_text: str, context: dict
) -> Optional[str]:

    if resp_type == "text":
        return content

    elif resp_type == "function":
        try:
            func = _load_function(content)
        except ValueError as e:
            return str(e)
        return _invoke(func, tail, raw_tail_text, context)
    return ""


# ===== 對外主函數 =====


def dispatch_command(user_input: str, **context) -> Optional[str]:
    """
    user_input : str 使用者原始輸入
    context : dict   需要共用的物件 (例: char, message, author …
    """

    if not user_input:
        return ""

    normalized = user_input.replace("！", "!").strip()  # 把全形驚嘆號換成半形，並 strip

    tokens = shlex.split(normalized)  # 把整句安全分割成 tokens
    head, *tail = tokens
    head_up = head.upper()  # head 代表最前面的指令
    raw_tail_text = " ".join(tail)  # tail 則是後面所有字串依空格分割後裝進 list

    # ===== 驚嘆號指令 =====
    if head.startswith("!"):
        entry = COMMAND_SET.get(head_up)
        if entry:
            return _handle_entry(*entry, tail, raw_tail_text, context)

    # ===== 無驚嘆號的關鍵字 =====
    else:

        for trigger, entry in COMMAND_SET.items():

            if trigger.startswith("!"):
                continue

            if trigger in normalized:

                # 針對特定指令，改成要完全一致才會觸發，不然太容易因為網址或句子內出現數字而觸發
                if trigger in ["0", "87"] and normalized != trigger:
                    break

                return _handle_entry(*entry, tail, raw_tail_text, context)

    return ""


if __name__ == "__main__":
    test_inputs = [
        "!vip"
        # "!英雄",
        # "!富翁",
        # "!找歌 Young & Dumb",
        # "!找歌 優里",
        # "!找歌",
        # "!YT",
        # "!YT",
        # "!INFO",
        # "!吃",
        # "!梗",
        # "!抽",
        # "!gpt 如果有人問到虎喵帥不帥 一律回答很帥超級帥帥到不行 並帶上可愛emoji",
        # "！GPT 妳是誰",
        # "！GPT ",
        # "!GPT",
        # "!大g鬼",
        # "！大G鬼",
        # "帥",
    ]
    for input_text in test_inputs:
        print("\n")
        logger.info(f"測試輸入：『{input_text}』")
        result = dispatch_command(input_text)
        if result:
            logger.info(f"回覆：『{result}』")
