#!/usr/bin/env python3
"""presign_engine.py — 사전서명 명령 엔진 [실전 · 제시형]
원칙: 알림 안에 점수·근거·게이트·킬 4종 탑재. 사다리는 ATR 배수. 쿨다운 14일. 문구는 제시형."""
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
        {"name": "TDR-SGI 교차 눌림매수", "if": {"tdr_gte": 2.0, "sgi_gte": 55}, "then": "눌림매수 3단 분할 리밋", "tickers": "*"},
        {"name": "극심 과잉반응 일격", "if": {"tdr_gte": 3.0}, "then": "적극 눌림매수 — 전략 현금 30% 투입", "tickers": "*"},
        {"name": "논제파괴 쇼크 철수", "if": {"shock_cls": "논제파괴"}, "then": "신규매수 전면 중단 + 킬 기준 재심사", "tickers": "*"},
        {"name": "심각 과소반응 축소", "if": {"tdr_lt": 0.4}, "then": "비중 1/3 축소 — 피해 미반영 구간 이탈", "tickers": "*"},
    ]
    json.dump(rules, open(os.path.join(DATA, "presign_rules.json"), "w"), ensure_ascii=False, indent=1)

tdr = load("thesis_status.json").get("tickers", {})
TM = load("thesis_map.json")
scores = load("scores.json")
rows = scores.get("rows") or scores.get("scores") or []
gate = scores.get("gate", {})
god = {r.get("t") or r.get("ticker"): r.get("god") or r.get("score") for r in rows}
act = {r.get("t") or r.get("ticker"): r.get("action") for r in rows}
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

def atr_ladder(t):
    """ATR(14) 배수 사다리: 1.0× / 2.0× / 3.0× ATR 아래. 변동성 스케일링."""
    try:
        import yfinance as yf
        h = yf.Ticker(t).history(period="3mo")
        if len(h) < 20: return None, None
        tr = (h["High"] - h["Low"]).abs()
        atr = float(tr.tail(14).mean())
        px = float(h["Close"].iloc[-1])
        return round(px, 2), [round(px - k*atr, 2) for k in (1.0, 2.0, 3.0)]
    except Exception:
        return None, None

tickers = set(tdr) | set(sgi) | set(scls)
fired = []
for rule in rules:
    pool = tickers if rule.get("tickers") == "*" else rule.get("tickers", [])
    for t in sorted(pool):
        if match(t, rule["if"]):
            px, ladder = atr_ladder(t)
            fired.append({"rule": rule["name"], "ticker": t, "order": rule["then"],
                          "price": px, "ladder": ladder,
                          "god": god.get(t), "action": act.get(t),
                          "kill": (TM.get(t) or {}).get("kill", ""),
                          "gate": gate.get("zone"),
                          "tdr": (tdr.get(t) or {}).get("tdr"), "sgi": sgi.get(t),
                          "reason": (tdr.get(t) or {}).get("worst") or (tdr.get(t) or {}).get("status", "")})

now = datetime.datetime.now(datetime.UTC)
json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "simulation_only": False,
           "fired": fired, "rule_count": len(rules)},
          open(os.path.join(DATA, "presign_fired.json"), "w"), ensure_ascii=False, indent=1)

# 쿨다운 14일 — 영구 1회 아님. 조건이 더 좋아져 재발동하면 다시 알림.
COOLDOWN_D = 14
prev = load("presign_sent.json", [])
fresh = []
new_fired = []
for f_prev in prev:
    try:
        ts = datetime.datetime.fromisoformat(f_prev["ts"])
        if (now - ts).days < COOLDOWN_D: fresh.append(f_prev)
    except Exception: pass
sent_keys = {(f["rule"], f["ticker"]) for f in fresh}
for f in fired:
    if (f["rule"], f["ticker"]) not in sent_keys:
        new_fired.append(f)

if new_fired:
    lines = ["⚖ 사전서명 조건 충족 — 승인 시 아래 주문 접수"]
    for f in new_fired:
        l = (" | 사다리(ATR배수) " + "/".join(str(x) for x in f["ladder"])) if f.get("ladder") else ""
        lines.append("▶ %s — %s%s" % (f["ticker"], f["order"], l))
        ev = []
        if f.get("god") is not None: ev.append("점수 %s" % f["god"])
        if f.get("reason"): ev.append("근거 %s" % str(f["reason"])[:60])
        if f.get("gate"): ev.append("게이트 %s" % f["gate"])
        if f.get("kill"): ev.append("킬 %s" % str(f["kill"])[:50])
        lines.append("  " + " · ".join(ev))
    lines.append("거부하셔도 됩니다 — 판단은 신이시여의 몫입니다.")
    try:
        cfg = json.load(open("/root/gods_plan/config.json"))
        body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": "\n".join(lines)}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
    except Exception as e:
        print("tg fail:", e)
    for f in new_fired:
        f["ts"] = now.isoformat()
        fresh.append(f)
    json.dump(fresh, open(os.path.join(DATA, "presign_sent.json"), "w"), ensure_ascii=False)

print("평가 완료 (%s) · 규칙 %d건 · 발동 %d건 · 신규통보 %d건" % (now.strftime("%m-%d %H:%M"), len(rules), len(fired), len(new_fired)))
for f in fired: print(" ▶", f["rule"], "·", f["ticker"], "·", f["order"][:40])
