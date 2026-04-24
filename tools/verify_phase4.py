"""Phase 4 artifact verifier — runs on the server.

Pass --webroot to point at /var/www/html; default data/.
"""
from __future__ import annotations

import argparse
import json
import os


def _load(path: str) -> dict | list | None:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001
        return {"_error": str(exc)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--webroot", default="data")
    args = ap.parse_args()

    root = args.webroot.rstrip("/")
    files = [
        "deploy_plan.json",
        "insider_flow.json",
        "secular_trends.json",
        "ipo_radar.json",
        "patent_signal.json",
        "lesson_digest.json",
        "lessons_index.json",
        "behavioral_state.json",
    ]
    print(f"=== PHASE 4 VERIFY ({root}) ===")
    all_ok = True
    for fn in files:
        p = f"{root}/{fn}"
        data = _load(p)
        if data is None:
            print(f"  MISSING  {fn}")
            all_ok = False
            continue
        if isinstance(data, dict) and data.get("_error"):
            print(f"  ERROR    {fn} :: {data['_error']}")
            all_ok = False
            continue
        size = os.path.getsize(p)
        print(f"  OK  {fn:28s} {size:>8d} B")

    print()
    dp = _load(f"{root}/deploy_plan.json") or {}
    if isinstance(dp, dict):
        print("DEPLOY PLAN")
        print(f"  status : {dp.get('status')}")
        picks = [p.get("ticker") for p in dp.get("top_picks", [])]
        print(f"  picks  : {picks}")
        print(f"  mandate: {(dp.get('mandate') or '')[:220]}")

    st = _load(f"{root}/secular_trends.json") or {}
    if isinstance(st, dict):
        summ = st.get("summary", {}) if isinstance(st.get("summary"), dict) else {}
        print("SECULAR")
        print(f"  mandate: {summ.get('mandate', 'n/a')}")
        leaders = summ.get("leaders") or []
        print(f"  leaders: {leaders[:5]}")

    ins = _load(f"{root}/insider_flow.json") or {}
    if isinstance(ins, dict):
        print("INSIDER")
        print(f"  rows   : {ins.get('rows_total', 'n/a')}")
        clu = ins.get("cluster") or []
        top = [(r.get("ticker"), round(r.get("cluster_score", 0), 2)) for r in clu[:5]]
        print(f"  top    : {top}")

    ipo = _load(f"{root}/ipo_radar.json") or {}
    if isinstance(ipo, dict):
        print("IPO RADAR")
        imm = ipo.get("imminent_30d") or []
        print(f"  30d    : {[r.get('name') for r in imm[:5]]}")

    beh = _load(f"{root}/behavioral_state.json") or {}
    if isinstance(beh, dict):
        print("BEHAVIORAL")
        print(f"  cooldowns     : {len(beh.get('cooldowns', []))}")
        print(f"  pending       : {len(beh.get('pending_restatements', []))}")
        print(f"  overrides_30d : {len(beh.get('recent_overrides', []))}")

    lr = _load(f"{root}/lesson_digest.json") or {}
    if isinstance(lr, dict):
        print("LESSONS")
        print(f"  cards: {lr.get('cards_total', 'n/a')}")
        print(f"  win/loss: {lr.get('wins', 'n/a')}/{lr.get('losses', 'n/a')}")

    print()
    print("OK" if all_ok else "MISSING FILES DETECTED")


if __name__ == "__main__":
    main()
