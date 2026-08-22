#!/usr/bin/env python3
"""autopsy_90d.py — 모든 체결의 90일 강제 부검 (망설임 구조화 장치)
입력: data/executions.jsonl — {"date","t","side","price","thesis","kill"} (신이시여가 체결 시 1줄 추가)
90일 경과 시 텔레그램으로 강제 되묻기: 논제 생존? 킬 기준 발동? 초과수익?"""
import json, os, datetime, warnings
warnings.filterwarnings("ignore")
P = "/root/gods_plan/data/executions.jsonl"
DONE = "/root/gods_plan/data/autopsy_done.json"
if not os.path.exists(P):
    print("no executions yet"); raise SystemExit
done = set(json.load(open(DONE))) if os.path.exists(DONE) else set()
import yfinance as yf
today = datetime.date.today()
msgs = []
for l in open(P):
    if not l.strip(): continue
    e = json.loads(l)
    key = f"{e['date']}_{e['t']}_{e['side']}"
    if key in done: continue
    age = (today - datetime.date.fromisoformat(e["date"])).days
    if age < 90: continue
    try:
        h = yf.Ticker(e["t"]).history(period="6mo")["Close"].astype(float)
        p1 = float(h.iloc[-1]); ret = (p1 / float(e["price"]) - 1) * 100
    except Exception:
        p1, ret = None, None
    msgs.append(f"🔬 <b>90일 부검</b> · {e['t']} ({e['date']} {e['side']} @ {e['price']})\n"
                f"논제: {e.get('thesis','—')}\n킬 기준: {e.get('kill','—')}\n"
                f"현재가 {p1} · 수익률 {ret:+.1f}%\n→ 논제 생존 여부와 킬 기준 발동 여부를 오늘 답할 것")
    done.add(key)
json.dump(sorted(done), open(DONE, "w"))
if msgs:
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from telegram_bot import send_telegram
    for m in msgs: send_telegram(m)
print("autopsy fired:", len(msgs))
