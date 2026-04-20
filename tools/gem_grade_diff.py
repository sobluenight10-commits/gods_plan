"""
gem_grade_diff.py — Daily GEM ranking diff digest for Telegram.

Design rules (GOD feedback 2026-04-20):
  1. Every line must be signal-dense — NO noise.
  2. "UNKNOWN → X" is a data-merge artifact (previous gem run had no risk
     integration yet). Suppressed, never shown as a "change".
  3. Every ticker block ends with "→ SO WHAT" — a concrete action
     derived from (minerva_gem.so_what.action + change direction + risk).
  4. Real risk escalations get top-2 risk drivers from risk_latest.json.
  5. Header deduped — no more "grade A→B · grade A→B".
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEM_DIR = os.path.join(BASE, "gem_results")
RISK_LATEST = os.path.join(BASE, "data", "skill_results", "risk_latest.json")
STATE = os.path.join(BASE, "data", "gem_diff_state.json")

GRADE_ORDER = ["S", "A+", "A", "B+", "B", "C+", "C", "D", "F"]
GRADE_RANK = {g: i for i, g in enumerate(GRADE_ORDER)}
RISK_RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3, "UNKNOWN": -1, "": -1}


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
            print(f"[GEM_DIFF] HTTP {r.status_code}: {r.text[:200]}")
        return bool(r.ok)
    except Exception as exc:
        print(f"[GEM_DIFF] Telegram error: {exc}")
        return False


def _load(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_risk_drivers() -> Dict[str, List[str]]:
    """Map ticker → top-2 critical risk dimensions from risk_latest.json."""
    d = _load(RISK_LATEST) or {}
    out: Dict[str, List[str]] = {}
    for tk, rd in (d.get("results") or {}).items():
        crits = rd.get("critical_risks") or []
        if crits:
            out[tk] = [c.replace("_", " ") for c in crits[:2]]
    return out


def _row(doc: Dict[str, Any], tk: str) -> Dict[str, Any]:
    for r in doc.get("results", []):
        if r.get("ticker") == tk:
            g = r.get("grading") or {}
            sw = r.get("so_what") or {}
            return {
                "grade": g.get("grade", "F"),
                "tier": g.get("precision_tier", 1),
                "pgrade": g.get("precision_grade", g.get("grade", "F")),
                "gem": g.get("gem_score"),
                "u1y": g.get("upside_1y_pct"),
                "u5y": g.get("upside_5y_pct"),
                "worst1y": g.get("worst_drop_1y_pct"),
                "risk": (g.get("risk_level") or "").upper() or "UNKNOWN",
                "risk_avg": g.get("risk_avg"),
                "sw_action": sw.get("action", ""),
                "sw_signal": sw.get("signal", ""),
                "near": sw.get("near_term", ""),
                "long": sw.get("long_term", ""),
            }
    return {}


def _ordered(doc: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    rows = []
    for r in doc.get("results", []):
        tk = r.get("ticker", "?")
        rows.append((tk, _row(doc, tk)))
    rows.sort(key=lambda x: (
        GRADE_RANK.get(x[1]["grade"], 9),
        x[1]["tier"] or 1,
        -(x[1]["u5y"] or 0),
    ))
    return rows


# ─────────────────────────── NOISE SUPPRESSION ───────────────────────────
def _risk_real_change(prev_risk: str, cur_risk: str) -> bool:
    """True only if both sides are real readings AND the level actually changed."""
    p = (prev_risk or "").upper()
    c = (cur_risk or "").upper()
    if p in ("", "UNKNOWN") or c in ("", "UNKNOWN"):
        return False
    return p != c


def _risk_direction(prev_risk: str, cur_risk: str) -> int:
    """+1 worse, -1 better, 0 none."""
    if not _risk_real_change(prev_risk, cur_risk):
        return 0
    return 1 if RISK_RANK[cur_risk] > RISK_RANK[prev_risk] else -1


# ─────────────────────────── SO WHAT MAPPING ───────────────────────────
def _so_what(prev: Dict[str, Any], cur: Dict[str, Any], *, direction: str) -> str:
    """
    Concrete action line. Uses minerva_gem's so_what.action as the anchor
    and layers in direction + risk context.
    """
    base = (cur.get("sw_action") or "").strip()
    risk_dir = _risk_direction(prev.get("risk", ""), cur.get("risk", ""))
    ev1_drop = (cur.get("u1y") or 0) < (prev.get("u1y") or 0) - 2.0
    ev5_intact = (cur.get("u5y") or 0) >= 50
    grade_down = GRADE_RANK.get(cur["grade"], 9) > GRADE_RANK.get(prev.get("grade", cur["grade"]), 9)
    grade_up = GRADE_RANK.get(cur["grade"], 9) < GRADE_RANK.get(prev.get("grade", cur["grade"]), 9)
    cur_risk = cur.get("risk", "")

    # Base from minerva so_what
    if "Avoid" in base or "Exit" in base:
        return "EXIT / TRIM — thesis signal: " + base.lower()
    if "Add" in base or "Accumulate" in base or "Buy" in base:
        if cur_risk in ("HIGH", "CRITICAL"):
            return "ADD CAREFULLY — half-size; wait for risk to ease before full entry"
        return f"ADD — {base.lower()} on next intraday dip"
    # Hold — monitor is the common case; layer context
    if grade_down and risk_dir > 0:
        return (
            f"TRIM 20–25% into next bounce — risk escalated to {cur_risk}; "
            + ("re-enter if 5Y EV stays >50% and risk eases" if ev5_intact
               else "do not re-enter until 5Y EV re-expands")
        )
    if grade_down and ev1_drop and ev5_intact:
        return (
            "HOLD full — short-term EV compression, long-term thesis intact "
            f"(5Y EV {cur['u5y']:+.0f}%)"
        )
    if grade_down and not ev5_intact:
        return "TRIM — both grade and long-term EV compressing; preserve capital"
    if grade_up and cur_risk not in ("HIGH", "CRITICAL"):
        return f"ADD / KEEP — quality upgrade to {cur['grade']}; fundamentals improving"
    if direction == "rank_gain":
        return f"ATTENTION — catching tailwind ({cur['grade']} still); watch for entry"
    if direction == "rank_loss":
        return "TIGHTEN STOP — momentum turning; keep position but reduce size on break"
    if direction == "new":
        return f"WATCH — newly covered, {cur['grade']} · risk {cur_risk}"
    # Fallback: use minerva's own line
    return base or ("HOLD — monitor daily" if cur_risk in ("HIGH", "CRITICAL") else "HOLD")


def _driver(prev: Dict[str, Any], cur: Dict[str, Any]) -> str:
    """Single line: the strongest reason this row is showing up."""
    parts = []
    if _risk_real_change(prev.get("risk", ""), cur.get("risk", "")):
        parts.append(f"Risk {prev['risk']}→<b>{cur['risk']}</b>")
    if prev.get("tier") != cur.get("tier") and cur.get("tier") is not None:
        parts.append(f"Tier {prev['tier']}→<b>{cur['tier']}</b>")
    for k, label in (("u1y", "1Y EV"), ("u5y", "5Y EV")):
        a, b = prev.get(k) or 0, cur.get(k) or 0
        if abs(b - a) >= 2.5:
            parts.append(f"{label} {a:+.1f}%→<b>{b:+.1f}%</b>")
    return " · ".join(parts) or "—"


def _risk_drivers_line(tk: str, risk_map: Dict[str, List[str]], cur_risk: str) -> str:
    if cur_risk not in ("HIGH", "CRITICAL"):
        return ""
    drv = risk_map.get(tk) or []
    if not drv:
        return ""
    return f"⚠️  Risk drivers: <i>{', '.join(drv)}</i>"


# ─────────────────────────── MAIN ───────────────────────────
def _gem_files() -> List[str]:
    if not os.path.isdir(GEM_DIR):
        return []
    return sorted(f for f in os.listdir(GEM_DIR) if f.startswith("gem_") and f.endswith(".json"))


def _fmt_rank_changes(lbl: str, icon: str, items, risk_map) -> List[str]:
    if not items:
        return []
    out = [f"{icon} <b>{lbl}</b>"]
    for tk, pr, cr, prev, cur, direction in items[:8]:
        header = f"<b>{tk}</b>  #{pr} → <b>#{cr}</b>  · {cur['pgrade']}"
        drv = _driver(prev, cur)
        rdrv = _risk_drivers_line(tk, risk_map, cur.get("risk", ""))
        sw = _so_what(prev, cur, direction=direction)
        out.append(header)
        if drv != "—":
            out.append(f"  {drv}")
        if rdrv:
            out.append("  " + rdrv)
        out.append(f"  → <b>SO WHAT:</b> {sw}")
        out.append("")
    return out


def _fmt_grade_changes(lbl: str, icon: str, items, risk_map) -> List[str]:
    if not items:
        return []
    out = [f"{icon} <b>{lbl}</b>"]
    for tk, prev, cur, direction in items[:10]:
        header = f"<b>{tk}</b>  {prev['grade']} → <b>{cur['grade']}</b>"
        drv = _driver(prev, cur)
        rdrv = _risk_drivers_line(tk, risk_map, cur.get("risk", ""))
        sw = _so_what(prev, cur, direction=direction)
        out.append(header)
        if drv != "—":
            out.append(f"  {drv}")
        if rdrv:
            out.append("  " + rdrv)
        out.append(f"  → <b>SO WHAT:</b> {sw}")
        out.append("")
    return out


def run() -> int:
    _load_env()
    files = _gem_files()
    if len(files) < 2:
        print("[GEM_DIFF] need at least 2 gem_*.json runs")
        return 0

    latest_name = files[-1]
    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding="utf-8")) or {}
        except Exception:
            pass
    if state.get("last_sent") == latest_name:
        print(f"[GEM_DIFF] already sent for {latest_name}")
        return 0

    prev_doc = _load(os.path.join(GEM_DIR, files[-2])) or {}
    cur_doc = _load(os.path.join(GEM_DIR, latest_name)) or {}
    risk_map = _load_risk_drivers()

    prev_rows = {tk: r for tk, r in _ordered(prev_doc)}
    cur_ordered = _ordered(cur_doc)
    cur_rows = {tk: r for tk, r in cur_ordered}
    cur_rank = {tk: i + 1 for i, (tk, _) in enumerate(cur_ordered)}
    prev_ordered = _ordered(prev_doc)
    prev_rank = {tk: i + 1 for i, (tk, _) in enumerate(prev_ordered)}

    grade_ups, grade_downs = [], []
    rank_gainers, rank_losers = [], []
    new_names = []
    dropped = []

    for i, (tk, cur) in enumerate(cur_ordered):
        prev = prev_rows.get(tk)
        if not prev:
            new_names.append((tk, cur))
            continue
        dg = GRADE_RANK.get(cur["grade"], 9) - GRADE_RANK.get(prev["grade"], 9)
        if dg < 0:
            grade_ups.append((tk, prev, cur, "grade_up"))
        elif dg > 0:
            grade_downs.append((tk, prev, cur, "grade_down"))
        pr = prev_rank.get(tk)
        cr = cur_rank.get(tk)
        if pr and cr and pr != cr and i < 15:
            delta = pr - cr
            if delta >= 2:
                rank_gainers.append((tk, pr, cr, prev, cur, "rank_gain"))
            elif delta <= -2:
                rank_losers.append((tk, pr, cr, prev, cur, "rank_loss"))

    for tk in prev_rows:
        if tk not in cur_rows:
            dropped.append(tk)

    lines: List[str] = [
        "📊 <b>GEM GRADE DIFF</b>",
        f"<b>{cur_doc.get('run_date','?')} {cur_doc.get('run_time','')}</b> "
        f"vs {prev_doc.get('run_date','?')}  · "
        f"{len(grade_ups)+len(grade_downs)} grade moves · "
        f"{len(rank_gainers)+len(rank_losers)} rank moves",
        "<i>UNKNOWN→X suppressed as data-merge artifact.</i>",
        "",
    ]

    any_change = bool(grade_ups or grade_downs or rank_gainers or rank_losers or new_names or dropped)
    if not any_change:
        lines.append("No change in grade or order vs previous run.")
    else:
        lines += _fmt_grade_changes("GRADE UPGRADES", "🟢", grade_ups, risk_map)
        lines += _fmt_grade_changes("GRADE DOWNGRADES", "🔴", grade_downs, risk_map)
        lines += _fmt_rank_changes("RANK GAINERS (top 15)", "⬆️", rank_gainers, risk_map)
        lines += _fmt_rank_changes("RANK LOSERS (top 15)", "⬇️", rank_losers, risk_map)
        if new_names:
            lines.append("🆕 <b>NEW IN UNIVERSE</b>")
            for tk, c in new_names[:6]:
                lines.append(f"  <b>{tk}</b> · {c['pgrade']} · risk {c['risk']}")
                rdrv = _risk_drivers_line(tk, risk_map, c.get("risk", ""))
                if rdrv:
                    lines.append("  " + rdrv)
                lines.append(f"  → <b>SO WHAT:</b> {_so_what({'grade':c['grade'],'risk':'','u1y':0,'u5y':0,'tier':c['tier']}, c, direction='new')}")
                lines.append("")
        if dropped:
            lines.append("🧹 <b>DROPPED FROM UNIVERSE:</b> " + ", ".join(dropped[:10]))
            lines.append("")

    lines.append("🏆 <b>TODAY TOP 5</b>")
    for i, (tk, c) in enumerate(cur_ordered[:5], 1):
        ev1 = f"{c['u1y']:+.1f}%" if c['u1y'] is not None else "—"
        ev5 = f"{c['u5y']:+.1f}%" if c['u5y'] is not None else "—"
        rdrv = ""
        if c.get("risk") in ("HIGH", "CRITICAL") and risk_map.get(tk):
            rdrv = f"  · <i>{', '.join(risk_map[tk])}</i>"
        lines.append(f"  {i}. <b>{tk}</b> · {c['pgrade']} · 1Y {ev1} · 5Y {ev5} · risk {c['risk']}{rdrv}")
    lines.append("")
    lines.append("<i>Signal-only digest · not personalized advice.</i>")

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
