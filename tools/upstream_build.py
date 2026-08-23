#!/usr/bin/env python3
"""upstream_build.py — 괴리 엔진 + 상류 수집기 (GOD pipeline directive 2026-08-22)
[괴리 엔진] 종목별 상류 동인 지정 → 60일 롤링 상관 + 5일 괴리 감지.
  · 동인 ↑인데 종목 정지/하락 = 서사 갭(기회) / 동인 ↓인데 종목 ↑ = 과열 경보
  · 상관 부호 반전(60d vs 120d) = 원인-결과 파열 경보
  · 2일 연속 지속 시에만 발사 (노이즈 차단)
[상류 수집] 구리·브렌트·우라늄(URA)·금리(TLT) 일일 + TSMC 월매출 스크레이프.
관세청 10일 통계는 API 키 필요 — 캘린더에 매복 시각 등록, 키 입력 시 자동 활성."""
import json, datetime, warnings
warnings.filterwarnings("ignore")
import yfinance as yf

GROUPS = {  # 동인 → 종속 종목들
 "SMH":  ["NVDA","AVGO","TSM","AMD","000660.KS","005930.KS","CDNS","TER"],
 "URA":  ["UEC","UUUU","URNM","OKLO","BWXT"],
 "HG=F": ["FCX","PRY.MI","NTR"],
 "TLT":  ["OKLO","RKLB","TSLA","PLTR","PL","NTLA","SPCX","ARKQ","BOTZ"],
 "QQQ":  ["MSFT","GOOGL","AAPL","META","PLTR","COHR","REGN","TMO"],
 "ITA":  ["KTOS","272210.KS","009540.KS","BWXT"],
 "BZ=F": ["CWEN","NTR"],
}
NOW = datetime.datetime.now(datetime.timezone.utc)
today = datetime.date.today()

# ── 가격 수집 (동인 + 종목, 6개월 일봉)
allsyms = sorted(set(GROUPS) | {m2 for mem in GROUPS.values() for m2 in mem})
px = {}
for s in allsyms:
    try:
        h = yf.Ticker(s).history(period="6mo", interval="1d")["Close"].astype(float)
        try:
            h.index = h.index.tz_localize(None).normalize()   # 한국/미국 시차 제거 — 날짜만으로 정합
        except Exception: pass
        if len(h) > 30: px[s] = h
    except Exception: pass

def ret(s, n):
    h = px.get(s)
    if h is None or len(h) < n + 2: return None
    return float(h.iloc[-1] / h.iloc[-1 - n] - 1) * 100

import pandas as pd
def corr(a, b, win):
    ha, hb = px.get(a), px.get(b)
    if ha is None or hb is None: return None
    df = pd.concat([ha.pct_change(), hb.pct_change()], axis=1).dropna().tail(win)
    return round(float(df.corr().iloc[0, 1]), 2) if len(df) > win * 0.7 else None

def leadlag(a, b, max_lag=10):
    # cross-corr: lag k>0 이면 동인(a)이 종목(b)을 k일 선행
    ha, hb = px.get(a), px.get(b)
    if ha is None or hb is None: return None, None
    df = pd.concat([ha.pct_change().rename("d"), hb.pct_change().rename("m")], axis=1).dropna()
    if len(df) < 40: return None, None
    best_lag, best_c = 0, -2.0
    for k in range(-max_lag, max_lag + 1):
        c = df["d"].corr(df["m"].shift(-k)) if k != 0 else df["d"].corr(df["m"])
        if c is not None and c == c and c > best_c:
            best_c, best_lag = float(c), k
    return best_lag, round(best_c, 2)

def ret_lag(s, n, lag):
    h = px.get(s)
    if h is None or len(h) < n + lag + 2: return None
    return float(h.iloc[-1 - lag] / h.iloc[-1 - lag - n] - 1) * 100

