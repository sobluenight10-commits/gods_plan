"""
HEADS-UP PUBLISHER — consolidates Point A + Point B + proximity into ONE feed.

Doctrine — alerts must be PROXIMATE. The user's complaint:
    "Telegram told me PLTR: watch for dip below €95 to trigger stop. Price
     is €126. 25% away. That is noise, not a heads-up."

Rules:
    - Stop alert fires only when current price within 5% of stop level.
    - Limit alert fires only when current price within 3% of limit level.
    - Point B WARNING fires once per ticker per day at the -10% boundary.
    - Point B EXECUTE fires once per ticker per day at the -15% boundary.
    - Point A FIRED (3-of-3) is rare; always alerts.
    - Point A WATCH (2-of-3) is digest-only.
    - Thesis Review (base broken) always alerts — this is critical.

Output:  data/heads_up.json
    {
      schema_version, generated_utc,
      tiers: {
        tier_2_point_a_fired: [...],
        tier_3a_point_b_warning: [...],
        tier_3b_point_b_execute: [...],
        tier_3c_thesis_review: [...],
        tier_4_stop_proximity: [...],   ← within 5% of stop
        tier_5_limit_proximity: [...],  ← within 3% of limit
        digest_point_a_watch: [...],    ← 2-of-3, no alert
      },
      one_command: most-actionable single line,
      first_30min_block: deterministic Telegram block (replaces GPT noise)
    }

Telegram dedup state lives in `data/heads_up_dedup.json`. Each (ticker, tier)
key is recorded with a UTC date; we suppress repeat alerts within the same
calendar day. Daily resets are automatic.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

POINT_A = os.path.join(BASE, "data", "point_a_scan.json")
POINT_B = os.path.join(BASE, "data", "point_b_scan.json")
STATE = os.path.join(BASE, "state.json")
DEDUP = os.path.join(BASE, "data", "heads_up_dedup.json")
OUT = os.path.join(BASE, "data", "heads_up.json")
WEBROOT_OUT = "/var/www/html/heads_up.json"

STOP_PROXIMITY_PCT = 5.0    # Within 5% above stop = alert
LIMIT_PROXIMITY_PCT = 3.0   # Within 3% above limit = alert (waiting for fill)


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _load_prices() -> Dict[str, float]:
    """Pull current prices from yfinance via fetch_data (cached if available)."""
    try:
        from fetch_data import get_live_prices
        return get_live_prices() or {}
    except Exception:
        return {}


def _stop_proximity(state_doc: Dict[str, Any], prices: Dict[str, float]) -> List[Dict[str, Any]]:
    """Stops within STOP_PROXIMITY_PCT of current price (above stop, falling toward it)."""
    out: List[Dict[str, Any]] = []
    for s in (state_doc.get("active_stops") or []):
        tk = s.get("ticker")
        stop = s.get("stop_USD") or s.get("stop_EUR")
        if tk is None or stop is None:
            continue
        try:
            stop_f = float(stop)
        except (TypeError, ValueError):
            continue
        px = prices.get(tk)
        if px is None or px <= 0:
            continue
        # Distance percentage — positive means price is ABOVE stop.
        dist_pct = (px - stop_f) / stop_f * 100
        # Skip if already triggered (price ≤ stop) — that's a different alert.
        if dist_pct < 0:
            out.append({
                "ticker": tk, "current_price": px, "stop": stop_f,
                "dist_pct": round(dist_pct, 2),
                "severity": "TRIGGERED",
                "message": f"{tk} stop ${stop_f} TRIGGERED — current ${px} ({dist_pct:+.1f}%)",
                "note": s.get("note", ""),
            })
            continue
        if dist_pct <= STOP_PROXIMITY_PCT:
            severity = "URGENT" if dist_pct <= 2.0 else "APPROACHING"
            out.append({
                "ticker": tk, "current_price": px, "stop": stop_f,
                "dist_pct": round(dist_pct, 2),
                "severity": severity,
                "message": f"{tk} ${px} approaching stop ${stop_f} ({dist_pct:.1f}% above)",
                "note": s.get("note", ""),
            })
    return out


def _limit_proximity(state_doc: Dict[str, Any], prices: Dict[str, float]) -> List[Dict[str, Any]]:
    """Limits where current price within LIMIT_PROXIMITY_PCT above limit (i.e., about to fill)."""
    out: List[Dict[str, Any]] = []
    for l in (state_doc.get("active_limits") or []):
        tk = l.get("ticker")
        limit = l.get("limit_EUR") or l.get("limit_USD") or l.get("limit")
        if tk is None or limit is None:
            continue
        try:
            limit_f = float(limit)
        except (TypeError, ValueError):
            continue
        px = prices.get(tk)
        if px is None or px <= 0:
            continue
        dist_pct = (px - limit_f) / limit_f * 100
        if dist_pct < 0:
            out.append({
                "ticker": tk, "current_price": px, "limit": limit_f,
                "dist_pct": round(dist_pct, 2),
                "severity": "FILLED",
                "message": f"{tk} limit {limit_f} FILLED — current {px} ({dist_pct:+.1f}%)",
                "reason": l.get("reason", ""),
            })
            continue
        if dist_pct <= LIMIT_PROXIMITY_PCT:
            severity = "READY" if dist_pct <= 1.0 else "APPROACHING"
            out.append({
                "ticker": tk, "current_price": px, "limit": limit_f,
                "dist_pct": round(dist_pct, 2),
                "severity": severity,
                "message": f"{tk} {px} approaching limit {limit_f} ({dist_pct:.1f}% above)",
                "reason": l.get("reason", ""),
            })
    return out


def _build_first_30min_block(tiers: Dict[str, List[Any]]) -> str:
    """Deterministic Telegram block to replace GPT-generated 'FIRST 30 MIN WATCH' noise.

    Lists ONLY proximate items. If nothing is proximate, says so explicitly.
    """
    lines: List[str] = []
    urgent_stops = [s for s in tiers.get("tier_4_stop_proximity", [])
                     if s.get("severity") in ("URGENT", "TRIGGERED")]
    approaching_stops = [s for s in tiers.get("tier_4_stop_proximity", [])
                          if s.get("severity") == "APPROACHING"]
    ready_limits = [l for l in tiers.get("tier_5_limit_proximity", [])
                     if l.get("severity") in ("READY", "FILLED")]
    approaching_limits = [l for l in tiers.get("tier_5_limit_proximity", [])
                           if l.get("severity") == "APPROACHING"]
    b_execute = tiers.get("tier_3b_point_b_execute") or []
    b_warning = tiers.get("tier_3a_point_b_warning") or []
    a_fired = tiers.get("tier_2_point_a_fired") or []
    review = tiers.get("tier_3c_thesis_review") or []

    if urgent_stops:
        lines.append("🚨 STOPS — URGENT (within 2% of trigger):")
        for s in urgent_stops:
            lines.append(f"  • {s['ticker']} ${s['current_price']} → stop ${s['stop']} "
                         f"({s['dist_pct']:+.1f}%)")
    if approaching_stops:
        lines.append("⚠️ STOPS — APPROACHING (within 5%):")
        for s in approaching_stops:
            lines.append(f"  • {s['ticker']} ${s['current_price']} → stop ${s['stop']} "
                         f"({s['dist_pct']:+.1f}%)")
    if review:
        lines.append("🔻 THESIS REVIEW (base broken — written justification required):")
        for r in review:
            lines.append(f"  • {r['ticker']} ${r['last_close']} below base ${r['breakout_base']} "
                         f"({r['dist_pct']:.1f}% from 20d high)")
    if a_fired:
        lines.append("🎯 POINT A FIRED (macro + funding + below 20W MA):")
        for a in a_fired:
            lines.append(f"  • {a['ticker']} ${a.get('last_close')} "
                         f"(MA20W ${a.get('ma_20w')}, {a.get('dist_to_ma_pct')}%)")
    if b_execute:
        lines.append("🎯 POINT B EXECUTE (-15% from 20d high, base intact):")
        for b in b_execute:
            lines.append(f"  • {b['ticker']} ${b['last_close']} "
                         f"(soros gap {b['soros_gap_pct']}%, exec at ${b['buy_zone_b']['execute_at']})")
    if b_warning:
        lines.append("🟡 POINT B WARNING (-10% from 20d high — get ready):")
        for b in b_warning:
            lines.append(f"  • {b['ticker']} ${b['last_close']} "
                         f"(soros gap {b['soros_gap_pct']}%, exec at ${b['buy_zone_b']['execute_at']})")
    if ready_limits:
        lines.append("✅ LIMITS READY TO FILL (within 1%):")
        for l in ready_limits:
            lines.append(f"  • {l['ticker']} {l['current_price']} → limit {l['limit']}")
    if approaching_limits:
        lines.append("📍 LIMITS APPROACHING (within 3%):")
        for l in approaching_limits:
            lines.append(f"  • {l['ticker']} {l['current_price']} → limit {l['limit']}")

    if not lines:
        return ("⚪ No proximate triggers. No first-30-min action required. "
                "Stops, limits and Point A/B levels all far away.")
    return "\n".join(lines)


def _build_one_command(tiers: Dict[str, List[Any]]) -> str:
    review = tiers.get("tier_3c_thesis_review") or []
    if review:
        r = review[0]
        return (f"🔻 THESIS REVIEW — {r['ticker']} broke breakout base. "
                f"Document justification before any further action.")
    urgent_stops = [s for s in tiers.get("tier_4_stop_proximity", [])
                     if s.get("severity") in ("URGENT", "TRIGGERED")]
    if urgent_stops:
        s = urgent_stops[0]
        return (f"🚨 {s['ticker']} stop ${s['stop']} URGENT — current ${s['current_price']} "
                f"({s['dist_pct']:+.1f}%). Decide before market open.")
    a_fired = tiers.get("tier_2_point_a_fired") or []
    if a_fired:
        a = a_fired[0]
        return (f"🎯 POINT A FIRED — {a['ticker']}. Macro tailwind + funding easing + price "
                f"below 20W MA. Entry window open.")
    b_execute = tiers.get("tier_3b_point_b_execute") or []
    if b_execute:
        b = b_execute[0]
        return (f"🎯 POINT B EXECUTE — {b['ticker']} at ${b['last_close']} "
                f"(-{b['soros_gap_pct']}% from 20d high). Fire prepared orders.")
    ready_limits = [l for l in tiers.get("tier_5_limit_proximity", [])
                     if l.get("severity") in ("READY", "FILLED")]
    if ready_limits:
        l = ready_limits[0]
        return f"✅ {l['ticker']} limit {l['limit']} fills — confirm broker."
    b_warning = tiers.get("tier_3a_point_b_warning") or []
    if b_warning:
        b = b_warning[0]
        return (f"🟡 {b['ticker']} approaching B zone (-{b['soros_gap_pct']}% from high). "
                f"Pre-stage limit at ${b['buy_zone_b']['execute_at']}.")
    return "⚪ HOLD — no proximate triggers. Powder safe."


def _load_dedup() -> Dict[str, str]:
    return _load(DEDUP, {}) or {}


def _save_dedup(d: Dict[str, str]) -> None:
    try:
        os.makedirs(os.path.dirname(DEDUP), exist_ok=True)
        with open(DEDUP, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[heads_up] dedup save failed: {exc}")


def _should_alert(tier: str, ticker: str, dedup: Dict[str, str]) -> bool:
    today = date.today().isoformat()
    key = f"{tier}:{ticker}"
    if dedup.get(key) == today:
        return False
    dedup[key] = today
    return True


def _send_telegram(text: str) -> bool:
    """Best-effort Telegram push using config.TELEGRAM_*. Silent on failure."""
    try:
        import config
        token = getattr(config, "TELEGRAM_BOT_TOKEN", None)
        chat = getattr(config, "TELEGRAM_CHAT_ID", None)
        if not token or not chat:
            return False
        import urllib.parse, urllib.request
        body = urllib.parse.urlencode({
            "chat_id": chat, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"[heads_up] telegram send failed: {exc}")
        return False


def run(send_telegram: bool = True) -> Dict[str, Any]:
    a_doc = _load(POINT_A, {})
    b_doc = _load(POINT_B, {})
    state_doc = _load(STATE, {})
    prices = _load_prices()

    a_fired = a_doc.get("shortlist_fired") or []
    a_watch = a_doc.get("shortlist_watch") or []
    b_execute = b_doc.get("shortlist_execute") or []
    b_warning = b_doc.get("shortlist_warning") or []
    b_review = b_doc.get("shortlist_review") or []

    stops = _stop_proximity(state_doc, prices)
    limits = _limit_proximity(state_doc, prices)

    tiers = {
        "tier_2_point_a_fired": a_fired,
        "tier_3a_point_b_warning": b_warning,
        "tier_3b_point_b_execute": b_execute,
        "tier_3c_thesis_review": b_review,
        "tier_4_stop_proximity": stops,
        "tier_5_limit_proximity": limits,
        "digest_point_a_watch": a_watch,
    }

    one_command = _build_one_command(tiers)
    first_30min_block = _build_first_30min_block(tiers)

    out = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tiers": tiers,
        "counts": {
            "a_fired": len(a_fired), "a_watch": len(a_watch),
            "b_execute": len(b_execute), "b_warning": len(b_warning),
            "b_review": len(b_review),
            "stop_proximity": len(stops), "limit_proximity": len(limits),
        },
        "one_command": one_command,
        "first_30min_block": first_30min_block,
        "doctrine": (
            "Heads-up MUST be proximate. Stop alerts only when current price ≤ "
            "stop × 1.05. Limit alerts only when current price ≤ limit × 1.03. "
            "Point B alerts at -10% (warning) and -15% (execute), per ticker per day. "
            "Anything else is noise and gets suppressed."
        ),
    }
    _write(out)

    if send_telegram:
        _push_alerts(tiers)

    return out


def _push_alerts(tiers: Dict[str, List[Any]]) -> None:
    dedup = _load_dedup()
    pushed = 0

    # Tier 3c — Thesis review (always alert, daily dedup)
    for r in tiers.get("tier_3c_thesis_review", []) or []:
        if _should_alert("review", r["ticker"], dedup):
            msg = (f"🔻 <b>THESIS REVIEW — {r['ticker']}</b>\n"
                   f"Close ${r['last_close']} broke breakout base ${r['breakout_base']} "
                   f"({r['dist_pct']:.1f}% from 20d high).\n"
                   f"Document justification before any further action.")
            _send_telegram(msg)
            pushed += 1

    # Tier 2 — Point A FIRED (always alert)
    for a in tiers.get("tier_2_point_a_fired", []) or []:
        if _should_alert("a_fired", a["ticker"], dedup):
            msg = (f"🎯 <b>POINT A FIRED — {a['ticker']}</b>\n"
                   f"Macro tailwind ✓ funding easing ✓ price below 20W MA ✓\n"
                   f"Close ${a.get('last_close')} · MA20W ${a.get('ma_20w')} "
                   f"({a.get('dist_to_ma_pct')}%)\n"
                   f"Entry window open — review thesis and pre-stage orders.")
            _send_telegram(msg)
            pushed += 1

    # Tier 3b — Point B EXECUTE (always alert)
    for b in tiers.get("tier_3b_point_b_execute", []) or []:
        if _should_alert("b_execute", b["ticker"], dedup):
            msg = (f"🎯 <b>POINT B EXECUTE — {b['ticker']}</b>\n"
                   f"Soros gap {b['soros_gap_pct']}% · close ${b['last_close']} "
                   f"vs 20d high ${b['high_20d']}\n"
                   f"Base ${b['breakout_base']} INTACT. Fire prepared orders.")
            _send_telegram(msg)
            pushed += 1

    # Tier 3a — Point B WARNING (daily dedup)
    for b in tiers.get("tier_3a_point_b_warning", []) or []:
        if _should_alert("b_warning", b["ticker"], dedup):
            msg = (f"🟡 <b>POINT B WARNING — {b['ticker']}</b>\n"
                   f"Pulled back {b['dist_pct']:.1f}% from 20d high.\n"
                   f"Pre-stage limit at ${b['buy_zone_b']['execute_at']}.")
            _send_telegram(msg)
            pushed += 1

    # Tier 4 — URGENT/TRIGGERED stops only (proximate)
    for s in tiers.get("tier_4_stop_proximity", []) or []:
        if s.get("severity") not in ("URGENT", "TRIGGERED"):
            continue
        if _should_alert(f"stop_{s.get('severity')}", s["ticker"], dedup):
            msg = (f"🚨 <b>STOP {s['severity']} — {s['ticker']}</b>\n"
                   f"Current ${s['current_price']} · stop ${s['stop']} "
                   f"({s['dist_pct']:+.1f}%)")
            _send_telegram(msg)
            pushed += 1

    # Tier 5 — READY/FILLED limits
    for l in tiers.get("tier_5_limit_proximity", []) or []:
        if l.get("severity") not in ("READY", "FILLED"):
            continue
        if _should_alert(f"limit_{l.get('severity')}", l["ticker"], dedup):
            msg = (f"✅ <b>LIMIT {l['severity']} — {l['ticker']}</b>\n"
                   f"Current {l['current_price']} · limit {l['limit']} "
                   f"({l['dist_pct']:+.1f}%)")
            _send_telegram(msg)
            pushed += 1

    if pushed:
        _save_dedup(dedup)
    print(f"[heads_up] {pushed} telegram alert(s) pushed")


def _write(payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    try:
        if os.path.isdir(os.path.dirname(WEBROOT_OUT)):
            shutil.copy2(OUT, WEBROOT_OUT)
    except Exception as exc:
        print(f"[heads_up] webroot mirror failed: {exc}")


if __name__ == "__main__":
    out = run(send_telegram=("--no-telegram" not in sys.argv))
    print(json.dumps({k: v for k, v in out.items() if k != "tiers"}, indent=2, ensure_ascii=False))
    print()
    print("=== FIRST 30 MIN BLOCK ===")
    print(out.get("first_30min_block"))
    print()
    print("=== ONE COMMAND ===")
    print(out.get("one_command"))
