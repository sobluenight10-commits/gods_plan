#!/usr/bin/env python3
# verdict_score.py — 일요일 판정 채점: 지난주 [GOD] 판정을 시장 결과와 대조
# "직관은 읽기가 아니라 예측에서 자란다. 채점당하는 것이 훈련이다."
import json, datetime, os, re, urllib.request, urllib.parse
D="/root/gods_plan/data/"
CFG=json.load(open("/root/gods_plan/config.json"))
VP=D+"verdicts.jsonl"
if not os.path.exists(VP): print("no verdicts"); raise SystemExit
today=datetime.date.today()
week_ago=today-datetime.timedelta(days=7)
rows=[]
for l in open(VP):
    try: r=json.loads(l)
    except: continue
    d=datetime.datetime.strptime(r["date"],"%Y-%m-%d %H:%M").date()
    if week_ago<=d<=today: rows.append(r)
if not rows:
    print("no verdicts this week"); raise SystemExit

import yfinance as yf
TK=re.findall(r"([0-9]{6}\.K[SQ]|[A-Z][A-Z0-9\.\-]{0,6})", " ".join(r["verdict"] for r in rows))
NAMES=json.load(open(D+"ticker_names.json")) if os.path.exists(D+"ticker_names.json") else {}
# 역방향 한글명→티커
KO={v:k for k,v in NAMES.items()}
lines=[f"📝 주간 판정 채점 ({week_ago} ~ {today}) — {len(rows)}건",""]
scored=0
for r in rows:
    v=r["verdict"]
    tk=None
    for name,t in KO.items():
        if name in v: tk=t; break
    if not tk:
        m=re.search(r"\b([A-Z]{1,5}|[0-9]{6}\.K[SQ])\b", v)
        if m: tk=m.group(1)
    direction=None
    if re.search(r"오른|상승|강세|매수|돌파", v): direction=1
    elif re.search(r"내리|하락|약세|매도|붕괴|조정", v): direction=-1
    line=f"[{r['slot']}] {v[:60]}"
    if tk and direction:
        try:
            h=yf.Ticker(tk).history(period="10d")["Close"]
            if len(h)>=3:
                r5=float(h.iloc[-1]/h.iloc[0]-1)*100
                hit = (r5*direction)>0
                scored+=1
                line+=f" → {tk} 주간 {r5:+.1f}% {'✅적중' if hit else '❌빗나감'}"
        except Exception: pass
    lines.append(line)
lines.append("")
lines.append(f"자동채점 {scored}건 / 총 {len(rows)}건 — 나머지는 GOD가 자기채점하십시오.")
msg="\n".join(lines)
data=urllib.parse.urlencode({"chat_id":CFG["tg_chat"],"text":msg[:3900]}).encode()
urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage"%CFG["tg_token"],data,timeout=20).read()
print("verdicts scored:",len(rows))
