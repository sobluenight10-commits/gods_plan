"""Diagnose why the dashboard liquidity card shows stale data.

Reads /var/www/html/directives.json + data/liquidity_state.json +
data/fred_cache.json and prints the chain so we can see where the
staleness originates.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone


CANDIDATES = [
    "/var/www/html/directives.json",
    "data/directives.json",
    "/var/www/html/liquidity_state.json",
    "data/liquidity_state.json",
    "/var/www/html/fred_cache.json",
    "data/fred_cache.json",
]


def _load(path: str):
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def main() -> None:
    now = datetime.now(timezone.utc)
    for p in CANDIDATES:
        data = _load(p)
        if data is None:
            print(f"  MISSING  {p}")
            continue
        if isinstance(data, dict) and data.get("_error"):
            print(f"  ERROR    {p} :: {data['_error']}")
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc)
        age_h = (now - mtime).total_seconds() / 3600
        size = os.path.getsize(p)
        print(f"  {p}  ({size} B, age {age_h:.1f} h)")

        if p.endswith("directives.json"):
            liq = (data or {}).get("liquidity") or {}
            keys = [
                "net_liq_value", "net_liq_b", "net_liq_text",
                "zone", "last_updated", "change_text",
                "velocity_7d_b", "velocity_4w_b",
                "expectation_low_b", "expectation_high_b", "expectation_mid_b",
                "surprise_score", "macro_liquidity_regime",
            ]
            for k in keys:
                print(f"      liquidity.{k} = {liq.get(k)!r}")
            print(f"      top-level as_of = {data.get('as_of')!r}")
            print(f"      top-level generated_utc = {data.get('generated_utc')!r}")
        elif p.endswith("liquidity_state.json"):
            for k in ("as_of", "net_liq_b", "net_liq_value", "last_updated",
                      "velocity_7d_b", "velocity_4w_b", "zone"):
                print(f"      {k} = {data.get(k)!r}")
        elif p.endswith("fred_cache.json"):
            # pull last RESPPANWW, WTREGEN, RRPONTSYD observation dates
            try:
                for series, v in (data.items() if isinstance(data, dict) else []):
                    if isinstance(v, list) and v:
                        last = v[-1]
                        print(f"      {series} last: {last}")
                    elif isinstance(v, dict):
                        obs = v.get("observations") or v.get("data") or []
                        if obs:
                            print(f"      {series} last: {obs[-1]}")
            except Exception as exc:  # noqa: BLE001
                print(f"      (fred_cache parse issue: {exc})")

    sys.exit(0)


if __name__ == "__main__":
    main()
