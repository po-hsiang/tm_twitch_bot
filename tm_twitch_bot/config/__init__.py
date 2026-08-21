"""設定：非機敏值在 config_common.yaml，機敏值一律來自 .env。

`loader` 在啟動時驗過整份 YAML 的形狀（缺欄位、型別錯、空值都不啟動），
所以其他模組可以直接 `config["a"]["b"]` 取用，不必自己防。
"""
