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

def run():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_FILE, "r") as f:
        positions = json.load(f)

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

    grade_order = {"A": 0, "B": 1, "C": 2, "D": 3}
    results.sort(key=lambda r: (
        grade_order.get(r["grading"]["grade"], 9),
        -r["grading"]["upside_5y_pct"]
    ))

    output = {
        "run_date":     datetime.now().strftime("%Y-%m-%d"),
        "run_time":     datetime.now().strftime("%H:%M"),
        "total_positions": len(results),
        "grade_summary": {
            "A": sum(1 for r in results if r["grading"]["grade"] == "A"),
            "B": sum(1 for r in results if r["grading"]["grade"] == "B"),
            "C": sum(1 for r in results if r["grading"]["grade"] == "C"),
            "D": sum(1 for r in results if r["grading"]["grade"] == "D"),
        },
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
