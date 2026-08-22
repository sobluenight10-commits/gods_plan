#!/usr/bin/env python3
"""presign_engine.py — 사전서명 명령 엔진 v4 [입증 부담 방식]
§08 최상위 원칙: 어떤 종목도 금지되지 않는다. 핵심에서 멀수록 증거 요구치가 가팔라진다.
계층별 문턱: 1셔블 GOD≥55(사이즈 1.0) · 2LEGEND ≥65(0.5) · 3위성 ≥75+사실게이트+스틸맨(0.25) · 4관찰 ≥85+전게이트+논제등재(0.1 스타터)
위험 예산: 신규 자본의 27.5% = 기회 예산(분기). 3·4계층 매수만 소진. 소진 시 해당 분기 차단.
알림 표기: 3σ 20일 예상최대손실 — 사후 확인이 아니라 사전 승인."""
import json, os, math, datetime, urllib.request, urllib.parse

DATA = "/root/gods_plan/data"
def load(f, d=None):
    p = f if f.startswith("/") else os.path.join(DATA, f)
    if os.path.exists(p):
        try: return json.load(open(p))
        except Exception: pass
    return {} if d is None else d

TIERS = load("tiers.json", [])
if not TIERS:
    TIERS = {"1": ["CDNS", "BWXT", "LIN", "PRY.MI"], "2": ["000660.KS", "272210.KS"]}
    json.dump(TIERS, open(os.path.join(DATA, "tiers.json"), "w"), ensure_ascii=False, indent=1)
TIER_OF = {t: int(k) for k, v in TIERS.items() for t in v}

THRESH = {1: 55, 2: 65, 3: 75, 4: 85}
SIZE = {1: 1.0, 2: 0.5, 3: 0.25, 4: 0.1}
OPP_PCT = 0.275  # 분기 신규자본 대비 기회 예산

