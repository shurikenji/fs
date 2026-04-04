import requests
import json
BASE = "https://api.aabao.vip"
URL = f"{BASE}/api/log/self"

USER_ID = "465"
ACCESS_TOKEN = "zdUpTLgITEtI7U/OytA0rJCsQpm2xGjj"  # token bạn đang dùng

params = {
    "p": 1,
    "page_size": 100,
    "type": 0,
    "token_name": "duynguyenzl-pz3dqs",              # endpoint này bạn để trống như URL
    "model_name": "",
    # "start_timestamp": 1770138000,
    # "end_timestamp": 1770154511,
    "group": "",
}

headers = {
    "Accept": "application/json",
    "New-Api-User": USER_ID,
    "Authorization": f"Bearer {ACCESS_TOKEN}",
}

r = requests.get(URL, headers=headers, params=params, timeout=30)

print("Status:", r.status_code)
print("URL:", r.url)
print("Body:", r.text)

r.raise_for_status()
data = r.json()

with open("log.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)
print("JSON:", data)
