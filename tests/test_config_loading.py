"""哪些環境變數是「少了就別啟動」，哪些是「少了只失去一個指令」。

這個分界是刻意的取捨（CODE_REVIEW P1-37）：
**整場開台沒有機器人，比少了一個 ! 指令嚴重得多。**
所以只有「少了就根本無法運作」的才擋在啟動，其餘一律記 warning 後照常上線。

`load_yaml()` 每次都重讀 YAML 與環境變數，且回傳新的 dict、
不會動到模組級的 `config`，所以可以安全地重複呼叫。
"""

import logging

import pytest

from tm_twitch_bot.utils import yaml_utils


# ===== 硬性要求 =====


@pytest.mark.parametrize(
    "key",
    [
        "TWITCH_CLIENT_ID",
        "TWITCH_CLIENT_SECRET",
        "TWITCH_ACCESS_TOKEN",
        "TWITCH_REFRESH_TOKEN",
    ],
)
def test_twitch_credentials_stop_startup_when_missing(monkeypatch, key):
    """這四個少了任何一個，Bot 根本連不上 Twitch——沒有降級的意義。"""
    monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError) as exc:
        yaml_utils.load_yaml()

    assert key in str(exc.value)  # 錯誤訊息要講清楚缺哪一個


def test_the_error_message_points_at_the_env_file(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)

    with pytest.raises(RuntimeError) as exc:
        yaml_utils.load_yaml()

    assert ".env" in str(exc.value)


# ===== 選填 =====


def test_a_missing_openai_key_does_not_stop_startup(monkeypatch, caplog):
    """AI 問答改走 n8n 之後，OPENAI_API_KEY 只剩 !pk 用得到。

    為了一個娛樂指令讓整個 Bot 起不來，與 P1-37 的取捨完全相反。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING):
        cfg = yaml_utils.load_yaml()

    assert cfg["openai"]["api_key"] == ""  # 空字串，不是拋例外
    assert "OPENAI_API_KEY" in caplog.text  # 但一定要留下痕跡


def test_a_missing_agent_secret_does_not_stop_startup(monkeypatch, caplog):
    """少了它只會讓 AI 問答指令失效。"""
    monkeypatch.delenv("TM_AI_AGENT_SECRET", raising=False)

    with caplog.at_level(logging.WARNING):
        cfg = yaml_utils.load_yaml()

    assert cfg["tm_ai_agent"]["webhook_secret"] == ""
    assert "TM_AI_AGENT_SECRET" in caplog.text


def test_both_optional_keys_missing_still_boots(monkeypatch):
    """兩個都沒有也要起得來——聊天 RPG、遊戲、排行榜、VIP 都不經過它們。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TM_AI_AGENT_SECRET", raising=False)

    cfg = yaml_utils.load_yaml()

    assert cfg["twitch"]["channel"]  # 設定本體照常載入


# ===== 機敏資訊不進 YAML =====


def test_secrets_come_from_the_env_not_the_yaml_file():
    """YAML 進版控，機敏值一律只從 .env 來。"""
    import io

    raw = io.open(yaml_utils.CONFIG_COMMON_PATH, encoding="utf-8").read()

    for forbidden in ("client_secret", "access_token", "refresh_token", "api_key", "webhook_secret"):
        assert f"{forbidden}:" not in raw, f"{forbidden} 不該出現在 config_common.yaml"
