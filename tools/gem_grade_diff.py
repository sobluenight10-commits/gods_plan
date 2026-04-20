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

# ─────────────────────────── PER-TICKER SIGNAL MAPS ───────────────────────────
# Sector re-entry triggers (no generic phrases — specific, monitorable conditions)
SECTOR_REENTRY = {
    "Energy":       "uranium spot U3O8 sustainably >$90 + term-market contract flow",
    "Space":        "next NASA/NGA contract extension or DoD EOCL award visible",
    "Intelligence": "next-quarter capex print + hyperscaler order book re-acceleration",
    "Robotics":     "concentration diluted or swap to direct pure-play (KTOS, TSLA, ISRG)",
    "Semis":        "HBM4 qualification or Blackwell order-book uplift",
    "Defense":      "FY-26 DoD budget finalization + congressional CR resolution",
    "Luxury":       "China Tmall/JD double-digit sequential recovery signal",
    "Pharma":       "Phase-3 readout or FDA calendar event within 60 days",
    "Biotech":      "Phase-2/3 readout or partnership announcement",
    "Finance":      "yield-curve steepening and NIM expansion commentary",
    "Auto":         "monthly delivery beat vs consensus + regulatory credit visibility",
}

# 9-dim → readable risk category (used when narrative is empty)
DIM_SHORT = {
    "revenue_concentration": "rev concentration",
    "profitability_trend":   "margin trajectory",
    "balance_sheet_leverage":"leverage",
    "cash_runway":           "cash runway",
    "revenue_volatility":    "rev volatility",
    "valuation_cushion":     "valuation cushion",
    "liquidity_risk":        "float/liquidity",
    "sector_cyclicality":    "sector cyclicality",
    "catalyst_dependency":   "binary-event dependency",
}


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


TG_LIMIT = 3800  # safe margin under 4096


def _tg_post(text: str) -> bool:
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


def _chunk_lines(lines: List[str], limit: int = TG_LIMIT) -> List[str]:
    """Greedy line-boundary chunker — never splits inside a ticker block (blank line = boundary)."""
    chunks: List[str] = []
    buf: List[str] = []
    cur_len = 0
    for ln in lines:
        add = len(ln) + 1
        if cur_len + add > limit and buf:
            # Trim trailing blanks
            while buf and not buf[-1].strip():
                buf.pop()
            chunks.append("\n".join(buf))
            buf = []
            cur_len = 0
        buf.append(ln)
        cur_len += add
    if buf:
        while buf and not buf[-1].strip():
            buf.pop()
        chunks.append("\n".join(buf))
    return chunks


def _send_tg(text: str) -> bool:
    lines = text.split("\n")
    parts = _chunk_lines(lines)
    if len(parts) == 1:
        return _tg_post(parts[0])
    ok_any = False
    total = len(parts)
    for i, p in enumerate(parts, 1):
        tagged = f"<i>[{i}/{total}]</i>\n" + p if total > 1 else p
        if _tg_post(tagged):
            ok_any = True
    return ok_any


