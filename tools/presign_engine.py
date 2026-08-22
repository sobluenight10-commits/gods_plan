#!/usr/bin/env python3
"""presign_engine.py — 사전서명 명령 엔진 [실전 · 제시형 · 계층 필터]
계층: 1=셔블(CDNS BWXT LIN PRY.MI) 2=LEGEND(000660.KS 272210.KS) → 매수 실행 가능
      3=보유 위성 → 청산 관리 전용 (매수 알림 억제)  4=관찰 → 정보용
근거 출처 태그: [출처: SEC 8-K]=검증됨 / [추정·미검증]=자동집행 보류 / 정량화 불가=대시보드 확인
사다리: ATR(14) 배수, 단계당 하한 3% ~ 상한 15%
쿨다운: 14일 경과 또는 직전 알림가 대비 1 ATR 추가 하락 시 재발동
유효기한: 발동 후 48시간, 이후 자동 소멸"""
import json, os, datetime, urllib.request, urllib.parse

DATA = "/root/gods_plan/data"
TIER1 = {"CDNS", "BWXT", "LIN", "PRY.MI"}
TIER2 = {"000660.KS", "272210.KS"}
EXEC_TIERS = TIER1 | TIER2
BUY_WORDS = ("눌림매수", "적극 눌림", "매수 3단", "현금 30%")

def load(f, d=None):
    p = os.path.join(DATA, f)
    if os.path.exists(p):
        try: return json.load(open(p))
        except Exception: pass
    return {} if d is None else d

rules = load("presign_rules.json", [])
tdr = load("thesis_status.json").get("tickers", {})
TM = load("thesis_map.json")
scores = load("scores.json")
rows = scores.get("rows") or scores.get("scores") or []
gate = scores.get("gate", {})
god = {r.get("t") or r.get("ticker"): r.get("god") or r.get("score") for r in rows}
sgi = {r.get("t") or r.get("ticker"): (r.get("sgi") or {}).get("score") if isinstance(r.get("sgi"), dict) else r.get("sgi") for r in rows}
scls = load("shock_class.json").get("by_ticker", {})
sevents = load("shock_events.json", [])

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

def atr_data(t):
    try:
        import yfinance as yf
        h = yf.Ticker(t).history(period="3mo")
        if len(h) < 20: return None, None
        atr = float((h["High"] - h["Low"]).abs().tail(14).mean())
        return float(h["Close"].iloc[-1]), atr
    except Exception:
        return None, None

def ladder(px, atr):
    """ATR 배수 사다리, 단계당 하한 3% ~ 상한 15%"""
    out = []
    for k in (1.0, 2.0, 3.0):
        pct = min(max(k * atr / px * 100, 3.0), 15.0)
        out.append(round(px * (1 - pct / 100), 2))
    return out

def provenance(t):
    """근거 출처 태그: SEC 8-K 확인 → 검증됨 / 뉴스·키워드 기반 → 추정·미검증"""
    for e in reversed(sevents):
        if e.get("t") == t and e.get("sec_8k"):
            return "[출처: SEC 8-K]", True
    if (tdr.get(t) or {}).get("worst"):
        return "[추정·미검증]", False
    return "[정량화 불가 — 대시보드 확인 요망]", False

now = datetime.datetime.now(datetime.UTC)
tickers = set(tdr) | set(sgi) | set(scls)
fired, suppressed = [], []
for rule in rules:
    pool = tickers if rule.get("tickers") == "*" else rule.get("tickers", [])
    for t in sorted(pool):
        if not match(t, rule["if"]): continue
        is_buy = any(w in rule["then"] for w in BUY_WORDS)
        if is_buy and t not in EXEC_TIERS:
            suppressed.append({"rule": rule["name"], "ticker": t, "why": "계층 3·4 — 매수 알림 억제 (청산 관리 전용)"})
            continue
        px, atr = atr_data(t)
        lad = ladder(px, atr) if (px and atr and is_buy) else None
        prov, verified = provenance(t)
        fired.append({"rule": rule["name"], "ticker": t, "order": rule["then"],
                      "price": round(px,2) if px else None, "ladder": lad,
                      "god": god.get(t), "kill": (TM.get(t) or {}).get("kill", ""),
                      "gate": gate.get("zone"), "prov": prov, "verified": verified,
                      "auto_ok": verified or not is_buy,
                      "tdr": (tdr.get(t) or {}).get("tdr"), "sgi": sgi.get(t),
                      "reason": (tdr.get(t) or {}).get("worst") or (tdr.get(t) or {}).get("status", ""),
                      "ts": now.isoformat(), "expires": (now + datetime.timedelta(hours=48)).isoformat()})

json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "simulation_only": False,
           "fired": fired, "suppressed": suppressed, "rule_count": len(rules)},
          open(os.path.join(DATA, "presign_fired.json"), "w"), ensure_ascii=False, indent=1)

# 쿨다운: 14일 경과 또는 직전 알림가 대비 1 ATR 추가 하락 시 재발동
COOLDOWN_D = 14
prev = load("presign_sent.json", [])
fresh, new_fired = [], []
for p in prev:
    try:
        if (now - datetime.datetime.fromisoformat(p["ts"])).days < COOLDOWN_D:
            fresh.append(p)
    except Exception: pass
for f in fired:
    dup = next((p for p in fresh if p["rule"] == f["rule"] and p["ticker"] == f["ticker"]), None)
    if dup is None:
        new_fired.append(f)
    else:
        # 1 ATR 추가 하락 시 쿨다운 무시하고 재발동 (기회가 깊어지는 구간 봉쇄 방지)
        px, atr = atr_data(f["ticker"])
        prev_px = dup.get("price")
        if px and atr and prev_px and px <= prev_px - atr:
            new_fired.append(f)

if new_fired:
    lines = ["⚖ 사전서명 조건 충족 — 승인 시 아래 주문 접수 (유효 48시간)"]
    for f in new_fired:
        l = (" | 사다리 " + "/".join(str(x) for x in f["ladder"])) if f.get("ladder") else ""
        lines.append("▶ %s — %s%s" % (f["ticker"], f["order"], l))
        ev = []
        if f.get("god") is not None: ev.append("점수 %s" % f["god"])
        if f.get("reason"): ev.append("근거 %s %s" % (str(f["reason"])[:50], f["prov"]))
        if f.get("gate"): ev.append("게이트 %s" % f["gate"])
        if f.get("kill"): ev.append("킬 %s" % str(f["kill"])[:45])
        lines.append("  " + " · ".join(ev))
        if not f["auto_ok"]:
            lines.append("  ⚠ 미검증 근거 — 자동집행 보류, 확인 후 판단 요망")
    if suppressed:
        lines.append("(매수 억제 %d건: 계층 3·4 — 청산 관리 전용)" % len(suppressed))
    lines.append("거부하셔도 됩니다 — 판단은 신이시여의 몫입니다.")
    try:
        cfg = json.load(open("/root/gods_plan/config.json"))
        body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": "\n".join(lines)}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
    except Exception as e:
        print("tg fail:", e)
    fresh.extend(new_fired)
    json.dump(fresh, open(os.path.join(DATA, "presign_sent.json"), "w"), ensure_ascii=False)

print("평가 완료 · 발동 %d건 (매수억제 %d건) · 신규통보 %d건" % (len(fired), len(suppressed), len(new_fired)))
for f in fired: print(" ▶", f["rule"], "·", f["ticker"], f["prov"])
