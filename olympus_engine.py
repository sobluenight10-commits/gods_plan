"""olympus_engine.py — ENGINE LAYER"""
import os, json, sys
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

def classify_macro(liq_change, vix):
    if liq_change > 25:   status = "EXPANSION"
    elif liq_change < -25: status = "CONTRACTION"
    else:                  status = "STABLE"
    if vix < 15:    vreg = "CALM"
    elif vix <= 25: vreg = "NORMAL"
    else:           vreg = "FEAR"
    if status == "EXPANSION" and vreg in ["CALM","NORMAL"]: deploy_pct = 30
    elif status == "STABLE" and vreg == "NORMAL":           deploy_pct = 20
    else:                                                   deploy_pct = 10
    return {"status": status, "vix_regime": vreg, "deploy_pct": deploy_pct}

def get_gem_projections():
    gem_dir = os.path.join(BASE, "gem_results")
    files = sorted(f for f in os.listdir(gem_dir) if f.startswith("gem_") and f.endswith(".json"))
    if not files: return {}
    with open(os.path.join(gem_dir, files[-1])) as f:
        data = json.load(f)
    return {r["ticker"]: r for r in data.get("results", [])}

def compute_action(pos_cfg, price, gem, macro):
    ticker     = pos_cfg.get("ticker","")
    # THESIS GUARD — single source of truth
    # thesis in fetch_data.py is a HINT, not authoritative.
    # thesis_guard.py is authoritative.
    try:
        from thesis_guard import validate
        _proposed = pos_cfg.get("thesis","intact")
        _event    = pos_cfg.get("company_event","")
        _force    = pos_cfg.get("force_thesis", False)
        _guard    = validate(ticker, _proposed, _event, _force)
        thesis    = _guard["authoritative_thesis"]
        if _guard["blocked"]:
            import logging
            logging.getLogger("olympus_engine").warning(
                f"THESIS BLOCKED {ticker}: {_guard['reason']}"
            )
    except ImportError:
        thesis = pos_cfg.get("thesis","intact")
    stop       = pos_cfg.get("stop",0)
    ez_low     = pos_cfg.get("ez_low",0)
    ez_high    = pos_cfg.get("ez_high",0)
    soros_gap  = pos_cfg.get("soros_gap",0)
    soros_type = pos_cfg.get("soros_type","")
    limit      = pos_cfg.get("limit",0)
    sector_fear= pos_cfg.get("sector_fear",False)
    sf_pct     = pos_cfg.get("sector_fear_pct",0)
    conviction = pos_cfg.get("conviction",7)
    grade      = gem.get("grading",{}).get("grade","D") if gem else "D"

    if thesis == "dead":
        return {"action":"EXIT","display":"EXIT NOW","urgency":"IMMEDIATE",
                "reason":"Thesis dead"}

    if stop > 0 and price > 0 and price < stop:
        if thesis == "intact":
            return {"action":"ARMED_ONE_SHOT",
                    "display":f"ARMED · ONE SHOT · thesis intact · {soros_gap}%+ gap",
                    "urgency":"MAXIMUM",
                    "reason":f"Below stop ${stop} — thesis intact — dip = widest gap = max conviction"}
        return {"action":"EXIT_REVIEW","display":"EXIT REVIEW","urgency":"HIGH",
                "reason":f"Below stop ${stop} — thesis wounded"}

    if sector_fear and thesis=="intact" and ez_high>0 and price>0 and price<=ez_high:
        return {"action":"ADD","display":f"ADD · sector fear dip · better than ${ez_high:.0f}",
                "urgency":"HIGH","reason":f"Sector -{sf_pct}% but thesis intact. Price in zone."}

    if soros_type=="narrative" and soros_gap>=20:
        if limit>0 and price>0 and limit<price:
            return {"action":"ARMED","display":f"ARMED · limit ${limit:.0f}","urgency":"READY",
                    "reason":f"Narrative gap {soros_gap}% intact. Limit armed."}
        if ez_low>0 and ez_high>0 and price>0 and ez_low<=price<=ez_high:
            return {"action":"ADD","display":f"ADD · in zone ${ez_low:.0f}–${ez_high:.0f}",
                    "urgency":"HIGH","reason":f"Narrative gap {soros_gap}%. In entry zone."}
        if ez_high>0 and price>0 and price>ez_high:
            return {"action":"DIP_WATCH","display":f"DIP WATCH · entry ${ez_low:.0f}–${ez_high:.0f}",
                    "urgency":"PATIENT","reason":f"Narrative gap {soros_gap}%. Above zone. Wait."}

    if grade=="A" and macro["deploy_pct"]>=20:
        if ez_high>0 and price>0 and price<=ez_high:
            return {"action":"ADD","display":"ADD · Grade A in zone",
                    "urgency":"HIGH","reason":f"Grade A. Price in zone."}

    return {"action":"HOLD","display":"HOLD","urgency":"NORMAL","reason":"Thesis intact."}

