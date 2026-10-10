import os, json, requests
from dotenv import load_dotenv

load_dotenv()
url = os.getenv("GOOGLE_SCRIPT_URL", "")
secret = os.getenv("GOOGLE_SCRIPT_SECRET", "")

r = requests.post(url, data=json.dumps({"secret": secret, "action": "ensure", "sheets": {"Test": ["a", "b"]}}),
                  headers={"Content-Type": "text/plain; charset=utf-8"}, timeout=120)
print("STATUS:", r.status_code)
print("TYPE:", r.headers.get("Content-Type"))
print("FINAL URL:", r.url[:120])
print(r.text[:700])