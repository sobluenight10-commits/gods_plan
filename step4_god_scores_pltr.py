import json
from pathlib import Path

path = Path("data/god_scores.json")
if path.exists():
    with path.open("r", encoding="utf-8") as f:
        scores = json.load(f)
    if not isinstance(scores, list):
        scores = []
else:
    path.parent.mkdir(parents=True, exist_ok=True)
    scores = []

found = False
for stock in scores:
    if stock.get("ticker") == "PLTR":
        found = True
        old_action = stock.get("action", "")
        stock["action"] = "DIP_WATCH"
        stock["action_display"] = "DIP WATCH · entry $95–109"
        stock["action_reason"] = "Narrative gap 59% intact. $130 above entry zone. Wait for dip to $95–109."
        stock["entry_zone_low"] = 95
        stock["entry_zone_high"] = 109
        stock["soros_gap_pct"] = 59
        stock["soros_type"] = "narrative"
        print(f"PLTR: {old_action} → DIP_WATCH")
        break

if not found:
    scores.append(
        {
            "ticker": "PLTR",
            "action": "DIP_WATCH",
            "action_display": "DIP WATCH · entry $95–109",
            "action_reason": "Narrative gap 59% intact. $130 above entry zone. Wait for dip to $95–109.",
            "entry_zone_low": 95,
            "entry_zone_high": 109,
            "soros_gap_pct": 59,
            "soros_type": "narrative",
        }
    )
    print("PLTR: (new row) → DIP_WATCH")

with path.open("w", encoding="utf-8") as f:
    json.dump(scores, f, indent=2)
print("god_scores.json updated")