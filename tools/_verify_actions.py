import json
d = json.load(open("data/directives.json"))
liq = d.get("liquidity", {})
print("DIRECTIVES liquidity:")
print("  zone     :", liq.get("zone"))
print("  direction:", liq.get("direction"))
print("  net_liq_b:", liq.get("net_liq_b"))
print("  updated  :", liq.get("last_updated"))
print()
aa = json.load(open("/var/www/html/active_actions.json"))
print("ACTIVE ACTIONS:")
print("  gate:", aa["liquidity_gate"])
for tk in ["KTOS", "OKLO", "CCJ", "UUUU", "PLTR"]:
    a = aa["actions"].get(tk, {})
    blk = " · blocked=" + ",".join(a.get("blocks", [])) if a.get("blocks") else ""
    verb = a.get("verb", "?")
    thesis = a.get("thesis", "?")
    reason = a.get("reason", "")[:60]
    print(f"  {tk:6s} -> {verb:5s}  thesis={thesis:8s}  {reason}{blk}")
