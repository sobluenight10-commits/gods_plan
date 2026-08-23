#!/usr/bin/env python3
"""multiple_build.py — Q2 엔진: 7년 배수 추정기
배수 = TAM × 목표점유율 × 영업마진 × 만기PE / 현재시총
전부 [추정] 태그 — 정밀도가 아니라 순위가 목적. tam_map.json 수동 갱신."""
import json, os, datetime
import yfinance as yf

DATA = "/root/gods_plan/data"
TAM = {  # [추정] 2033 TAM($B), 목표점유율, 영업마진, 만기PE
 "OKLO":    {"tam": 150, "share": 0.05, "margin": 0.25, "pe": 30, "note": "SMR 발전"},
 "RKLB":    {"tam": 60,  "share": 0.10, "margin": 0.15, "pe": 35, "note": "발사+우주시스템"},
 "PL":      {"tam": 30,  "share": 0.08, "margin": 0.20, "pe": 30, "note": "지구관측 데이터"},
 "UEC":     {"tam": 25,  "share": 0.08, "margin": 0.40, "pe": 20, "note": "우라늄 채굴"},
 "UUUU":    {"tam": 30,  "share": 0.10, "margin": 0.35, "pe": 20, "note": "우라늄+희토류"},
 "NTLA":    {"tam": 50,  "share": 0.05, "margin": 0.30, "pe": 40, "note": "CRISPR 치료제"},
 "KTOS":    {"tam": 40,  "share": 0.05, "margin": 0.12, "pe": 30, "note": "드론·방산"},
 "BWXT":    {"tam": 60,  "share": 0.15, "margin": 0.18, "pe": 30, "note": "핵연료·해군 원자로"},
 "CCJ":     {"tam": 25,  "share": 0.18, "margin": 0.35, "pe": 22, "note": "우라늄 메이저"},
 "PLTR":    {"tam": 300, "share": 0.05, "margin": 0.35, "pe": 45, "note": "기업 AI 플랫폼"},
 "NVDA":    {"tam": 800, "share": 0.35, "margin": 0.55, "pe": 30, "note": "AI 가속기"},
 "TSM":     {"tam": 400, "share": 0.60, "margin": 0.45, "pe": 22, "note": "파운드리"},
 "AVGO":    {"tam": 200, "share": 0.20, "margin": 0.40, "pe": 25, "note": "AI ASIC+네트워킹"},
 "CDNS":    {"tam": 30,  "share": 0.30, "margin": 0.35, "pe": 40, "note": "EDA 듀오폴리"},
 "LIN":     {"tam": 200, "share": 0.25, "margin": 0.25, "pe": 25, "note": "산업가스"},
 "FCX":     {"tam": 350, "share": 0.08, "margin": 0.25, "pe": 15, "note": "구리"},
 "TSLA":    {"tam": 900, "share": 0.10, "margin": 0.15, "pe": 40, "note": "EV+로봇+에너지"},
 "000660.KS": {"tam": 250, "share": 0.35, "margin": 0.45, "pe": 15, "note": "HBM·메모리"},
 "005930.KS": {"tam": 250, "share": 0.30, "margin": 0.20, "pe": 14, "note": "메모리+파운드리"},
 "272210.KS": {"tam": 30, "share": 0.08, "margin": 0.12, "pe": 25, "note": "방산 전자"},
 "009540.KS": {"tam": 120, "share": 0.10, "margin": 0.10, "pe": 15, "note": "조선"},
}
NAMES = json.load(open(os.path.join(DATA, "ticker_names.json")))
out = {}
for t, a in TAM.items():
    try:
        info = yf.Ticker(t).info or {}
        mc = (info.get("marketCap") or 0) / 1e9
        if not mc: continue
        fut_rev = a["tam"] * a["share"]
        fut_ni = fut_rev * a["margin"]
        fut_mc = fut_ni * a["pe"]
        out[t] = {"name": NAMES.get(t, t), "mcap_b": round(mc, 1), "tam": a["tam"], "share": a["share"],
                  "fut_mcap_b": round(fut_mc, 1), "multiple": round(fut_mc / mc, 1),
                  "note": a["note"], "tag": "[추정]"}
    except Exception: pass
json.dump({"updated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M"),
           "formula": "배수 = TAM×점유율×마진×만기PE / 시총 · 전부 [추정] — 정밀도 아닌 순위가 목적",
           "multiples": out}, open(os.path.join(DATA, "multiples.json"), "w"), ensure_ascii=False, indent=1)
top = sorted(out.items(), key=lambda x: -x[1]["multiple"])[:10]
for t, v in top: print(t, v["name"], v["multiple"], "x ·", v["note"])
