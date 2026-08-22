#!/usr/bin/env python3
"""presign_engine.py — 사전서명 명령 엔진
presign_rules.json 의 if-then 규칙을 매일 평가. 조건 충족 시 허브+텔레그램으로 '사전서명 명령 집행' 통보.
규칙 예: {"if": {"tdr_gte": 2.0, "sgi_gte": 55}, "then": "눌림매수 리밋 무장 — 3단 분할", "tickers": "*"}"""
import json, os, datetime

DATA = "/root/gods_plan/data"
def load(f, d=None):
    p = os.path.join(DATA, f)
    if os.path.exists(p):
        try: return json.load(open(p))
        except Exception: pass
    return {} if d is None else d

rules = load("presign_rules.json", [])
if not rules:
    # 기본 규칙 세트 (신이시여 승인 전까지 시뮬레이션 전용 플래그)
    rules = [
        {"name": "TDR-SGI 교차 눌림매수", "if": {"tdr_gte": 2.0, "sgi_gte": 55}, "then": "눌림매수 3단 분할 리밋 무장 (1차 현재가-2%, 2차 -5%, 3차 -8%)", "tickers": "*"},
        {"name": "극심 과잉반응 일격", "if": {"tdr_gte": 3.0}, "then": "적극 눌림매수 — 전략 현금 30% 즉시 투입 검토", "tickers": "*"},
        {"name": "논제파괴 쇼크 철수", "if": {"shock_cls": "논제파괴"}, "then": "해당 종목 신규매수 전면 중단 + 킬 기준 재심사", "tickers": "*"},
        {"name": "심각 과소반응 축소", "if": {"tdr_lt": 0.4}, "then": "비중 1/3 축소 검토 — 시장이 피해를 아직 가격에 반영하지 않음", "tickers": "*"},
    ]
    json.dump(rules, open(os.path.join(DATA, "presign_rules.json"), "w"), ensure_ascii=False, indent=1)

tdr = load("thesis_status.json").get("tickers", {})
scores = load("scores.json")
rows = scores.get("rows") or scores.get("scores") or []
sgi = {r.get("t") or r.get("ticker"): (r.get("sgi") or {}).get("score") if isinstance(r.get("sgi"), dict) else r.get("sgi") for r in rows}
scls = load("shock_class.json").get("by_ticker", {})

def match(t, cond):
    tv = (tdr.get(t) or {}).get("tdr")
    sv = sgi.get(t)
    if "tdr_gte" in cond and not (tv is not None and tv >= cond["tdr_gte"]): return False
    if "tdr_lt" in cond and not (tv is not None and tv < cond["tdr_lt"]): return False
    if "sgi_gte" in cond and not (sv is not None and sv >= cond["sgi_gte"]): return False
    if "shock_cls" in cond:
        cats = [x["cls"] for x in scls.get(t, [])]
        if cond["shock_cls"] not in cats: return False
    return True

tickers = set(tdr) | set(sgi) | set(scls)
fired = []
for rule in rules:
    pool = tickers if rule.get("tickers") == "*" else rule.get("tickers", [])
    for t in sorted(pool):
        if match(t, rule["if"]):
            fired.append({"rule": rule["name"], "ticker": t, "order": rule["then"],
                          "tdr": (tdr.get(t) or {}).get("tdr"), "sgi": sgi.get(t)})

now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
json.dump({"updated": now, "simulation_only": True, "fired": fired, "rule_count": len(rules)},
          open(os.path.join(DATA, "presign_fired.json"), "w"), ensure_ascii=False, indent=1)
print(f"사전서명 평가 완료 ({now}) · 규칙 {len(rules)}건 · 발동 {len(fired)}건")
for f in fired: print(" ▶", f["rule"], "·", f["ticker"], "·", f["order"][:40])
