"""news_scan.py

Lightweight thesis scanner hook.

This is intentionally minimal: it keeps the daily pipeline stable even when no
news scanning is configured yet.

Expected side-effect (optional): write data/thesis_status.json with structure:
{ "results": { "PLTR": {"status":"INTACT","evidence":"...","source":"...","date":"YYYY-MM-DD"}, ... } }
"""

import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def scan_all_theses() -> None:
    """Run thesis scan. No-op if no scanner configured."""
    # If a thesis_status.json already exists, leave it untouched.
    thesis_path = os.path.join(BASE, "data", "thesis_status.json")
    if os.path.exists(thesis_path):
        return

    # Create an empty scaffold so output layer can rely on the file shape.
    os.makedirs(os.path.dirname(thesis_path), exist_ok=True)
    with open(thesis_path, "w", encoding="utf-8") as f:
        json.dump({"results": {}}, f, indent=2)
