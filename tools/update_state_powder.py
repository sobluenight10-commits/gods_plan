"""One-shot update of state.json dry_powder.TR_EUR + liquidity_state block.

Usage:  python3 tools/update_state_powder.py --tr-eur 1600 [--kw-usd 0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(BASE, "state.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tr-eur", type=float, required=True, help="TR cash in EUR")
    ap.add_argument("--kw-usd", type=float, default=None, help="Kiwoom cash in USD")
    ap.add_argument("--net-liq-b", type=float, default=None, help="Live net liquidity in $B (optional)")
    ap.add_argument("--vel-7d-b", type=float, default=None, help="7d velocity in $B (optional)")
    ap.add_argument("--vel-4w-b", type=float, default=None, help="4w velocity in $B (optional)")
    ap.add_argument("--zone", default=None, help="DANGER/WARNING/NORMAL/ABUNDANCE (optional)")
    ap.add_argument("--vector", default=None, help="CONTRACTING/EXPANDING/NEUTRAL (optional)")
    args = ap.parse_args()

    if not os.path.exists(STATE):
        print(f"ERROR: {STATE} not found")
        sys.exit(2)

    with open(STATE, "r", encoding="utf-8") as f:
        s = json.load(f)

    dp = s.get("dry_powder") or {}
    dp["TR_EUR"] = round(float(args.tr_eur))
    if args.kw_usd is not None:
        dp["Kiwoom_USD"] = round(float(args.kw_usd))
    dp["last_updated"] = date.today().isoformat()
    s["dry_powder"] = dp

    if any(x is not None for x in (args.net_liq_b, args.vel_7d_b, args.vel_4w_b, args.zone, args.vector)):
        liq = s.get("liquidity_state") or {}
        if args.net_liq_b is not None:
            liq["net_liq_B"] = round(float(args.net_liq_b))
        if args.vel_7d_b is not None:
            liq["velocity_7d_B"] = round(float(args.vel_7d_b))
        if args.vel_4w_b is not None:
            liq["velocity_4w_B"] = round(float(args.vel_4w_b))
        if args.zone is not None:
            liq["zone"] = args.zone.upper()
        if args.vector is not None:
            liq["vector_7d"] = args.vector.upper()
        liq["last_recalc"] = date.today().isoformat()
        liq["source"] = "live FRED via data/directives.json"
        s["liquidity_state"] = liq

    s.setdefault("meta", {})["last_updated"] = date.today().isoformat()

    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)
    print(f"updated {STATE}")
    print(f"  dry_powder: TR €{dp['TR_EUR']} · Kiwoom ${dp.get('Kiwoom_USD', 0)}")
    if "liquidity_state" in s:
        liq = s["liquidity_state"]
        print(f"  liquidity : ${liq.get('net_liq_B')}B · {liq.get('zone')} · 7d Δ {liq.get('velocity_7d_B')}B · {liq.get('vector_7d')}")


if __name__ == "__main__":
    main()