# 상태 파일 (지속성 추적)
import os
STP = "/root/gods_plan/data/diverge_state.json"
state = json.load(open(STP)) if os.path.exists(STP) else {}
alerts, rows = [], []
for drv, members in GROUPS.items():
    d5 = ret(drv, 5)
    if d5 is None: continue
    for m in members:
        m5 = ret(m, 5)
        if m5 is None: continue
        gap = round(d5 - m5, 1)                    # +면 종목이 동인에 밀림(서사 갭), −면 과열
        c60, c120 = corr(drv, m, 60), corr(drv, m, 120)
        flip = c60 is not None and c120 is not None and (c60 > 0) != (c120 > 0)
        bl, bc = leadlag(drv, m)                   # 리드-랙: bl>0 이면 동인이 bl일 선행
        d5l = ret_lag(drv, 5, max(0, bl))          # 랙 정합 동인 수익률
        gap_adj = round(d5l - m5, 1) if d5l is not None else None
        lag_cls = ("무관계(노이즈)" if bc is None or bc < 0.25 else
                   "실시간" if abs(bl) <= 1 else
                   ("동인선행 %d일" % bl if bl > 0 else "종목선행 %d일" % (-bl)))
        key = f"{drv}->{m}"
        active = abs(gap) >= 4 or flip
        cnt = state.get(key, 0)
        cnt = cnt + 1 if active else 0
        state[key] = cnt
        row = {"driver": drv, "ticker": m, "d5": round(d5,1), "m5": round(m5,1),
               "gap": gap, "corr60": c60, "corr120": c120, "flip": flip, "streak": cnt,
               "best_lag": bl, "lag_corr": bc, "lag_cls": lag_cls, "gap_adj": gap_adj}
        rows.append(row)
        if cnt >= 2 and (abs(gap) >= 4 or flip):
            kind = ("상관 부호 반전" if flip else
                    ("동인↑ 종목 정체 — 서사 갭(기회 후보)" if gap > 0 else "동인↓ 종목↑ — 과열 경보"))
            alerts.append({**row, "kind": kind})
json.dump(state, open(STP, "w"))

# ── 상류 원자재 스냅샷
upstream = {}
for s, nm in [("HG=F","구리"),("BZ=F","브렌트"),("URA","우라늄(URA)"),("TLT","미 장기금리(TLT)"),("SMH","반도체(SMH)")]:
    r1, r20 = ret(s,1), ret(s,20)
    if r1 is not None:
        upstream[nm] = {"1d": round(r1,2), "20d": round(r20,2)}

# ── TSMC 월매출 스크레이프 (best-effort)
tsmc = None
try:
    import requests
    rr = requests.get("https://pr.tsmc.com/english/monthly-revenue", timeout=15,
                      headers={"User-Agent": "Mozilla/5.0"})
    if rr.status_code == 200 and "Revenue" in rr.text:
        tsmc = {"fetched": True, "bytes": len(rr.text)}
except Exception as e:
    tsmc = {"fetched": False, "err": str(e)[:80]}

out = {"generated_utc": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
       "alerts": alerts, "rows": rows, "upstream": upstream, "tsmc": tsmc,
       "note": "gap>0: 동인 대비 종목 정체(서사 갭·기회 후보) / gap<0: 과열 경보 / 2일 연속 시에만 경보"}
# ── 관세청 10일 통계 — Google News RSS 매복 (API 키 불요). 매월 1·11·21일 신선 데이터 감지
customs = []
try:
    import requests, re as _re
    import xml.etree.ElementTree as ET
    rss = requests.get("https://news.google.com/rss/search?q=%EA%B4%80%EC%84%B8%EC%B2%AD+%EC%88%98%EC%B6%9C+%EB%B0%98%EB%8F%84%EC%B2%B4&hl=ko&gl=KR&ceid=KR:ko",
                       timeout=15, headers={"User-Agent": "Mozilla/5.0"}).text
    root = ET.fromstring(rss)
    for item in root.iter("item"):
        ti = item.findtext("title") or ""
        pd_ = item.findtext("pubDate") or ""
        m = _re.findall(r"([+-]?\d+\.\d+)%", ti)
        if "수출" in ti or "반도체" in ti:
            customs.append({"title": ti[:90], "pub": pd_, "pcts": m[:4]})
    customs = customs[:6]
except Exception as e:
    customs = [{"err": str(e)[:80]}]
out["customs_rss"] = customs
json.dump(out, open("/root/gods_plan/data/divergence.json", "w"), ensure_ascii=False, indent=1)

print("rows", len(rows), "| alerts", len(alerts), "| upstream", len(upstream), "| tsmc", tsmc)
