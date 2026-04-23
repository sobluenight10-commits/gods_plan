"""
catalyst_digest.py — Telegram pre-event digest.

Fires daily (after olympus_daily). Content:

  🎯 CATALYST RADAR — <today>
  ━━━━━━━━━━━━━━━━━━━━━━━━━━
  ⚠ CLUSTER: 3 high-sensitivity events in days +3..+10 — KTOS, NVDA, TSM

  T-1  KTOS 2026-04-24 earnings
    base rate (n=8): 63% win, avg |7.4%|, best +18%, worst -12%
    asymmetry +62 · setup ELEVATED_EXPECTATIONS (+14% vs 50d, analysts more_bullish)
    thesis intact · attention 72/100
    SO WHAT: size ≤ base, skip adds. If beat + gap-up day1 → fade. If miss → reload
                 into UNDER_POSITIONED zone.

  T-7  NVDA 2026-04-30 earnings  ...

Designed to run daily. Silent if no events inside T-14 window.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

RADAR = os.path.join(BASE, "data", "catalyst_radar.json")


# ── Telegram chunked sender (re-uses pattern from gem_grade_diff) ──────────
TG_LIMIT = 3800


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


def _tg_post(text: str) -> None:
    import requests
    tok = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        print("[DIGEST] Telegram creds missing — skipping send")
        print(text[:1500])
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat,
            "text":    text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=20)
        if not r.ok:
            print(f"[DIGEST] TG {r.status_code}: {r.text[:300]}")
    except Exception as exc:
        print(f"[DIGEST] TG error: {exc}")


def _chunk(lines: List[str]) -> List[str]:
    out, buf, n = [], [], 0
    for ln in lines:
        ln_len = len(ln) + 1
        if n + ln_len > TG_LIMIT and buf:
            out.append("\n".join(buf))
            buf, n = [], 0
        buf.append(ln)
        n += ln_len
    if buf:
        out.append("\n".join(buf))
    return out


# ── Flag → SO WHAT mapping (per-event actionable guidance) ─────────────
def _so_what(ev: Dict[str, Any]) -> str:
    flag  = ev.get("setup_flag", "NEUTRAL")
    asym  = ev.get("asymmetry_score", 0)
    days  = ev.get("days", 0)
    base  = ev.get("base_rate") or {}
    direction = ev.get("expected_direction", "binary")
    ticker = ev.get("ticker", "")

    if flag == "THESIS_RISK":
        return f"Thesis not intact — skip sizing. Event could reset the thesis; wait for post-event clarity."

    if flag == "ELEVATED_EXPECTATIONS":
        if asym <= -20:
            return "Size ≤ base. Historical asymmetry bearish + crowded positioning = easy disappointment."
        return "Trim pre-event or skip adds. If beat + gap-up day1 → fade. If miss → reload target lower."

    if flag == "UNDER_POSITIONED":
        if asym >= 30:
            return "Setup favors add pre-event — positive base rate + positioning is light. Size up into the print."
        return "Quiet accumulation zone. Add on any further weakness. Event likely non-event unless thesis breaks."

    if flag == "QUIET_PRE_EVENT":
        return "Attention is subdued going in — surprise move is more likely. Keep a stop near 50d MA, carry base size."

    if flag == "CROWDED":
        return "Retail attention elevated — fade post-event regardless of direction. Options IV likely rich; sell premium if avail."

    # NEUTRAL
    if direction == "binary":
        return "Event is binary — don't size over base. Use straddle-implied move as sizing cap."
    if asym >= 30:
        return "History favors the long side; size to base, trim only if setup weakens in final 2 days."
    if asym <= -30:
        return "History tilts bearish; skip adds, consider partial trim if above 50d by +10%+."
    return "Hold base. No edge either way — observe."


def _fmt_event(ev: Dict[str, Any]) -> List[str]:
    days = ev.get("days", 0)
    if days < 0:    t_label = f"T{days:+d}"
    elif days == 0: t_label = "T-0  TODAY"
    else:           t_label = f"T-{days:<2}"

    ttype = ev.get("type", "event").replace("_", " ")
    title = ev.get("title", "")
    base  = ev.get("base_rate") or {}
    asym  = ev.get("asymmetry_score", 0)
    flag  = ev.get("setup_flag", "NEUTRAL")
    reasons = "; ".join(ev.get("setup_reasons") or [])
    thesis = ev.get("thesis_state", "intact")
    att    = ev.get("attention_score")
    tone   = ev.get("analyst_tone", "") or ""

    lines = [f"<b>{t_label}  {ev.get('ticker','?')}</b>  {ev.get('date','?')}  <i>{ttype}</i>"]
    if title and title != f"{ev.get('ticker','')} earnings":
        lines.append(f"   {title}")

    # Base rate line
    if base and base.get("n"):
        n    = base["n"]
        wr   = base.get("win_rate", 0) or 0
        abs_m= base.get("mean_abs_move_pct", 0) or 0
        best = base.get("best_pct", 0) or 0
        worst= base.get("worst_pct", 0) or 0
        lines.append(
            f"   base rate (n={n}): {wr*100:.0f}% win · |{abs_m:.1f}%| avg · "
            f"best {best:+.0f}% / worst {worst:+.0f}%"
        )
    else:
        lines.append("   base rate: — (no prior history)")

    # Asymmetry + setup
    arrow = "+" if asym >= 0 else ""
    flag_label = {
        "ELEVATED_EXPECTATIONS": "⚠️ ELEVATED",
        "UNDER_POSITIONED":      "✅ UNDER-POSITIONED",
        "QUIET_PRE_EVENT":       "🔇 QUIET",
        "CROWDED":               "🚨 CROWDED",
        "THESIS_RISK":           "🔴 THESIS RISK",
        "NEUTRAL":               "· neutral",
    }.get(flag, flag)
    lines.append(
        f"   asymmetry {arrow}{asym} · setup {flag_label}"
        + (f" ({reasons})" if reasons else "")
    )

    # Context line
    ctx_bits = []
    ctx_bits.append(f"thesis {thesis}")
    if att is not None:       ctx_bits.append(f"attention {att}/100")
    if tone:                  ctx_bits.append(f"analysts {tone.replace('_',' ')}")
    price_ctx = ev.get("price_context") or {}
    if price_ctx.get("pct_vs_50") is not None:
        ctx_bits.append(f"{price_ctx['pct_vs_50']:+.0f}% vs 50d")
    lines.append("   " + " · ".join(ctx_bits))

    # SO WHAT
    lines.append(f"   <b>SO WHAT:</b> {_so_what(ev)}")
    lines.append("")
    return lines


def build_digest(horizon: int = 14) -> str:
    if not os.path.exists(RADAR):
        return ""
    with open(RADAR, encoding="utf-8") as f:
        radar = json.load(f)

    events: List[Dict[str, Any]] = radar.get("events") or []
    window = [e for e in events if 0 <= e.get("days", 999) <= horizon]
    window.sort(key=lambda x: x["days"])

    if not window:
        return ""

    lines = []
    lines.append(f"🎯 <b>CATALYST RADAR</b> — next {horizon}d  ·  "
                 f"{datetime.utcnow().strftime('%Y-%m-%d')}")
    lines.append("━" * 28)

    # Concentration warnings first (tactical priority)
    for w in (radar.get("concentration_warnings") or []):
        lines.append(f"⚠ <b>{w}</b>")
    if radar.get("concentration_warnings"):
        lines.append("")

    # Setup-flag summary line
    c = radar.get("counts", {})
    flag_summary = (
        f"under-positioned {c.get('under_positioned',0)} · "
        f"elevated {c.get('elevated',0)} · "
        f"quiet {c.get('quiet',0)} · "
        f"thesis-risk {c.get('thesis_risk',0)}"
    )
    lines.append(f"<i>{flag_summary}</i>")
    lines.append("")

    # Then events T-sorted
    for ev in window:
        lines.extend(_fmt_event(ev))

    return "\n".join(lines)


def run(horizon: int = 14) -> None:
    _load_env()
    text = build_digest(horizon)
    if not text.strip():
        print(f"[DIGEST] No events inside T-{horizon} window.")
        return
    for chunk in _chunk(text.split("\n")):
        _tg_post(chunk)
    print(f"[DIGEST] sent catalyst digest ({len(text)} chars)")


def main() -> int:
    horizon = 14
    for a in sys.argv[1:]:
        if a.startswith("--days"):
            try:
                horizon = int(a.split("=", 1)[1]) if "=" in a else int(sys.argv[sys.argv.index(a) + 1])
            except Exception:
                pass
    run(horizon)
    return 0


if __name__ == "__main__":
    sys.exit(main())
