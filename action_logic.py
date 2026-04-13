"""
OLYMPUS ACTION LOGIC ENGINE
Determines correct action for each position based on:
1. GEM grade + EV signals
2. Soros Gap type (narrative vs fundamental)
3. Current price vs entry zone
4. Thesis status

PLTR CASE STUDY:
  - Soros: 59% NARRATIVE gap → thesis intact → conviction entry on dip
  - GEM 1Y EV: -29.4% at $130 → overvalued at current price
  - GEM 1Y EV at $95-109: would be approximately flat to positive
  - CONCLUSION: ARMED at $95-109 dip, NOT HOLD

ACTION STATES:
  ARMED       = limit order placed, waiting to fill (single action)
  DIP WATCH   = no order yet, watching for entry zone
  HOLD        = thesis intact, not adding, not exiting
  ADD         = actively building position at current price
  TRIM        = reducing position (thesis intact but position too large)
  EXIT REVIEW = thesis wounded, evaluating
  EXIT        = thesis dead, execute immediately
"""


def compute_action(data: dict) -> dict:
    """
    data fields used:
      current_price, entry_price, god_score,
      thesis_status, macro_status,
      soros_gap_pct, soros_type,  (narrative / fundamental)
      gem_grade, gem_1y_ev_pct, gem_5y_ev_pct,
      limit_price,          (if ARMED limit is set)
      stop_price,           (stop loss price)
      entry_zone_low, entry_zone_high,  (re-entry zone)
      position_status,      (held / watchlist / ipo)
    """
    ticker       = data.get("ticker", "")
    P0           = float(data.get("current_price", 0))
    entry        = float(data.get("entry_price", 0) or 0)
    thesis       = data.get("thesis_status", "intact")
    macro        = data.get("macro_status", "neutral")
    soros_gap    = float(data.get("soros_gap_pct", 0) or 0)
    soros_type   = data.get("soros_type", "")
    gem_grade    = data.get("gem_grade", "D")
    u1y          = float(data.get("gem_1y_ev_pct", 0) or 0)
    u5y          = float(data.get("gem_5y_ev_pct", 0) or 0)
    limit        = float(data.get("limit_price", 0) or 0)
    stop         = float(data.get("stop_price", 0) or 0)
    ez_low       = float(data.get("entry_zone_low", 0) or 0)
    ez_high      = float(data.get("entry_zone_high", 0) or 0)
    pos_status   = data.get("position_status", "held")

    # ── LAYER 0: Thesis dead → EXIT immediately ──────────────────────────────
    if thesis == "dead":
        return {
            "action": "EXIT",
            "urgency": "IMMEDIATE",
            "reason": "Thesis dead. Exit regardless of price.",
            "display": "EXIT NOW"
        }

    # ── LAYER 1: Macro broken → hold cash, no adds ──────────────────────────
    if macro == "broken":
        return {
            "action": "HOLD",
            "urgency": "CAUTION",
            "reason": "Macro broken. No new entries until macro clears.",
            "display": "HOLD · macro broken"
        }

    # ── LAYER 2: Thesis wounded → exit review ───────────────────────────────
    if thesis == "wounded":
        return {
            "action": "EXIT_REVIEW",
            "urgency": "HIGH",
            "reason": "Thesis wounded. Quantify damage before deciding.",
            "display": "EXIT REVIEW"
        }

    # From here: thesis intact ───────────────────────────────────────────────

    # ── LAYER 3: Soros narrative gap → ARMED logic ──────────────────────────
    # Narrative gap + thesis intact = maximum conviction entry on price dip
    # The question is: is current price AT the entry zone or above it?

    if soros_type == "narrative" and soros_gap >= 20:
        in_entry_zone = (ez_low > 0 and ez_high > 0 and
                         ez_low <= P0 <= ez_high)
        above_zone    = (ez_high > 0 and P0 > ez_high)
        has_limit     = limit > 0

        if has_limit and limit < P0:
            # Limit order is set below current price — genuinely ARMED
            return {
                "action": "ARMED",
                "urgency": "READY",
                "reason": f"Narrative gap {soros_gap:.0f}% intact. Limit at {limit:.0f} armed below current price.",
                "display": f"ARMED · limit {limit:.0f}",
                "entry_zone": f"{ez_low:.0f}–{ez_high:.0f}" if ez_low else None
            }
        elif in_entry_zone:
            # Price IS in the entry zone right now
            return {
                "action": "ADD",
                "urgency": "HIGH",
                "reason": f"Narrative gap {soros_gap:.0f}%. Price in entry zone {ez_low:.0f}–{ez_high:.0f}. Add now.",
                "display": f"ADD · in zone",
                "entry_zone": f"{ez_low:.0f}–{ez_high:.0f}"
            }
        elif above_zone:
            # Price is ABOVE the entry zone — watch for dip, do not chase
            return {
                "action": "DIP_WATCH",
                "urgency": "PATIENT",
                "reason": f"Narrative gap {soros_gap:.0f}%. Current ${P0:.0f} above entry zone {ez_low:.0f}–{ez_high:.0f}. Wait for dip.",
                "display": f"DIP WATCH · entry {ez_low:.0f}–{ez_high:.0f}",
                "entry_zone": f"{ez_low:.0f}–{ez_high:.0f}",
                "stop": stop if stop else None
            }
        else:
            # No entry zone defined — set a limit
            return {
                "action": "DIP_WATCH",
                "urgency": "PATIENT",
                "reason": f"Narrative gap {soros_gap:.0f}%. Set limit at dip zone.",
                "display": "DIP WATCH · set limit"
            }

    # ── LAYER 4: Fundamental gap → thesis review required ───────────────────
    if soros_type == "fundamental" and soros_gap >= 20:
        return {
            "action": "EXIT_REVIEW",
            "urgency": "HIGH",
            "reason": f"Fundamental gap {soros_gap:.0f}%. Thesis may be broken, not just narrative.",
            "display": "EXIT REVIEW · fund gap"
        }

    # ── LAYER 5: GEM grade drives action for non-Soros positions ────────────
    if gem_grade == "A":
        if pos_status == "watchlist":
            return {
                "action": "ADD",
                "urgency": "HIGH",
                "reason": f"Grade A. 1y {u1y:+.1f}%, 5y {u5y:+.1f}%. Enter now.",
                "display": "ADD · Grade A"
            }
        else:
            return {
                "action": "HOLD",
                "urgency": "NORMAL",
                "reason": f"Grade A held position. 1y {u1y:+.1f}%, 5y {u5y:+.1f}%.",
                "display": "HOLD · Grade A"
            }

    if gem_grade == "B":
        return {
            "action": "HOLD",
            "urgency": "NORMAL",
            "reason": f"Grade B. 1y {u1y:+.1f}%, 5y {u5y:+.1f}%. Thesis intact.",
            "display": "HOLD · Grade B"
        }

    if gem_grade == "C":
        return {
            "action": "HOLD",
            "urgency": "MONITOR",
            "reason": f"Grade C. 1y {u1y:+.1f}%, 5y {u5y:+.1f}%. Watch thesis.",
            "display": "HOLD · Grade C"
        }

    # Grade D — check stop
    if stop > 0 and P0 < stop:
        return {
            "action": "EXIT_REVIEW",
            "urgency": "HIGH",
            "reason": f"Grade D and price below stop {stop:.0f}. Review immediately.",
            "display": f"EXIT REVIEW · stop {stop:.0f}"
        }

    return {
        "action": "HOLD",
        "urgency": "MONITOR",
        "reason": f"Grade D. 1y {u1y:+.1f}%, 5y {u5y:+.1f}%. Hold but watch.",
        "display": "HOLD · Grade D"
    }


