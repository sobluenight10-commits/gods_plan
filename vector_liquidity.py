"""
Vector Liquidity Engine v2 — zone (level) × vector (7d net-liq change).

Institutions optimize for range; OLYMPUS optimizes for VECTOR at the margin.
Zones use GOD's thresholds (billions USD net liquidity):
  DANGER:    net < 1,900
  SELECTIVE: 1,900 ≤ net < 2,200
  DEPLOY:    net ≥ 2,200

Vector: sign/magnitude of ~7d change in net liq (from pre_alarm velocity_7d_b).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Thresholds (billions)
DANGER_MAX = 1900.0
SELECTIVE_HIGH = 2200.0
VECTOR_NEUTRAL_ABS = 8.0  # |Δ| below this → NEUTRAL (noisy FRED week)


def _band(net_b: float) -> str:
    if net_b < DANGER_MAX:
        return "DANGER"
    if net_b < SELECTIVE_HIGH:
        return "SELECTIVE"
    return "DEPLOY"


def _vector_label(v7: Optional[float]) -> str:
    if v7 is None:
        return "UNKNOWN"
    if abs(float(v7)) < VECTOR_NEUTRAL_ABS:
        return "NEUTRAL"
    if float(v7) > 0:
        return "EXPANDING"
    return "CONTRACTING"


def _state_id(band: str, vec: str) -> int:
    if band == "DANGER" and vec == "CONTRACTING":
        return 1
    if band == "DANGER" and vec == "EXPANDING":
        return 2
    if band == "DANGER" and vec == "NEUTRAL":
        return 1  # cautious: treat as drain risk
    if band == "SELECTIVE" and vec == "EXPANDING":
        return 3
    if band == "SELECTIVE" and vec in ("CONTRACTING", "NEUTRAL"):
        return 4
    if band == "DEPLOY" and vec == "EXPANDING":
        return 5
    if band == "DEPLOY" and vec in ("CONTRACTING", "NEUTRAL"):
        return 6
    if band == "DEPLOY" and vec == "UNKNOWN":
        return 5
    return 4


def _title(state: int) -> str:
    return {
        1: "STATE 1 — DANGER + CONTRACTING",
        2: "STATE 2 — DANGER + EXPANDING (strike window)",
        3: "STATE 3 — SELECTIVE + EXPANDING",
        4: "STATE 4 — SELECTIVE + CONTRACTING / NEUTRAL",
        5: "STATE 5 — DEPLOY + EXPANDING",
        6: "STATE 6 — DEPLOY + CONTRACTING (secure profits)",
    }[state]


def _actions(state: int) -> list:
    return {
        1: [
            "FREEZE all new adds (liquidity gate).",
            "Hold dry powder; do NOT panic-sell INTACT names into sector drawdowns.",
            "Exception: thesis DEAD → exit regardless.",
            "Watch for vector reversal (7d turn positive) — not calendar dates.",
        ],
        2: [
            "STRIKE window: net still < $1.9T but vector turning positive = tide shifting.",
            "Max 1–2 names · thesis INTACT · GOD ≥70 · size 30–40% of dry powder each.",
            "Does NOT bypass thesis guard or GEM minimums — clears liquidity only.",
        ],
        3: [
            "DEPLOY broadly: add to core on dips; arm bench limits.",
            "Ride INTACT; no trimming solely because sector wobbles.",
        ],
        4: [
            "SECURE: take profit on tactical sleeve >30% gain; tighten stops.",
            "No new entries; rebuild cash for State 2.",
            "Do NOT liquidate core winners into weakness unless thesis breaks.",
        ],
        5: [
            "RIDE + ARM: max exposure on INTACT; arm highest-conviction bench.",
            "Trim only if >50% gain AND GEM grade deteriorated materially.",
        ],
        6: [
            "SECURE: trim 20–30% of highest-gain tactical names; cancel stale limits.",
            "Build dry powder — vector falling from DEPLOY = pre-correction setup.",
            "Sell strength on extended tacticals; not core on thesis alone.",
        ],
    }[state]


def _so_what_one_liner(state: int, net_b: float, v7: Optional[float]) -> str:
    vtxt = f"{v7:+.0f}B" if v7 is not None else "n/a"
    base = f"[V2] Net ${net_b:.0f}B · 7d Δ {vtxt} · {_title(state)}. "
    tail = {
        1: "Default: freeze adds, hold core, no forced trims.",
        2: "Selective strike only (1–2) with full thesis + score gate.",
        3: "Tailwind — deploy discipline on dips.",
        4: "Draining — harvest tacticals, stand down new risk.",
        5: "Maximum liquidity tailwind — ride core, arm best bench.",
        6: "Liquidity rolling over from high — secure tactical gains, raise cash.",
    }[state]
    return base + tail


def _projection_lines(state: int, band: str, vec: str) -> list:
    """Rolling macro copy — no stale calendar dates."""
    acts = _actions(state)
    lead = acts[0] if acts else ""
    return [
        {
            "date": "Vector-driven",
            "event": f"Zone {band} · 7d vector {vec}",
            "impact": "Projection follows FRED + velocity — refresh daily (olympus_daily).",
        },
        {
            "date": "Tax / TGA",
            "event": "US fiscal flows still move TGA (no fixed calendar in engine)",
            "impact": "Watch net liq velocity; positive 7d Δ often follows large TGA paydowns.",
        },
        {
            "date": "Your mandate",
            "event": _title(state),
            "impact": lead,
        },
    ]


def build_vector_engine(net_b: float, velocity_7d_b: Optional[float]) -> Dict[str, Any]:
    band = _band(float(net_b))
    vec = _vector_label(velocity_7d_b)
    sid = _state_id(band, vec)
    actions = _actions(sid)
    return {
        "engine": "vector_liquidity_v2",
        "zone_band": band,
        "vector_7d": vec,
        "velocity_7d_b": None if velocity_7d_b is None else round(float(velocity_7d_b), 1),
        "state_id": sid,
        "state_title": _title(sid),
        "actions": actions,
        "so_what_one_liner": _so_what_one_liner(sid, float(net_b), velocity_7d_b),
        "projection_items": _projection_lines(sid, band, vec),
        "thresholds": {
            "danger_max_b": DANGER_MAX,
            "selective_high_b": SELECTIVE_HIGH,
            "vector_neutral_abs_b": VECTOR_NEUTRAL_ABS,
        },
    }


def attach_to_liquidity_dict(liq: Dict[str, Any], net_b: float, velocity_7d_b: Optional[float]) -> None:
    liq["liquidity_vector_engine"] = build_vector_engine(net_b, velocity_7d_b)
    liq["so_what_consolidated"] = liq["liquidity_vector_engine"]["so_what_one_liner"]
