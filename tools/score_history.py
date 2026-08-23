#!/usr/bin/env python3
"""score_history.py — 매일 점수 스냅샷 축적 (신호 성과 회계의 원천 데이터)"""
import json, datetime
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
sc = json.load(open("/root/gods_plan/data/scores.json"))
vs = json.load(open("/root/gods_plan/data/value_sakata.json")).get("tickers", {})
rec = {"date": now, "zone": sc["gate"]["zone"],
       "rows": [{"t": r["t"], "god": r["god"], "action": r["action"],
                 "s26": r.get("sakata27"), "sent": r.get("sent"),
                 "price": (vs.get(r["t"]) or {}).get("price")} for r in sc["scores"]]}
path = "/root/gods_plan/data/score_history.jsonl"
lines = open(path).read().strip().split("\n") if __import__("os").path.exists(path) else []
lines = [l for l in lines if json.loads(l)["date"] != now]
lines.append(json.dumps(rec, ensure_ascii=False))
open(path, "w").write("\n".join(lines) + "\n")
print("snapshot", now, len(rec["rows"]))