def ranto28_engine(posts, universe_tickers):
    bias = {t:0 for t in universe_tickers}
    action_posts = []
    for p in posts:
        affected = [t for t in p.get("affected_tickers",[]) if t in universe_tickers]
        sig = p.get("signal","NONE")
        for t in affected:
            if sig=="BUY":    bias[t] = min(15, bias[t]+10)
            elif sig=="WATCH": bias[t] = min(15, bias[t]+5)
            elif sig=="REDUCE":bias[t] = max(-15,bias[t]-10)
        action_posts.append({
            "title": p.get("title",""),
            "date": p.get("date",""),
            "url": p.get("url",""),
            "theme": p.get("macro_theme",""),
            "tickers": affected,
            "affected_tickers": p.get("affected_tickers",[]),
            "action": sig,
            "summary": p.get("summary",""),
            "sectors": p.get("sectors",[]),
        })
    return action_posts, bias

def score_action(action_result, gem, pos_cfg, ranto_bias, macro):
    score = 0
    a = action_result["action"]
    if a == "EXIT":             score += 80
    elif a == "EXIT_REVIEW":    score += 60
    elif a == "ARMED_ONE_SHOT": score += 70
    elif a == "ARMED":          score += 50
    elif a == "ADD":
        grade = gem.get("grading",{}).get("grade","D") if gem else "D"
        if grade=="A" and pos_cfg.get("conviction",7)>=9: score += 40
        elif grade=="A": score += 30
        else: score += 15
    elif a == "DIP_WATCH": score += 20
    score += ranto_bias.get(pos_cfg.get("ticker",""),0)
    if pos_cfg.get("macro","neutral")=="tailwind": score += 10
    return score

def run_engine(data):
    macro = classify_macro(
        data["liquidity"]["liquidity_change_7d_bn"],
        data.get("vix", 19.12)
    )
    gem_data = get_gem_projections()
    universe = data["universe"]
    prices = data["prices"]
    ranto_posts, ranto_bias = ranto28_engine(
        data.get("blog_ranto28",[]), list(universe.keys())
    )

    results = {}
    scored = []
    for ticker, cfg in universe.items():
        cfg["ticker"] = ticker
        price = prices.get(ticker, 0)
        gem = gem_data.get(ticker)
        action = compute_action(cfg, price, gem, macro)
        score  = score_action(action, gem, cfg, ranto_bias, macro)
        proj   = gem.get("projections",{}) if gem else {}

        results[ticker] = {
            "ticker":     ticker,
            "sector":     cfg["sector"],
            "status":     cfg["status"],
            "currency":   cfg.get("currency","USD"),
            "price":      price,
            "entry":      cfg.get("entry",0),
            "pnl_pct":    round((price-cfg["entry"])/cfg["entry"]*100,1) if cfg.get("entry",0)>0 and price>0 else None,
            "god_score":  cfg.get("god_score", 0),
            "conviction": cfg.get("conviction",7),
            "ez_low":     cfg.get("ez_low",0),
            "ez_high":    cfg.get("ez_high",0),
            "action":     action,
            "score":      score,
            "gem_grade":  gem.get("grading",{}).get("grade","\u2014") if gem else "\u2014",
            "gem_u1y":    gem.get("grading",{}).get("upside_1y_pct") if gem else None,
            "gem_u5y":    gem.get("grading",{}).get("upside_5y_pct") if gem else None,
            "projections": proj,
            "ranto_bias": ranto_bias.get(ticker,0),
            "soros_gap":  cfg.get("soros_gap",0),
            "soros_type": cfg.get("soros_type",""),
            "scenarios": data.get("scenarios",{}).get(ticker,{}),
        }
        scored.append((score, ticker))

    scored.sort(reverse=True)
    max_deploy = min(macro["deploy_pct"]/100 * (9000+data["dry_powder_eur"]), data["dry_powder_eur"])

    # ONE COMMAND — highest scoring ADD/ARMED/ONE_SHOT
    one_command = "NO TRADE — HOLD & OBSERVE"
    one_ticker = None
    for score, ticker in scored:
        r = results[ticker]
        if score >= 40 and r["action"]["action"] in ["ADD","ARMED","ARMED_ONE_SHOT"]:
            one_command = f"{r['action']['display']} — {r['action']['reason']}"
            one_ticker = ticker
            break

    return {
        "date": data["date_berlin"],
        "time": data.get("time_berlin","07:00"),
        "macro": macro,
        "liquidity": data["liquidity"],
        "vix": data.get("vix",19.12),
        "dry_powder": data["dry_powder_eur"],
        "max_deploy": max_deploy,
        "universe_results": results,
        "scored_tickers": scored,
        "one_command": one_command,
        "one_ticker": one_ticker,
        "ranto_posts": ranto_posts,
        "ranto_bias": ranto_bias,
    }
