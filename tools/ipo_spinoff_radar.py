"""
IPO / SPINOFF RADAR — upcoming IPOs scored against the 8-sector framework.

Day-1 IPOs and parent spinoffs are two of the cleanest asymmetric setups
retail can access at scale. Institutions already know; the edge is in
pre-scoring each name against the 8 GOD sectors BEFORE the ticker
prints.

This module:
  1. Loads gem_inputs/ipo_calendar.json (user-curated list of upcoming
     IPOs and spin-offs — hand-kept because "reliable public IPO
     calendar" is an unsolved problem; we include sensible defaults).
  2. For each pending IPO: scores against a simple 0-10 framework —
     sector fit (0-4), scale (0-2), moat (0-2), governance (0-2).
  3. Computes a conviction tier (A/B/C/D/PASS) from total score.
  4. Flags any name crossing IPO date within 30/60/90d.
  5. Output: data/ipo_radar.json (mirrored to webroot).

Updates to the watchlist itself happen by editing gem_inputs/ipo_calendar.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, date
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

CAL = os.path.join(BASE, "gem_inputs", "ipo_calendar.json")
OUT = os.path.join(BASE, "data", "ipo_radar.json")
WEBROOT_OUT = "/var/www/html/ipo_radar.json"

# Seed calendar so the dashboard has real data on day 1. These dates are
# best-public-estimates; update in gem_inputs/ipo_calendar.json.
DEFAULT_CALENDAR: Dict[str, Any] = {
    "version": 1,
    "last_updated": "2026-04-24",
    "pending_ipos": [
        {
            "name": "Anthropic PBC",
            "symbol": "ANTH",
            "expected_date": "2026-10-15",
            "type": "IPO",
            "sector": "AI_COMPUTE",
            "scale": 4,
            "moat": 4,
            "governance": 3,
            "notes": "Claude franchise. Amazon + Google backers. Likely mega-cap listing. Day-1 discipline: wait for 3rd earnings print."
        },
        {
            "name": "SpaceX",
            "symbol": "SPCX",
            "expected_date": "2026-06-30",
            "type": "IPO",
            "sector": "SPACE_ECON",
            "scale": 4,
            "moat": 4,
            "governance": 2,
            "notes": "Starlink alone justifies $150-200B. Lockup + dual class risk."
        },
        {
            "name": "Databricks",
            "symbol": "DBRX",
            "expected_date": "2026-08-31",
            "type": "IPO",
            "sector": "AI_COMPUTE",
            "scale": 3,
            "moat": 3,
            "governance": 3,
            "notes": "Lakehouse standard. Snowflake competitor. Pre-IPO ARR ~$3B."
        },
        {
            "name": "Stripe",
            "symbol": "STRP",
            "expected_date": "2026-11-30",
            "type": "IPO",
            "sector": "FINTECH",
            "scale": 3,
            "moat": 3,
            "governance": 3,
            "notes": "Out of GOD framework — pass unless sector expansion."
        },
        {
            "name": "Helion Energy",
            "symbol": "HELN",
            "expected_date": "2027-03-31",
            "type": "IPO",
            "sector": "NUCLEAR",
            "scale": 2,
            "moat": 4,
            "governance": 2,
            "notes": "Fusion commercial timeline unclear — bet on optionality, not revenue."
        }
    ],
    "recent_spinoffs": [
        {
            "parent": "General Electric",
            "children": ["GE Aerospace (GE)", "GE HealthCare (GEHC)", "GE Vernova (GEV)"],
            "completed": "2024-04-02",
            "sector_hits": ["DEFENSE_AUTON", "BIOTECH_INFRA"],
            "notes": "GEV = energy transition play; GE = defense/aerospace pure-play."
        }
    ]
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _days_to(d: Optional[str]) -> Optional[int]:
    if not d:
        return None
    try:
        t = datetime.fromisoformat(d[:10]).date()
        return (t - date.today()).days
    except Exception:
        return None


def _tier(total: int) -> str:
    if total >= 12:
        return "A"
    if total >= 10:
        return "B"
    if total >= 8:
        return "C"
    if total >= 6:
        return "D"
    return "PASS"


def _score(entry: Dict[str, Any]) -> Dict[str, Any]:
    # Sector fit (0-4): 4 if our 8 themes, 2 if adjacent, 0 otherwise
    sector_map = {
        "AI_COMPUTE": 4, "NUCLEAR": 4, "SPACE_ECON": 4, "GENE_EDITING": 4,
        "DEFENSE_AUTON": 4, "BIOTECH_INFRA": 4, "CYBER": 4, "CRITICAL_MIN": 4,
        "FINTECH": 2, "CONSUMER": 1, "INDUSTRIAL": 1,
    }
    sector_fit = sector_map.get(entry.get("sector"), 0)
    scale = int(entry.get("scale") or 0)     # 0-4
    moat = int(entry.get("moat") or 0)       # 0-4
    governance = int(entry.get("governance") or 0)  # 0-4
    total = sector_fit + min(scale, 2) + min(moat, 2) + min(governance, 2)
    tier = _tier(total)
    return {
        **entry,
        "score_sector_fit": sector_fit,
        "score_scale": min(scale, 2),
        "score_moat": min(moat, 2),
        "score_governance": min(governance, 2),
        "score_total": total,
        "tier": tier,
        "days_to": _days_to(entry.get("expected_date")),
    }


def _ensure_seed() -> Dict[str, Any]:
    if not os.path.exists(CAL):
        os.makedirs(os.path.dirname(CAL), exist_ok=True)
        with open(CAL, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CALENDAR, f, indent=2, ensure_ascii=False)
        return DEFAULT_CALENDAR
    return _load(CAL, DEFAULT_CALENDAR)


def run() -> Dict[str, Any]:
    cal = _ensure_seed()
    scored = [_score(e) for e in (cal.get("pending_ipos") or [])]
    scored.sort(key=lambda r: (r.get("days_to") if r.get("days_to") is not None else 9999))

    imminent_30 = [s for s in scored if (s.get("days_to") or 9999) <= 30 and s.get("tier") in ("A", "B")]
    imminent_90 = [s for s in scored if (s.get("days_to") or 9999) <= 90 and s.get("tier") in ("A", "B")]

    payload = {
        "schema_version": 1,
        "generated_utc": _now_iso(),
        "pending_ipos": scored,
        "recent_spinoffs": cal.get("recent_spinoffs") or [],
        "imminent_30d": imminent_30,
        "imminent_90d": imminent_90,
        "mandate": _mandate(imminent_30, imminent_90, scored),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    try:
        import shutil
        shutil.copy2(OUT, WEBROOT_OUT)
    except Exception:
        pass
    return payload


def _mandate(imm30: List[Dict[str, Any]], imm90: List[Dict[str, Any]],
             scored: List[Dict[str, Any]]) -> str:
    if imm30:
        names = ", ".join(f"{s['name']}({s['tier']})" for s in imm30)
        return f"IPO watch (next 30d): {names} — prep reading list, do not buy day 1."
    if imm90:
        names = ", ".join(f"{s['name']}({s['tier']})" for s in imm90[:3])
        return f"IPO watch (next 90d): {names}."
    if scored:
        return f"No imminent A/B IPOs in 90d. Track {len(scored)} on calendar."
    return "Calendar empty — add upcoming IPOs to gem_inputs/ipo_calendar.json."


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "mandate": out.get("mandate"),
        "imminent_30d": [x["name"] for x in out.get("imminent_30d") or []],
        "imminent_90d": [x["name"] for x in out.get("imminent_90d") or []],
    }, indent=2))
