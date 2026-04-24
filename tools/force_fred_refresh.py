"""Force-run FRED liquidity fetch, show raw FRED result + full directives.liquidity block.

Use to diagnose why the stale April-14 block survives on the server.
"""
from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

def _dump_liq(label: str, path: str) -> None:
    print(f"\n--- {label} ({path}) ---")
    if not os.path.exists(path):
        print("  MISSING")
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as exc:  # noqa: BLE001
        print(f"  parse error: {exc}")
        return
    liq = (d or {}).get("liquidity") or {}
    for k in sorted(liq.keys()):
        v = liq[k]
        print(f"  {k} = {v!r}")
    print(f"  top.last_updated = {d.get('last_updated')!r}")


def main() -> None:
    data_dir = os.path.join(BASE, "data")
    webroot = "/var/www/html"
    directives_local = os.path.join(data_dir, "directives.json")
    directives_web = os.path.join(webroot, "directives.json")

    print(f"run_ts: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"BASE  : {BASE}")
    print(f"local : {directives_local} (exists={os.path.exists(directives_local)})")
    print(f"web   : {directives_web} (exists={os.path.exists(directives_web)})")

    try:
        from battle_rhythm import fetch_fred_liquidity
    except Exception as exc:  # noqa: BLE001
        print(f"IMPORT FAIL: {exc}")
        traceback.print_exc()
        return

    print("\n[1] before FRED:")
    _dump_liq("data/directives.json", directives_local)

    print("\n[2] running fetch_fred_liquidity() ...")
    try:
        out = fetch_fred_liquidity() or {}
        keys = ["net_liq", "change", "res_b", "tga_b", "rrp_b", "direction",
                "net_liq_text", "reserves", "tga", "rrp"]
        for k in keys:
            print(f"   {k} = {out.get(k)!r}")
        missing = [k for k in ("reserves", "tga", "rrp") if out.get(k) is None]
        if missing:
            print(f"   !! FRED incomplete — missing {missing} -> writer skipped")
    except Exception as exc:  # noqa: BLE001
        print(f"   FRED FAIL: {exc}")
        traceback.print_exc()

    print("\n[3] after FRED:")
    _dump_liq("data/directives.json", directives_local)

    print("\n[4] also publishing to webroot:")
    try:
        import shutil
        if os.path.isfile(directives_local):
            shutil.copy2(directives_local, directives_web)
            print(f"   copied -> {directives_web}")
    except Exception as exc:  # noqa: BLE001
        print(f"   publish failed: {exc}")

    print("\n[5] final webroot state:")
    _dump_liq("/var/www/html/directives.json", directives_web)


if __name__ == "__main__":
    main()
