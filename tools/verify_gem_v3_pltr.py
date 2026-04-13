#!/usr/bin/env python3
from minerva_gem import evaluate

r = evaluate(
    {
        "ticker": "PLTR",
        "current_price": 130,
        "vol_1y_pct": 65,
        "eps_1y_base": 0.55,
        "eps_1y_bear": 0.30,
        "eps_1y_bull": 0.90,
        "pe_normal": 150,
        "pe_bear": 60,
        "pe_bull": 250,
        "rev_cagr_5y_normal": 0.28,
        "rev_cagr_5y_bear": 0.12,
        "rev_cagr_5y_bull": 0.45,
        "exit_multiple_normal": 60,
        "exit_multiple_bear": 25,
        "exit_multiple_bull": 120,
        "discount_rate": 0.10,
        "macro_liquidity_regime": "neutral",
        "sentiment": "positive",
        "thesis_status": "intact",
        "macro_status": "tailwind",
    }
)
p6m = r["projections"]["6m"]["worst"]
status = "PASS v3" if p6m > 50 else "FAIL still v2"
print(f"PLTR 6M worst: {p6m} — {status}")
