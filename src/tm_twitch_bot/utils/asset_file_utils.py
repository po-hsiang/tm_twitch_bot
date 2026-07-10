# from utils.error_utils import notify
# from pathlib import Path
# import aiohttp
# import re

# ASSET_DOWNLOAD_PATH = Path("./downloaded_assets")
# CHUNK_SIZE = 64 * 1024  # 64KB, 依實際情況可調整
# GOOGLE_DRIVE_EXPORT_URL = "https://drive.google.com/uc?export=download&id="


# def extract_drive_id(share_link: str) -> str:
#     # 用正則表達式找出 /d/ 與 /view 之間的部分作為檔案 id
#     match = re.search(r"/d/([a-zA-Z0-9_-]+)", share_link)
#     if match:
#         file_id = match.group(1)
#         download_url = f"{GOOGLE_DRIVE_EXPORT_URL}{file_id}"
#         return download_url
#     return share_link  # 如果沒有找到 id，就回傳原始連結


# async def download_asset(file_url: str, file_type: str, temp_file_name: str) -> Path:
#     """
#     先轉換連結再下載檔案，並存放至 ASSET_DOWNLOAD_PATH 中，
#     若下載成功，回傳檔案的 Path 物件；若失敗則拋出例外。
#     """
#     file_url = extract_drive_id(file_url)  # 轉換 Google Drive 分享連結為下載連結

#     ASSET_DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)  # 確保下載資料夾存在
#     file_path = ASSET_DOWNLOAD_PATH / f"{temp_file_name}.{file_type}"  # 預設檔案名稱，例如 "pt-BR.mp4"

#     async with aiohttp.ClientSession() as session:
#         try:
#             async with session.get(file_url) as response:
#                 if response.status != 200:
#                     raise ValueError(f"下載失敗 (Status: {response.status}), url: {file_url}")
#                 with open(file_path, "wb") as f:  # 寫入檔案
#                     while True:
#                         chunk = await response.content.read(CHUNK_SIZE)
#                         if not chunk:
#                             break
#                         f.write(chunk)
#         except Exception as e:
#             notify(f"下載 {temp_file_name} 時發生錯誤", e)
#             raise e
#     return file_path


# def remove_local_asset(file_path: Path) -> bool:
#     # 刪除指定路徑下的檔案，若檔案存在則刪除並回傳 True；若不存在或刪除失敗則回傳 False。
#     if file_path.exists():
#         try:
#             file_path.unlink()
#             return True
#         except Exception as e:
#             notify(f"刪除檔案 {file_path} 失敗", e)
#             return False
#     notify(f"刪除檔案發現 {file_path} 不存在", FileNotFoundError)
#     return False
