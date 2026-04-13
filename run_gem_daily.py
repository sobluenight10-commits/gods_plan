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

def run():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_FILE, "r") as f:
        positions = json.load(f)

    results = []
    grade_changes = []

    # Load previous day result if exists for change detection
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

    # Sort by grade A→D then by 5y upside desc
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
