#!/usr/bin/env python3
"""kill_audit.py — 킬 기준 측정가능성 감사. 발동될 수 없는 킬 기준은 장식.
각 kill을 수집 가능한 시계열에 묶음: auto:price / auto:news / manual:quarterly / manual:annual"""
import json, re
p = "/root/gods_plan/data/thesis_map.json"
tm = json.load(open(p))
PRICE = r"주가|가격|-[0-9]+%|하락|이탈"
NEWS = r"수주|계약|인수|합병|상장|IPO|규제|승인|허가|FDA|계획 철회|취소"
MANUAL_Q = r"점유율|마진|가동률|재고|출하|ASP"
n = {"auto:price":0,"auto:news":0,"manual:quarterly":0,"manual:annual":0}
for t, v in tm.items():
    k = v.get("kill", "")
    if re.search(PRICE, k): src = "auto:price"
    elif re.search(NEWS, k): src = "auto:news"
    elif re.search(MANUAL_Q, k): src = "manual:quarterly"
    else: src = "manual:annual"
    v["kill_src"] = src
    n[src] += 1
json.dump(tm, open(p, "w"), ensure_ascii=False, indent=1)
print(n)
