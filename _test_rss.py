import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_data import get_ranto28

posts = get_ranto28()
print(f"{len(posts)} posts found within 48h")
for p in posts:
    t = p.get("title", "")[:60]
    d = p.get("date", "?")
    tks = p.get("affected_tickers", [])
    secs = p.get("sectors", [])
    print(f"  [{d}] {t}")
    print(f"         tickers={tks}  sectors={secs}")
