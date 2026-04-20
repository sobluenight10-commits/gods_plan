"""
staleness_watch.py — OLYMPUS health heartbeat.

Fires a Telegram alert if critical daily artifacts are older than threshold
hours. Intended to be run hourly via cron so silent pipeline failures
(like the UTF-16 encoding bug that killed olympus_daily for 6 days) can
never go unnoticed again.

Thresholds (hours):
  dashboard_state.json   → 30   (daily pipeline)
  directives.json        → 30   (one_command refresh)
  risk_latest.json       → 30   (9-dim skill)
  fundamentals_latest    → 30
  prices.json            → 24
"""
from __future__ import annotations

import os
import json
import time
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

CHECKS = [
    ("dashboard_state", os.path.join(DATA, "dashboard_state.json"),      30),
    ("directives",       os.path.join(DATA, "directives.json"),          30),
    ("risk_latest",      os.path.join(DATA, "skill_results", "risk_latest.json"), 30),
    ("fundamentals",     os.path.join(DATA, "skill_results", "fundamentals_latest.json"), 30),
    ("prices",           os.path.join(BASE, "prices.json"),              24),
]

STATE_PATH = os.path.join(DATA, "staleness_state.json")


def _load_env():
    env_path = os.path.join(BASE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _send_telegram(text: str) -> bool:
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return bool(r.ok)
    except Exception:
        return False


def _age_hours(path: str) -> float | None:
    if not os.path.exists(path):
        return None
    return (time.time() - os.path.getmtime(path)) / 3600.0


def _cooldown_ok(key: str, hours: float = 6.0) -> bool:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:
        s = {}
    last = s.get(key, 0)
    return (time.time() - last) > hours * 3600


def _mark_sent(keys: list[str]) -> None:
    try:
        s = {}
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, encoding="utf-8") as f:
                s = json.load(f) or {}
        now = time.time()
        for k in keys:
            s[k] = now
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except Exception:
        pass


def main() -> int:
    _load_env()
    stale = []
    for name, path, threshold_h in CHECKS:
        age = _age_hours(path)
        if age is None:
            stale.append((name, None, threshold_h, "MISSING"))
        elif age > threshold_h:
            stale.append((name, age, threshold_h, "STALE"))

    if not stale:
        print(f"[staleness_watch] OK at {datetime.now().isoformat(timespec='seconds')}")
        return 0

    fire = [x for x in stale if _cooldown_ok(x[0])]
    if not fire:
        print("[staleness_watch] stale but within cooldown — no alert")
        return 0

    lines = ["⚠️ <b>OLYMPUS STALENESS ALERT</b>", ""]
    for name, age, thr, status in fire:
        if status == "MISSING":
            lines.append(f"❌ <b>{name}</b> — file MISSING (threshold {thr}h)")
        else:
            lines.append(f"⏳ <b>{name}</b> — {age:.1f}h old (>{thr}h threshold)")
    lines.append("")
    lines.append("Pipeline likely silently failing. SSH Minerva and run:")
    lines.append("<code>cd ~/gods_plan && python3 olympus_daily.py 2>&1 | tail</code>")
    msg = "\n".join(lines)
    ok = _send_telegram(msg)
    if ok:
        _mark_sent([x[0] for x in fire])
        print("[staleness_watch] alert sent")
    else:
        print("[staleness_watch] alert NOT sent (no Telegram creds or API fail)")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