rules = load("presign_rules.json", [])
tdr = load("thesis_status.json").get("tickers", {})
TM = load("thesis_map.json")
scores = load("scores.json")
rows = scores.get("rows") or scores.get("scores") or []
gate = scores.get("gate", {})
god = {r.get("t"): r.get("god") for r in rows}
held_set = {r.get("t") for r in rows if r.get("held")}
sgi = {r.get("t"): (r.get("sgi") or {}).get("score") if isinstance(r.get("sgi"), dict) else r.get("sgi") for r in rows}
scls = load("shock_class.json").get("by_ticker", {})
sevents = load("shock_events.json", [])
steel = load("steelman.json", [])
budget = load("risk_budget.json", [])
if not budget:
    budget = {"monthly_capital_eur": None, "opp_pct": OPP_PCT, "quarter": "%dQ%d" % (datetime.date.today().year, (datetime.date.today().month-1)//3+1), "opp_spent": 0.0}

def tier_of(t):
    if t in TIER_OF: return TIER_OF[t]
    return 3 if t in held_set else 4

def match_cond(t, cond):
    tv = (tdr.get(t) or {}).get("tdr")
    sv = sgi.get(t)
    if "tdr_gte" in cond and not (tv is not None and tv >= cond["tdr_gte"]): return False
    if "tdr_lt" in cond and not (tv is not None and tv < cond["tdr_lt"]): return False
    if "sgi_gte" in cond and not (sv is not None and sv >= cond["sgi_gte"]): return False
    if "shock_cls" in cond:
        if cond["shock_cls"] not in [x["cls"] for x in scls.get(t, [])]: return False
    return True

def atr_data(t):
    try:
        import yfinance as yf
        h = yf.Ticker(t).history(period="3mo")
        if len(h) < 20: return None, None, None
        atr = float((h["High"] - h["Low"]).abs().tail(14).mean())
        vol20 = float(h["Close"].pct_change().tail(20).std())
        return float(h["Close"].iloc[-1]), atr, vol20
    except Exception:
        return None, None, None

def ladder(px, atr):
    return [round(px * (1 - min(max(k * atr / px * 100, 3.0), 15.0) / 100), 2) for k in (1.0, 2.0, 3.0)]

def provenance(t):
    for e in reversed(sevents):
        if e.get("t") == t and e.get("sec_8k"):
            return "[출처: SEC 8-K]", True
    if (tdr.get(t) or {}).get("worst"):
        return "[추정·미검증]", False
    return "[정량화 불가]", False

BUY_WORDS = ("눌림매수", "적극 눌림", "매수 3단", "현금 30%")
now = datetime.datetime.now(datetime.UTC)
qnow = "%dQ%d" % (now.year, (now.month-1)//3+1)
if budget.get("quarter") != qnow:
    budget["quarter"], budget["opp_spent"] = qnow, 0.0

fired, blocked = [], []
for rule in rules:
    pool = set(tdr) | set(sgi) | set(scls) | set(god)
    if rule.get("tickers") != "*": pool = set(rule.get("tickers", []))
    for t in sorted(pool):
        if not match_cond(t, rule["if"]): continue
        is_buy = any(w in rule["then"] for w in BUY_WORDS)
        tr = tier_of(t)
        px, atr, vol20 = atr_data(t)
        prov, verified = provenance(t)
        g = god.get(t)
        if is_buy:
            # 입증 부담: 점수 문턱
            if g is None or g < THRESH[tr]:
                blocked.append({"ticker": t, "rule": rule["name"], "why": "GOD %s < 문턱 %d (계층%d)" % (g, THRESH[tr], tr)})
                continue
            # 3·4계층 추가 게이트
            if tr >= 3:
                if not verified:
                    blocked.append({"ticker": t, "rule": rule["name"], "why": "사실게이트 미통과 — SEC 공시 근거 필요"})
                    continue
                if t not in steel:
                    blocked.append({"ticker": t, "rule": rule["name"], "why": "스틸맨 미문서화 — 반대 논거 명시 필요"})
                    continue
                need = SIZE[tr]
                if budget["opp_spent"] + need > budget["opp_pct"]:
                    blocked.append({"ticker": t, "rule": rule["name"], "why": "기회 예산 소진 (분기 %.3f/%.3f)" % (budget["opp_spent"], budget["opp_pct"])})
                    continue
            if tr == 4 and not (TM.get(t) or {}).get("thesis"):
                blocked.append({"ticker": t, "rule": rule["name"], "why": "논제 미등재 — thesis_map 등록 필요"})
                continue
            budget["opp_spent"] += SIZE[tr] if tr >= 3 else 0.0
        lad = ladder(px, atr) if (px and atr and is_buy) else None
        maxloss = round(3 * vol20 * math.sqrt(20) * 100, 1) if vol20 else None
        fired.append({"rule": rule["name"], "ticker": t, "order": rule["then"], "tier": tr,
                      "price": round(px,2) if px else None, "ladder": lad,
                      "size_unit": SIZE[tr], "max_loss_3sigma_pct": maxloss,
                      "god": g, "kill": (TM.get(t) or {}).get("kill", ""),
                      "kill_src": (TM.get(t) or {}).get("kill_src", ""),
                      "gate": gate.get("zone"), "prov": prov, "verified": verified,
                      "auto_ok": verified or not is_buy,
                      "tdr": (tdr.get(t) or {}).get("tdr"), "sgi": sgi.get(t),
                      "reason": (tdr.get(t) or {}).get("worst") or (tdr.get(t) or {}).get("status", ""),
                      "ts": now.isoformat(), "expires": (now + datetime.timedelta(hours=48)).isoformat()})

json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "simulation_only": False,
           "fired": fired, "blocked": blocked,
           "budget": {"opp_pct": budget["opp_pct"], "opp_spent": budget["opp_spent"], "quarter": budget["quarter"]}},
          open(os.path.join(DATA, "presign_fired.json"), "w"), ensure_ascii=False, indent=1)
json.dump(budget, open(os.path.join(DATA, "risk_budget.json"), "w"), ensure_ascii=False, indent=1)

COOLDOWN_D = 14
prev = load("presign_sent.json", [])
fresh = [p for p in prev if (now - datetime.datetime.fromisoformat(p.get("ts", now.isoformat()).replace("Z",""))).days < COOLDOWN_D] if isinstance(prev, list) else []
new_fired = []
for f in fired:
    dup = next((p for p in fresh if p.get("rule") == f["rule"] and p.get("ticker") == f["ticker"]), None)
    if dup is None:
        new_fired.append(f)
    else:
        px, atr, _ = atr_data(f["ticker"])
        if px and atr and dup.get("price") and px <= dup["price"] - atr:
            new_fired.append(f)

if new_fired:
    lines = ["⚖ 사전서명 조건 충족 — 승인 시 아래 주문 접수 (유효 48시간)"]
    for f in new_fired:
        l = (" | 사다리 " + "/".join(str(x) for x in f["ladder"])) if f.get("ladder") else ""
        sz = "사이즈 %.2f단위" % f["size_unit"]
        ml = (" · 3σ최대손실 −%s%%" % f["max_loss_3sigma_pct"]) if f.get("max_loss_3sigma_pct") else ""
        lines.append("▶ %s [계층%d] — %s%s" % (f["ticker"], f["tier"], f["order"], l))
        lines.append("  %s%s" % (sz, ml))
        ev = []
        if f.get("god") is not None: ev.append("점수 %.1f" % f["god"])
        if f.get("reason"): ev.append("근거 %s %s" % (str(f["reason"])[:45], f["prov"]))
        if f.get("gate"): ev.append("게이트 %s" % f["gate"])
        if f.get("kill"): ev.append("킬 %s[%s]" % (str(f["kill"])[:40], f.get("kill_src") or "미분류"))
        lines.append("  " + " · ".join(ev))
        if not f["auto_ok"]:
            lines.append("  ⚠ 미검증 근거 — 자동집행 보류, 확인 후 판단 요망")
    if blocked:
        lines.append("(입증 부담 미충족 %d건 — 허브에서 사유 확인)" % len(blocked))
    lines.append("거부하셔도 됩니다 — 판단은 신이시여의 몫입니다.")
    try:
        cfg = json.load(open("/root/gods_plan/config.json"))
        body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": "\n".join(lines)}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
    except Exception as e:
        print("tg fail:", e)
    fresh.extend(new_fired)
    json.dump(fresh, open(os.path.join(DATA, "presign_sent.json"), "w"), ensure_ascii=False)

print("평가 완료 · 발동 %d건 · 차단 %d건 · 신규통보 %d건 · 기회예산 %.3f/%.3f" % (len(fired), len(blocked), len(new_fired), budget["opp_spent"], budget["opp_pct"]))
for f in fired: print(" ▶", f["ticker"], "[계층%d]" % f["tier"], f["rule"], "3σ", f.get("max_loss_3sigma_pct"))
for bl in blocked[:5]: print(" ✗", bl["ticker"], "—", bl["why"])
