#!/usr/bin/env python3
"""thesis_decay.py — 논제 부패 시계 (청산 엔진 · 교훈 #12)
가격 손절 아님. 시간과 논제로 자른다. 스트라이크는 증거가 있을 때만 적립.
① 진입 6개월+ (스코어 히스토리 증거) ② 카탈리스트 기한 경과 ③ 논제 미갱신 30일+ ④ 자금조달 이벤트
2개+ → 강제 재심사 상신(제시형). 데이터 부재는 스트라이크가 아니라 메모."""
import json, os, re, datetime, urllib.request, urllib.parse

DATA = "/root/gods_plan/data"
def load(f, d=None):
    p = os.path.join(DATA, f)
    if os.path.exists(p):
        try: return json.load(open(p))
        except Exception: pass
    return {} if d is None else d

now = datetime.datetime.now(datetime.UTC)
TM = load("thesis_map.json")
OVR = load("/var/www/html/data/holdings_override.json") if os.path.exists("/var/www/html/data/holdings_override.json") else {}
HELD = [k for k, v in OVR.items() if isinstance(v, dict) and v.get("held")] or list(TM.keys())

first_seen = {}
hp = os.path.join(DATA, "score_history.jsonl")
if os.path.exists(hp):
    for line in open(hp):
        try:
            d = json.loads(line)
            for r in (d.get("scores") or d.get("rows") or []):
                t = r.get("t") or r.get("ticker")
                if t and t not in first_seen: first_seen[t] = d.get("date") or d.get("ts")
        except Exception: pass

FUND = re.compile(r"증자|유상증자|전환사채|CB 발행|offering|share sale|capital raise|채권 발행|debt raise", re.I)
fund_hit = {}
fp = "/root/gods_plan/data/ranto28/full_feed_v2.jsonl"
if os.path.exists(fp):
    for line in open(fp):
        try:
            d = json.loads(line)
            t = d.get("t") or d.get("ticker")
            if not t: continue
            txt = (d.get("title") or "") + " " + (d.get("body") or d.get("summary") or "")
            if FUND.search(txt): fund_hit.setdefault(t, []).append((d.get("title") or "")[:60])
        except Exception: pass

tm_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(DATA, "thesis_map.json")), datetime.UTC)
map_age = (now - tm_mtime).days

out = {}
LEGEND = {"000660.KS", "272210.KS"}  # 승자 보호 조항 (교훈 #13)
for t in sorted(set(HELD) | set(TM.keys())):
    v = TM.get(t, {})
    if t in LEGEND:
        out[t] = {"strikes": [], "notes": ["LEGEND — 승자 보호 조항 적용: 부패 시계 면제, 킬 기준만 감시"], "n": 0,
                  "months": None, "verdict": "LEGEND 보호", "thesis": v.get("thesis", ""),
                  "kill": v.get("kill", ""), "kill_src": v.get("kill_src", "")}
        continue
    strikes, notes = [], []
    fs = first_seen.get(t)
    months = None
    if fs:
        try:
            d0 = datetime.datetime.fromisoformat(str(fs)[:10]).replace(tzinfo=datetime.UTC)
            months = round((now - d0).days / 30.4, 1)
            if months >= 6: strikes.append("진입 후 %.0f개월 경과" % months)
        except Exception: pass
        if months is None or months < 6: notes.append("진입 시계 %.1f개월 [추정]" % (months or 0))
    else:
        notes.append("진입 시점 기록 없음 [추정]")
    cat = v.get("catalyst")
    if cat:
        try:
            if datetime.datetime.fromisoformat(str(cat)[:10]).replace(tzinfo=datetime.UTC) < now:
                strikes.append("카탈리스트 기한 경과")
        except Exception: pass
    else:
        notes.append("카탈리스트 미등록")
    rev = v.get("reviewed")
    if rev:
        try:
            if (now - datetime.datetime.fromisoformat(str(rev)).replace(tzinfo=datetime.UTC)).days >= 30:
                strikes.append("논제 미갱신 30일+")
        except Exception: pass
    elif map_age >= 30:
        strikes.append("논제 지도 생성 후 무갱신 30일+")
    else:
        notes.append("논제 지도 신생 — 갱신 시계 미개시")
    if t in fund_hit: strikes.append("자금조달 이벤트: " + fund_hit[t][0])
    verdict = "강제 재심사 상신" if len(strikes) >= 2 else ("주의" if len(strikes) == 1 else "양호")
    out[t] = {"strikes": strikes, "notes": notes, "n": len(strikes), "months": months,
              "verdict": verdict, "thesis": v.get("thesis", ""),
              "kill": v.get("kill", ""), "kill_src": v.get("kill_src", "")}

alerts = {t: v for t, v in out.items() if v["n"] >= 2}
json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"),
           "rule": "부패 시계 4적립 중 2+ → 강제 재심사 상신 · 증거 없는 부재는 스트라이크 아님",
           "tickers": out}, open(os.path.join(DATA, "thesis_decay.json"), "w"), ensure_ascii=False, indent=1)

if alerts:
    lines = ["⏳ 논제 부패 시계 — 강제 재심사 상신 (%d종목)" % len(alerts)]
    for t, v in sorted(alerts.items(), key=lambda x: -x[1]["n"])[:8]:
        lines.append("▶ %s — 적립 %d/4: %s" % (t, v["n"], " · ".join(v["strikes"][:2])))
    lines.append("가격이 아니라 시간과 논제가 기준입니다. 유지·축소·청산을 결정해 주십시오.")
    try:
        cfg = json.load(open("/root/gods_plan/config.json"))
        body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": "\n".join(lines)}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
    except Exception as e:
        print("tg fail:", e)
print("부패 시계 평가:", len(out), "종목 · 상신", len(alerts), "건")
for t, v in sorted(alerts.items(), key=lambda x: -x[1]["n"])[:10]: print(" ", t, v["n"], "/4 ·", "; ".join(v["strikes"])[:70])
