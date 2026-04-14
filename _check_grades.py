import json, os

gem_dir = "gem_results"
files = sorted(f for f in os.listdir(gem_dir) if f.startswith("gem_") and f.endswith(".json"))
d = json.load(open(os.path.join(gem_dir, files[-1])))

grades = [r["grading"]["grade"] for r in d["results"]]

print("GRADE DISTRIBUTION:")
for g in ["S", "A+", "A", "B+", "B", "C+", "C", "D", "F"]:
    c = grades.count(g)
    if c > 0:
        print(f"  {g:3}: {c}")
print(f"  Total: {len(grades)}\n")

print(f"{'TICKER':10} {'GRADE':4} {'GEM':>6} {'1Y EV%':>8} {'5Y EV%':>8} {'WORST%':>8} {'BULL%':>8}")
print("-" * 62)
for r in sorted(d["results"], key=lambda x: -x["grading"]["gem_score"]):
    g = r["grading"]
    print(f"{r['ticker']:10} {g['grade']:4} {g['gem_score']:6.1f} {g['upside_1y_pct']:+7.1f}% {g['upside_5y_pct']:+7.1f}% {g['worst_drop_1y_pct']:+7.1f}% {g['bull_gain_1y_pct']:+7.1f}%")
