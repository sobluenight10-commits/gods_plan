#!/usr/bin/env bash
set -euo pipefail
cd /root/gods_plan
python3 <<'PY'
from battle_rhythm import fetch_fred_liquidity
import json
import shutil

fetch_fred_liquidity()
with open("data/directives.json", encoding="utf-8") as f:
    d = json.load(f)
liq = d.get("liquidity", {})
print("NET:", liq.get("net_liq_value"), "B")
print("ZONE:", liq.get("zone"))
print("HIST:", liq.get("hist_parallel"))
print("S1:", liq.get("net_liq_text"))
print("S2:", liq.get("outlook_text"))
print("S3:", liq.get("action_text"))
shutil.copy("data/directives.json", "/var/www/html/data/directives.json")
print("Dashboard updated")
PY
echo DEPLOYED
