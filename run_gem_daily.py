"""
run_gem_daily.py — MINERVA_GEM Daily Runner
Runs every weekday on the Minerva server.
Processes all positions in gem_inputs/portfolio_all.json
Outputs: gem_results/gem_YYYYMMDD.json
"""

import json
import sys
import os
from datetime import datetime
from minerva_gem import evaluate

INPUT_FILE  = os.path.join(os.path.dirname(__file__), "gem_inputs", "portfolio_all.json")
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "gem_results")
RISK_DIR    = os.path.join(os.path.dirname(__file__), "data", "skill_results")

TIER_LABELS = {1: "I", 2: "II", 3: "III"}


def assign_precision_tiers(results):
    """Within each letter grade, rank stocks into Tier I/II/III using
    a 35% 1Y-EV + 65% 5Y-EV composite.  Buckets with < 3 stocks get Tier I."""

    from collections import defaultdict
    buckets = defaultdict(list)
    for r in results:
        buckets[r["grading"]["grade"]].append(r)

    for grade, group in buckets.items():
        if len(group) < 3:
            for r in group:
                r["grading"]["precision_tier"] = 1
                r["grading"]["precision_grade"] = f"{grade}.I"
                r["grading"]["precision_composite"] = None
            continue

        vals_1y = [r["grading"].get("upside_1y_pct", 0) or 0 for r in group]
        vals_5y = [r["grading"].get("upside_5y_pct", 0) or 0 for r in group]

        min1, max1 = min(vals_1y), max(vals_1y)
        min5, max5 = min(vals_5y), max(vals_5y)
        span1 = max1 - min1 if max1 != min1 else 1
        span5 = max5 - min5 if max5 != min5 else 1

        for r in group:
            u1 = r["grading"].get("upside_1y_pct", 0) or 0
            u5 = r["grading"].get("upside_5y_pct", 0) or 0
            norm1 = (u1 - min1) / span1
            norm5 = (u5 - min5) / span5
            r["_pc"] = 0.35 * norm1 + 0.65 * norm5

        group.sort(key=lambda r: -r["_pc"])
        n = len(group)
        cut1 = n // 3
        cut2 = 2 * n // 3

        for i, r in enumerate(group):
            if i < cut1:
                tier = 1
            elif i < cut2:
                tier = 2
            else:
                tier = 3
            r["grading"]["precision_tier"] = tier
            r["grading"]["precision_grade"] = f"{grade}.{TIER_LABELS[tier]}"
            r["grading"]["precision_composite"] = round(r.pop("_pc"), 3)

def fetch_live_prices(tickers):
    """Fetch FRESH prices from yfinance. Returns {ticker: price} dict."""
    prices = {}
    try:
        import yfinance as yf
        print(f"[GEM] Fetching live prices for {len(tickers)} tickers...")
        for t in tickers:
            try:
                h = yf.Ticker(t).history(period="5d")
                if not h.empty:
                    live = round(float(h["Close"].iloc[-1]), 4)
                    if live > 0:
                        prices[t] = live
            except Exception as e:
                print(f"  [WARN] {t}: yfinance failed: {e}")
        print(f"[GEM] Got live prices for {len(prices)}/{len(tickers)} tickers")
    except ImportError:
        print("[GEM] WARNING: yfinance not installed")
    return prices

def _load_risk_scores():
    """Load latest risk screener results. Returns {ticker: {avg_risk, risk_level, critical_risks}}."""
    risk_map = {}
    try:
        candidates = sorted(
            [f for f in os.listdir(RISK_DIR) if f.startswith("risk_") and f.endswith(".json")],
            reverse=True
        )
        if not candidates:
            print("[GEM] No risk screener results found — running without risk integration")
            return risk_map
        path = os.path.join(RISK_DIR, candidates[0])
        with open(path) as f:
            data = json.load(f)
        for tk, rd in data.get("results", {}).items():
            risk_map[tk] = {
                "avg_risk": rd.get("avg_risk", 5.0),
                "risk_level": rd.get("risk_level", "UNKNOWN"),
                "critical_risks": rd.get("critical_risks", []),
            }
        print(f"[GEM] Loaded risk scores from {candidates[0]} ({len(risk_map)} tickers)")
    except Exception as e:
        print(f"[GEM] Risk score load failed: {e}")
    return risk_map


