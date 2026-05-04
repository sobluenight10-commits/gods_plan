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
POINT_B = os.path.join(BASE, "data", "point_b_scan.json")
POINT_A = os.path.join(BASE, "data", "point_a_scan.json")
SECULAR = os.path.join(BASE, "data", "secular_trends.json")
INSIDER = os.path.join(BASE, "data", "insider_flow.json")
PATENT = os.path.join(BASE, "data", "patent_signal.json")
CATALYST = os.path.join(BASE, "data", "catalyst_radar.json")
DIRECTIVES = os.path.join(BASE, "data", "directives.json")
CORE_SAT = os.path.join(BASE, "gem_inputs", "core_satellite.json")
STATE = os.path.join(BASE, "state.json")
OUT = os.path.join(BASE, "data", "strike_cards.json")
WEBROOT_OUT = "/var/www/html/strike_cards.json"

# Killer blocks that veto a card unconditionally.
KILLER_BLOCKS = {
    "sentinel_freeze", "sentinel_veto", "kernel_freeze",
    "correlation_veto", "ops_extreme", "pending_catalyst",
    "tail_defcon1", "tail_defcon2",
}

# Liquidity-related blocks: respected by default but DOWNGRADED to a soft
# penalty (no hard zero) when Strike Radar reports a pivot state. Strike
# Radar v2 is the modern vector+decomposition gate; liquidity_freeze is the
# legacy zone-only v1 gate. When the radar detects a true pivot, the legacy
# gate yields.
LIQUIDITY_BLOCKS = {
    "liquidity_freeze", "liquidity_danger_freeze",
    "liquidity_contracting_freeze", "vector_freeze",
}

PIVOT_STATES = {"STRIKE_PIVOT_EARLY", "STRIKE_WINDOW_OPEN"}

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


def _risk_penalty(action: Dict[str, Any], pivot_active: bool = False) -> int:
    """Subtractive 0..15 — bigger penalty = worse.

    pivot_active = Strike Radar state ∈ PIVOT_STATES. When true, liquidity
    blocks become a -3 penalty rather than triggering a hard veto upstream.
    """
    penalty = 0
    blocks = action.get("blocks") or []
    vetoes = action.get("vetoes") or []
    seen = list(blocks) + list(vetoes)
    if any(b in KILLER_BLOCKS for b in seen):
        return 100  # hard zero handled separately
    if any(b in LIQUIDITY_BLOCKS for b in seen):
        penalty += 0 if pivot_active else 100
        if pivot_active:
            penalty += 3
    pc1 = action.get("correlation_pc1_share")
    if pc1 is not None and float(pc1) >= 0.6:
        penalty += 5
    if action.get("stop_distance_pct") is not None:
        d = float(action["stop_distance_pct"])
        if d > 25:
            penalty += 5
    return min(15, penalty) if penalty < 100 else 100


