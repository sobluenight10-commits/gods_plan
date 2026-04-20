"""
gem_grade_diff.py — Daily GEM ranking diff digest for Telegram.

Compares the latest gem_YYYYMMDD.json against the previous run and reports:
  1. Grade changes (letter up/down)
  2. Top-10 ranking order changes
  3. New entries / fell-off names
  4. What drives each change (risk, EV, precision tier)

Runs at the tail of olympus_daily.py (07:00 Berlin) and can be invoked manually.
Dedupes so it fires at most once per new gem_ file.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEM_DIR = os.path.join(BASE, "gem_results")
STATE = os.path.join(BASE, "data", "gem_diff_state.json")

GRADE_ORDER = ["S", "A+", "A", "B+", "B", "C+", "C", "D", "F"]
GRADE_RANK = {g: i for i, g in enumerate(GRADE_ORDER)}


def _load_env() -> None:
    env_path = os.path.join(BASE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _send_tg(text: str) -> bool:
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("[GEM_DIFF] no Telegram creds")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=12,
        )
        if not r.ok:
            print(f"[GEM_DIFF] Telegram HTTP {r.status_code}: {r.text[:160]}")
        return bool(r.ok)
    except Exception as exc:
        print(f"[GEM_DIFF] Telegram error: {exc}")
        return False


def _load(path: str) -> Dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _rank_rows(doc: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    rows = []
    for r in doc.get("results", []):
        g = r.get("grading") or {}
        rows.append((r.get("ticker", "?"), {
            "grade": g.get("grade", "F"),
            "tier": g.get("precision_tier", 1),
            "pgrade": g.get("precision_grade", g.get("grade", "F")),
            "gem": g.get("gem_score"),
            "u1y": g.get("upside_1y_pct"),
            "u5y": g.get("upside_5y_pct"),
            "risk": g.get("risk_level", "UNKNOWN"),
            "reason": (g.get("reason") or "")[:140],
        }))
    rows.sort(key=lambda x: (GRADE_RANK.get(x[1]["grade"], 9), x[1]["tier"], -(x[1]["u5y"] or 0)))
    return rows


def _driver(prev: Dict[str, Any], cur: Dict[str, Any]) -> str:
    parts = []
    if prev["grade"] != cur["grade"]:
        parts.append(f"grade {prev['grade']}→{cur['grade']}")
    if prev["tier"] != cur["tier"]:
        parts.append(f"tier {prev['tier']}→{cur['tier']}")
    if prev["risk"] != cur["risk"]:
        parts.append(f"risk {prev['risk']}→{cur['risk']}")
    for k, label in (("u1y", "1Y EV"), ("u5y", "5Y EV")):
        a, b = prev.get(k) or 0, cur.get(k) or 0
        if abs(b - a) >= 2.5:
            parts.append(f"{label} {a:+.1f}→{b:+.1f}%")
    return " · ".join(parts) or cur.get("reason", "—")


def _gem_files() -> List[str]:
    if not os.path.isdir(GEM_DIR):
        return []
    return sorted(f for f in os.listdir(GEM_DIR) if f.startswith("gem_") and f.endswith(".json"))


def run() -> int:
    _load_env()
    files = _gem_files()
    if len(files) < 2:
        print("[GEM_DIFF] need at least 2 gem_*.json runs")
        return 0

    latest_name = files[-1]
    # Dedupe: only fire once per latest file
    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8")) or {}
        except Exception:
            state = {}
    if state.get("last_sent") == latest_name:
        print(f"[GEM_DIFF] already sent for {latest_name}")
        return 0

    prev_doc = _load(os.path.join(GEM_DIR, files[-2])) or {}
    cur_doc = _load(os.path.join(GEM_DIR, latest_name)) or {}
    prev_rows = dict(_rank_rows(prev_doc))
    cur_ordered = _rank_rows(cur_doc)
    cur_rank = {tk: i + 1 for i, (tk, _) in enumerate(cur_ordered)}
    prev_rank = {tk: i + 1 for i, (tk, _) in enumerate(_rank_rows(prev_doc))}

    grade_ups, grade_downs, new_names, dropped = [], [], [], []
    rank_gainers, rank_losers = [], []

    for i, (tk, cur) in enumerate(cur_ordered):
        prev = prev_rows.get(tk)
        if not prev:
            new_names.append((tk, cur))
            continue
        dg = GRADE_RANK.get(cur["grade"], 9) - GRADE_RANK.get(prev["grade"], 9)
        if dg < 0:
            grade_ups.append((tk, prev, cur))
        elif dg > 0:
            grade_downs.append((tk, prev, cur))
        pr = prev_rank.get(tk)
        cr = cur_rank.get(tk)
        if pr and cr and pr != cr and i < 15:
            delta = pr - cr
            if delta >= 2:
                rank_gainers.append((tk, pr, cr, cur))
            elif delta <= -2:
                rank_losers.append((tk, pr, cr, cur))
    for tk in prev_rows:
        if tk not in cur_rank:
            dropped.append(tk)

    lines = [
        "📊 <b>GEM GRADE DIFF</b>",
        f"<b>{cur_doc.get('run_date','?')} {cur_doc.get('run_time','?')}</b>  "
        f"vs {prev_doc.get('run_date','?')}",
        "",
    ]
    if not (grade_ups or grade_downs or rank_gainers or rank_losers or new_names or dropped):
        lines.append("No change in order or grade vs previous run.")
    else:
        if grade_ups:
            lines.append("🟢 <b>GRADE UPGRADES</b>")
            for tk, p, c in grade_ups[:10]:
                lines.append(f"  {tk}: {p['grade']} → <b>{c['grade']}</b>  · {_driver(p, c)}")
            lines.append("")
        if grade_downs:
            lines.append("🔴 <b>GRADE DOWNGRADES</b>")
            for tk, p, c in grade_downs[:10]:
                lines.append(f"  {tk}: {p['grade']} → <b>{c['grade']}</b>  · {_driver(p, c)}")
            lines.append("")
        if rank_gainers:
            lines.append("⬆️ <b>RANK GAINERS (top 15)</b>")
            for tk, pr, cr, c in rank_gainers[:8]:
                lines.append(f"  {tk}: #{pr} → <b>#{cr}</b>  · {_driver(prev_rows.get(tk,{'grade':c['grade'],'tier':c['tier'],'risk':c['risk'],'u1y':0,'u5y':0,'reason':''}), c)}")
            lines.append("")
        if rank_losers:
            lines.append("⬇️ <b>RANK LOSERS (top 15)</b>")
            for tk, pr, cr, c in rank_losers[:8]:
                lines.append(f"  {tk}: #{pr} → <b>#{cr}</b>  · {_driver(prev_rows.get(tk,{'grade':c['grade'],'tier':c['tier'],'risk':c['risk'],'u1y':0,'u5y':0,'reason':''}), c)}")
            lines.append("")
        if new_names:
            lines.append("🆕 <b>NEW IN UNIVERSE</b>")
            for tk, c in new_names[:6]:
                lines.append(f"  {tk}: {c['grade']} · risk {c['risk']}")
            lines.append("")
        if dropped:
            lines.append("🧹 <b>DROPPED</b>: " + ", ".join(dropped[:10]))
            lines.append("")

    # Today's top 5 for fast scan
    lines.append("🏆 <b>TODAY TOP 5</b>")
    for i, (tk, c) in enumerate(cur_ordered[:5], 1):
        ev1 = f"{c['u1y']:+.1f}%" if c['u1y'] is not None else "—"
        lines.append(f"  {i}. {tk} · {c['pgrade']} · 1Y {ev1} · {c['risk']}")
    lines.append("")
    lines.append("<i>Read alongside OLYMPUS dashboard. Not personalized advice.</i>")
    msg = "\n".join(lines)

    if _send_tg(msg):
        try:
            with open(STATE, "w", encoding="utf-8") as f:
                json.dump({"last_sent": latest_name, "sent_at": datetime.now().isoformat(timespec="seconds")}, f, indent=2)
        except Exception:
            pass
        print(f"[GEM_DIFF] sent for {latest_name}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(run())