def run():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_FILE, "r") as f:
        positions = json.load(f)

    # RISK INTEGRATION — load latest risk screener scores
    risk_map = _load_risk_scores()
    for p in positions:
        tk = p["ticker"]
        if tk in risk_map:
            p["_risk_avg"] = risk_map[tk]["avg_risk"]
            p["_risk_level"] = risk_map[tk]["risk_level"]

    # LIVE PRICE OVERRIDE — always use freshest yfinance prices
    all_tickers = [p["ticker"] for p in positions]
    live_prices = fetch_live_prices(all_tickers)

    updated = 0
    for p in positions:
        t = p["ticker"]
        if t in live_prices:
            old = p.get("current_price", 0)
            new = live_prices[t]
            p["current_price"] = new
            if abs(new - old) / max(old, 1) > 0.03:
                print(f"  [PRICE] {t}: {old} -> {new} ({(new-old)/max(old,1)*100:+.1f}%)")
                updated += 1

    if updated:
        print(f"[GEM] {updated} prices significantly changed")
    else:
        print("[GEM] All prices current (or yfinance unavailable)")

    # AUTO-CALIBRATE PE multiples to live prices
    # Formula: pe_normal = live_price * 1.05 / eps_base (Normal ≈ market is roughly fair)
    # This prevents the "Grade D epidemic" where stale pe × eps << live price
    calibrated = 0
    for p in positions:
        t = p["ticker"]
        live = p.get("current_price", 0)
        eps = p.get("eps_1y_base", 0)
        if live > 0 and eps > 0:
            ideal_pe = round(live * 1.05 / eps, 1)
            old_pe = p.get("pe_normal", 0)
            if old_pe > 0 and abs(ideal_pe - old_pe) / old_pe > 0.15:
                ratio = ideal_pe / old_pe
                p["pe_normal"] = round(ideal_pe)
                p["pe_bear"] = max(1, round(p.get("pe_bear", old_pe * 0.5) * ratio))
                p["pe_bull"] = round(p.get("pe_bull", old_pe * 1.5) * ratio)
                print(f"  [PE-CAL] {t}: pe_normal {old_pe} -> {round(ideal_pe)} (ratio {ratio:.2f})")
                calibrated += 1
    if calibrated:
        print(f"[GEM] Auto-calibrated PE for {calibrated} tickers")

    results = []
    grade_changes = []

    prev_grades = {}
    prev_files = sorted([f for f in os.listdir(OUTPUT_DIR) if f.startswith("gem_") and f.endswith(".json")])
    if prev_files:
        try:
            with open(os.path.join(OUTPUT_DIR, prev_files[-1])) as pf:
                prev_data = json.load(pf)
                for r in prev_data.get("results", []):
                    prev_grades[r["ticker"]] = r["grading"]["grade"]
        except Exception:
            pass

    for pos in positions:
        result = evaluate(pos)
        new_grade = result["grading"]["grade"]
        old_grade = prev_grades.get(pos["ticker"])
        if old_grade and old_grade != new_grade:
            grade_changes.append({
                "ticker": pos["ticker"],
                "from": old_grade,
                "to": new_grade,
                "reason": result["grading"]["reason"]
            })
        results.append(result)

    grade_order = {"S":0,"A+":1,"A":2,"B+":3,"B":4,"C+":5,"C":6,"D":7,"F":8}

    assign_precision_tiers(results)

    results.sort(key=lambda r: (
        grade_order.get(r["grading"]["grade"], 9),
        r["grading"].get("precision_tier", 1),
        -r["grading"]["upside_5y_pct"]
    ))

    all_grades = [r["grading"]["grade"] for r in results]
    grade_summary = {}
    for g in ["S","A+","A","B+","B","C+","C","D","F"]:
        c = all_grades.count(g)
        if c > 0:
            grade_summary[g] = c

    output = {
        "run_date":     datetime.now().strftime("%Y-%m-%d"),
        "run_time":     datetime.now().strftime("%H:%M"),
        "total_positions": len(results),
        "grade_summary": grade_summary,
        "grade_changes": grade_changes,
        "alerts": [r for r in results if r["grading"].get("god_score_warning")],
        "results": results
    }

    date_str = datetime.now().strftime("%Y%m%d")
    out_path = os.path.join(OUTPUT_DIR, f"gem_{date_str}.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output, indent=2))
    return output

if __name__ == "__main__":
    run()
