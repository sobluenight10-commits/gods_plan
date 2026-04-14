from morning_brief_v2 import fetch_prices
p = fetch_prices(["RKLB","URNM","PLTR","TSM"])
print("Live prices:")
for t in ["RKLB","URNM","PLTR","TSM"]:
    print(f"  {t}: ${p.get(t)}")