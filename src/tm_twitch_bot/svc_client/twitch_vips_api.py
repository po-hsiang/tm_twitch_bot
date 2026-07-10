from typing import Tuple, Optional
import requests

HELIX = "https://api.twitch.tv/helix"


def _headers(token: str, client_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Client-Id": client_id}


def get_user_id_by_user_name(token: str, client_id: str, user_name: str) -> str:
    r = requests.get(
        f"{HELIX}/users",
        headers=_headers(token, client_id),
        params={"login": user_name},
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        raise ValueError(f"找不到使用者：{user_name}")
    print(f"data: {data}")
    return data[0]["id"]


def add_channel_vip(
    token: str, client_id: str, broadcaster_id: str, user_id: str
) -> Tuple[bool, Optional[str]]:
    r = requests.post(
        f"{HELIX}/channels/vips",
        headers=_headers(token, client_id),
        params={"broadcaster_id": broadcaster_id, "user_id": user_id},
    )
    if r.status_code == 204:
        return True, None
    return False, r.json()


def remove_channel_vip(
    token: str, client_id: str, broadcaster_id: str, user_id: str
) -> Tuple[bool, Optional[str]]:
    r = requests.delete(
        f"{HELIX}/channels/vips",
        headers=_headers(token, client_id),
        params={"broadcaster_id": broadcaster_id, "user_id": user_id},
    )
    if r.status_code == 204:
        return True, None
    return False, r.json()


def get_vips(
    token: str,
    client_id: str,
    broadcaster_id: str,
    first: int = 100,
    after: Optional[str] = None,
):
    params = {"broadcaster_id": broadcaster_id, "first": first}
    if after:
        params["after"] = after
    r = requests.get(
        f"{HELIX}/channels/vips", headers=_headers(token, client_id), params=params
    )
    r.raise_for_status()
    return r.json()
