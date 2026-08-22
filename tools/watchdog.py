#!/usr/bin/env python3
"""watchdog.py — 망자의 스위치. 침묵이 고장 신호일 때 울리는 유일한 알림 (교훈 #04)
2시간마다 크론. 핵심 산출물의 최종 갱신이 허용 시간을 넘기면 경보."""
import json, os, time, urllib.request, urllib.parse

DATA = "/root/gods_plan/data"
WATCH = [("scores.json", 26), ("thesis_status.json", 26), ("presign_fired.json", 26),
         ("divergence.json", 26), ("shock_events.json", 48)]
stale = []
now = time.time()
for f, maxh in WATCH:
    p = os.path.join(DATA, f)
    if not os.path.exists(p):
        stale.append((f, "파일 없음")); continue
    age_h = (now - os.path.getmtime(p)) / 3600
    if age_h > maxh:
        stale.append((f, "%.0f시간 경과" % age_h))

open(os.path.join(DATA, "watchdog_last.txt"), "w").write(str(now))
state_p = os.path.join(DATA, "watchdog_state.json")
state = json.load(open(state_p)) if os.path.exists(state_p) else {}
alerted = state.get("alerted", False)

def tg(msg):
    try:
        cfg = json.load(open("/root/gods_plan/config.json"))
        body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": msg}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
    except Exception as e:
        print("tg fail:", e)

if stale and not alerted:
    tg("⚠️ 시스템 무응답 — 침묵이 고장 신호입니다 (교훈 #04)\n" + "\n".join("· %s: %s" % s for s in stale) + "\nMinerva 점검 요망.")
    state["alerted"] = True
    print("ALERT:", stale)
elif not stale and alerted:
    tg("✅ 시스템 복구 확인 — 감시 재개.")
    state["alerted"] = False
    print("recovered")
else:
    print("ok" if not stale else "still stale (alerted)", stale if stale else "")
json.dump(state, open(state_p, "w"))
