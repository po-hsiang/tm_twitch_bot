"""把不知道是什麼形狀的物件攤成 dict，方便印出來看。

**刻意沒有任何呼叫端**（CODE_REVIEW P2-28 點過這件事）。它是手動除錯用的：
twitchio 與 twitchAPI 的事件物件是 attrs 類別，`print()` 出來看不到欄位，
臨時要看清楚裡面有什麼就 import 這一支。留著的理由是它十行、import 階段
沒有任何副作用，而需要它的時候通常是「線上發生了怪事」那種當下。

（也是 pyproject 宣告 attrs 的唯一理由——這裡真的 import attr。
過去只靠 twitchAPI 的傳遞依賴才裝得到，那哪天會壞。）
"""

import dataclasses
import attr


def dump_obj(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if attr.has(type(obj)):
        return attr.asdict(obj)
    # attrs / dataclass 都不是 → fallback
    return {s: getattr(obj, s) for s in getattr(obj, "__slots__", [])} or str(obj)
