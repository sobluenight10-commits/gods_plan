#!/usr/bin/env python3
"""fill_listener.py — 텔레그램 답장 '체결 TICKER 가격 수량 [메모]' 자동 기록 → executions.jsonl
신호 원장이 '발송된 신호'가 아니라 '실제 체결'을 채점하기 위한 입력."""
import json, os, re, urllib.request, urllib.parse, datetime

DATA = "/root/gods_plan/data"
cfg = json.load(open("/root/gods_plan/config.json"))
tok, chat = cfg["tg_token"], str(cfg["tg_chat"])
off_p = os.path.join(DATA, "tg_offset.txt")
offset = int(open(off_p).read()) if os.path.exists(off_p) else 0

url = "https://api.telegram.org/bot%s/getUpdates?offset=%d&timeout=0" % (tok, offset)
try:
    upd = json.loads(urllib.request.urlopen(url, timeout=15).read())
except Exception as e:
    print("poll fail:", e); raise SystemExit

exec_p = os.path.join(DATA, "executions.jsonl")
PAT = re.compile(r"^체결\s+(\S+)\s+([0-9.,]+)\s*([0-9.,]+)?\s*(.*)$")
n = 0
for u in upd.get("result", []):
    offset = max(offset, u["update_id"] + 1)
    msg = u.get("message") or {}
    if str(msg.get("chat", {}).get("id")) != chat: continue
    text = (msg.get("text") or "").strip()
    mv = re.match(r"^판정\s+(\S+)\s*(.*)$", text)
    if mv:
        vp = os.path.join(DATA, "verdicts.jsonl")
        rec = {"date": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M"),
               "slot": mv.group(1), "verdict": mv.group(2).strip(), "src": "telegram"}
        with open(vp, "a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            body = urllib.parse.urlencode({"chat_id": chat, "text": "판정 기록: [%s] — 일요일 채점 대상 등재" % mv.group(1)}).encode()
            urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, body, timeout=10)
        except Exception: pass
        n += 1
        continue
    mg = re.match(r"^논제갱신\s+(\S+)\s*(.*)$", text)
    if mg:
        import os as _os
        tmp = "/root/gods_plan/data/thesis_map.json"
        tm = json.load(open(tmp))
        tk2, memo2 = mg.group(1), mg.group(2).strip()
        if tk2 in tm:
            tm[tk2]["reviewed"] = datetime.date.today().isoformat()
            if memo2: tm[tk2]["review_note"] = memo2
            json.dump(tm, open(tmp, "w"), ensure_ascii=False, indent=1)
            try:
                body = urllib.parse.urlencode({"chat_id": chat, "text": "논제 갱신 완료: %s — 부패 시계 리셋" % tk2}).encode()
                urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, body, timeout=10)
            except Exception: pass
            n += 1
        continue
    m = PAT.match(text)
    if not m: continue
    tk, price, qty, memo = m.group(1), m.group(2).replace(",", ""), m.group(3), m.group(4)
    rec = {"date": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M"),
           "t": tk, "side": "FILL", "price": float(price),
           "qty": float(qty.replace(",", "")) if qty else None,
           "thesis": memo.strip() or None, "src": "telegram"}
    with open(exec_p, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    n += 1
    # 접수 확인 답장
    try:
        body = urllib.parse.urlencode({"chat_id": chat, "text": "기록 완료: %s @ %s%s — 30일 후 심문 예정" % (tk, price, (" x"+qty) if qty else "")}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % tok, body, timeout=10)
    except Exception: pass

open(off_p, "w").write(str(offset))
print("fills recorded:", n)
