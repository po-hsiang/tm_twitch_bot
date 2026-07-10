from tm_twitch_bot.svc_client.mongo_atlas import mongo_atlas_client
from tm_twitch_bot.utils.yaml_utils import config


def _format_rank_list(rank_data: list[dict], mode: str) -> str:
    parts = []
    for idx, doc in enumerate(rank_data, 1):
        name = doc.get("display_names", ["?"])[-1]
        if mode == "hero":
            parts.append(f"【 {idx}. {name} | Lv.{doc['level']} | {doc['job']} 】")
        else:
            parts.append(f"【 {idx}. {name} | GOLD {doc['gold']} 】")
    return " / ".join(parts) if parts else "目前沒有資料…"


def top_heroes(*args, **kwargs) -> str:
    docs = mongo_atlas_client.find(
        "tm_twitch_users",
        filter={"user_id": {"$ne": config["tigermeowtw_id"]}},
        projection={"_id": 0, "display_names": 1, "level": 1, "exp": 1, "job": 1},
        sort=[["level", -1], ["exp", -1]],
        limit=3,
    )
    return _format_rank_list(docs, "hero")


def top_richest(*args, **kwargs) -> str:
    docs = mongo_atlas_client.find(
        "tm_twitch_users",
        filter={"user_id": {"$ne": config["tigermeowtw_id"]}},
        projection={"_id": 0, "display_names": 1, "gold": 1},
        sort=[["gold", -1]],
        limit=3,
    )
    return _format_rank_list(docs, "rich")


if __name__ == "__main__":
    print(top_heroes())
    print(top_richest())
