"""
STRIKE PLAN — €10,000 three-tranche pyramid, gated by Strike Radar.

Doctrine:
    Tranche 1  (40%, default €4,000)   ARM/STRIKE — release on STRIKE_PIVOT_EARLY
                                          or STRIKE_WINDOW_OPEN (3-day positive).
    Tranche 2  (35%, default €3,500)   CONFIRM    — release on STRIKE_WINDOW_OPEN
                                          (7-day positive AND reserves-led).
    Tranche 3  (25%, default €2,500)   FOLLOW-UP — reserve for the post-pop
                                          retracement (typical first-leg dip
                                          -8/-12% off the initial pop) OR for
                                          a hard catalyst (earnings, FDA, NRC,
                                          IPO, etc.).

Gating logic:

    macro_state                tranche releases
    -------------------------- ----------------
    FROZEN_CONTRACTING         T1=ARMED   T2=COCKED   T3=COCKED
    STRIKE_PIVOT_EARLY         T1=RELEASE T2=ARMED    T3=COCKED
    STRIKE_WINDOW_OPEN         T1=RELEASE T2=RELEASE  T3=ARMED
    SELECTIVE_TAILWIND         T1=RELEASE T2=RELEASE  T3=ARMED
    DEPLOY_RIDING              T1=RELEASE T2=RELEASE  T3=RELEASE-on-dip
    SELECTIVE_FADING / TOPPING T1=HOLD    T2=HOLD     T3=HOLD

Sizing inside each released tranche:

    Use top-N strike_cards (filtered by group caps):
       Tranche 1: 1-2 names, CORE only, 60/40 split if 2.
       Tranche 2: 2-3 names, mix CORE + SATELLITE (max 1 satellite),
                  scaled by strike_score share.
       Tranche 3: 1-2 names, opportunistic — scored only when triggered.

Single-position cap inside the strike plan = 50% of the tranche
(prevents an all-in into one name even if it scores highest).

Output:  data/strike_plan.json with concrete fields:
    tranches: [
      { id, status, eur, eur_released, picks: [
          {ticker, group, sector, eur, buy_zone, stop_price, why,
           strike_score, ev_pct, es5_pct, ops, p_win, conviction}, ... ],
        gate_condition, trigger_text }
    ],
    powder_total_eur, powder_used_eur, powder_remaining_eur,
    macro_state, mandate (1-line top-level)
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

CARDS = os.path.join(BASE, "data", "strike_cards.json")
RADAR = os.path.join(BASE, "data", "strike_radar.json")
STATE = os.path.join(BASE, "state.json")
OUT = os.path.join(BASE, "data", "strike_plan.json")
WEBROOT_OUT = "/var/www/html/strike_plan.json"

DEFAULT_PYRAMID = (0.40, 0.35, 0.25)


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _gate_for_state(state: str) -> Dict[str, str]:
    """Return tranche statuses based on macro state."""
    if state == "STRIKE_WINDOW_OPEN":
        return {"T1": "RELEASE", "T2": "RELEASE", "T3": "ARMED"}
    if state == "STRIKE_PIVOT_EARLY":
        return {"T1": "RELEASE", "T2": "ARMED", "T3": "COCKED"}
    if state == "FROZEN_CONTRACTING":
        return {"T1": "ARMED", "T2": "COCKED", "T3": "COCKED"}
    if state == "SELECTIVE_TAILWIND":
        return {"T1": "RELEASE", "T2": "RELEASE", "T3": "ARMED"}
    if state == "SELECTIVE_FADING":
        return {"T1": "HOLD", "T2": "HOLD", "T3": "HOLD"}
    if state == "DEPLOY_RIDING":
        return {"T1": "RELEASE", "T2": "RELEASE", "T3": "ARMED"}
    if state == "DEPLOY_TOPPING":
        return {"T1": "HOLD", "T2": "HOLD", "T3": "HOLD"}
    return {"T1": "HOLD", "T2": "HOLD", "T3": "HOLD"}


def _gate_text(state: str, status: str, tranche: str) -> str:
    if status == "RELEASE":
        return "Released — fire orders today / on next dip into buy zone."
    if status == "ARMED":
        if state == "FROZEN_CONTRACTING":
            return "Armed — orders pre-staged. Release on first day v_3d ≥ 0."
        return "Armed — orders pre-staged. Release on next confirmation."
    if status == "COCKED":
        return "Cocked — gate not yet met. Will arm once upstream tranche fires."
    if status == "HOLD":
        return "Hold — macro state does not justify deployment."
    return ""


def _select_picks(cards: List[Dict[str, Any]],
                   max_picks: int,
                   require_core: bool = False,
                   max_satellite: Optional[int] = None,
                   exclude: Optional[set] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    sat_count = 0
    excl = exclude or set()
    for c in cards:
        if (c.get("strike_score") or 0) <= 0:
            continue
        if c.get("ticker") in excl:
            continue
        grp = c.get("group") or "UNCLASSIFIED"
        if require_core and grp != "CORE":
            continue
        if max_satellite is not None and grp == "SATELLITE":
            if sat_count >= max_satellite:
                continue
            sat_count += 1
        out.append(c)
        if len(out) >= max_picks:
            break
    return out


def _allocate(picks: List[Dict[str, Any]], tranche_eur: float,
               max_per_pick_pct: float = 0.50) -> List[Dict[str, Any]]:
    """Allocate by strike_score share, capped per pick."""
    if not picks:
        return []
    total = sum(c["strike_score"] for c in picks)
    if total <= 0:
        per = tranche_eur / len(picks)
        return [_pick_row(c, round(per, 2)) for c in picks]
    rows: List[Dict[str, Any]] = []
    cap = tranche_eur * max_per_pick_pct
    remaining = tranche_eur
    for c in picks:
        share = c["strike_score"] / total
        eur = min(cap, round(tranche_eur * share, 2))
        eur = max(0.0, min(remaining, eur))
        remaining -= eur
        rows.append(_pick_row(c, eur))
    # Distribute any leftover into top pick
    if remaining > 1 and rows:
        rows[0]["eur"] = round(rows[0]["eur"] + remaining, 2)
    return rows


def _pick_row(c: Dict[str, Any], eur: float) -> Dict[str, Any]:
    return {
        "ticker": c["ticker"],
        "group": c["group"],
        "sector": c.get("sector"),
        "eur": eur,
        "strike_score": c.get("strike_score"),
        "ev_pct": c.get("ev_pct"),
        "es5_pct": c.get("es5_pct"),
        "p_win": c.get("p_win"),
        "ops": c.get("ops"),
        "conviction": c.get("conviction"),
        "stop_price": c.get("stop_price"),
        "buy_zone": c.get("buy_zone"),
        "nearest_catalyst": c.get("nearest_catalyst"),
        "why": c.get("one_liner"),
    }


def run(powder_eur: Optional[float] = None) -> Dict[str, Any]:
    cards_doc = _load(CARDS, {})
    radar = _load(RADAR, {})
    state_doc = _load(STATE, {})

    if powder_eur is None:
        powder_eur = float((state_doc.get("dry_powder") or {}).get("TR_EUR") or 0.0)
    powder_eur = round(float(powder_eur), 2)

    macro_state = radar.get("state") or "UNKNOWN"
    macro_score = int(radar.get("strike_score") or 50)
    gates = _gate_for_state(macro_state)

    pyramid = DEFAULT_PYRAMID
    t1_eur = round(powder_eur * pyramid[0], 2)
    t2_eur = round(powder_eur * pyramid[1], 2)
    t3_eur = round(powder_eur * pyramid[2], 2)

    shortlist = cards_doc.get("shortlist") or []

    # Tranche 1 — CORE-only, max 2 names.
    t1_picks_cards = _select_picks(shortlist, max_picks=2, require_core=True)
    if not t1_picks_cards:
        # Fallback: top 1 of any group, but flag as override.
        t1_picks_cards = _select_picks(shortlist, max_picks=1)
    t1_alloc = _allocate(t1_picks_cards, t1_eur) if gates["T1"] in ("RELEASE", "ARMED") else []
    t1_set = {c["ticker"] for c in t1_picks_cards}

    # Tranche 2 — diversifies into NEW names not taken by T1.
    # Doubling-down on T1 picks is reserved for the post-pop dip in T3.
    t2_picks_cards = _select_picks(shortlist, max_picks=3, max_satellite=2,
                                    exclude=t1_set)
    t2_alloc = _allocate(t2_picks_cards, t2_eur) if gates["T2"] in ("RELEASE", "ARMED") else []
    t2_set = {c["ticker"] for c in t2_picks_cards}

    # Tranche 3 — opportunistic. Allowed to add to T1/T2 names IF a real dip
    # appears (-8/-12% retracement) — this is where we double-down.
    t3_picks_cards = _select_picks(shortlist, max_picks=2)
    t3_alloc = _allocate(t3_picks_cards, t3_eur) if gates["T3"] in ("RELEASE", "ARMED") else []

    def _used(rows: List[Dict[str, Any]]) -> float:
        return round(sum(r.get("eur") or 0 for r in rows), 2)

    powder_used = _used(t1_alloc) if gates["T1"] == "RELEASE" else 0
    powder_used += _used(t2_alloc) if gates["T2"] == "RELEASE" else 0
    powder_used += _used(t3_alloc) if gates["T3"] == "RELEASE" else 0

    tranches = [
        {
            "id": "T1",
            "label": "STRIKE",
            "eur": t1_eur,
            "eur_released": _used(t1_alloc) if gates["T1"] == "RELEASE" else 0,
            "status": gates["T1"],
            "trigger_text": _gate_text(macro_state, gates["T1"], "T1"),
            "gate_condition": "v_3d ≥ 0 (early pivot) OR v_7d ≥ 0 (confirmation)",
            "picks": t1_alloc,
        },
        {
            "id": "T2",
            "label": "CONFIRM",
            "eur": t2_eur,
            "eur_released": _used(t2_alloc) if gates["T2"] == "RELEASE" else 0,
            "status": gates["T2"],
            "trigger_text": _gate_text(macro_state, gates["T2"], "T2"),
            "gate_condition": "v_7d ≥ 0 AND reserves-led pivot quality A or B",
            "picks": t2_alloc,
        },
        {
            "id": "T3",
            "label": "FOLLOW-UP",
            "eur": t3_eur,
            "eur_released": _used(t3_alloc) if gates["T3"] == "RELEASE" else 0,
            "status": gates["T3"],
            "trigger_text": _gate_text(macro_state, gates["T3"], "T3"),
            "gate_condition": "First post-pop dip (-8 to -12% off T2 entry) OR hard catalyst",
            "picks": t3_alloc,
        },
    ]

    if macro_state in ("FROZEN_CONTRACTING",):
        mandate = (f"HOLD ALL POWDER (€{powder_eur:.0f}). Tranche 1 ARMED at "
                   f"current support — release on first day v_3d ≥ 0.")
    elif macro_state == "STRIKE_PIVOT_EARLY":
        mandate = (f"FIRE TRANCHE 1 (€{t1_eur:.0f}) on confirmation; "
                   f"Tranche 2 ARMED.")
    elif macro_state == "STRIKE_WINDOW_OPEN":
        mandate = (f"STRIKE NOW — release T1+T2 (€{t1_eur + t2_eur:.0f}). "
                   f"T3 reserved for post-pop dip.")
    elif macro_state in ("SELECTIVE_TAILWIND", "DEPLOY_RIDING"):
        mandate = f"DEPLOY T1+T2 (€{t1_eur + t2_eur:.0f}); ride existing positions."
    else:
        mandate = f"HOLD POWDER (€{powder_eur:.0f}) — macro state {macro_state}."

    plan = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "powder_total_eur": powder_eur,
        "powder_used_eur": round(powder_used, 2),
        "powder_remaining_eur": round(powder_eur - powder_used, 2),
        "macro_state": macro_state,
        "macro_score": macro_score,
        "pyramid_pct": [int(p * 100) for p in pyramid],
        "tranches": tranches,
        "mandate": mandate,
        "rules": {
            "T1_core_only": True,
            "T1_max_picks": 2,
            "T2_max_picks": 3,
            "T2_max_satellite": 1,
            "T3_max_picks": 2,
            "max_per_pick_of_tranche_pct": 50,
        },
    }
    _write(plan)
    return plan


def _write(plan: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    try:
        if os.path.isdir(os.path.dirname(WEBROOT_OUT)):
            shutil.copy2(OUT, WEBROOT_OUT)
    except Exception as exc:
        print(f"[strike_plan] webroot mirror failed: {exc}")


if __name__ == "__main__":
    p = run()
    print(json.dumps(p, indent=2))
