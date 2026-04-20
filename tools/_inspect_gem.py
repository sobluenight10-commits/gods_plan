"""Quick peek at one ticker's GEM output (server use)."""
import json, sys, os
from pathlib import Path

gem = sys.argv[1] if len(sys.argv) > 1 else "gem_results/gem_20260420.json"
tk  = sys.argv[2] if len(sys.argv) > 2 else "UEC"

with open(gem) as f:
    d = json.load(f)
r = next((x for x in d["results"] if x["ticker"] == tk), None)
if not r:
    print(f"{tk} not found")
    sys.exit(1)

print("=== grading ===")
print(json.dumps(r.get("grading", {}), indent=2, default=str))
print("=== so_what ===")
print(json.dumps(r.get("so_what", {}), indent=2, default=str))
print("=== keys ===", list(r.keys()))
