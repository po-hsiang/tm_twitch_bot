"""對外 HTTP 呼叫的唯一出入口，一個檔案對一個服務。

四個本機 Go 微服務（9091~9094）、自架 n8n 的 AI Agent、以及 Twitch Helix 的
VIP API。服務清單、埠號、掛掉的影響見 docs/SERVICES.md。

這一層刻意只做「把參數包成請求、把回應拆成 Python 值」，不做業務判斷：
重試與逾時在 utils/http_utils，業務規則在 commands/ 與 model/。
"""
