"""哪些環境變數是「少了就別啟動」，哪些是「少了只失去一個指令」。

這個分界是刻意的取捨（CODE_REVIEW P1-37）：
**整場開台沒有機器人，比少了一個 ! 指令嚴重得多。**
所以只有「少了就根本無法運作」的才擋在啟動，其餘一律記 warning 後照常上線。

`load_yaml()` 每次都重讀 YAML 與環境變數，且回傳新的 dict、
不會動到模組級的 `config`，所以可以安全地重複呼叫。
"""

import copy
import logging
from pathlib import Path

import pytest
import yaml

from tm_twitch_bot.config import loader


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
        loader.load_yaml()

    assert key in str(exc.value)  # 錯誤訊息要講清楚缺哪一個


def test_the_error_message_points_at_the_env_file(monkeypatch):
    monkeypatch.delenv("TWITCH_CLIENT_ID", raising=False)

    with pytest.raises(RuntimeError) as exc:
        loader.load_yaml()

    assert ".env" in str(exc.value)


# ===== 選填 =====


def test_a_missing_openai_key_does_not_stop_startup(monkeypatch, caplog):
    """AI 問答改走 n8n 之後，OPENAI_API_KEY 只剩 !pk 用得到。

    為了一個娛樂指令讓整個 Bot 起不來，與 P1-37 的取捨完全相反。
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with caplog.at_level(logging.WARNING):
        cfg = loader.load_yaml()

    assert cfg["openai"]["api_key"] == ""  # 空字串，不是拋例外
    assert "OPENAI_API_KEY" in caplog.text  # 但一定要留下痕跡


def test_a_missing_agent_secret_does_not_stop_startup(monkeypatch, caplog):
    """少了它只會讓 AI 問答指令失效。"""
    monkeypatch.delenv("TM_AI_AGENT_SECRET", raising=False)

    with caplog.at_level(logging.WARNING):
        cfg = loader.load_yaml()

    assert cfg["tm_ai_agent"]["webhook_secret"] == ""
    assert "TM_AI_AGENT_SECRET" in caplog.text


def test_both_optional_keys_missing_still_boots(monkeypatch):
    """兩個都沒有也要起得來——聊天 RPG、遊戲、排行榜、VIP 都不經過它們。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TM_AI_AGENT_SECRET", raising=False)

    cfg = loader.load_yaml()

    assert cfg["twitch"]["channel"]  # 設定本體照常載入


# ===== 機敏資訊不進 YAML =====


def test_secrets_come_from_the_env_not_the_yaml_file():
    """YAML 進版控，機敏值一律只從 .env 來。"""
    import io

    raw = io.open(loader.CONFIG_COMMON_PATH, encoding="utf-8").read()

    for forbidden in ("client_secret", "access_token", "refresh_token", "api_key", "webhook_secret"):
        assert f"{forbidden}:" not in raw, f"{forbidden} 不該出現在 config_common.yaml"


# ===== config_common.yaml 的 schema（CODE_REVIEW P2-22）=====
#
# 原本 config 完全沒有驗證。最實際的後果在 vip_system：`c.get("enabled")`
# 打錯 key 就是 None，整個 VIP 功能靜默停用，沒有任何警告。
# 現在同樣的錯誤會在啟動時就擋下來，而且訊息指名是哪個 key。


