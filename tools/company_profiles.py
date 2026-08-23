#!/usr/bin/env python3
"""company_profiles.py — 종목 핵심 프로필 (주 1회, 일요일)
yfinance: 섹터·주요 사업·최근 5년 매출/순이익/영업현금흐름 + 현재 밸류에이션.
출력: company_profiles.json — 허브 모달의 원자료."""
import json, os, datetime
import yfinance as yf

DATA = "/root/gods_plan/data"
TM = json.load(open(os.path.join(DATA, "thesis_map.json")))
NAMES = json.load(open(os.path.join(DATA, "ticker_names.json")))
scores = json.load(open(os.path.join(DATA, "scores.json")))
rows = scores.get("rows") or scores.get("scores") or []
TKS = sorted({r.get("t") for r in rows} | set(TM.keys()))

out = {}
for t in TKS:
    try:
        tk = yf.Ticker(t)
        info = tk.info or {}
        fin = tk.financials  # annual, columns = recent years
        cf = tk.cashflow
        def series(df, key, n=5):
            try:
                row = df.loc[key].dropna()
                return {str(k.date()): (None if v != v else round(float(v)/1e9, 2)) for k, v in list(row.items())[:n]}
            except Exception:
                return {}
        rev = series(fin, "Total Revenue")
        ni = series(fin, "Net Income")
        ocf = series(cf, "Operating Cash Flow")
        out[t] = {
            "name": NAMES.get(t) or info.get("shortName") or t,
            "sector": info.get("sector"), "industry": info.get("industry"),
            "biz": (info.get("longBusinessSummary") or "")[:400],
            "mcap_b": round((info.get("marketCap") or 0)/1e9, 1),
            "pe": info.get("trailingPE"), "rev_g5y": None,
            "rev": rev, "ni": ni, "ocf": ocf,
            "currency": info.get("financialCurrency"),
            "thesis": TM.get(t, {}).get("thesis", ""), "kill": TM.get(t, {}).get("kill", ""),
        }
        yrs = sorted(rev)
        if len(yrs) >= 2 and rev[yrs[0]] and rev[yrs[-1]]:
            out[t]["rev_g5y"] = round((rev[yrs[-1]]/rev[yrs[0]])**(1/len(yrs))*100-100, 1)
    except Exception as e:
        out[t] = {"error": str(e)[:80]}
json.dump({"updated": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M"), "unit": "십억(현지통화)", "profiles": out},
          open(os.path.join(DATA, "company_profiles.json"), "w"), ensure_ascii=False, indent=1)
ok = sum(1 for v in out.values() if v.get("rev"))
print("profiles:", len(out), "· 재무 확보:", ok)
