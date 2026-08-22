#!/usr/bin/env python3
"""value_sakata_build.py — 완전 자동화 밸류에이션 + 사카타2026 (GOD directive 2026-08-22)
1) val_auto: 5년 주간 trailing P/E 백분위 (낮을수록 저평가 → 점수↑). EPS 없으면 20W괴리 대리(표기).
2) sakata26: 사카타 핵심(위치+전환)만 계승해 현대화.
   pos  = 0.25·d5 + 0.35·d10 + 0.40·d20        (레벨: 이평선 대비 위치)
   vel  = 0.5·Δd5(2주) + 0.3·Δd10(3주) + 0.2·Δd20(4주)  (속도: 어느 방향으로 가속 중인가)
   v2 (평가 4지시 반영):
   pos = 0.25·d5+0.35·d10+0.40·d20 (위치)
   vel = 0.5·Δd5(4주)+0.3·Δd10(5주)+0.2·Δd20(6주) (기세, 창 확대 — 휩쏘 방지)
   acc = vel(t) − vel(t−4주) (가속도 = 소진 포착: 깊게 빠졌는데 감속=바닥, 가속=낙하칼날)
   reldiv = d20 − 섹터중앙값(d20) (상대괴리: 동료 대비 홀로 눌림)
   raw = clip(50 + 1.8·vel + 1.2·acc + 0.9·reldiv − 1.0·pos, 0~100)
   사실계수 게이트: 7일 내 8-K/10-Q/10-K 공시 → ×0 (수동 해제 전 정지)  [TSLA 89.7 오신호 차단]
   밸류캡: 자기 5년 P/E 백분위 ≥80 → min(raw, 30)  [VRT 함정 차단]"""
import json, datetime, warnings
warnings.filterwarnings("ignore")
import yfinance as yf

SAK = json.load(open("/root/gods_plan/data/sakata.json"))
OVR = json.load(open("/var/www/html/data/holdings_override.json"))
syms = sorted(set(SAK.keys()) | {k for k, v in OVR.items() if isinstance(v, dict) and v.get("held")})
clip = lambda x, lo=0, hi=100: max(lo, min(hi, x))
import statistics as _st
SECMAP = {k: (v or {}).get("sector") for k, v in SAK.items()}
# 섹터 중앙값 d20은 1차 패스 후 계산하므로 일단 수집
_d20s = {}
import requests as _rq
def _sec_gate(sym):
    """미국 상장사: 7일 내 8-K/10-Q/10-K 있으면 사실계수 0."""
    if sym.endswith((".KS", ".MI", ".PA")) or "." in sym and not sym.isalpha():
        return None
    try:
        ct = _rq.get("https://www.sec.gov/files/company_tickers.json",
                     headers={"User-Agent": "Minerva/1.0 titan@gods-plan.io"}, timeout=15).json()
        cik = next((v["cik_str"] for v in ct.values() if v["ticker"] == sym), None)
        if not cik: return None
        sub = _rq.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
                      headers={"User-Agent": "Minerva/1.0 titan@gods-plan.io"}, timeout=15).json()
        rec = sub["filings"]["recent"]
        cutoff = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        hits = [(f, d) for f, d in zip(rec["form"], rec["filingDate"])
                if f in ("8-K", "10-Q", "10-K") and d >= cutoff]
        return {"blocked": bool(hits), "latest": hits[0] if hits else None}
    except Exception:
        return None