@pytest.fixture
def raw_yaml():
    """config_common.yaml 的原始內容（還沒合併 .env 的那份）。"""
    return yaml.safe_load(loader.CONFIG_COMMON_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def load_with(monkeypatch, tmp_path):
    """用改過的設定內容跑一次 load_yaml()。"""

    def _load(cfg: dict):
        path = tmp_path / "config_common.yaml"
        path.write_text(
            yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        monkeypatch.setattr(loader, "CONFIG_COMMON_PATH", path)
        return loader.load_yaml()

    return _load


def test_the_real_config_passes_the_schema(raw_yaml):
    """線上那份設定檔本身必須是合法的——否則下面的測試都沒有意義。"""
    assert loader.validate_config(raw_yaml) == []


def test_the_schema_covers_every_key_in_the_real_config(raw_yaml):
    """漂移守門員：新增了設定卻沒宣告型別，這裡會失敗。

    刻意讓 CI 失敗而不是讓 Bot 起不來——那時人還坐在電腦前，
    而開台時多一個沒宣告的 key 不會讓任何功能壞掉。
    """
    unknown = loader.unknown_config_keys(raw_yaml)
    assert unknown == [], f"這些欄位還沒宣告在 loader._SCHEMA：{unknown}"


def test_a_missing_key_is_reported_by_name(raw_yaml):
    cfg = copy.deepcopy(raw_yaml)
    del cfg["vip_system"]["enabled"]

    problems = loader.validate_config(cfg)

    assert any("vip_system.enabled" in p for p in problems)


def test_a_whole_missing_section_is_reported(raw_yaml):
    cfg = copy.deepcopy(raw_yaml)
    del cfg["vip_system"]

    problems = loader.validate_config(cfg)

    assert len(problems) == 4  # 這一節的四個欄位都要各自被點名
    assert all("vip_system." in p for p in problems)


def test_a_wrong_type_is_reported_with_both_types(raw_yaml):
    cfg = copy.deepcopy(raw_yaml)
    cfg["vip_system"]["gold_cost"] = "一百"

    problems = loader.validate_config(cfg)

    assert len(problems) == 1
    assert "gold_cost" in problems[0]
    assert "int" in problems[0] and "str" in problems[0]


def test_a_bool_is_not_accepted_as_an_int(raw_yaml):
    """isinstance(True, int) 是 True——bool 是 int 的子類別。

    但 gold_cost: true 顯然是設定錯了，不能因為型別系統的細節就放過。
    """
    cfg = copy.deepcopy(raw_yaml)
    cfg["vip_system"]["gold_cost"] = True

    problems = loader.validate_config(cfg)

    assert len(problems) == 1
    assert "bool" in problems[0]


@pytest.mark.parametrize(
    "path, empty_value",
    [
        (("google_sheets", "svc_url"), ""),
        (("twitch", "channel"), ""),
    ],
)
def test_an_empty_string_is_as_bad_as_a_missing_key(raw_yaml, path, empty_value):
    """空的 svc_url 只會讓每一次呼叫都失敗，跟沒填一樣壞。"""
    cfg = copy.deepcopy(raw_yaml)
    cfg[path[0]][path[1]] = empty_value

    problems = loader.validate_config(cfg)

    assert len(problems) == 1
    assert "不能是空的" in problems[0]


def test_an_empty_admin_list_is_rejected(raw_yaml):
    """admin_user_id 空掉的話，開遊戲與 !reload 全部失效，而且不會有錯誤。"""
    cfg = copy.deepcopy(raw_yaml)
    cfg["admin_user_id"] = []

    problems = loader.validate_config(cfg)

    assert any("admin_user_id" in p for p in problems)


def test_every_problem_is_reported_at_once(raw_yaml):
    """啟動失敗的重試成本很高，不能修一個才發現下一個。"""
    cfg = copy.deepcopy(raw_yaml)
    del cfg["is_test"]
    cfg["vip_system"]["vip_cap"] = "五十一"
    cfg["youtube"]["svc_url"] = ""

    problems = loader.validate_config(cfg)

    assert len(problems) == 3


def test_a_broken_config_stops_startup(raw_yaml, load_with):
    """schema 不只是個工具函式，load_yaml() 真的會擋下來。"""
    cfg = copy.deepcopy(raw_yaml)
    del cfg["rpg_parameter"]["exp_req_multiple"]

    with pytest.raises(RuntimeError) as exc:
        load_with(cfg)

    assert "rpg_parameter.exp_req_multiple" in str(exc.value)
    assert "config_common.yaml" in str(exc.value)


def test_an_unknown_key_only_warns(raw_yaml, load_with, caplog):
    """多一個沒宣告的 key 不該讓整場開台沒有機器人（同 P1-37 的取捨）。"""
    cfg = copy.deepcopy(raw_yaml)
    cfg["vip_system"]["future_feature"] = 123

    with caplog.at_level(logging.WARNING):
        loaded = load_with(cfg)

    assert loaded["vip_system"]["future_feature"] == 123  # 照常載入
    assert "vip_system.future_feature" in caplog.text
    assert "_SCHEMA" in caplog.text  # 訊息要講怎麼修


def test_the_vip_section_is_read_strictly(monkeypatch):
    """VIP 設定改成直接索引，不再是 .get() 拿到 None 然後靜默停用。

    schema 已保證這四個 key 存在，所以「打錯 key」現在會在啟動時就炸，
    而不是等到有人回報「!vip 沒反應」。
    """
    from tm_twitch_bot.commands import vip as vs

    monkeypatch.setitem(vs.config, "vip_system", {"enabled": True})

    with pytest.raises(KeyError):
        vs._load_vip_config()


# ===== 設定值不要在程式碼裡再抄一份（CODE_REVIEW P3-36）=====


def test_no_python_file_hardcodes_the_command_sheet_url():
    """上線公告原本內嵌了一份指令集網址。

    抓表用的是 config 那一份、公告用的是程式碼那一份，換試算表時只改一邊，
    觀眾就會拿到指向舊表的連結——而且不會有任何錯誤。

    這條測試比「檢查公告內容」更有效：它擋的是「下次又有人貼一份網址進去」。
    """
    src_root = Path(loader.__file__).resolve().parents[1]
    offenders = [
        path.relative_to(src_root).as_posix()
        for path in src_root.rglob("*.py")
        if "docs.google.com" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"這些檔案內嵌了試算表網址，請改讀 config：{offenders}"


def test_the_announcement_url_comes_from_config():
    from tm_twitch_bot import bot

    assert bot.COMMAND_SHEET_URL == loader.config["google_sheets"]["sheet_url"]
