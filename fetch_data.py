"""fetch_data.py — DATA LAYER"""
import datetime, json, os

BASE = os.path.dirname(os.path.abspath(__file__))

UNIVERSE = {
    # PORTFOLIO
    "PLTR":      {"entry":109.32,"stop":95,"soros_gap":59,"soros_type":"narrative","ez_low":95,"ez_high":109,"thesis":"intact","macro":"tailwind","conviction":9,"sector":"Intelligence","status":"portfolio"},
    "TSM":       {"entry":287.40,"stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":9,"sector":"Intelligence","status":"portfolio"},
    "000660.KS": {"entry":85000, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":10,"sector":"Intelligence","status":"portfolio","currency":"KRW"},
    "1810.HK":   {"entry":3.88,  "stop":0, "soros_gap":41,"soros_type":"narrative","ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":7, "sector":"Intelligence","status":"portfolio","currency":"HKD"},
    "UEC":       {"entry":12.19, "stop":0, "soros_gap":38,"soros_type":"narrative","ez_low":10,"ez_high":12, "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Energy",      "status":"portfolio","limit":11},
    "URNM":      {"entry":14.65, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":7, "sector":"Energy",      "status":"portfolio"},
    "RKLB":      {"entry":59.67, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Space",       "status":"portfolio"},
    "PL":        {"entry":26.88, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":7, "sector":"Space",       "status":"portfolio"},
    "TMO":       {"entry":438.66,"stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Bio",         "status":"portfolio"},
    "KTOS":      {"entry":80.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":65,"ez_high":80, "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Robotics",    "status":"portfolio","sector_fear":True,"sector_fear_pct":11.2},
    "COHR":      {"entry":214.21,"stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Infra",       "status":"portfolio"},
    "VRT":       {"entry":65.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Infra",       "status":"portfolio"},
    "NTR":       {"entry":65.94, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Global",      "status":"portfolio"},
    "272210.KS": {"entry":45000, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":9, "sector":"Robotics",    "status":"portfolio","currency":"KRW"},
    # WATCHLIST — all must have projections too
    "NVDA":      {"entry":0,     "stop":0, "soros_gap":45,"soros_type":"narrative","ez_low":150,"ez_high":200,"thesis":"intact","macro":"tailwind","conviction":9, "sector":"Intelligence","status":"watchlist"},
    "OKLO":      {"entry":0,     "stop":0, "soros_gap":60,"soros_type":"narrative","ez_low":40, "ez_high":50, "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Energy",      "status":"watchlist","limit":44},
    "CCJ":       {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":95, "ez_high":105,"thesis":"intact","macro":"tailwind","conviction":8, "sector":"Energy",      "status":"watchlist","limit":100},
    "ASML":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":1050,"ez_high":1100,"thesis":"intact","macro":"tailwind","conviction":9,"sector":"Infra",      "status":"watchlist","limit":1080,"currency":"EUR"},
    "ASTS":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":60, "ez_high":80, "thesis":"intact","macro":"tailwind","conviction":7, "sector":"Space",       "status":"watchlist"},
    "BEAM":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":25, "ez_high":35, "thesis":"intact","macro":"neutral", "conviction":7, "sector":"Bio",         "status":"watchlist"},
    "NTLA":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":10, "ez_high":18, "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Bio",         "status":"watchlist"},
    "AMAT":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":350,"ez_high":420,"thesis":"intact","macro":"tailwind","conviction":7, "sector":"Infra",       "status":"watchlist"},
    "FCX":       {"entry":52.0,  "stop":54.5,"soros_gap":32,"soros_type":"narrative","ez_low":52,"ez_high":58,"thesis":"intact","macro":"neutral","conviction":6, "sector":"Global",      "status":"portfolio"},
    "CWEN":      {"entry":29.32, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Energy",      "status":"portfolio"},
    "UUUU":      {"entry":18.21, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Energy",      "status":"portfolio"},
    "CRSP":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":40, "ez_high":55, "thesis":"wounded","macro":"neutral", "conviction":5, "sector":"Bio",         "status":"watchlist"},
    "ARKQ":      {"entry":55.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Robotics",    "status":"portfolio"},
    "BOTZ":      {"entry":23.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Robotics",    "status":"portfolio"},
    "MC.PA":     {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":8, "sector":"Locked",      "status":"locked",  "currency":"EUR"},
    "IAU":       {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":3, "sector":"Tactical",    "status":"portfolio"},
}

def get_live_prices():
    import yfinance as yf
    tickers = list(UNIVERSE.keys())
    prices = {}
    for t in tickers:
        try:
            h = yf.Ticker(t).history(period="2d")
            if not h.empty:
                prices[t] = round(float(h["Close"].iloc[-1]), 4)
        except: pass
    return prices

def get_liquidity():
    path = os.path.join(BASE, "data", "directives.json")
    with open(path) as f: d = json.load(f)
    liq = d.get("liquidity", {})
    return {
        "liquidity_usd_bn": liq.get("net_liq_value", 2368),
        "liquidity_change_7d_bn": liq.get("vs_last_week_b", 189),
        "zone": liq.get("zone", "WARNING"),
        "action": liq.get("action_text", ""),
        "last_updated": liq.get("last_updated", "")
    }

def get_ranto28():
    try:
        path = os.path.join(BASE, "data", "blog_signals.json")
        with open(path) as f: return json.load(f)
    except: return []

def get_all_data():
    prices = get_live_prices()
    liquidity = get_liquidity()
    ranto = get_ranto28()
    return {
        "date_berlin": datetime.datetime.now().strftime("%Y-%m-%d"),
        "time_berlin": datetime.datetime.now().strftime("%H:%M"),
        "universe": UNIVERSE,
        "prices": prices,
        "liquidity": liquidity,
        "dry_powder_eur": 1500.0,
        "vix": prices.get("^VIX", 19.12),
        "blog_ranto28": ranto,
    }
