"""tools/why_engine.py — THE WHY ENGINE (Lesson #09 made mechanical).

GOD's discipline, Jun 27 2026: "Trade the cause, not the exposed result."

Every price move and every headline is a RESULT. The market reflexively staples
the nearest plausible narrative onto it ("SK Hynix cut output → AI demand dying").
That narrative is frequently wrong on causation, and when it is, the SIGN of the
signal inverts. A China tungsten squeeze forcing a 25% WF6 cliff is an INPUT shock
that RAISES memory prices — bullish for incumbents — yet the tape sold it as
bearish demand skepticism.

This engine intercepts a result and forces it through a classifier BEFORE any
directive is issued:

    Result → Candidate causes → Root cause → Cause class
            (DEMAND / SUPPLY / FINANCING / SENTIMENT / MACRO)
           → Sign (does this HELP or HURT the thesis?)
           → Second-order: who does this make richer?

Output is JSON, persisted to data/why_tape.json (dashboard) and rendered as a
compact card for Telegram. Deterministic fallback when GPT is unavailable.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
TAPE_FILE = os.path.join(DATA, "why_tape.json")
WEBROOT = "/var/www/html"

CAUSE_CLASSES = ("DEMAND", "SUPPLY", "FINANCING", "SENTIMENT", "MACRO")

_SIGN_ICON = {"HELPS": "🟢↑", "HURTS": "🔴↓", "NEUTRAL": "⚪→"}
_CLASS_ICON = {
    "DEMAND": "📉", "SUPPLY": "🏭", "FINANCING": "💳",
    "SENTIMENT": "🗣", "MACRO": "🌐", "UNKNOWN": "❓",
}

# Keyword heuristics for the deterministic fallback (no GPT).
_SUPPLY_HINTS = ("export control", "export ban", "shortage", "wf6", "tungsten",
                 "gallium", "germanium", "rare earth", "capacity cut", "supply",
                 "rationing", "chokepoint", "substrate", "neon", "curtail")
_FINANCING_HINTS = ("dilution", "offering", "secondary", "convertible", "raise",
                    "debt", "refinanc", "bankruptcy", "going concern", "atm program")
_DEMAND_HINTS = ("guidance cut", "demand", "orders", "bookings", "miss", "slowdown",
                 "weak demand", "cancellation", "soft")
_MACRO_HINTS = ("fed", "rate", "cpi", "inflation", "yields", "tariff", "recession",
                "dollar", "vix", "jobs", "fomc", "treasury")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chokepoint_hint() -> str:
    """Feed the engine the current supply-chain chokepoint map so it can
    recognise a supply cause instead of defaulting to the demand narrative."""
    try:
        from tools.chokepoint_radar import CHOKEPOINTS
        rows = []
        for cp in CHOKEPOINTS:
            rows.append(
                f"- {cp['label']}: China ~{cp.get('china_control_pct')}% · "
                f"hurts={', '.join(cp.get('victims', [])[:2])} · "
                f"benefits={', '.join(str(b) for b in cp.get('beneficiaries', [])[:3])} · "
                f"{cp.get('sign_note','')[:140]}"
            )
        return "KNOWN SUPPLY CHOKEPOINTS (use to detect SUPPLY causes):\n" + "\n".join(rows)
    except Exception:
        return ""


def _gpt(system: str, user: str, tokens: int = 500) -> str:
    try:
        from battle_rhythm import _gpt as _bgpt
        return _bgpt(system, user, tokens=tokens)
    except Exception as exc:  # noqa: BLE001
        print(f"[WHY] gpt unavailable: {exc}")
        return ""


def _fallback(result_text: str, ticker: str | None, move_pct: float | None) -> dict:
    t = (result_text or "").lower()
    cls = "UNKNOWN"
    if any(k in t for k in _SUPPLY_HINTS):
        cls = "SUPPLY"
    elif any(k in t for k in _FINANCING_HINTS):
        cls = "FINANCING"
    elif any(k in t for k in _MACRO_HINTS):
        cls = "MACRO"
    elif any(k in t for k in _DEMAND_HINTS):
        cls = "DEMAND"
    elif move_pct is not None:
        cls = "SENTIMENT"
    sign = "NEUTRAL"
    misread = False
    if cls == "SUPPLY":
        # Supply shocks to a constrained input are frequently bullish for incumbents.
        sign = "HELPS"
        misread = True
    elif cls in ("DEMAND", "FINANCING") and (move_pct or 0) < 0:
        sign = "HURTS"
    return {
        "result": result_text[:200],
        "candidate_causes": [],
        "root_cause": "Not traced — GPT unavailable; classified by keyword heuristic.",
        "cause_class": cls,
        "sign": sign,
        "misread_risk": misread,
        "confidence": 2,
        "beneficiaries": [],
        "victims": [],
        "action": "HOLD · trace cause manually before acting.",
        "engine": "fallback",
    }


def classify(
    result_text: str,
    ticker: str | None = None,
    move_pct: float | None = None,
    headlines: list[str] | None = None,
    context: str | None = None,
) -> dict:
    """Trace a result to its root cause and classify it. Returns a why-card dict."""
    headlines = headlines or []
    hl_block = "\n".join(f"- {h}" for h in headlines[:8]) or "(no headlines in window)"
    move_str = f"{move_pct:+.1f}%" if isinstance(move_pct, (int, float)) else "n/a"
    choke = _chokepoint_hint()

    system = (
        "You are the WHY ENGINE inside MINERVA. Your sole job is causal diagnosis. "
        "You obey Lesson #09: every price move and headline is a RESULT; the market "
        "staples the nearest narrative onto it and is frequently WRONG on causation. "
        "Trace the result UP the causal chain to the root driver. Classify the root "
        "cause into exactly one class. Determine the SIGN versus the company's thesis "
        "(does the ROOT CAUSE help or hurt it?), which may be the OPPOSITE of what the "
        "tape assumes. Then map second-order beneficiaries — who does this make richer? "
        "Output ONLY valid minified JSON, no prose, no code fences."
    )
    user = f"""RESULT TO DIAGNOSE:
