"""Verify each top strike card has an entry_ladder."""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = json.load(open(os.path.join(BASE, "data", "strike_cards.json")))

print("=== TOP 8 SHORTLIST — entry_ladder check ===")
for c in d.get("shortlist", [])[:8]:
    tk = c.get("ticker")
    sc = c.get("strike_score")
    el = c.get("entry_ladder")
    if not el:
        print(f"  {tk:10s} score={sc:>5}  [NO LADDER — Point B data missing]")
        continue
    tiers = el.get("tiers", [])
    parts = " / ".join([f"${t['price']} ({t['size_pct']}%)" for t in tiers])
    print(f"  {tk:10s} score={sc:>5}  best=${el['best_single']:>7.2f}  "
          f"ladder={parts}  abort<${el['abort_below']}")
print()
print("=== full ladder for CCJ ===")
ccj = next((c for c in d.get("cards", []) if c.get("ticker") == "CCJ"), None)
if ccj:
    print(json.dumps(ccj.get("entry_ladder"), indent=2))
else:
    print("CCJ not in cards")
