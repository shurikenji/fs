# import requests

# BASE = "https://api.aabao.top"
# URL = f"{BASE}/api/pricing"

# # USER_ID = "465"
# # ACCESS_TOKEN = "BFcot9/Cno1HzvJR/cD+IXlcwPj5oZ0="  # token bạn đang dùng

# params = {
#     # "token": "sk-lrAwopjN1WvjIIZtz3LaigjMsAiMubEMUvz3iUOSP4bhqThz"
# }

# headers = {
#     # "Accept": "application/json",
#     # "New-Api-User": USER_ID,
#     # "Authorization": f"Bearer {ACCESS_TOKEN}",
# }

# r = requests.get(URL, headers=headers, params=params, timeout=30)

# data = r.json()

# print(data)

import requests
import json

BASE = "https://api.aabao.top"
URL = f"{BASE}/api/pricing"

params = {}

headers = {}

r = requests.get(URL, headers=headers, params=params, timeout=30)
data = r.json()

# Ghi ra file
with open("pricing.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)

print("Đã lưu vào pricing.json")