# ── SELF-TEST ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        {
            "label": "PLTR — narrative gap, above entry zone",
            "data": {
                "ticker": "PLTR", "current_price": 130, "entry_price": 109.32,
                "thesis_status": "intact", "macro_status": "tailwind",
                "soros_gap_pct": 59, "soros_type": "narrative",
                "gem_grade": "D", "gem_1y_ev_pct": -29.4, "gem_5y_ev_pct": -37.0,
                "limit_price": 0, "stop_price": 95,
                "entry_zone_low": 95, "entry_zone_high": 109,
                "position_status": "held"
            },
            "expected_action": "DIP_WATCH"
        },
        {
            "label": "PLTR — narrative gap, price IN entry zone at $100",
            "data": {
                "ticker": "PLTR", "current_price": 100, "entry_price": 109.32,
                "thesis_status": "intact", "macro_status": "tailwind",
                "soros_gap_pct": 59, "soros_type": "narrative",
                "gem_grade": "D", "gem_1y_ev_pct": -29.4, "gem_5y_ev_pct": -37.0,
                "limit_price": 0, "stop_price": 95,
                "entry_zone_low": 95, "entry_zone_high": 109,
                "position_status": "held"
            },
            "expected_action": "ADD"
        },
        {
            "label": "PLTR — limit order set at 95",
            "data": {
                "ticker": "PLTR", "current_price": 130, "entry_price": 109.32,
                "thesis_status": "intact", "macro_status": "tailwind",
                "soros_gap_pct": 59, "soros_type": "narrative",
                "gem_grade": "D", "gem_1y_ev_pct": -29.4, "gem_5y_ev_pct": -37.0,
                "limit_price": 95, "stop_price": 95,
                "entry_zone_low": 95, "entry_zone_high": 109,
                "position_status": "held"
            },
            "expected_action": "ARMED"
        },
        {
            "label": "UEC — narrative gap, limit armed",
            "data": {
                "ticker": "UEC", "current_price": 11.7, "entry_price": 12.19,
                "thesis_status": "intact", "macro_status": "tailwind",
                "soros_gap_pct": 38, "soros_type": "narrative",
                "gem_grade": "D", "gem_1y_ev_pct": -34.2, "gem_5y_ev_pct": -22.0,
                "limit_price": 11, "stop_price": 0,
                "entry_zone_low": 10, "entry_zone_high": 12,
                "position_status": "held"
            },
            "expected_action": "ARMED"
        },
        {
            "label": "AVAV — thesis dead",
            "data": {
                "ticker": "AVAV", "current_price": 170, "entry_price": 180,
                "thesis_status": "dead", "macro_status": "tailwind",
                "soros_gap_pct": 0, "soros_type": "",
                "gem_grade": "D", "gem_1y_ev_pct": -20, "gem_5y_ev_pct": -10,
                "position_status": "held"
            },
            "expected_action": "EXIT"
        },
        {
            "label": "VRT — Grade C, no Soros gap",
            "data": {
                "ticker": "VRT", "current_price": 65, "entry_price": 65,
                "thesis_status": "intact", "macro_status": "tailwind",
                "soros_gap_pct": 0, "soros_type": "",
                "gem_grade": "C", "gem_1y_ev_pct": 25.7, "gem_5y_ev_pct": 87.9,
                "position_status": "held"
            },
            "expected_action": "HOLD"
        },
    ]

    print("=" * 65)
    print("ACTION LOGIC ENGINE — SELF-TEST")
    print("=" * 65)
    all_pass = True
    for t in tests:
        result = compute_action(t["data"])
        ok = result["action"] == t["expected_action"]
        status = "✓ PASS" if ok else "✗ FAIL"
        if not ok:
            all_pass = False
        print(f"\n{t['label']}")
        print(f"  Expected: {t['expected_action']}")
        print(f"  Got:      {result['action']} — {result['display']}")
        print(f"  Reason:   {result['reason']}")
        print(f"  {status}")

    print(f"\n{'='*65}")
    print(f"OVERALL: {'ALL PASS' if all_pass else 'ISSUES FOUND'}")
    print(f"{'='*65}")
