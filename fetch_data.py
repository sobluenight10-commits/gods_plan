"""fetch_data.py — DATA LAYER"""
import datetime, json, os

BASE = os.path.dirname(os.path.abspath(__file__))

UNIVERSE = {
    # PORTFOLIO
    "PLTR":      {"entry":109.32,"stop":95,"soros_gap":59,"soros_type":"narrative","ez_low":95,"ez_high":109,"thesis":"intact","macro":"tailwind","conviction":9,"sector":"Intelligence","status":"portfolio","god_score":72},
    "TSM":       {"entry":287.40,"stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":9,"sector":"Intelligence","status":"portfolio","god_score":90},
    "000660.KS": {"entry":85000, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":10,"sector":"Intelligence","status":"portfolio","currency":"KRW","god_score":95},
    "1810.HK":   {"entry":3.88,  "stop":0, "soros_gap":41,"soros_type":"narrative","ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":7, "sector":"Intelligence","status":"portfolio","currency":"HKD","god_score":68},
    "UEC":       {"entry":12.19, "stop":0, "soros_gap":38,"soros_type":"narrative","ez_low":10,"ez_high":12, "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Energy",      "status":"portfolio","limit":11,"god_score":78},
    "URNM":      {"entry":14.65, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":7, "sector":"Energy",      "status":"portfolio","god_score":74},
    "RKLB":      {"entry":59.67, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Space",       "status":"portfolio","god_score":58},
    "PL":        {"entry":26.88, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":7, "sector":"Space",       "status":"portfolio","god_score":84},
    "TMO":       {"entry":438.66,"stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Bio",         "status":"portfolio","god_score":68},
    "KTOS":      {"entry":80.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":65,"ez_high":80, "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Robotics",    "status":"portfolio","sector_fear":True,"sector_fear_pct":11.2,"god_score":80},
    "COHR":      {"entry":214.21,"stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Infra",       "status":"portfolio","god_score":76},
    "VRT":       {"entry":65.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Infra",       "status":"portfolio","god_score":84},
    "NTR":       {"entry":65.94, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Global",      "status":"portfolio","god_score":72},
    "272210.KS": {"entry":45000, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":9, "sector":"Robotics",    "status":"portfolio","currency":"KRW","god_score":92},
    # WATCHLIST — all must have projections too
    "NVDA":      {"entry":0,     "stop":0, "soros_gap":45,"soros_type":"narrative","ez_low":150,"ez_high":200,"thesis":"intact","macro":"tailwind","conviction":9, "sector":"Intelligence","status":"watchlist","god_score":96},
    "OKLO":      {"entry":0,     "stop":0, "soros_gap":60,"soros_type":"narrative","ez_low":40, "ez_high":50, "thesis":"intact","macro":"tailwind","conviction":8, "sector":"Energy",      "status":"watchlist","limit":44,"god_score":70},
    "CCJ":       {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":95, "ez_high":105,"thesis":"intact","macro":"tailwind","conviction":8, "sector":"Energy",      "status":"watchlist","limit":100,"god_score":82},
    "ASML":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":1050,"ez_high":1100,"thesis":"intact","macro":"tailwind","conviction":9,"sector":"Infra",      "status":"watchlist","limit":1080,"currency":"EUR","god_score":87},
    "ASTS":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":60, "ez_high":80, "thesis":"intact","macro":"tailwind","conviction":7, "sector":"Space",       "status":"watchlist","god_score":72},
    "BEAM":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":25, "ez_high":35, "thesis":"intact","macro":"neutral", "conviction":7, "sector":"Bio",         "status":"watchlist","god_score":70},
    "NTLA":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":10, "ez_high":18, "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Bio",         "status":"watchlist","god_score":55},
    "AMAT":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":350,"ez_high":420,"thesis":"intact","macro":"tailwind","conviction":7, "sector":"Infra",       "status":"watchlist","god_score":79},
    "FCX":       {"entry":52.0,  "stop":54.5,"soros_gap":32,"soros_type":"narrative","ez_low":52,"ez_high":58,"thesis":"intact","macro":"neutral","conviction":6, "sector":"Global",      "status":"portfolio","god_score":45},
    "CWEN":      {"entry":29.32, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":6, "sector":"Energy",      "status":"portfolio","god_score":68},
    "UUUU":      {"entry":18.21, "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Energy",      "status":"portfolio","god_score":72},
    "CRSP":      {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":40, "ez_high":55, "thesis":"wounded","macro":"neutral", "conviction":5, "sector":"Bio",         "status":"watchlist","god_score":48},
    "ARKQ":      {"entry":55.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Robotics",    "status":"portfolio","god_score":62},
    "BOTZ":      {"entry":23.0,  "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"tailwind","conviction":6, "sector":"Robotics",    "status":"portfolio","god_score":60},
    "MC.PA":     {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":8, "sector":"Locked",      "status":"locked",  "currency":"EUR","god_score":75},
    "IAU":       {"entry":0,     "stop":0, "soros_gap":0, "soros_type":"",         "ez_low":0, "ez_high":0,  "thesis":"intact","macro":"neutral", "conviction":3, "sector":"Tactical",    "status":"portfolio","god_score":30},
}

SCENARIOS = {
  "PLTR": {
    "W": "Defense budget cuts + AI spending freeze + multiple compression",
    "N": "Steady gov contracts + AIP enterprise growth",
    "B": "AI mega-cycle + NATO adoption + commercial inflection"
  },
  "TSM": {
    "W": "China invasion risk + foundry overcapacity + smartphone slump",
    "N": "Consensus semi cycle + steady foundry demand",
    "B": "AI mega-cycle + N2 monopoly + CoWoS shortage premium"
  },
  "000660.KS": {
    "W": "Memory oversupply + China DRAM dumping + smartphone slump",
    "N": "HBM3E ramp + steady server demand",
    "B": "AI memory supercycle + HBM monopoly pricing power"
  },
  "1810.HK": {
    "W": "China economic slowdown + EV margin compression",
    "N": "Smartphone + IoT steady growth + EV scale",
    "B": "EV breakout + ecosystem lock-in + global expansion"
  },
  "UEC": {
    "W": "Uranium price collapse + permitting delays",
    "N": "Burke Hollow production ramp + utility contracts",
    "B": "Nuclear renaissance + spot uranium $120+ + US energy security"
  },
  "URNM": {
    "W": "Uranium spot crash + ETF outflows",
    "N": "Structural uranium deficit + utility restocking",
    "B": "Nuclear renaissance + 50 new reactors globally"
  },
  "RKLB": {
    "W": "Neutron delay + launch failure + funding gap",
    "N": "Electron cadence + Neutron 2027 + backlog growth",
    "B": "Neutron success + constellation wins + space infrastructure"
  },
  "PL": {
    "W": "NASA budget cuts + satellite failure + cash burn",
    "N": "NASA contract expansion + defense demand",
    "B": "Climate data monopoly + defense upside + constellation expansion"
  },
  "TMO": {
    "W": "Biotech funding winter + pharma capex cuts",
    "N": "Steady life sciences demand + bolt-on M&A",
    "B": "Gene therapy boom + pandemic preparedness spending"
  },
  "KTOS": {
    "W": "Defense sequestration + drone competition",
    "N": "Valkyrie program + steady defense budgets",
    "B": "AI drone adoption + autonomous systems mega-trend"
  },
  "COHR": {
    "W": "Fiber glut + datacom pricing pressure",
    "N": "AI datacom growth + photonics demand",
    "B": "800G/1.6T upgrade supercycle + silicon photonics monopoly"
  },
  "VRT": {
    "W": "Data center build pause + competition + margin pressure",
    "N": "Steady DC power demand + Vertiv backlog",
    "B": "AI power density surge + cooling monopoly + pricing power"
  },
  "NTR": {
    "W": "Fertilizer price collapse + crop oversupply",
    "N": "Steady ag demand + potash/nitrogen pricing",
    "B": "Food security crisis + fertilizer supply disruption + China P ban"
  },
  "272210.KS": {
    "W": "Humanoid delay + competition from China",
    "N": "Factory automation growth + robotics adoption",
    "B": "Humanoid breakout + Samsung/Hyundai partnerships"
  },
  "NVDA": {
    "W": "AI spending freeze + China export ban + AMD competition",
    "N": "Blackwell ramp + enterprise AI adoption",
    "B": "AGI compute layer monopoly + sovereign AI + $10T TAM"
  },
  "OKLO": {
    "W": "NRC rejection + technology failure + no revenue",
    "N": "SMR certification + Meta power deal + first reactor",
    "B": "SMR mass deployment + nuclear renaissance + 100 reactors"
  },
  "CCJ": {
    "W": "Uranium spot crash + Canadian regulatory risk",
    "N": "Utility contracts + steady production + spot $80",
    "B": "Nuclear renaissance + spot $150 + western supply premium"
  },
  "ASML": {
    "W": "Recession + AI capex freeze + China export ban",
    "N": "Consensus semi cycle + steady foundry demand",
    "B": "AI mega-cycle + EUV monopoly + new fab orders"
  },
  "ASTS": {
    "W": "Satellite failure + spectrum issues + cash burn",
    "N": "BlueBird constellation + carrier partnerships",
    "B": "Direct-to-device monopoly + 2B subscriber TAM"
  },
  "BEAM": {
    "W": "Clinical failure + FDA rejection + cash burn",
    "N": "Phase 1/2 data readout + partnership deals",
    "B": "Base editing platform proves out + $50B gene therapy TAM"
  },
  "NTLA": {
    "W": "Phase 3 TTR failure + competition + dilution",
    "N": "TTR approval path + pipeline progress",
    "B": "In-vivo CRISPR proves safe + platform value unlocked"
  },
  "AMAT": {
    "W": "Semi capex downcycle + China restrictions",
    "N": "Steady equipment demand + technology transitions",
    "B": "AI fab buildout supercycle + ICAPS leadership"
  },
  "FCX": {
    "W": "Copper price crash + Indonesian political risk",
    "N": "Steady copper demand + Grasberg production",
    "B": "AI data center copper demand + green energy supercycle"
  },
  "CWEN": {
    "W": "Interest rate spike + PPA renegotiation risk",
    "N": "Contracted cash flows + dividend growth",
    "B": "Renewable premium pricing + acquisition upside"
  },
  "UUUU": {
    "W": "Uranium/REE price crash + permitting issues",
    "N": "White Mesa production + REE diversification",
    "B": "US energy security premium + REE supply chain decoupling"
  },
  "CRSP": {
    "W": "Casgevy commercial failure + competition + dilution",
    "N": "Casgevy steady launch + pipeline progress",
    "B": "CRISPR platform dominance + ex-vivo scale"
  },
  "ARKQ": {
    "W": "Innovation selloff + rate shock + redemptions",
    "N": "Robotics/AI basket steady growth",
    "B": "Autonomous revolution + robotics adoption curve"
  },
  "BOTZ": {
    "W": "Robotics hype fade + rate shock + outflows",
    "N": "Factory automation steady growth",
    "B": "Humanoid revolution + AI-robot convergence"
  },
  "MC.PA": {
    "W": "Luxury demand collapse + China slowdown",
    "N": "Steady luxury demand + pricing power",
    "B": "Aspirational class expansion + brand monopoly"
  },
  "IAU": {
    "W": "Gold crash + real rates spike + dollar surge",
    "N": "Inflation hedge + central bank buying",
    "B": "Currency crisis + gold $4000+ + de-dollarization"
  }
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
        "scenarios": SCENARIOS,
    }
