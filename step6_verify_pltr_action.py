from action_logic import compute_action

result = compute_action(
    {
        "ticker": "PLTR",
        "current_price": 130,
        "entry_price": 109.32,
        "thesis_status": "intact",
        "macro_status": "tailwind",
        "soros_gap_pct": 59,
        "soros_type": "narrative",
        "gem_grade": "D",
        "gem_1y_ev_pct": -29.4,
        "gem_5y_ev_pct": -37.0,
        "limit_price": 0,
        "stop_price": 95,
        "entry_zone_low": 95,
        "entry_zone_high": 109,
        "position_status": "held",
    }
)
print("PLTR action:", result["action"])
print("Display:", result["display"])
print("PASS" if result["action"] == "DIP_WATCH" else "FAIL")