out = {}
for sym in syms:
    try:
        tk = yf.Ticker(sym)
        wk = tk.history(period="5y", interval="1wk")
        if wk is None or len(wk) < 60:
            continue
        close = wk["Close"].astype(float)
        try: close.index = close.index.tz_localize(None)
        except Exception: pass
        price = float(close.iloc[-1])
        # P/E 백분위
        val_auto, pe_now, pe_pct, proxy = None, None, None, True
        try:
            qa = tk.quarterly_financials
            an = tk.financials
            sh_now = None
            try: sh_now = float(tk.info.get("sharesOutstanding") or 0) or None
            except Exception: sh_now = None
            eps_pts = []  # (날짜, TTM EPS)
            for src, is_q in ((qa, True), (an, False)):
                if src is None or src.empty: continue
                row = None
                for nm in ("Diluted EPS", "Basic EPS", "Net Income"):
                    if nm in src.index: row = src.loc[nm]; break
                if row is None: continue
                if "EPS" not in str(row.name) and sh_now: row = row / sh_now
                row = row.sort_index()
                try: row.index = row.index.tz_localize(None)
                except Exception: pass
                if is_q:
                    ttm = row.rolling(4).sum().dropna()
                    eps_pts += [(d, float(v)) for d, v in ttm.items()]
                else:
                    eps_pts += [(d, float(v)) for d, v in row.items()]
            if eps_pts:
                import pandas as pd
                eps_s = pd.Series(dict(eps_pts)).sort_index()
                eps_s = eps_s[~eps_s.index.duplicated(keep="last")]
                pe_series = []
                for d, p in close.items():
                    past = eps_s[eps_s.index <= d]
                    if len(past):
                        e = float(past.iloc[-1])
                        if e > 0: pe_series.append(float(p) / e)
                if len(pe_series) > 30 and 3 < pe_series[-1] < 500:   # ADR 주식수 불일치 등 이상치 배제(TSM PE 1.0 사례)
                    pe_now = pe_series[-1]
                    pe_pct = round(100 * sum(1 for x in pe_series if x <= pe_now) / len(pe_series), 1)
                    val_auto = round(clip(100 - pe_pct), 1); proxy = False
        except Exception:
            pass
        ma = lambda n: float(close.rolling(n).mean().iloc[-1])
        d5 = round(100 * (price / ma(5) - 1), 2)
        d10 = round(100 * (price / ma(10) - 1), 2)
        d20 = round(100 * (price / ma(20) - 1), 2)
        dv = lambda n: (close / close.rolling(n).mean() - 1) * 100
        s5, s10, s20 = dv(5).dropna(), dv(10).dropna(), dv(20).dropna()
        def _vel_at(i):  # i=주 단위 과거 인덱스
            v5 = float(s5.iloc[i] - s5.iloc[i - 4]) if len(s5) > 4 - i else 0.0
            v10 = float(s10.iloc[i] - s10.iloc[i - 5]) if len(s10) > 5 - i else 0.0
            v20 = float(s20.iloc[i] - s20.iloc[i - 6]) if len(s20) > 6 - i else 0.0
            return 0.5 * v5 + 0.3 * v10 + 0.2 * v20
        vel = _vel_at(-1)
        acc = vel - _vel_at(-5) if len(s20) > 10 else 0.0   # 4주 전 대비 가속도 = 소진
        pos = 0.25 * d5 + 0.35 * d10 + 0.40 * d20
        _d20s[sym] = d20
        raw0 = 50 + 1.8 * vel + 1.2 * acc - 1.0 * pos       # reldiv는 2차 패스
        if val_auto is None:
            val_auto = round(clip(50 - 2 * d20), 1)  # 대리치
        gate = _sec_gate(sym)
        out[sym] = {"price": round(price, 2), "pe": round(pe_now, 1) if pe_now else None,
                    "pe_pct5y": pe_pct, "val_auto": val_auto, "val_proxy": proxy,
                    "d5": d5, "d10": d10, "d20": d20, "vel": round(vel, 2), "acc": round(acc, 2),
                    "pos": round(pos, 2), "raw0": raw0, "sec_gate": gate}
    except Exception as e:
        print("skip", sym, str(e)[:60])
# ── 2차 패스: 섹터 중앙값, 상대괴리, 사실게이트, 밸류캡
_sec_d = {}
for _s, _v in _d20s.items():
    _sec_d.setdefault(SECMAP.get(_s) or "기타", []).append(_v)
SECMED = {k: _st.median(v) for k, v in _sec_d.items()}
for _s, _d in out.items():
    reldiv = _d20s[_s] - SECMED.get(SECMAP.get(_s) or "기타", 0)
    import math as _m
    inner = (_d["raw0"] - 50) + 0.9 * reldiv   # raw0는 이미 50+1.8vel+1.2acc−1.0pos
    raw = 50 + 25 * _m.tanh(inner / 25)        # 포화 방지 스쿼시 — 순위 보존, 극단 클리핑 제거
    capped = False
    if _d.get("pe_pct5y") is not None and _d["pe_pct5y"] >= 80:
        raw = min(raw, 30); capped = True                 # 밸류캡 (VRT 함정 차단)
    g = _d.pop("sec_gate")
    fact_gate = 1
    gate_note = ""
    if g and g.get("blocked"):
        fact_gate = 0
        gate_note = f"7일 내 {g['latest'][0]} 공시({g['latest'][1]}) — 사실계수 0, 수동 해제 전 정지"
    _d["reldiv"] = round(reldiv, 2)
    _d["fact_gate"] = fact_gate
    _d["gate_note"] = gate_note
    _d["sakata26"] = round(raw * fact_gate, 1) if fact_gate else None
    _d.pop("raw0", None)
json.dump({"generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "formula": "SAKATA26 = 50+25·tanh((1.8·vel+1.2·acc+0.9·reldiv−1.0·pos)/25) × 사실계수(SEC공시 게이트) · 밸류캡(PE백분위≥80→≤30) · vel 창 4~6주 · acc=vel−vel(4주전) · reldiv=d20−섹터중앙값",
           "tickers": out}, open("/root/gods_plan/data/value_sakata.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out))
