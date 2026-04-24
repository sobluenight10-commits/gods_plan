"""Write gem_meta.json from latest gem_results for dashboard clock."""
import glob
import json
import os
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    files = sorted(
        glob.glob(os.path.join(BASE, "gem_results", "gem_*.json")),
        reverse=True,
    )
    if not files:
        print("[gem_meta] no gem_*.json")
        return
    path = files[0]
    with open(path, encoding="utf-8") as f:
        g = json.load(f)
    meta = {
        "source": os.path.basename(path),
        "run_date": g.get("run_date"),
        "run_time": g.get("run_time"),
        "total_positions": g.get("total_positions"),
        "grade_summary": g.get("grade_summary"),
    }
    out = os.path.join(BASE, "data", "gem_meta.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    try:
        shutil.copy2(out, "/var/www/html/gem_meta.json")
    except Exception as exc:
        print(f"[gem_meta] webroot copy skipped: {exc}")
    print(f"[gem_meta] {meta.get('source')} {meta.get('run_date')} {meta.get('run_time')}")


if __name__ == "__main__":
    main()
