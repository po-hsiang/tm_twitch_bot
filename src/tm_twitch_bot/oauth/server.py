from fastapi import FastAPI, Request, HTTPException
from tm_twitch_bot.utils.yaml_utils import config
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
    state = req.query_params.get("state")
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
