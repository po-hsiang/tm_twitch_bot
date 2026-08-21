from fastapi import FastAPI, Request, HTTPException
from tm_twitch_bot.config.loader import config
from tm_twitch_bot.utils.log_utils import logger
import uvicorn
import httpx

"""
https://id.twitch.tv/oauth2/authorize
  ?client_id=pj6c7xy4ge0j1r5q47vs7lo7zvhc9m
  &redirect_uri=https://welcome-my-jellyfin.pohsiangjuan.com/callback
  &response_type=code
  &scope=chat:read+chat:edit+channel:read:redemptions
  &state=xyz123
"""
"""
https://id.twitch.tv/oauth2/authorize
  ?client_id=pj6c7xy4ge0j1r5q47vs7lo7zvhc9m
  &redirect_uri=https://welcome-my-jellyfin.pohsiangjuan.com/callback
  &response_type=code
  &scope=chat:read+chat:edit+channel:read:redemptions+channel:read:vips+channel:manage:vips
  &force_verify=true

"""

twitch_config = config["twitch"]

app = FastAPI()


@app.get("/callback")
async def oauth_callback(req: Request):
    code = req.query_params.get("code")
    # 這裡刻意「不」取 state：現行的授權網址（見上方第二個註解區塊）已經沒有
    # 帶 &state=，所以 Twitch 也不會回傳，取了只會拿到 None。
    # 也就是說這條 callback 目前沒有 CSRF 防護。之所以還可以接受：
    # 它是頻道主自己在本機手動跑一次的一次性工具，不是常駐服務。
    # 要補的話得三件一起做——產生隨機 state、放進手動貼的授權網址、
    # 回來時比對——屬於 CODE_REVIEW P3-34 的範圍，不在這次的 lint 清理裡。
    if not code:
        raise HTTPException(400, "Missing Code")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": twitch_config["client_id"],
                "client_secret": twitch_config["client_secret"],
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": twitch_config["redirect_uri"],
            },
        )
        data = resp.json()
        logger.info(f"oauth2/token Response: {data}")
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8096)
