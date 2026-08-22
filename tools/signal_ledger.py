#!/usr/bin/env python3
"""signal_ledger.py — 신호 성과 회계: 5/20거래일 경과 신호의 초과수익 vs SPY.
판정: alpha>+3% '적중', ±3% '중립', <-3% '오신호'. 신호 유형별 승률을 주간 프렙에 공급."""
import json, datetime, warnings
warnings.filterwarnings("ignore")

HIST = "/root/gods_plan/data/score_history.jsonl"
recs = [json.loads(l) for l in open(HIST)]
today = datetime.date.today()
import yfinance as yf
spy = yf.Ticker("SPY").history(period="3mo")["Close"].astype(float)

verdicts = []
for rec in recs[:-1]:
    d0 = datetime.date.fromisoformat(rec["date"])
    age = (today - d0).days
    horizon = 5 if age >= 7 else None
    if age >= 28: horizon = 20
    if not horizon: continue
    try:
        spy0 = float(spy[spy.index.date <= d0].iloc[-1]); spy1 = float(spy.iloc[-1])
        spy_ret = spy1 / spy0 - 1
    except Exception:
        continue
    for r in rec["rows"]:
        if r["action"] not in ("ACCUMULATE", "BUY ON DIP", "TRIM") or not r.get("price"):
            continue
        try:
            tk = yf.Ticker(r["t"]); h = tk.history(period="3mo")["Close"].astype(float)
            p0 = float(h[h.index.date <= d0].iloc[-1]); p1 = float(h.iloc[-1])
        except Exception:
            continue
        ret = p1 / p0 - 1; alpha = ret - spy_ret
        v = "적중" if alpha > 0.03 else "오신호" if alpha < -0.03 else "중립"
        if r["action"] == "TRIM":   # 익절 신호는 하락이 적중
            v = "적중" if alpha < -0.03 else "오신호" if alpha > 0.03 else "중립"
        verdicts.append({"signal_date": rec["date"], "t": r["t"], "action": r["action"],
                         "god": r["god"], "s26": r.get("s26"), "age_d": age,
                         "alpha_pct": round(100 * alpha, 1), "verdict": v})
out = {}
for v in verdicts:
    k = v["action"]
    out.setdefault(k, {"n": 0, "적중": 0, "오신호": 0, "중립": 0, "alpha_sum": 0})
    o = out[k]; o["n"] += 1; o[v["verdict"]] += 1; o["alpha_sum"] += v["alpha_pct"]
summary = {k: {**o, "hit_rate": round(o["적중"] / o["n"], 2) if o["n"] else None,
               "avg_alpha": round(o["alpha_sum"] / o["n"], 1) if o["n"] else None} for k, o in out.items()}
json.dump({"generated": str(today), "n_signals": len(verdicts),
           "by_action": summary, "detail": verdicts[-60:]},
          open("/root/gods_plan/data/signal_ledger.json", "w"), ensure_ascii=False, indent=1)
print("verdicts", len(verdicts), summary)