def _load(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_risk_full() -> Dict[str, Dict[str, Any]]:
    """Return full per-ticker risk records so we can read narratives."""
    d = _load(RISK_LATEST) or {}
    return d.get("results") or {}


def _specific_risk_lines(tk: str, risk_full: Dict[str, Dict[str, Any]]) -> List[str]:
    """
    Pull the TICKER-SPECIFIC narratives for the top-ranked risk dimensions.
    These are concrete facts ("P/E 352 — extreme multiple", "D/E = 2.5")
    and are never generic.
    """
    rd = risk_full.get(tk) or {}
    crits = rd.get("critical_risks") or []
    scores = rd.get("scores") or {}
    narr = rd.get("narratives") or {}
    # If no criticals, pick top-2 scored dims (≥5 only — else noise)
    if not crits:
        dims_sorted = sorted(scores.items(), key=lambda x: -x[1])
        crits = [d for d, s in dims_sorted if s >= 5][:2]
    out = []
    for d in crits[:2]:
        text = (narr.get(d) or "").strip()
        if not text:
            continue
        # Skip no-data placeholders — they're noise
        low = text.lower()
        if any(x in low for x in ("no data", "insufficient", "unavailable", "no balance sheet", "assumed")):
            continue
        out.append(f"{DIM_SHORT.get(d, d)} — {text}")
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
                "bull1y": g.get("bull_gain_1y_pct"),
                "risk": (g.get("risk_level") or "").upper() or "UNKNOWN",
                "risk_avg": g.get("risk_avg"),
                "sw_action": sw.get("action", ""),
                "sw_signal": sw.get("signal", ""),
                "near": sw.get("near_term", ""),
                "long": sw.get("long_term", ""),
                "sector": r.get("sector", ""),
                "price": r.get("current_price"),
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


# ─────────────────────────── PER-TICKER REASONING ENGINE ───────────────────────────
def _asymmetry(cur: Dict[str, Any]) -> Optional[float]:
    """bull-gain / worst-drop ratio (reward-to-risk) — ticker-specific number."""
    b = cur.get("bull1y")
    w = cur.get("worst1y")
    if b is None or w is None or w == 0:
        return None
    try:
        return round(float(b) / abs(float(w)), 2)
    except Exception:
        return None


def _horizon_line(cur: Dict[str, Any]) -> str:
    """Concrete horizon interpretation from near/long valuation."""
    near = (cur.get("near") or "").upper()
    lng = (cur.get("long") or "").upper()
    if not near and not lng:
        return ""
    if near == "OVERVALUED" and lng == "OVERVALUED":
        return "Near OVERVALUED + Long OVERVALUED → exit, compound elsewhere"
    if near == "OVERVALUED" and lng == "UNDERVALUED":
        return "Near OVERVALUED but Long UNDERVALUED → accumulate only on pullback"
    if near == "FAIR" and lng == "UNDERVALUED":
        return "Near FAIR, Long UNDERVALUED → hold for 5Y compounder, no fresh adds today"
    if near == "UNDERVALUED" and lng == "UNDERVALUED":
        return "Near+Long UNDERVALUED → both horizons favour adding"
    if near == "UNDERVALUED":
        return "Near UNDERVALUED → near-term entry valid"
    return f"Near {near or '—'}, Long {lng or '—'}"


def _ticker_action(
    prev: Dict[str, Any],
    cur: Dict[str, Any],
    *,
    direction: str,
    risk_lines: List[str],
) -> str:
    """
    Ticker-unique action. Combines:
      • minerva so_what.action (anchor)
      • specific risk narratives (the WHY)
      • sector re-entry trigger (the WHEN-to-come-back)
      • asymmetry ratio (the size)
    No two tickers produce the same sentence unless their data genuinely matches.
    """
    base = (cur.get("sw_action") or "").strip() or "Hold — monitor"
    cur_risk = cur.get("risk", "")
    sector = (cur.get("sector") or "").strip()
    reentry = SECTOR_REENTRY.get(sector, "thesis-level catalyst confirmation")
    grade_down = GRADE_RANK.get(cur["grade"], 9) > GRADE_RANK.get(prev.get("grade", cur["grade"]), 9)
    grade_up = GRADE_RANK.get(cur["grade"], 9) < GRADE_RANK.get(prev.get("grade", cur["grade"]), 9)
    risk_dir = _risk_direction(prev.get("risk", ""), cur.get("risk", ""))
    asym = _asymmetry(cur)
    asym_str = f" (R/R {asym}×)" if asym else ""
    price = cur.get("price")
    price_str = f" @ ${price:.2f}" if isinstance(price, (int, float)) else ""

    # Exit/Avoid → concrete exit
    if "Avoid" in base or "Exit" in base:
        return (
            f"EXIT / close position{price_str}; minerva signal <i>{base}</i>. "
            f"Redeploy to a ticker with better {('asymmetry'+asym_str) if asym else 'risk/reward'}."
        )

    # Add/Accumulate
    if any(x in base for x in ("Add", "Accumulate", "Buy")):
        if cur_risk in ("HIGH", "CRITICAL") and risk_lines:
            first = risk_lines[0].split(" — ", 1)[-1]
            return (
                f"ADD HALF-SIZE{price_str} — favourable upside but constrained by "
                f"<i>{first}</i>; full-size only once {reentry}."
            )
        return f"ADD{price_str} — {base.lower()}; re-rate trigger = {reentry}"

    # Grade down + real risk escalation: ticker-specific trim
    if grade_down and risk_dir > 0 and risk_lines:
        first = risk_lines[0].split(" — ", 1)[-1]
        return (
            f"TRIM 20–25%{price_str} — risk broke out to {cur_risk} on <i>{first}</i>. "
            f"Re-add when {reentry}{asym_str}."
        )

    # Grade down, no risk breakout — use the specific narrative if any, else EV/horizon
    if grade_down and risk_lines:
        first = risk_lines[0].split(" — ", 1)[-1]
        return (
            f"HOLD but tighten — 1Y EV compressed because <i>{first}</i>. "
            f"No fresh adds until {reentry}{asym_str}."
        )
    if grade_down:
        ev1 = cur.get("u1y")
        ev5 = cur.get("u5y")
        if ev5 and ev5 >= 50:
            return (
                f"HOLD full position{price_str} — 1Y EV {ev1:+.1f}% is soft but "
                f"5Y EV {ev5:+.0f}% intact. Don't add until {reentry}{asym_str}."
            )
        return (
            f"TRIM — both 1Y ({ev1:+.1f}%) and 5Y ({ev5:+.0f}%) EVs compressed; "
            "preserve capital for better-asymmetry names."
        )

    # Grade up
    if grade_up:
        if cur_risk in ("HIGH", "CRITICAL") and risk_lines:
            first = risk_lines[0].split(" — ", 1)[-1]
            return (
                f"ADD SMALL{price_str} — quality upgrade to {cur['grade']} but "
                f"still capped by <i>{first}</i>. Full-size when {reentry}."
            )
        return f"ADD / keep building{price_str} — upgrade to {cur['grade']}, {_horizon_line(cur).lower()}."

    # Rank-only movers
    if direction == "rank_gain":
        return (
            f"ATTENTION{price_str} — {cur['grade']} but climbing the leaderboard"
            + (f"; entry valid if {reentry}" if cur_risk in ('HIGH','CRITICAL') else ', open entry on dip')
            + "."
        )
    if direction == "rank_loss":
        if risk_lines:
            first = risk_lines[0].split(" — ", 1)[-1]
            return f"TIGHTEN STOP{price_str} — leaderboard slip driven by <i>{first}</i>; reduce on break."
        return f"TIGHTEN STOP{price_str} — leaderboard slipping; reduce on break below recent support."
    if direction == "new":
        return f"WATCH — newly covered at {cur['grade']}, risk {cur_risk}. Size only once {reentry}."

    return base


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


def _risk_drivers_lines(risk_lines: List[str], cur_risk: str) -> List[str]:
    """
    Return 1-2 ticker-specific narrative lines. Always shown when available,
    regardless of risk level — these are the facts driving the change.
    """
    if not risk_lines:
        return []
    icon = "⚠️" if cur_risk in ("HIGH", "CRITICAL") else "📌"
    return [f"  {icon} <i>{ln}</i>" for ln in risk_lines[:2]]


# ─────────────────────────── MAIN ───────────────────────────
def _gem_files() -> List[str]:
    if not os.path.isdir(GEM_DIR):
        return []
    return sorted(f for f in os.listdir(GEM_DIR) if f.startswith("gem_") and f.endswith(".json"))


def _fmt_rank_changes(lbl: str, icon: str, items, risk_full) -> List[str]:
    if not items:
        return []
    out = [f"{icon} <b>{lbl}</b>"]
    for tk, pr, cr, prev, cur, direction in items[:8]:
        header = f"<b>{tk}</b>  #{pr} → <b>#{cr}</b>  · {cur['pgrade']}"
        drv = _driver(prev, cur)
        risk_lines = _specific_risk_lines(tk, risk_full)
        horizon = _horizon_line(cur)
        sw = _ticker_action(prev, cur, direction=direction, risk_lines=risk_lines)
        out.append(header)
        if drv != "—":
            out.append(f"  {drv}")
        out += _risk_drivers_lines(risk_lines, cur.get("risk", ""))
        if horizon:
            out.append(f"  🧭 <i>{horizon}</i>")
        out.append(f"  → <b>SO WHAT:</b> {sw}")
        out.append("")
    return out


def _fmt_grade_changes(lbl: str, icon: str, items, risk_full) -> List[str]:
    if not items:
        return []
    out = [f"{icon} <b>{lbl}</b>"]
    for tk, prev, cur, direction in items[:10]:
        header = f"<b>{tk}</b>  {prev['grade']} → <b>{cur['grade']}</b>"
        drv = _driver(prev, cur)
        risk_lines = _specific_risk_lines(tk, risk_full)
        horizon = _horizon_line(cur)
        sw = _ticker_action(prev, cur, direction=direction, risk_lines=risk_lines)
        out.append(header)
        if drv != "—":
            out.append(f"  {drv}")
        out += _risk_drivers_lines(risk_lines, cur.get("risk", ""))
        if horizon:
            out.append(f"  🧭 <i>{horizon}</i>")
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
    risk_full = _load_risk_full()

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
        lines += _fmt_grade_changes("GRADE UPGRADES", "🟢", grade_ups, risk_full)
        lines += _fmt_grade_changes("GRADE DOWNGRADES", "🔴", grade_downs, risk_full)
        lines += _fmt_rank_changes("RANK GAINERS (top 15)", "⬆️", rank_gainers, risk_full)
        lines += _fmt_rank_changes("RANK LOSERS (top 15)", "⬇️", rank_losers, risk_full)
        if new_names:
            lines.append("🆕 <b>NEW IN UNIVERSE</b>")
            for tk, c in new_names[:6]:
                lines.append(f"  <b>{tk}</b> · {c['pgrade']} · risk {c['risk']}")
                rl = _specific_risk_lines(tk, risk_full)
                lines += _risk_drivers_lines(rl, c.get("risk", ""))
                fake_prev = {"grade": c["grade"], "risk": "", "u1y": 0, "u5y": 0, "tier": c["tier"]}
                lines.append(f"  → <b>SO WHAT:</b> {_ticker_action(fake_prev, c, direction='new', risk_lines=rl)}")
                lines.append("")
        if dropped:
            lines.append("🧹 <b>DROPPED FROM UNIVERSE:</b> " + ", ".join(dropped[:10]))
            lines.append("")

    lines.append("🏆 <b>TODAY TOP 5</b>")
    for i, (tk, c) in enumerate(cur_ordered[:5], 1):
        ev1 = f"{c['u1y']:+.1f}%" if c['u1y'] is not None else "—"
        ev5 = f"{c['u5y']:+.1f}%" if c['u5y'] is not None else "—"
        asym = _asymmetry(c)
        asym_str = f" · R/R {asym}×" if asym else ""
        lines.append(f"  {i}. <b>{tk}</b> · {c['pgrade']} · 1Y {ev1} · 5Y {ev5} · risk {c['risk']}{asym_str}")
    lines.append("")
    lines.append("<i>Signal-only digest · ticker-specific reasoning · not personalized advice.</i>")

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