Ticker: {ticker or 'n/a'} · Move: {move_str}
Event/observation: {result_text}

Recent headlines (48h):
{hl_block}

{context or ''}

{choke}

Return JSON with EXACTLY these keys:
{{
 "candidate_causes": ["..." up to 3 plausible causes],
 "root_cause": "one sentence — the real driver, traced up the chain",
 "cause_class": one of {list(CAUSE_CLASSES)},
 "sign": "HELPS" | "HURTS" | "NEUTRAL"  (effect of the ROOT CAUSE on the thesis),
 "misread_risk": true|false  (true if the market's likely first read has the sign backwards),
 "confidence": integer 1-10,
 "beneficiaries": ["tickers/entities this constrained input or event makes richer"],
 "victims": ["who is genuinely hurt"],
 "action": "one decisive line: HOLD / ADD zone / TRIM / EXIT REVIEW / WATCH — be specific"
}}

Rules:
- SUPPLY shock to a scarce, non-substitutable input into firm/rising demand is usually
  INFLATIONARY for incumbents -> sign HELPS for the supplier with pricing power, even if
  the headline reads bearish (set misread_risk true).
- DEMAND deterioration is real thesis risk -> usually HURTS.
- FINANCING (dilution/raise) -> de-rating, often HURTS price but may not break thesis.
- SENTIMENT/MACRO with intact fundamentals -> often NEUTRAL or a HELPS dip-to-buy.
- Never output a SELL/EXIT unless the ROOT CAUSE is DEMAND or FINANCING thesis-break.
"""
    raw = _gpt(system, user, tokens=520)
    if not raw:
        return _fallback(result_text, ticker, move_pct)
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:]
    # extract first {...}
    s, e = clean.find("{"), clean.rfind("}")
    if s >= 0 and e > s:
        clean = clean[s : e + 1]
    try:
        d = json.loads(clean)
    except Exception:
        return _fallback(result_text, ticker, move_pct)

    cls = str(d.get("cause_class", "UNKNOWN")).upper()
    if cls not in CAUSE_CLASSES:
        cls = "UNKNOWN"
    sign = str(d.get("sign", "NEUTRAL")).upper()
    if sign not in _SIGN_ICON:
        sign = "NEUTRAL"
    try:
        conf = int(d.get("confidence", 5))
    except Exception:
        conf = 5
    return {
        "result": result_text[:200],
        "ticker": ticker,
        "move_pct": move_pct,
        "candidate_causes": list(d.get("candidate_causes", []))[:3],
        "root_cause": str(d.get("root_cause", ""))[:300],
        "cause_class": cls,
        "sign": sign,
        "misread_risk": bool(d.get("misread_risk", False)),
        "confidence": max(1, min(10, conf)),
        "beneficiaries": [str(x) for x in (d.get("beneficiaries") or [])][:6],
        "victims": [str(x) for x in (d.get("victims") or [])][:6],
        "action": str(d.get("action", "HOLD"))[:160],
        "engine": "gpt",
    }


def tag(card: dict) -> str:
    """Compact inline tag, e.g. '[SUPPLY 🟢↑ MISREAD]'."""
    cls = card.get("cause_class", "UNKNOWN")
    sign = _SIGN_ICON.get(card.get("sign", "NEUTRAL"), "⚪→")
    mis = " MISREAD" if card.get("misread_risk") else ""
    return f"[{cls} {sign}{mis}]"


def format_card(card: dict) -> str:
    cls = card.get("cause_class", "UNKNOWN")
    icon = _CLASS_ICON.get(cls, "❓")
    sign = card.get("sign", "NEUTRAL")
    sicon = _SIGN_ICON.get(sign, "⚪→")
    lines = [f"{icon} <b>WHY ENGINE</b> — {tag(card)}"]
    if card.get("root_cause"):
        lines.append(f"🧭 ROOT CAUSE: {card['root_cause']}")
    cc = card.get("candidate_causes") or []
    if cc:
        lines.append("• considered: " + " | ".join(cc))
    lines.append(f"↕️ SIGN vs thesis: {sicon} {sign}"
                 + (" — TAPE LIKELY HAS SIGN BACKWARDS" if card.get("misread_risk") else "")
                 + f" · conf {card.get('confidence','?')}/10")
    if card.get("beneficiaries"):
        lines.append("🟢 SECOND-ORDER WINNERS: " + ", ".join(card["beneficiaries"]))
    if card.get("victims"):
        lines.append("🔻 PRESSURED: " + ", ".join(card["victims"]))
    lines.append(f"⚔ ACTION: {card.get('action','HOLD')}")
    return "\n".join(lines)


def format_card_plain(card: dict) -> str:
    """Plain-text card (no HTML) for senders that don't set parse_mode."""
    sign = card.get("sign", "NEUTRAL")
    sicon = _SIGN_ICON.get(sign, "⚪→")
    cls = card.get("cause_class", "UNKNOWN")
    lines = [f"🧭 WHY ENGINE — [{cls} {sicon}{' MISREAD' if card.get('misread_risk') else ''}]"]
    if card.get("root_cause"):
        lines.append(f"ROOT CAUSE: {card['root_cause']}")
    lines.append(f"SIGN vs thesis: {sign} · conf {card.get('confidence','?')}/10")
    if card.get("misread_risk"):
        lines.append("⚠️ tape likely has the sign backwards")
    if card.get("beneficiaries"):
        lines.append("WINNERS: " + ", ".join(card["beneficiaries"]))
    lines.append(f"ACTION: {card.get('action','HOLD')}")
    return "\n".join(lines)


def append_tape(card: dict, max_items: int = 60) -> None:
    os.makedirs(DATA, exist_ok=True)
    tape = {"updated_at": _now(), "cards": []}
    try:
        with open(TAPE_FILE, "r", encoding="utf-8") as f:
            tape = json.load(f)
    except Exception:
        pass
    entry = dict(card)
    entry["ts"] = _now()
    cards = [entry] + (tape.get("cards") or [])
    tape["cards"] = cards[:max_items]
    tape["updated_at"] = _now()
    with open(TAPE_FILE, "w", encoding="utf-8") as f:
        json.dump(tape, f, indent=2, ensure_ascii=False)
    try:
        if os.path.isdir(WEBROOT):
            import shutil
            shutil.copy2(TAPE_FILE, os.path.join(WEBROOT, "why_tape.json"))
    except Exception:
        pass


def diagnose_and_record(
    result_text: str,
    ticker: str | None = None,
    move_pct: float | None = None,
    headlines: list[str] | None = None,
    context: str | None = None,
) -> dict:
    card = classify(result_text, ticker, move_pct, headlines, context)
    try:
        append_tape(card)
    except Exception as exc:  # noqa: BLE001
        print(f"[WHY] tape append failed: {exc}")
    return card


if __name__ == "__main__":
    demo = diagnose_and_record(
        "SK Hynix slows advanced AI-chip output; memory names sell off on 'AI demand skepticism'.",
        ticker="000660.KS",
        move_pct=-4.0,
        headlines=["SK Hynix cuts advanced node output", "Micron -13% on memory glut fears"],
    )
    print(json.dumps(demo, indent=2, ensure_ascii=False))
    print("\n" + format_card(demo))
