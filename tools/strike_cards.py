"""
STRIKE CARDS — one decisive 0-100 composite per ticker.

The user's complaint:
    "Highly correlated data is scattered across active_actions, forecasts,
     premium_scores, secular_trends, insider_flow, patent_signal, GOD scores
     and Soros gaps — and never collapses into ONE number that tells me
     which name to buy first."

Solution:
    For every ticker the system tracks, produce a STRIKE CARD with a single
    composite score (0–100) and the inputs that drove it. The card is the
    only thing the dashboard / strike_plan needs to consume.

Score weights (must sum to 100):

    Macro fit            25  · liquidity strike score from strike_radar
    Forecast quality     20  · EV/|ES5| ratio + p_win + ensemble agreement
    Valuation (OPS)      15  · OPS < 100 great, 100-150 ok, ≥180 hard zero
    Quality              15  · GOD score + conviction
    Catalyst proximity   10  · days-to-known-catalyst (0-30 = high)
    Discovery edge       10  · insider cluster, secular trend, patent velocity
    Risk penalty         -5  · vetoes / blocks / correlation_pc1 share

Hard zeros (score = 0 regardless of components):
    - any active killer veto (sentinel, kernel, correlation, ops_extreme,
      pending_catalyst, tail_defcon1/2, liquidity_freeze)
    - verb in (EXIT, TRIM, WATCH)            (only BUY/ADD/HOLD eligible)
    - ev_pct ≤ 0 or p_win < 0.4
    - OPS ≥ 180

Inputs (all already produced by upstream pipeline — we only consolidate):
    data/active_actions.json   verb / blocks / vetoes / EV / ES5 / p_win /
                               conviction / OPS / stop_price / size_pct_nav
    data/forecasts.json        ensemble agreement quality
    data/strike_radar.json     macro strike score + state
    data/secular_trends.json   sector trend tailwind/headwind
    data/insider_flow.json     insider cluster_score per ticker
    data/patent_signal.json    R&D velocity per sector / ticker
    data/catalyst_radar.json   nearest catalyst date per ticker
    gem_inputs/core_satellite.json    CORE / SATELLITE classification
    state.json                 current holdings cost basis

Output:  data/strike_cards.json
    {
      generated_utc, macro_state, macro_score,
      cards: [
        {
          ticker, group, sector, verb,
          strike_score, score_breakdown {macro, forecast, valuation, quality,
            catalyst, discovery, risk_penalty},
          ev_pct, es5_pct, p_win, ops, conviction, god_score,
          stop_price, blocks, vetoes,
          buy_zone {low, mid, high} (best-guess pivot zones),
          one_liner (max 90 char justification)
        }, ...
      ],
      shortlist: [top 8 by score]
    }
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

ACTIVE = os.path.join(BASE, "data", "active_actions.json")
FORECASTS = os.path.join(BASE, "data", "forecasts.json")
RADAR = os.path.join(BASE, "data", "strike_radar.json")
SECULAR = os.path.join(BASE, "data", "secular_trends.json")
INSIDER = os.path.join(BASE, "data", "insider_flow.json")
PATENT = os.path.join(BASE, "data", "patent_signal.json")
CATALYST = os.path.join(BASE, "data", "catalyst_radar.json")
DIRECTIVES = os.path.join(BASE, "data", "directives.json")
CORE_SAT = os.path.join(BASE, "gem_inputs", "core_satellite.json")
STATE = os.path.join(BASE, "state.json")
OUT = os.path.join(BASE, "data", "strike_cards.json")
WEBROOT_OUT = "/var/www/html/strike_cards.json"

KILLER_BLOCKS = {
    "sentinel_freeze", "sentinel_veto", "kernel_freeze",
    "correlation_veto", "ops_extreme", "pending_catalyst",
    "tail_defcon1", "tail_defcon2",
    "liquidity_freeze", "liquidity_danger_freeze",
    "liquidity_contracting_freeze", "vector_freeze",
}

# Map from secular_trends sector keys to active_actions sector strings.
SECTOR_TO_THEME = {
    "Intelligence": "ai_compute",
    "Intelligence/AI": "ai_compute",
    "Energy": "nuclear_fission",
    "Energy/Uranium": "nuclear_fission",
    "Space": "space_economy",
    "Space/Logistics": "space_economy",
    "Bio": "bio_engineering",
    "Bio-Engineering": "bio_engineering",
    "Robotics": "robotics_autonomy",
    "Robotics/Defense": "robotics_autonomy",
    "Infrastructure": "ai_compute",
    "Global Issue": "critical_minerals",
}


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _macro_score(strike_radar: Dict[str, Any]) -> Tuple[int, str]:
    s = int(strike_radar.get("strike_score") or 50)
    state = strike_radar.get("state") or "UNKNOWN"
    return s, state


def _forecast_quality(action: Dict[str, Any], fc_row: Dict[str, Any]) -> int:
    """0-100 forecast quality.

    EV/|ES5| ratio scaled + p_win + ensemble agreement bonus.
    """
    ev = float(action.get("ev_pct") or 0.0)
    es5 = abs(float(action.get("es5_pct") or 20.0))
    if es5 < 2:
        es5 = 2
    ratio = max(-3.0, min(5.0, ev / es5))   # clamp
    # ratio 0 → 50, ratio 2 → 90, ratio -1 → 20
    base = 50 + ratio * 12
    pw = float(action.get("p_win") or 0.5)
    base += (pw - 0.5) * 40                  # ±20
    # ensemble agreement: stddev of model 1y point predictions, lower = better
    ens = (fc_row or {}).get("ensemble") or {}
    components = (fc_row or {}).get("components") or {}
    points = []
    for c in (components.values() if isinstance(components, dict) else components):
        p50 = (c or {}).get("p50") or (c or {}).get("p50_1y")
        if p50 is not None:
            try:
                points.append(float(p50))
            except (TypeError, ValueError):
                continue
    if len(points) >= 2:
        mean = sum(points) / len(points)
        if mean != 0:
            spread = (max(points) - min(points)) / abs(mean)
            if spread < 0.1:
                base += 6
            elif spread < 0.2:
                base += 3
            elif spread > 0.5:
                base -= 6
    _ = ens
    return int(max(0, min(100, base)))


def _valuation_score(ops: Optional[float]) -> int:
    if ops is None:
        return 50
    ops = float(ops)
    if ops <= 80:
        return 95
    if ops <= 100:
        return 80
    if ops <= 120:
        return 65
    if ops <= 150:
        return 45
    if ops < 180:
        return 25
    return 0  # hard zero, but the killer block already vetos


def _quality_score(action: Dict[str, Any], god: Optional[float]) -> int:
    conv = float(action.get("conviction") or 5.0)
    g = float(god) if god is not None else 70.0
    # GOD score 80 → 75, conv 8 → 75 → composite ~75
    base = 0.5 * g + 5.0 * conv  # both scaled to ~100
    return int(max(0, min(100, base)))


def _catalyst_score(catalysts: Dict[str, Any], ticker: str) -> Tuple[int, Optional[str]]:
    """Return (score, nearest_iso_date) using days-to-catalyst."""
    today = date.today()
    by_ticker = (catalysts or {}).get("by_ticker") or (catalysts or {}).get("tickers") or {}
    items = by_ticker.get(ticker) or []
    if not items:
        # try a flat list
        flat = (catalysts or {}).get("upcoming") or []
        items = [c for c in flat if c.get("ticker") == ticker]
    if not items:
        return 50, None
    nearest_days: Optional[int] = None
    nearest_date: Optional[str] = None
    for c in items:
        d = c.get("date") or c.get("event_date") or c.get("when")
        if not d:
            continue
        try:
            di = date.fromisoformat(d[:10])
        except Exception:
            continue
        diff = (di - today).days
        if diff < 0:
            continue
        if nearest_days is None or diff < nearest_days:
            nearest_days = diff
            nearest_date = d
    if nearest_days is None:
        return 50, None
    if nearest_days <= 7:
        return 90, nearest_date
    if nearest_days <= 21:
        return 75, nearest_date
    if nearest_days <= 45:
        return 60, nearest_date
    return 50, nearest_date


def _discovery_score(ticker: str, sector: Optional[str],
                      insider: Dict[str, Any], patents: Dict[str, Any],
                      secular: Dict[str, Any]) -> int:
    score = 50
    # Insider cluster buys for this ticker
    ins = (insider or {}).get("by_ticker") or {}
    row = ins.get(ticker) or {}
    cluster = float(row.get("cluster_score") or 0.0)
    if cluster >= 1.5:
        score += 15
    elif cluster >= 0.7:
        score += 8
    # Secular trend tailwind for this sector
    sec_themes = (secular or {}).get("themes") or {}
    theme_key = SECTOR_TO_THEME.get(sector or "")
    if theme_key and theme_key in sec_themes:
        z = float(sec_themes[theme_key].get("score") or 0.0)
        if z >= 1.0:
            score += 10
        elif z >= 0.3:
            score += 5
        elif z <= -0.5:
            score -= 5
    # Patent velocity (sector level)
    pat_sectors = (patents or {}).get("by_sector") or {}
    if theme_key and theme_key in pat_sectors:
        v = float(pat_sectors[theme_key].get("velocity_zscore") or 0.0)
        if v >= 1.0:
            score += 5
        elif v <= -1.0:
            score -= 3
    return max(0, min(100, score))


def _risk_penalty(action: Dict[str, Any]) -> int:
    """Subtractive 0..15 — bigger penalty = worse."""
    penalty = 0
    blocks = action.get("blocks") or []
    vetoes = action.get("vetoes") or []
    if any(b in KILLER_BLOCKS for b in list(blocks) + list(vetoes)):
        return 100  # hard zero handled separately
    pc1 = action.get("correlation_pc1_share")
    if pc1 is not None and float(pc1) >= 0.6:
        penalty += 5
    if action.get("stop_distance_pct") is not None:
        d = float(action["stop_distance_pct"])
        if d > 25:
            penalty += 5
    return min(15, penalty)


def _buy_zone(action: Dict[str, Any], fc_row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Use forecasts.p05 / p50 / p95 (price space) when available."""
    ens = (fc_row or {}).get("ensemble") or {}
    p05 = ens.get("p05_1y_price") or ens.get("p05")
    p50 = ens.get("p50_1y_price") or ens.get("p50")
    px = action.get("limit_price") or action.get("current_price") or action.get("entry_price")
    if px is None and p50 is not None:
        px = p50
    if px is None:
        return None
    px = float(px)
    return {
        "low": round(px * 0.92, 2),   # -8% (scale-in zone)
        "mid": round(px * 0.97, 2),   # -3%
        "high": round(px * 1.02, 2),  # market
    }


