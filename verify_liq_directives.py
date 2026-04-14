import json
with open("data/directives.json", encoding="utf-8") as f:
    d = json.load(f)
liq = d.get("liquidity", {})
print("Net Liq in directives.json:", liq.get("net_liq_b", "MISSING"), "B")
print("Zone:", liq.get("zone", "MISSING"))
print("Last updated:", liq.get("last_updated", "MISSING"))
print("PASS" if liq.get("net_liq_b") else "FAIL")
