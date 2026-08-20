"""單例 metaclass，全專案共用這一份。

CODE_REVIEW P2-21：八個類別（四個微服務 client、n8n client、VipSystem、
兩個遊戲）各自貼了一份**完全相同**的 `_SingletonMeta`。要改行為得改八個地方，
而「八份真的一樣」這件事沒有任何東西保證——實際上第八輪把它記成七份，
是因為後來新增的 `n8n_ai_agent` 又貼了一份沒被算進去。

**合併之後才出現的風險：鎖從八把變成一把。**
八份各有自己的鎖時，「單例 A 的 `__init__` 裡建立單例 B」是安全的；
共用一把之後，同一條執行緒會在還持有鎖的狀態下再次要求同一把鎖，
而 `threading.Lock` 不可重入——那是死鎖，而且是整個程式卡住不動、
沒有任何錯誤訊息的那種。所以這裡用 `RLock`。
目前沒有任何 `__init__` 這樣做，但這種死鎖只要「加一行看起來無害的程式碼」
就會踩到，不值得為它省什麼。

**鎖本身為什麼留著**：全專案跑在單一事件圈上，而所有單例都是在 import 階段
的模組層 `foo = Foo()` 建立的，import 本身就有 import lock 擋著——所以現在
這把鎖確實沒有作用。留著是因為它的代價只有啟動時八次沒有競爭的鎖操作，
而哪天有人從 `asyncio.to_thread` 裡建立單例時它就有意義了。
"""

import threading
from typing import Any


class SingletonMeta(type):
    """讓 `Foo()` 永遠回傳同一個實例。

    `_instances` 以類別本身為 key，所以八個類別共用這一份 dict
    仍然是「一個類別一個實例」。
    """

    _instances: dict[type, Any] = {}
    _lock = threading.RLock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                # 進了鎖再檢查一次：等鎖的期間可能已經有人建好了
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
