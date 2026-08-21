"""聊天訊息的進出與派發。

    Twitch → message_controller（冷卻／洗頻／獎勵）→ dispatcher（比對指令集）
                                                        ↓
                                            commands/ 底下的功能函式
                                                        ↓
    Twitch ← sender（換行整平／長度截斷／速率保護）←───────┘

`sender` 是**全專案唯一**真的碰到 `channel.send` 的地方，所以每一則出站訊息
都適用的 Twitch 協定限制通通擺在那一層（見該模組說明）。
"""
