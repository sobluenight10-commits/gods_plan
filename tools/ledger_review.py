"""
ledger_review.py — Sunday behavioural-audit for thesis_ledger.

Runs weekly (Sunday 18:00 UTC = 20:00 Berlin summer). Pulls each open
decision and flags:
  • THESIS DRIFT   — price moved >20% but thesis_last_reviewed is >14d old
  • ANCHORING     — position -25% from entry AND thesis not reviewed 30d+
  • STOP BREACH   — price <= stop_loss
  • TARGET HIT    — price >= target (locks in decision to trim/hold)
  • CATALYST LAPSE— catalyst date passed, position still open
  • HIT-RATE      — rolling analytics on closed decisions (win rate, by type)

Output: one Telegram message (or chunked). Read alongside dashboard.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from thesis_ledger import list_open, hit_rate, LEDGER  # noqa: E402

PRICES = os.path.join(BASE, "data", "prices.json")
CATALYSTS = os.path.join(BASE, "data", "finnhub_catalysts.json")


def _load_env() -> None:
    env_path = os.path.join(BASE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _tg_post(text: str) -> bool:
    import requests
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not tok or not chat:
        print("[LEDGER_REVIEW] no Telegram creds")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=12,
        )
        if not r.ok:
            print(f"[LEDGER_REVIEW] HTTP {r.status_code}: {r.text[:200]}")
        return bool(r.ok)
    except Exception as exc:
        print(f"[LEDGER_REVIEW] TG error: {exc}")
        return False


def _send_chunked(text: str, limit: int = 3800) -> bool:
    parts: List[str] = []
    buf, cur = [], 0
    for ln in text.split("\n"):
        add = len(ln) + 1
        if cur + add > limit and buf:
            parts.append("\n".join(buf)); buf, cur = [], 0
        buf.append(ln); cur += add
    if buf:
        parts.append("\n".join(buf))
    ok_any = False
    for i, p in enumerate(parts, 1):
        tagged = f"<i>[{i}/{len(parts)}]</i>\n" + p if len(parts) > 1 else p
        if _tg_post(tagged):
            ok_any = True
    return ok_any


def _prices() -> Dict[str, float]:
    if not os.path.exists(PRICES):
        return {}
    try:
        with open(PRICES, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and "prices" in d:
            return {k: v.get("price") if isinstance(v, dict) else v for k, v in d["prices"].items()}
        if isinstance(d, dict):
            return {k: v.get("price") if isinstance(v, dict) else v for k, v in d.items()}
    except Exception:
        pass
    return {}


def _catalysts() -> Dict[str, Any]:
    if not os.path.exists(CATALYSTS):
        return {}
    try:
        with open(CATALYSTS, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _days_ago(iso: str) -> Optional[int]:
    try:
        return (date.today() - datetime.strptime(iso, "%Y-%m-%d").date()).days
    except Exception:
        return None


def audit() -> Dict[str, List[Dict[str, Any]]]:
    prices = _prices()
    cats = _catalysts()
    flags: Dict[str, List[Dict[str, Any]]] = {
        "drift": [], "anchor": [], "stop_breach": [], "target_hit": [],
        "catalyst_lapse": [], "fresh": [],
    }
    for rec in list_open():
        tk = rec["ticker"]
        px = prices.get(tk)
        if px is None:
            cquote = (cats.get(tk) or {}).get("quote") or {}
            px = cquote.get("c")
        entry = rec.get("price")
        stop = rec.get("stop_loss")
        target = rec.get("target")
        last_rev_days = _days_ago(rec.get("thesis_last_reviewed") or rec.get("date"))
        pnl_pct = None
        if px and entry:
            try:
                pnl_pct = round(100.0 * (float(px) / float(entry) - 1.0), 2)
            except Exception:
                pass
        row = {"rec": rec, "price": px, "pnl_pct": pnl_pct, "days_since_review": last_rev_days}

        # Stop / target — mechanical
        if stop and px and px <= stop:
            flags["stop_breach"].append(row); continue
        if target and px and px >= target:
            flags["target_hit"].append(row); continue

        # Thesis drift — price moved >20% in either direction since last review
        if pnl_pct is not None and abs(pnl_pct) >= 20 and (last_rev_days or 0) >= 14:
            flags["drift"].append(row); continue

        # Anchoring — losing position, not reviewed 30d
        if pnl_pct is not None and pnl_pct <= -25 and (last_rev_days or 0) >= 30:
            flags["anchor"].append(row); continue

        # Catalyst lapse — Finnhub next-earnings date is in the past, not updated
        ne = (cats.get(tk) or {}).get("next_earnings") or {}
        if ne.get("days_away") is not None and ne["days_away"] < 0 and (last_rev_days or 0) >= 7:
            flags["catalyst_lapse"].append(row); continue

        flags["fresh"].append(row)
    return flags


def _fmt(flags: Dict[str, List[Dict[str, Any]]]) -> str:
    today = date.today().isoformat()
    lines = [
        "📓 <b>THESIS LEDGER — WEEKLY AUDIT</b>",
        f"<b>{today}</b>  ·  {sum(len(v) for v in flags.values())} open positions",
        "",
    ]
    section_defs = [
        ("stop_breach", "🟥 STOP LOSS BREACHED", "MECHANICAL EXIT — execute now unless re-underwriting thesis today"),
        ("target_hit", "🟩 TARGET REACHED", "LOCK-IN DECISION — trim ≥25% or explicitly re-underwrite higher target"),
        ("drift", "🟧 THESIS DRIFT", "Price moved ≥20% but thesis not reviewed in 14d+ — you may be rationalizing"),
        ("anchor", "🟨 ANCHORING / SUNK-COST", "Position -25%, thesis not reviewed 30d+ — re-underwrite OR exit"),
        ("catalyst_lapse", "📅 CATALYST LAPSED", "Expected catalyst date passed — thesis must be re-formed, not re-held"),
    ]
    for key, title, prompt in section_defs:
        rows = flags.get(key) or []
        if not rows:
            continue
        lines.append(f"{title}  ({len(rows)})")
        lines.append(f"<i>{prompt}</i>")
        for row in rows:
            r = row["rec"]; px = row["price"]; pnl = row["pnl_pct"]
            pnl_s = f"{pnl:+.1f}%" if pnl is not None else "—"
            px_s = f"${px:.2f}" if isinstance(px, (int, float)) else "—"
            lines.append(f"  <b>{r['ticker']}</b> · entry ${r['price']} · now {px_s} · <b>{pnl_s}</b> · conv {r['conviction']}/10")
            lines.append(f"    thesis: {r['thesis'][:140]}")
            if r.get("exit_criteria"):
                lines.append(f"    exit-if: {r['exit_criteria'][:140]}")
            lines.append("    <b>→ SO WHAT:</b> re-underwrite now — <code>python3 thesis_ledger.py note {tk} \"...\"</code> or exit".replace("{tk}", r["ticker"]))
        lines.append("")
    # Fresh block (compact)
    fresh = flags.get("fresh") or []
    if fresh:
        lines.append(f"✅ <b>INTACT</b>  ({len(fresh)})")
        for row in fresh[:15]:
            r = row["rec"]; px = row["price"]; pnl = row["pnl_pct"]
            pnl_s = f"{pnl:+.1f}%" if pnl is not None else "—"
            px_s = f"${px:.2f}" if isinstance(px, (int, float)) else "—"
            lines.append(f"  <b>{r['ticker']}</b> · {pnl_s} · conv {r['conviction']}/10 · {r.get('thesis_type') or '—'}")
        lines.append("")

    # Hit-rate analytics
    hr = hit_rate()
    lines.append("📊 <b>HIT RATE (closed decisions)</b>")
    if not hr.get("n"):
        lines.append("  No closed decisions yet — ledger still seeding.")
    else:
        lines.append(f"  n={hr['n']} · win {hr['wins']} / loss {hr['losses']} · "
                     f"rate <b>{hr['win_rate']*100:.0f}%</b>")
        lines.append(f"  avg winner {hr['avg_winner_pct']:+.1f}% · avg loser {hr['avg_loser_pct']:+.1f}%")
        by = hr.get("by_thesis_type") or {}
        ranked = sorted(by.items(), key=lambda x: -x[1]["avg_pnl"])
        if ranked:
            lines.append("  <b>By thesis type</b> (best → worst avg P&L):")
            for t, bt in ranked[:8]:
                lines.append(f"    {t:<18} n={bt['n']} · win {bt['win_rate']*100:.0f}% · avg {bt['avg_pnl']:+.1f}%")
    lines.append("")
    lines.append("<i>Your own ledger = your structural edge. Institutions cannot do this per-individual.</i>")
    return "\n".join(lines)


def run() -> int:
    _load_env()
    flags = audit()
    text = _fmt(flags)
    ok = _send_chunked(text)
    print("[LEDGER_REVIEW] sent" if ok else "[LEDGER_REVIEW] failed or no Telegram")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(run())
