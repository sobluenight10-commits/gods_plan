#!/usr/bin/env python3
"""effective_n.py — 실질 분산도: 이름은 다섯이어도 위험은 하나일 수 있다
60일 일간수익률 상관행렬 고유값으로 실효 종목수 N_eff = (Σλ)²/Σλ².
N_eff ≤ 3 → 경보. 매주 일요일 + 수요일 실행."""
import json, os, datetime, urllib.request, urllib.parse
import numpy as np, yfinance as yf

DATA = "/root/gods_plan/data"
OVR = json.load(open("/var/www/html/data/holdings_override.json"))
HELD = [k for k, v in OVR.items() if isinstance(v, dict) and v.get("held")]

rets = {}
for t in HELD:
    try:
        h = yf.Ticker(t).history(period="4mo")
        if len(h) < 40: continue
        rets[t] = h["Close"].pct_change().dropna().tail(60)
    except Exception: pass

import pandas as pd
df = pd.DataFrame(rets)  # KR/US 거래일 불일치 허용 — 쌍별 상관
res = {"updated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M"), "n_names": len(df.columns)}
if len(df.columns) >= 3 and len(df.dropna(how="all")) >= 30:
    C = df.corr(min_periods=25).fillna(0).values
    ev = np.linalg.eigvalsh(C)
    ev = np.clip(ev, 0, None)
    n_eff = float(ev.sum()**2 / (ev**2).sum())
    # 상위 고유값 기여율 — 첫 팩터가 지배하면 하나의 위험
    top1 = float(ev.max() / ev.sum() * 100)
    res.update({"n_eff": round(n_eff, 1), "top1_factor_pct": round(top1, 1),
                "alarm": n_eff <= 3,
                "note": "N_eff = (Σλ)²/Σλ² · ≤3이면 분산 착각 경보"})
    if res["alarm"]:
        try:
            cfg = json.load(open("/root/gods_plan/config.json"))
            msg = "⚠ 분산 착각 경보 — 실효 종목수 %.1f (명목 %d종목) · 최대 팩터 %.0f%%\n이름은 %d개지만 위험은 %.0f개입니다." % (n_eff, len(df.columns), top1, len(df.columns), n_eff)
            body = urllib.parse.urlencode({"chat_id": cfg["tg_chat"], "text": msg}).encode()
            urllib.request.urlopen("https://api.telegram.org/bot"+cfg["tg_token"]+"/sendMessage", body, timeout=10)
        except Exception as e: print("tg fail:", e)
    print("N_eff =", res["n_eff"], "/", res["n_names"], "종목 · 최대 팩터", res["top1_factor_pct"], "%")
else:
    res["error"] = "데이터 부족"
    print("insufficient data")
json.dump(res, open(os.path.join(DATA, "effective_n.json"), "w"), ensure_ascii=False, indent=1)
