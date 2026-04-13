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
        "soros_gap_pct": 59,
        "soros_type": "narrative",
    }
)
p = r["projections"]
print("heston_used:", r["heston_used"])
print("PLTR 6M worst:", p["6m"]["worst"], "— expect ~$65")
print("two_layer:", r["two_layer_verdict"])
print("PASS" if r["heston_used"] and p["6m"]["worst"] > 50 else "FAIL")