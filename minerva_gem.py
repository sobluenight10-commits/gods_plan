"""
MINERVA_GEM v2 — Price Projection & GEM Filter Engine
OLYMPUS Investment System · Run every weekday.
Pre-revenue/negative-EPS: Revenue×PS model. Profitable: EPS×PE model.
"""
import math

WW, WN, WB = 0.5, 0.3, 0.2
LIQ_MULT  = {"tight": 0.95, "neutral": 1.00, "loose": 1.05}
SENT_MULT = {"negative": 0.97, "neutral": 1.00, "positive": 1.03}

def _r(v, n=2): return round(v, n)

def _is_prerev(data):
    return data.get("eps_1y_base", 0) <= 0 or data.get("pe_normal", 0) == 0

def evaluate(data):
    P0 = data["current_price"]
    ep = data.get("entry_price", 0.0) or 0.0
    gs = data.get("god_score", None)
    adj = LIQ_MULT.get(data.get("macro_liquidity_regime","neutral"),1.0) * \
          SENT_MULT.get(data.get("sentiment","neutral"),1.0)

    s1y = data["vol_1y_pct"]/100
    s1m = s1y/math.sqrt(12)
    s6m = s1y/math.sqrt(2)

    gb = data.get("rev_cagr_5y_bear",0.05)
    gn = data.get("rev_cagr_5y_normal",0.15)
    gu = data.get("rev_cagr_5y_bull",0.30)
    xb = data.get("exit_multiple_bear",8.0)
    xn = data.get("exit_multiple_normal",15.0)
    xu = data.get("exit_multiple_bull",30.0)
    dr = data.get("discount_rate",0.12)
    df = 1/(1+dr)**5

    def proj(w0,n0,b0):
        w,n,b = max(0,w0*adj), max(0,n0*adj), max(0,b0*adj)
        ev = WW*w+WN*n+WB*b
        return {"worst":_r(w),"normal":_r(n),"bull":_r(b),"ev":_r(ev),
                "upside_pct":_r((ev-P0)/P0*100),
                "worst_drop_pct":_r((w-P0)/P0*100),
                "bull_gain_pct":_r((b-P0)/P0*100)}

    p1m = proj(P0*(1-1.5*s1m), P0, P0*(1+1.5*s1m))
    p6m = proj(P0*(1-2.0*s6m), P0, P0*(1+2.0*s6m))

    if _is_prerev(data):
        rb = data.get("rev_1y_bear", P0*0.3)
        rn = data.get("rev_1y_base", P0*0.5)
        ru = data.get("rev_1y_bull", P0*0.9)
        sh = data.get("shares_out_m", 1.0)
        psb= data.get("ps_multiple_bear",4.0)
        psn= data.get("ps_multiple_normal",10.0)
        psu= data.get("ps_multiple_bull",20.0)
        p1y= proj(rb*psb/sh, rn*psn/sh, ru*psu/sh)
        p3y= proj(rb*(1+gb)**2*psb/sh, rn*(1+gn)**2*psn/sh, ru*(1+gu)**2*psu/sh)
        p5y= proj(rb*(1+gb)**4*xb/sh*df, rn*(1+gn)**4*xn/sh*df, ru*(1+gu)**4*xu/sh*df)
        mode="revenue_ps"
    else:
        eb=data["eps_1y_bear"]; en=data["eps_1y_base"]; eu=data["eps_1y_bull"]
        pb=data["pe_bear"]; pn=data["pe_normal"]; pu=data["pe_bull"]
        p1y= proj(eb*pb, en*pn, eu*pu)
        p3y= proj(eb*(1+gb)**2*pb, en*(1+gn)**2*pn, eu*(1+gu)**2*pu)
        p5y= proj(eb*(1+gb)**4*xb*df, en*(1+gn)**4*xn*df, eu*(1+gu)**4*xu*df)
        mode="eps_pe"

    u1=p1y["upside_pct"]; u5=p5y["upside_pct"]; d1=p1y["worst_drop_pct"]
    thesis=data.get("thesis_status","intact"); macro=data.get("macro_status","neutral")

    if thesis!="intact" or macro=="broken": grade="D"
    elif u1>=20 and u5>=100 and d1>-60: grade="A"
    elif u1>=10 and u5>=50  and d1>-50: grade="B"
    elif u1>=0  and u5>=20:             grade="C"
    else:                               grade="D"

    gem_u = grade in ["A","B"]
    gem_p = grade=="A"
    warn = f"GOD Score {gs} below 70 — manual review" if gem_p and gs and gs<70 else None

    reasons={"A":f"Grade A: 1y {u1:+.1f}%, 5y {u5:+.1f}%, worst {d1:.1f}%.",
             "B":f"Grade B: 1y {u1:+.1f}%, 5y {u5:+.1f}%, worst {d1:.1f}%.",
             "C":f"Grade C: 1y {u1:+.1f}%, 5y {u5:+.1f}%, marginal.",
             "D":f"Grade D: thesis={thesis}, 1y {u1:+.1f}%, 5y {u5:+.1f}%."}

    vs = {"unrealized_pnl_pct": _r((P0-ep)/ep*100) if ep>0 else None,
          "current_vs_ev_1y_pct": _r((p1y["ev"]-P0)/P0*100),
          "current_vs_ev_5y_pct": _r((p5y["ev"]-P0)/P0*100),
          "entry_vs_ev_1y_pct":   _r((p1y["ev"]-ep)/ep*100) if ep>0 else None,
          "entry_vs_ev_5y_pct":   _r((p5y["ev"]-ep)/ep*100) if ep>0 else None,
          "entry_margin_of_safety_1y_pct": _r((p1y["normal"]-ep)/ep*100) if ep>0 else None}

    return {"ticker":data["ticker"],"sector":data.get("sector",""),
            "track":data.get("track","B"),"valuation_mode":mode,
            "current_price":_r(P0),"entry_price":_r(ep) if ep>0 else None,
            "god_score":gs,"versus":vs,
            "projections":{"1m":p1m,"6m":p6m,"1y":p1y,"3y":p3y,"5y":p5y},
            "grading":{"upside_1y_pct":_r(u1),"upside_5y_pct":_r(u5),
                       "worst_drop_1y_pct":_r(d1),"grade":grade,
                       "gem_universe":gem_u,"gem_portfolio":gem_p,
                       "god_score_warning":warn,"reason":reasons[grade]}}
