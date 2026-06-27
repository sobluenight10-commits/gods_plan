"""tools/chokepoint_radar.py — supply-chain chokepoint tripwires (Lesson #09).

The system watched liquidity, FSI, oil, VIX, SEC filings. It watched NOTHING
upstream — and that blind spot nearly made us misread our own SK Hynix core
when China's tungsten squeeze forced a WF6 capacity cliff. The market sold the
*result* ("SK Hynix cut AI chips = demand dying"); the *cause* was a supply
shock that RAISES memory prices — bullish for incumbents.

This module monitors critical-input chokepoints. For each it tracks:
  - news velocity (Google News RSS, no API key) on export-control / shortage / price-surge
  - a hard-date countdown (e.g. WF6 July 1 2026 capacity cliff)
  - WHO it hurts (victims) and — the question the market skips — WHO it makes
    richer (beneficiaries / second-order winners)

Output: data/chokepoint_radar.json + a webroot mirror, and a deduped Telegram
tripwire when a chokepoint goes HOT. Wired into olympus_daily.

States: QUIET → WATCH → HOT → FIRED (hard date imminent).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")
OUT_FILE = os.path.join(DATA, "chokepoint_radar.json")
WEBROOT = "/var/www/html"
DEDUP_FILE = os.path.join(DATA, "chokepoint_dedup.json")

# ── Knowledge base — engraved from GOD's WF6 lesson, Jun 2026 ──────────────────
# Each chokepoint carries the causal map: input → who is hurt → who benefits.
# 'sign_note' is the Lesson #09 inversion: why the tape's first read is often
# wrong on causation.
CHOKEPOINTS = [
    {
        "id": "tungsten_wf6",
        "label": "Tungsten → WF6 gas",
        "inputs": ["tungsten", "WF6", "tungsten hexafluoride", "APT ammonium paratungstate"],
        "china_control_pct": 83,
        "hard_date": "2026-07-01",  # Kanto Denka + Central Glass cease WF6 (~25% global)
        "hard_date_note": "Kanto Denka + Central Glass permanently cease WF6 (~25% global capacity)",
        "queries": [
            "tungsten export control China",
            "WF6 tungsten hexafluoride shortage",
            "tungsten price surge semiconductor",
        ],
        "price_proxies": ["ALM.TO", "GMO.AX"],  # Almonty, Gold Mountain — non-China tungsten (best-effort)
        "victims": ["Samsung (≈80% WF6 from Japan)", "TSMC", "NAND/DRAM fabs broadly"],
        "beneficiaries": [
            "000660.KS",  # SK Hynix — better sourced (SK Specialty/Foosung/Peric) → relative advantage
            "MU",         # Micron — memory ASP tailwind
            "Foosung / SK Specialty (trades, not core)",
            "non-China tungsten miners (Materials sleeve)",
        ],
        "holdings_link": ["000660.KS", "FCX", "COHR"],
        "cause_class": "SUPPLY",
        "sign_note": (
            "A 25% cut to a non-substitutable input into RISING AI demand is "
            "INFLATIONARY for memory — bullish for SK Hynix/Micron pricing power. "
            "The 'AI demand skepticism' read has the sign backwards."
        ),
    },
    {
        "id": "gallium_germanium",
        "label": "Gallium / Germanium",
        "inputs": ["gallium", "germanium"],
        "china_control_pct": 90,
        "hard_date": None,
        "hard_date_note": "China export licensing since Aug 2023; precedent for tungsten sequel",
        "queries": [
            "gallium germanium export control China",
            "gallium germanium price",
        ],
        "price_proxies": [],
        "victims": ["compound-semi (RF/GaN) supply", "fiber optics", "defense optoelectronics"],
        "beneficiaries": [
            "COHR",   # photonics with non-China sourcing leverage
            "ex-China critical-minerals producers",
        ],
        "holdings_link": ["COHR", "FCX"],
        "cause_class": "SUPPLY",
        "sign_note": "Export curbs on inputs lift pricing for ex-China processors — map beneficiaries, not just victims.",
    },
    {
        "id": "rare_earths",
        "label": "Rare earths / magnets",
        "inputs": ["rare earth", "neodymium", "dysprosium", "permanent magnet"],
        "china_control_pct": 70,
        "hard_date": None,
        "hard_date_note": "China dominates refining + magnet output; recurring export-control flashpoint",
        "queries": [
            "rare earth export control China",
            "rare earth magnet shortage defense",
        ],
        "price_proxies": ["MP"],  # MP Materials
        "victims": ["EV motors", "wind turbines", "guided-munitions supply"],
        "beneficiaries": [
            "MP",            # MP Materials — ex-China rare earths
            "272210.KS",     # Hanwha Systems — defense magnet supply security premium
        ],
        "holdings_link": ["272210.KS", "KTOS", "FCX"],
        "cause_class": "SUPPLY",
        "sign_note": "Magnet curbs are a national-security premium for ex-China producers and defense primes.",
    },
    {
        "id": "neon_gas",
        "label": "Neon / noble gases",
        "inputs": ["neon gas", "noble gas lithography"],
        "china_control_pct": 0,
        "hard_date": None,
        "hard_date_note": "Ukraine supplied ~50% of semiconductor-grade neon; war = recurring squeeze",
        "queries": [
            "neon gas shortage semiconductor",
            "lithography gas supply Ukraine",
        ],
        "price_proxies": [],
        "victims": ["DUV lithography consumables", "fabs without inventory buffers"],
        "beneficiaries": ["ASML (installed-base services insulate it)", "fabs with neon recycling"],
        "holdings_link": ["ASML", "000660.KS", "TSM"],
        "cause_class": "SUPPLY",
        "sign_note": "A neon squeeze is a consumables-cost shock, not an equipment-demand signal.",
    },
    {
        "id": "abf_substrate",
        "label": "ABF substrate / advanced packaging",
        "inputs": ["ABF substrate", "advanced packaging substrate", "CoWoS"],
        "china_control_pct": 0,
        "hard_date": None,
        "hard_date_note": "CoWoS / ABF substrate is the real HBM/AI-accelerator bottleneck",
        "queries": [
            "ABF substrate shortage",
            "CoWoS capacity advanced packaging",
        ],
        "price_proxies": [],
        "victims": ["AI accelerator output if substrate-constrained"],
        "beneficiaries": [
            "TSM",        # CoWoS owner — packaging is the moat
            "000660.KS",  # HBM tied to packaging cadence
            "COHR",
        ],
        "holdings_link": ["TSM", "000660.KS", "COHR"],
        "cause_class": "SUPPLY",
        "sign_note": "Packaging scarcity concentrates value in the packagers (TSM CoWoS), not away from them.",
    },
]

_HOT_KEYWORDS = (
    "export control", "export ban", "export curb", "restrict", "license",
    "shortage", "halt", "cease", "ceases", "curtail", "suspend", "ban ",
    "surge", "spike", "soar", "rationing", "squeeze", "sanction",
)
_USER_AGENT = "Minerva-Chokepoint/1.0 (+gods-plan)"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _google_news_rss(query: str, max_items: int = 12) -> list[dict]:
    q = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    try:
        r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as exc:  # noqa: BLE001
        print(f"[CHOKEPOINT] RSS fail '{query}': {exc}")
        return []
    items = []
    for item in root.findall(".//item")[:max_items]:
        title = (item.findtext("title") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title:
            continue
        items.append({"title": title, "pub": pub, "link": link})
    return items


def _recency_days(pub: str) -> float:
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(pub, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (_now_utc() - dt).total_seconds() / 86400.0
        except Exception:
            continue
    return 999.0


def _days_to_hard_date(hard_date: str | None) -> int | None:
    if not hard_date:
        return None
    try:
        d = datetime.strptime(hard_date, "%Y-%m-%d").date()
        return (d - _now_utc().date()).days
    except Exception:
        return None


def _score_chokepoint(cp: dict) -> dict:
    headlines: list[dict] = []
    seen = set()
    for q in cp["queries"]:
        for h in _google_news_rss(q):
            key = h["title"].lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            headlines.append(h)
        time.sleep(0.3)

    fresh_hot = []
    for h in headlines:
        rec = _recency_days(h["pub"])
        tl = h["title"].lower()
        if rec <= 14 and any(k in tl for k in _HOT_KEYWORDS):
            fresh_hot.append({**h, "age_days": round(rec, 1)})

    fresh_hot.sort(key=lambda x: x["age_days"])
    n_hot = len(fresh_hot)

    dthd = _days_to_hard_date(cp.get("hard_date"))

    # State machine: news velocity + hard-date proximity.
    state = "QUIET"
    score = min(100, n_hot * 18)
    if dthd is not None and 0 <= dthd <= 30:
        state = "FIRED"
        score = max(score, 80)
    elif n_hot >= 3:
        state = "HOT"
        score = max(score, 60)
    elif n_hot >= 1:
        state = "WATCH"
        score = max(score, 30)
    if dthd is not None and 30 < dthd <= 90 and state in ("QUIET", "WATCH"):
        state = "WATCH"
        score = max(score, 40)

    return {
        "id": cp["id"],
        "label": cp["label"],
        "state": state,
        "score": int(score),
        "n_hot_headlines": n_hot,
        "days_to_hard_date": dthd,
        "hard_date": cp.get("hard_date"),
        "hard_date_note": cp.get("hard_date_note"),
        "china_control_pct": cp.get("china_control_pct"),
        "cause_class": cp.get("cause_class", "SUPPLY"),
        "sign_note": cp.get("sign_note", ""),
        "victims": cp.get("victims", []),
        "beneficiaries": cp.get("beneficiaries", []),
        "holdings_link": cp.get("holdings_link", []),
        "top_headlines": fresh_hot[:4],
    }


def _load_dedup() -> dict:
    try:
        with open(DEDUP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_dedup(d: dict) -> None:
    os.makedirs(DATA, exist_ok=True)
    with open(DEDUP_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)


def _format_tripwire(cp: dict) -> str:
    icon = {"FIRED": "🔴", "HOT": "🟠", "WATCH": "🟡", "QUIET": "⚪"}.get(cp["state"], "⚪")
    lines = [
        f"{icon} <b>CHOKEPOINT TRIPWIRE — {cp['label']}</b>",
        f"State: {cp['state']} · score {cp['score']}/100 · China control ~{cp['china_control_pct']}%",
    ]
    if cp.get("days_to_hard_date") is not None:
        lines.append(f"⏰ Hard date: {cp['hard_date']} (T-{cp['days_to_hard_date']}d) — {cp['hard_date_note']}")
    lines.append("")
    lines.append(f"🧭 CAUSE CLASS: {cp['cause_class']} (supply shock — read the cause, not the tape)")
    if cp.get("sign_note"):
        lines.append(f"↕️ SIGN: {cp['sign_note']}")
    if cp.get("beneficiaries"):
        lines.append("🟢 SECOND-ORDER WINNERS: " + ", ".join(cp["beneficiaries"]))
    if cp.get("victims"):
        lines.append("🔻 PRESSURED: " + ", ".join(cp["victims"]))
    if cp.get("holdings_link"):
        lines.append("📌 YOUR BOOK: " + ", ".join(cp["holdings_link"]))
    if cp.get("top_headlines"):
        lines.append("")
        lines.append("📰 Evidence:")
        for h in cp["top_headlines"][:3]:
            lines.append(f"  • {h['title'][:120]} ({h['age_days']}d)")
    lines.append("")
    lines.append("<i>Lesson #09 — trade the cause. Map who this input shortage makes richer.</i>")
    return "\n".join(lines)


def run(send_telegram: bool = True) -> dict:
    os.makedirs(DATA, exist_ok=True)
    results = [_score_chokepoint(cp) for cp in CHOKEPOINTS]
    results.sort(key=lambda c: c["score"], reverse=True)

    payload = {
        "generated_at": _now_utc().isoformat(),
        "chokepoints": results,
        "active": [c for c in results if c["state"] in ("HOT", "FIRED")],
        "doctrine": "Trade the cause, not the exposed result (Lesson #09).",
    }

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    try:
        if os.path.isdir(WEBROOT):
            import shutil
            shutil.copy2(OUT_FILE, os.path.join(WEBROOT, "chokepoint_radar.json"))
    except Exception as exc:  # noqa: BLE001
        print(f"[CHOKEPOINT] webroot mirror failed: {exc}")

    print(f"[CHOKEPOINT] {len(payload['active'])} active · "
          + ", ".join(f"{c['id']}={c['state']}" for c in results))

    if send_telegram and payload["active"]:
        try:
            from tools.alert_gate import weekend_muted
            if weekend_muted():
                print("[CHOKEPOINT] weekend mute — tripwire held")
                return payload
        except Exception:
            pass
        dedup = _load_dedup()
        today = _now_utc().strftime("%Y-%m-%d")
        for cp in payload["active"]:
            key = f"{cp['id']}_{cp['state']}_{today}"
            if dedup.get(key):
                continue
            try:
                from telegram_bot import send_telegram as _tg
                _tg(_format_tripwire(cp))
                dedup[key] = True
            except Exception as exc:  # noqa: BLE001
                print(f"[CHOKEPOINT] telegram failed: {exc}")
        # prune dedup to today only
        dedup = {k: v for k, v in dedup.items() if k.endswith(today)}
        _save_dedup(dedup)

    return payload


if __name__ == "__main__":
    import sys
    run(send_telegram="--no-telegram" not in sys.argv)
