"""One-shot: send Telegram ping after deploy (run on server with cwd=gods_plan)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv

load_dotenv()
import requests  # noqa: E402

t = os.getenv("TELEGRAM_BOT_TOKEN", "")
c = os.getenv("TELEGRAM_CHAT_ID", "")
r = requests.post(
    f"https://api.telegram.org/bot{t}/sendMessage",
    json={"chat_id": c, "text": "✅ MINERVA RESTORED\nTest now:\n/start\n/blog\n/macro"},
    timeout=20,
)
print(r.status_code, r.text[:200] if r.text else "")
