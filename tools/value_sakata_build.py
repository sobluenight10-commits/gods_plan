#!/usr/bin/env python3
"""value_sakata_build.py — 완전 자동화 밸류에이션 + 사카타2026 (GOD directive 2026-08-22)
1) val_auto: 5년 주간 trailing P/E 백분위 (낮을수록 저평가 → 점수↑). EPS 없으면 20W괴리 대리(표기).
2) sakata26: 사카타 핵심(위치+전환)만 계승해 현대화.
   pos  = 0.25·d5 + 0.35·d10 + 0.40·d20        (레벨: 이평선 대비 위치)
   vel  = 0.5·Δd5(2주) + 0.3·Δd10(3주) + 0.2·Δd20(4주)  (속도: 어느 방향으로 가속 중인가)
   SAKATA26 = clip(50 + 2.5·vel − 1.2·pos, 0, 100)
   → 바닥에서 상승 가속(삼천·삼병 계열) = 고득점, 고점 둔화(산봉 계열) = 저득점. 단일 숫자."""
import json, datetime, warnings
warnings.filterwarnings("ignore")
import yfinance as yf

SAK = json.load(open("/root/gods_plan/data/sakata.json"))
OVR = json.load(open("/var/www/html/data/holdings_override.json"))
syms = sorted(set(SAK.keys()) | {k for k, v in OVR.items() if isinstance(v, dict) and v.get("held")})
clip = lambda x, lo=0, hi=100: max(lo, min(hi, x))
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
        vel5 = float(s5.iloc[-1] - s5.iloc[-3]) if len(s5) > 3 else 0.0
        vel10 = float(s10.iloc[-1] - s10.iloc[-4]) if len(s10) > 4 else 0.0
        vel20 = float(s20.iloc[-1] - s20.iloc[-5]) if len(s20) > 5 else 0.0
        pos = 0.25 * d5 + 0.35 * d10 + 0.40 * d20
        vel = 0.5 * vel5 + 0.3 * vel10 + 0.2 * vel20
        sk = round(clip(50 + 2.5 * vel - 1.2 * pos), 1)
        if val_auto is None:
            val_auto = round(clip(50 - 2 * d20), 1)  # 대리치
        out[sym] = {"price": round(price, 2), "pe": round(pe_now, 1) if pe_now else None,
                    "pe_pct5y": pe_pct, "val_auto": val_auto, "val_proxy": proxy,
                    "d5": d5, "d10": d10, "d20": d20, "vel": round(vel, 2), "pos": round(pos, 2),
                    "sakata26": sk}
    except Exception as e:
        print("skip", sym, str(e)[:60])
json.dump({"generated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "formula": "SAKATA26 = clip(50 + 2.5·vel − 1.2·pos) · pos=0.25d5+0.35d10+0.40d20 · vel=0.5Δd5(2w)+0.3Δd10(3w)+0.2Δd20(4w)",
           "tickers": out}, open("/root/gods_plan/data/value_sakata.json", "w"), ensure_ascii=False, indent=1)
print("done", len(out))
