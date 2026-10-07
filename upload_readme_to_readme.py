import os
import requests
import json
import base64

api_key = os.getenv("README_API_KEY")
if not api_key:
    raise RuntimeError("README_API_KEY not set in environment!")

with open("README.md") as f:
    body = f.read()

payload = {"title": "README.md", "category": "test123", "body": body}

encoded = base64.b64encode(f"{api_key}:".encode()).decode()
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Basic {encoded}",
}

response = requests.post(
    "https://dash.readme.com/api/v1/docs", headers=headers, data=json.dumps(payload)
)
print(response.status_code)
print(response.text)