def _buy_zone(action: Dict[str, Any], fc_row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """Buy zone in PRICE space.

    Priority:
        1. action.limit_price (an explicit user-set limit) — most reliable.
        2. forecasts.ensemble.p50_1y_price — if the forecaster emits absolute
           prices (some pipelines do, others emit returns; we ignore returns).
        3. Reverse-engineer from stop_price assuming the stop is set 15-25%
           below the current price (typical ATR×2 calibration). We derive a
           rough "current ≈ stop / 0.82".
        4. None — refuse to fabricate a zone.

    Output is always {low (-8%), mid (-3%), high (+2%)} around the anchor.
    """
    anchor: Optional[float] = None
    lp = action.get("limit_price")
    if lp is not None:
        try:
            v = float(lp)
            if v > 0:
                anchor = v
        except (TypeError, ValueError):
            pass

    if anchor is None:
        ens = (fc_row or {}).get("ensemble") or {}
        for key in ("p50_1y_price", "p50_price", "p50_abs"):
            v = ens.get(key)
            if v is not None:
                try:
                    fv = float(v)
                    if fv > 1.0:
                        anchor = fv
                        break
                except (TypeError, ValueError):
                    continue

    if anchor is None:
        sp = action.get("stop_price")
        if sp is not None:
            try:
                fv = float(sp)
                if fv > 0:
                    anchor = fv / 0.82  # implied current = stop / 0.82
            except (TypeError, ValueError):
                pass

    if anchor is None:
        return None
    return {
        "low": round(anchor * 0.92, 2),   # scale-in
        "mid": round(anchor * 0.97, 2),   # base
        "high": round(anchor * 1.02, 2),  # market
        "anchor_source": ("limit_price" if action.get("limit_price")
                           else ("forecast_p50_price" if anchor > 1.0 and not action.get("stop_price")
                                  else "implied_from_stop")),
    }


def _is_eligible(action: Dict[str, Any], pivot_active: bool = False) -> Tuple[bool, str]:
    blocks = action.get("blocks") or []
    vetoes = action.get("vetoes") or []
    seen = list(blocks) + list(vetoes)
    if any(b in KILLER_BLOCKS for b in seen):
        return False, "killer_block"
    if any(b in LIQUIDITY_BLOCKS for b in seen) and not pivot_active:
        return False, "liquidity_freeze"
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


def _entry_ladder(
    ticker: str,
    action: Dict[str, Any],
    point_b: Dict[str, Any],
    point_a: Dict[str, Any],
    fc_row: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Concrete 3-tranche entry ladder per the user's standing instruction:

        Best single entry = -15% from 20d high (POINT_B_EXECUTE)
        Best execution    = ladder
            T1 light  -10%  →  30%   (warning level — toehold)
            T2 main   -15%  →  50%   (execute level — the trade)
            T3 deep   at base → 20%  (cancelled if base broken)

        Abort: close ≤ stop_below_base = breakout_base × 0.97.

    All three legs come from the Point B scanner output so the dashboard
    shows the SAME numbers as the Heads-Up panel.
    """
    pb = (point_b.get("tickers") or {}).get(ticker) or {}
    high_20d = pb.get("high_20d")
    base = pb.get("breakout_base")
    last = pb.get("last_close")
    bz = pb.get("buy_zone_b") or {}

    # If Point B has no data, fall back to existing buy_zone (ez_low/ez_high)
    if high_20d is None or base is None:
        return None

    warning_at = bz.get("warning_at") or round(high_20d * 0.90, 4)
    execute_at = bz.get("execute_at") or round(high_20d * 0.85, 4)
    base_floor = round(base, 4)
    stop_abort = pb.get("stop_below_base") or round(base * 0.97, 4)

    pa_row = (point_a.get("tickers") or {}).get(ticker) or {}
    ma_20w = pa_row.get("ma_20w")

    # The "best single entry" = whichever is *higher* between -15% from 20d
    # high and the 20W MA (you want the more conservative — i.e. the one
    # likeliest to get filled on a normal pullback). If MA is above -15%, MA
    # itself is already-filled territory; use -15% as the floor.
    if ma_20w is not None and execute_at is not None:
        best_single = max(execute_at, ma_20w)
    else:
        best_single = execute_at

    # Confidence note — 3-of-3 (FIRED) on Point A → B execute is even higher
    # asymmetry. 2-of-3 (WATCH) → wait for A3 (price ≤ MA20W) to flip.
    a_state = pa_row.get("state") or "INACTIVE"

    return {
        "best_single": round(best_single, 2),
        "tiers": [
            {"label": "T1 light", "price": round(warning_at, 2), "size_pct": 30,
             "trigger": "-10% from 20d high · POINT_B_WARNING"},
            {"label": "T2 main",  "price": round(execute_at, 2), "size_pct": 50,
             "trigger": "-15% from 20d high · POINT_B_EXECUTE"},
            {"label": "T3 deep",  "price": round(base_floor, 2), "size_pct": 20,
             "trigger": "at breakout base · cancel if abort fires"},
        ],
        "abort_below": round(stop_abort, 2),
        "high_20d": round(high_20d, 2) if high_20d else None,
        "ma_20w": round(ma_20w, 2) if ma_20w else None,
        "current_price": round(last, 2) if last else None,
        "soros_gap_pct": pb.get("soros_gap_pct"),
        "point_b_state": pb.get("state"),
        "point_a_state": a_state,
        "summary": (
            f"Best single entry: ${round(best_single,2)}. "
            f"Best execution: ladder ${round(warning_at,2)} (30%) / "
            f"${round(execute_at,2)} (50%) / ${round(base_floor,2)} (20%)."
        ),
    }


def run() -> Dict[str, Any]:
    active = _load(ACTIVE, {})
    actions = active.get("actions") or {}
    forecasts = (_load(FORECASTS, {}).get("tickers") or {})
    radar = _load(RADAR, {})
    insider = _load(INSIDER, {})
    patents = _load(PATENT, {})
    secular = _load(SECULAR, {})
    catalysts = _load(CATALYST, {})
    point_b = _load(POINT_B, {})
    point_a = _load(POINT_A, {})
    directives = _load(DIRECTIVES, {})
    god_scores = (directives or {}).get("god_scores") or {}
    cs = _load(CORE_SAT, {"core_tickers": [], "satellite_tickers": []})
    core_set = set(cs.get("core_tickers") or [])
    sat_set = set(cs.get("satellite_tickers") or [])

    macro_score, macro_state = _macro_score(radar)
    pivot_active = macro_state in PIVOT_STATES

    cards: List[Dict[str, Any]] = []
    for tk, action in actions.items():
        eligible, reason = _is_eligible(action, pivot_active=pivot_active)
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
        risk_pen = _risk_penalty(action, pivot_active=pivot_active)

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
        entry_ladder = _entry_ladder(tk, action, point_b, point_a, fc_row)
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
            "entry_ladder": entry_ladder,
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
        "pivot_active": pivot_active,
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
