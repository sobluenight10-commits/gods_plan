#!/usr/bin/env python3
"""presign_engine.py — 사전서명 명령 엔진 [실전 자동집행 모드]
presign_rules.json if-then 규칙 평가 → 충족 시 즉시 집행 통보(텔레그램+허브).
원칙: 출력은 단호하게. 행동 먼저, 근거는 허브로."""
import json, os, datetime, urllib.request, urllib.parse

DATA = "/root/gods_plan/data"
def load(f, d=None):
    p = os.path.join(DATA, f)
    if os.path.exists(p):
        try: return json.load(open(p))
        except Exception: pass
    return {} if d is None else d

rules = load("presign_rules.json", [])
if not rules:
    rules = [
        {"name": "TDR-SGI 교차 눌림매수", "if": {"tdr_gte": 2.0, "sgi_gte": 55}, "then": "눌림매수 3단 분할 리밋 무장 (1차 현재가-2%, 2차 -5%, 3차 -8%)", "tickers": "*"},
        {"name": "극심 과잉반응 일격", "if": {"tdr_gte": 3.0}, "then": "적극 눌림매수 — 전략 현금 30% 즉시 투입", "tickers": "*"},
        {"name": "논제파괴 쇼크 철수", "if": {"shock_cls": "논제파괴"}, "then": "해당 종목 신규매수 전면 중단 + 킬 기준 재심사", "tickers": "*"},
        {"name": "심각 과소반응 축소", "if": {"tdr_lt": 0.4}, "then": "비중 1/3 축소 — 피해 미반영 구간 이탈", "tickers": "*"},
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
            px = None
            try:
                import yfinance as yf
                px = round(float(yf.Ticker(t).history(period="5d")["Close"].iloc[-1]), 2)
            except Exception: pass
            ladder = [round(px*0.98,2), round(px*0.95,2), round(px*0.92,2)] if (px and "3단 분할" in rule["then"]) else None
            fired.append({"rule": rule["name"], "ticker": t, "order": rule["then"],
                          "price": px, "ladder": ladder,
                          "tdr": (tdr.get(t) or {}).get("tdr"), "sgi": sgi.get(t)})

now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M")
json.dump({"updated": now, "simulation_only": False, "fired": fired, "rule_count": len(rules)},
          open(os.path.join(DATA, "presign_fired.json"), "w"), ensure_ascii=False, indent=1)

# 자동집행 통보 — 행동 먼저, 소음 없이
if fired:
    prev = load("presign_sent.json", [])
    sent_keys = {(f["rule"], f["ticker"]) for f in prev}
    new_fired = [f for f in fired if (f["rule"], f["ticker"]) not in sent_keys]
    if new_fired:
        lines = ["[EXEC] 사전서명 명령 집행"]
        for f in new_fired:
            l = (" | 리밋 " + "/".join(str(x) for x in f["ladder"])) if f.get("ladder") else ""
            act = f["order"].split(" (")[0]
            lines.append("%s — %s%s" % (f["ticker"], act, l))
        lines.append("근거: 허브. 망설임 없이 집행하십시오.")
        try:
            cfg = json.load(open("/root/gods_plan/config.json"))
            body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": "\n".join(lines)}).encode()
            urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
        except Exception as e:
            print("tg fail:", e)
        json.dump(fired, open(os.path.join(DATA, "presign_sent.json"), "w"), ensure_ascii=False)
print("평가 완료 (%s) · 규칙 %d건 · 발동 %d건" % (now, len(rules), len(fired)))
for f in fired: print(" ▶", f["rule"], "·", f["ticker"], "·", (f["order"][:40]))
