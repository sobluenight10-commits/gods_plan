#!/usr/bin/env python3
"""shock_watch.py — L2 shock surveillance engine (30min, weekdays)
1d return |r|>=5% or 20d z>=2.5 -> shock_events.json + Telegram + SEC 8-K check."""
import json, os, time, urllib.request, urllib.parse, datetime
import yfinance as yf
DATA = "/root/gods_plan/data"
TM = json.load(open(os.path.join(DATA, "thesis_map.json")))
TKS = list(TM.keys())[:80]
def tg(msg):
    try:
        cfg = json.load(open("/root/gods_plan/config.json"))
        body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": msg}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
    except Exception as e:
        print("tg fail:", e)
now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M")
events_path = os.path.join(DATA, "shock_events.json")
events = json.load(open(events_path)) if os.path.exists(events_path) else []
seen = {(e["t"], e["date"]) for e in events}
hits = []
for t in TKS:
    try:
        h = yf.Ticker(t).history(period="3mo")
        if len(h) < 25: continue
        r = h["Close"].pct_change().dropna()
        last_r = float(r.iloc[-1]) * 100
        mu, sd = float(r.tail(20).mean()) * 100, float(r.tail(20).std()) * 100
        z = (last_r - mu) / sd if sd > 0 else 0
        if abs(last_r) >= 5 or abs(z) >= 2.5:
            date = str(h.index[-1].date())
            if (t, date) in seen: continue
            hits.append({"t": t, "date": date, "ret_pct": round(last_r, 2), "z": round(z, 2),
                         "price": round(float(h["Close"].iloc[-1]), 2), "ts": now})
    except Exception:
        continue
if hits:
    cp = os.path.join(DATA, "company_tickers.json")
    if not os.path.exists(cp):
        try:
            req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": "godsplan admin@example.com"})
            json.dump(json.loads(urllib.request.urlopen(req, timeout=20).read()), open(cp, "w"))
        except Exception: pass
    cmap = json.load(open(cp)) if os.path.exists(cp) else {}
    cik_of = {v["ticker"]: v["cik_str"] for v in cmap.values()} if isinstance(cmap, dict) else {}
    for e in hits:
        e["sec_8k"] = None
        t = e["t"]
        if "." in t: continue
        cik = cik_of.get(t)
        if not cik: continue
        try:
            req = urllib.request.Request("https://data.sec.gov/submissions/CIK%010d.json" % cik, headers={"User-Agent": "godsplan admin@example.com"})
            sub = json.loads(urllib.request.urlopen(req, timeout=20).read())
            rec = sub["filings"]["recent"]
            cutoff = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
            for form, dt in zip(rec["form"][:30], rec["filingDate"][:30]):
                if form.startswith("8-K") and dt >= cutoff:
                    e["sec_8k"] = form + " " + dt; break
            time.sleep(0.3)
        except Exception: pass
    events.extend(hits); events = events[-500:]
    json.dump(events, open(events_path, "w"), ensure_ascii=False, indent=1)
    lines = ["[SHOCK] price shock detected (" + now + " UTC)"]
    for e in hits:
        arrow = "UP" if e["ret_pct"] > 0 else "DOWN"
        sec = (" | SEC " + e["sec_8k"]) if e.get("sec_8k") else ""
        lines.append("%s %s %+.1f%% (z=%+.1f)%s" % (arrow, e["t"], e["ret_pct"], e["z"], sec))
    tg(chr(10).join(lines))
    print(chr(10).join(lines))
else:
    print("no shock", now)
