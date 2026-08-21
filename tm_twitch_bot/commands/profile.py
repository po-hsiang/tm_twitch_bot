"""`!INFO`／`!查`：把自己的角色數值印出來。

只有這一行指令函式，本體是 Character.get_info()。拆出來的理由是分層：
model/character.py 是全專案共用的資料模型，不該同時是某個指令的實作——
而且試算表指向的東西統一收在 commands/ 底下才好找（見 commands/__init__.py）。
"""

def check(*args, **kwargs):
    char = kwargs.get("char")
    return char.get_info()
