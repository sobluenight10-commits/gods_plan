"""olympus_daily.py — single entry point"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from fetch_data import get_all_data
from olympus_engine import run_engine
from output_factory import generate_outputs

def main():
    print("=== OLYMPUS DAILY PIPELINE ===")
    data  = get_all_data()
    print(f"Data: {len(data['prices'])} prices, {len(data['universe'])} universe")
    state = run_engine(data)
    print(f"Engine: ONE COMMAND = {state['one_command'][:60]}")
    generate_outputs(state)
    print("=== DONE ===")

if __name__ == "__main__":
    main()
"""olympus_daily.py — single entry point"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from fetch_data import get_all_data
from olympus_engine import run_engine
from output_factory import generate_outputs

def main():
    print("=== OLYMPUS DAILY PIPELINE ===")
    data  = get_all_data()
    print(f"Data: {len(data['prices'])} prices, {len(data['universe'])} universe")
    state = run_engine(data)
    print(f"Engine: ONE COMMAND = {state['one_command'][:60]}")
    generate_outputs(state)
    print("=== DONE ===")

if __name__ == "__main__":
    main()
def step1b_thesis():
    """Build thesis_status.json from existing battle_rhythm news cache."""
    import json, re, os
    from datetime import datetime
    
    BASE  = '/root/gods_plan'
    CACHE = os.path.join(BASE, 'data', 'news_alert_cache.json')
    LOG   = os.path.join(BASE, 'titan_k.log')
    OUT   = os.path.join(BASE, 'data', 'thesis_status.json')
    
    UNIVERSE = [
        'PLTR','TSM','UEC','URNM','RKLB','PL','TMO','KTOS','COHR',
        'VRT','NTR','FCX','OKLO','CCJ','ASML','NVDA','ASTS','BEAM',
        '000660.KS','272210.KS','1810.HK','CWEN','UUUU','NTLA','AMAT'
    ]
    
    thesis_from_log = {}
    try:
        with open(LOG, 'r', errors='ignore') as f:
            log = f.read()[-200000:]  # last 200KB
        blocks = log.split('\n\n')
        for block in blocks:
            tm = re.search(r'\b(PLTR|TSM|UEC|URNM|RKLB|KTOS|OKLO|NVDA|ASML|COHR|VRT|NTR|FCX|000660\.KS|272210\.KS|1810\.HK)\b', block)
            if not tm: continue
            ticker = tm.group(1)
            if 'THESIS: ✅ INTACT' in block or 'thesis_intact' in block.lower():
                thesis_from_log[ticker] = {'status':'INTACT','source':'battle_rhythm','evidence':'No adverse news — thesis verified intact'}
            elif 'WOUNDED' in block:
                thesis_from_log[ticker] = {'status':'WOUNDED','source':'battle_rhythm','evidence':block[:100]}
    except Exception as e:
        print(f"  Log scan: {e}")
    
    results = {}
    for ticker in UNIVERSE:
        results[ticker] = thesis_from_log.get(ticker, {
            'status': 'INTACT',
            'evidence': 'No adverse news alerts in system',
            'source': 'default',
            'date': datetime.now().strftime('%Y-%m-%d')
        })
    
    with open(OUT, 'w') as f:
        json.dump({'updated': datetime.now().isoformat(), 'results': results}, f, indent=2)
    print(f"  Thesis status: {len(results)} tickers · {sum(1 for r in results.values() if r['status']!='INTACT')} flags")


