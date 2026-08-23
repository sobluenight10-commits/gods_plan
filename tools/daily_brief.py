#!/usr/bin/env python3
# daily_brief.py — GOD 자체 채널: 메르형 5블록 데일리 브리프 (2026-08-23)
# 철학: 원자료는 Minerva가 읽고 사슬화한다. GOD는 판정만 한다. 시장이 채점한다.
# 포맷(5블록): 사슬(기원→메커니즘→현재→제약→그래서지금) / 숫자 하나 / 아직 안 끝난 것 / 반증 / [GOD] 판정
import json, re, datetime, os

D="/root/gods_plan/data/"
TODAY=datetime.date.today().isoformat()
FEED=D+"ranto28/full_feed_v2.jsonl"
CFG=json.load(open("/root/gods_plan/config.json"))

def load(p,default):
    try: return json.load(open(p))
    except Exception: return default

rows=[json.loads(l) for l in open(FEED) if l.strip()]
today=datetime.date.today()
def pd_(s):
    try: return datetime.date.fromisoformat(s)
    except: return None

# ── 슬롯1: 메르 압축 + 2·3차 파급
recent=[r for r in rows if pd_(r.get("date","")) and (today-pd_(r["date"])).days<=4
        and r.get("priority") in ("P0","P1") and r.get("sector")!="OTHER"]
recent.sort(key=lambda r:(0 if r["priority"]=="P0" else 1, r.get("date","")),reverse=False)
slot1=[]
for r in recent[:2]:
    thesis=(r.get("thesis") or "").strip()
    chain=(r.get("chain") or "").strip()
    nums=re.findall(r"\d[\d,\.]*\s*(?:%|억|조|달러|원|배|GW|bp)", thesis+" "+chain)
    named=r.get("named") or []
    # 2·3차 파급: 글에 없지만 동일 토픽에서 자주 공출현하는 보유/관찰 종목
    slot1.append({
        "title":r.get("title"),"url":r.get("url"),"date":r.get("date"),"prio":r.get("priority"),
        "chain": (thesis[:220]+(" → "+chain[:160] if chain else "")),
        "num": nums[0] if nums else "정량화 불가",
        "open": (r.get("fevent") if r.get("fevent") not in (None,"NONE") else None) or r.get("ewin") or "후속 이벤트 미등록",
        "tickers": named[:5],
    })

# ── 슬롯2: 원자료 1건 (가장 가까운 고민감도 카탈리스트 = 직접 확인할 1차 사실)
cr=load(D+"catalyst_radar.json",{})
evs=[e for e in cr.get("events",[]) if isinstance(e.get("days"),(int,float)) and 0<=e["days"]<=14]
evs.sort(key=lambda e:(0 if e.get("thesis_sensitivity")=="high" else 1, e["days"]))
slot2=evs[0] if evs else None

# ── 슬롯3: 물리층 (숫자만)
dv=load(D+"divergence.json",{})
sc=load(D+"scores.json",{})
lh=load(D+"liquidity_history.json",{})
upstream=dv.get("upstream",{})
top=sorted(sc.get("scores",[]),key=lambda x:-(x.get("god") or 0))[:3]
liq=lh.get("snapshots",[{}])[-1] if lh.get("snapshots") else {}

brief={"date":TODAY,"slot1":slot1,"slot2":slot2,
       "slot3":{"upstream":upstream,"top_god":[{"t":x["t"],"god":x.get("god"),"action":x.get("action")} for x in top],
                "net_liq":liq.get("net_liq"),"liq_date":liq.get("date")},
       "slot4":{"status":"유럽×한국 이중창 — 2026-10-23 활성화 예정"}}
json.dump(brief,open(D+"daily_brief.json","w"),ensure_ascii=False,indent=1)

# ── 텔레그램 (5블록, 판정 유도)
L=[f"📜 데일리 브리프 {TODAY} — 읽기 4분, 판정 1분",""]
for i,s in enumerate(slot1,1):
    L.append(f"■ 슬롯1-{i} 메르: {s['title']}")
    L.append(f"사슬: {s['chain']}")
    L.append(f"숫자: {s['num']} | 미완: {s['open']}")
    L.append(f"반증: 이 사슬이 틀리려면 무엇이 관측되어야 하나 — GOD 판정: '판정 1-{i} 내용'")
    L.append(f"원문: {s['url']}")
    L.append("")
if slot2:
    L.append(f"■ 슬롯2 원자료: {slot2.get('title')} ({slot2.get('date')}, D-{slot2.get('days')})")
    br=slot2.get("base_rate") or {}
    if br: L.append(f"베이스레이트: n={br.get('n')} 평균 {br.get('mean_move_pct')}% 승률 {br.get('win_rate')}")
    L.append("판정: '판정 2 내용'"); L.append("")
u=brief["slot3"]["upstream"]
if u:
    L.append("■ 슬롯3 물리층: "+" | ".join(f"{k} {v.get('1d')}%/{v.get('20d')}%" for k,v in list(u.items())[:5]))
L.append(f"순유동성 ${brief['slot3'].get('net_liq')}B ({brief['slot3'].get('liq_date')})")
L.append("GOD TOP3: "+", ".join(f"{x['t']} {x['god']}" for x in brief["slot3"]["top_god"]))
L.append("")
L.append("일요일에 이번 주 판정을 채점합니다.")
msg="\n".join(L)

import urllib.request
def tg(m):
    tok=CFG["tg_token"]; chat=CFG["tg_chat"]
    for i in range(0,len(m),4000):
        data=json.dumps({"chat_id":chat,"text":m[i:i+4000],"disable_web_page_preview":True}).encode()
        urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",data=data,headers={"Content-Type":"application/json"}),timeout=20).read()
if slot1 or slot2:
    tg(msg)
print("daily_brief:",TODAY,"slot1",len(slot1),"slot2",bool(slot2))