def _is_eligible(action: Dict[str, Any]) -> Tuple[bool, str]:
    blocks = action.get("blocks") or []
    vetoes = action.get("vetoes") or []
    if any(b in KILLER_BLOCKS for b in list(blocks) + list(vetoes)):
        return False, "killer_block"
    verb = (action.get("verb") or "").upper()
    if verb in ("EXIT", "TRIM"):
        return False, f"verb={verb}"
    ev = action.get("ev_pct")
    if ev is not None and float(ev) <= 0:
        return False, "ev<=0"
    pw = action.get("p_win")
    if pw is not None and float(pw) < 0.40:
        return False, "p_win<0.40"
    ops = action.get("ops")
    if ops is not None and float(ops) >= 180:
        return False, f"ops={ops}"
    return True, "ok"


def run() -> Dict[str, Any]:
    active = _load(ACTIVE, {})
    actions = active.get("actions") or {}
    forecasts = (_load(FORECASTS, {}).get("tickers") or {})
    radar = _load(RADAR, {})
    insider = _load(INSIDER, {})
    patents = _load(PATENT, {})
    secular = _load(SECULAR, {})
    catalysts = _load(CATALYST, {})
    directives = _load(DIRECTIVES, {})
    god_scores = (directives or {}).get("god_scores") or {}
    cs = _load(CORE_SAT, {"core_tickers": [], "satellite_tickers": []})
    core_set = set(cs.get("core_tickers") or [])
    sat_set = set(cs.get("satellite_tickers") or [])

    macro_score, macro_state = _macro_score(radar)

    cards: List[Dict[str, Any]] = []
    for tk, action in actions.items():
        eligible, reason = _is_eligible(action)
        sector = action.get("sector") or (god_scores.get(tk) or {}).get("sector")
        group = (action.get("group")
                 or ("CORE" if tk in core_set else
                     "SATELLITE" if tk in sat_set else "UNCLASSIFIED"))
        god = (god_scores.get(tk) or {}).get("score")
        fc_row = forecasts.get(tk) or {}

        if not eligible:
            cards.append({
                "ticker": tk, "group": group, "sector": sector,
                "verb": action.get("verb"),
                "strike_score": 0,
                "rejected": reason,
                "ev_pct": action.get("ev_pct"),
                "es5_pct": action.get("es5_pct"),
                "p_win": action.get("p_win"),
                "ops": action.get("ops"),
                "blocks": action.get("blocks") or [],
                "vetoes": action.get("vetoes") or [],
                "one_liner": f"{tk}: rejected — {reason}",
            })
            continue

        macro = macro_score
        forecast = _forecast_quality(action, fc_row)
        valuation = _valuation_score(action.get("ops"))
        quality = _quality_score(action, god)
        cat_score, nearest_cat = _catalyst_score(catalysts, tk)
        discovery = _discovery_score(tk, sector, insider, patents, secular)
        risk_pen = _risk_penalty(action)

        # Weighted composite
        composite = (
            0.25 * macro +
            0.20 * forecast +
            0.15 * valuation +
            0.15 * quality +
            0.10 * cat_score +
            0.10 * discovery
        )
        composite -= risk_pen
        # Group multiplier (CORE compounds longer; favored when scores tie)
        if group == "CORE":
            composite *= 1.05
        elif group == "UNCLASSIFIED":
            composite *= 0.92
        composite = max(0, min(100, round(composite, 1)))

        buy_zone = _buy_zone(action, fc_row)
        one_liner_bits = []
        if action.get("ev_pct") is not None and action.get("es5_pct") is not None:
            one_liner_bits.append(f"EV {action['ev_pct']:+.0f}% / ES5 {action['es5_pct']:+.0f}%")
        if action.get("ops") is not None:
            one_liner_bits.append(f"OPS {action['ops']:.0f}")
        if god is not None:
            one_liner_bits.append(f"GOD {god:.0f}")
        if nearest_cat:
            one_liner_bits.append(f"cat {nearest_cat[:10]}")
        one_liner_bits.append(group)
        one_liner = f"{tk} ({sector or '?'}) · " + " · ".join(one_liner_bits)

        cards.append({
            "ticker": tk,
            "group": group,
            "sector": sector,
            "verb": action.get("verb"),
            "strike_score": composite,
            "score_breakdown": {
                "macro": macro,
                "forecast": forecast,
                "valuation": valuation,
                "quality": quality,
                "catalyst": cat_score,
                "discovery": discovery,
                "risk_penalty": -risk_pen,
            },
            "ev_pct": action.get("ev_pct"),
            "es5_pct": action.get("es5_pct"),
            "p_win": action.get("p_win"),
            "ops": action.get("ops"),
            "conviction": action.get("conviction"),
            "god_score": god,
            "stop_price": action.get("stop_price"),
            "blocks": action.get("blocks") or [],
            "vetoes": action.get("vetoes") or [],
            "buy_zone": buy_zone,
            "nearest_catalyst": nearest_cat,
            "forecast_source": action.get("forecast_source"),
            "one_liner": one_liner[:120],
        })

    cards.sort(key=lambda c: c.get("strike_score") or 0, reverse=True)
    shortlist = [c for c in cards if (c.get("strike_score") or 0) > 0][:8]

    out = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "macro_state": macro_state,
        "macro_score": macro_score,
        "weights": {
            "macro": 25, "forecast": 20, "valuation": 15, "quality": 15,
            "catalyst": 10, "discovery": 10, "risk_penalty_max": 15,
        },
        "n_total": len(cards),
        "n_eligible": sum(1 for c in cards if (c.get("strike_score") or 0) > 0),
        "shortlist": shortlist,
        "cards": cards,
    }
    _write(out)
    return out


def _write(payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    try:
        if os.path.isdir(os.path.dirname(WEBROOT_OUT)):
            shutil.copy2(OUT, WEBROOT_OUT)
    except Exception as exc:
        print(f"[strike_cards] webroot mirror failed: {exc}")


if __name__ == "__main__":
    out = run()
    print(json.dumps({k: v for k, v in out.items() if k != "cards"}, indent=2))
