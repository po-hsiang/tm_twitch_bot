"""共用的業務模型：角色與轉職規則。

這裡的東西被 chat/、commands/ 全體共用，所以刻意不放在任何一個功能底下。
`Character` 會自己讀寫 MongoDB（不是純資料類別），這是為了讓「異動與存檔」
綁在同一個物件上——存檔的保證在 chat/message_controller 的 finally。
"""
