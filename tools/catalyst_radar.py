"""
catalyst_radar.py — OLYMPUS forward event map with base-rate asymmetry scoring.

Produces data/catalyst_radar.json with, per event:
  {
    "ticker": "NVDA",
    "type":   "earnings | product_launch | clinical_readout | macro | supply_event",
    "date":   "2026-05-22",
    "days":   35,                             # days until event (neg = past)
    "title":  "Q1 earnings",
    "thesis_sensitivity": "high|medium|low",
    "base_rate": {                            # from last 4-8 historical events of SAME type
      "n": 8,
      "mean_abs_move_pct": 7.4,
      "mean_move_pct": +1.8,
      "win_rate": 0.625,                      # pct of events where stock went UP T+1
      "best_pct": +18.2,
      "worst_pct": -12.4,
      "source": "yfinance (earnings +/- 1 day close-close)"
    } | null,
    "asymmetry_score": +62,                   # -100 to +100; bull-dominant events positive
    "setup_flag": "ELEVATED_EXPECTATIONS | UNDER_POSITIONED | QUIET_PRE_EVENT | CROWDED | NEUTRAL",
    "setup_reasons": ["+14% above 50d MA", "analyst tone slightly_more_bullish"],
    "attention_score": 72,                    # from attention_signal.py (0-100, null if unavail)
    "thesis_state": "intact|wounded|dead"     # from thesis_guard
  }

Sources:
  - Finnhub earnings dates        (data/finnhub_catalysts.json from catalyst_enricher.py)
  - Finnhub recommendation tone   (same file)
  - yfinance historical earnings  (for base-rate move distribution)
  - data/static_catalysts.json    (GOD-curated strategic events)
  - thesis_guard                  (current authoritative thesis per ticker)
  - attention_signal.py           (optional attention score; gracefully skipped if unavail)

Usage:
  python3 tools/catalyst_radar.py               # refresh all tickers in universe
  python3 tools/catalyst_radar.py NVDA PLTR     # refresh subset
  python3 tools/catalyst_radar.py --no-trends   # skip Google Trends (faster)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

CACHE          = os.path.join(BASE, "data", "catalyst_radar.json")
FINNHUB_CACHE  = os.path.join(BASE, "data", "finnhub_catalysts.json")
STATIC_FILE    = os.path.join(BASE, "data", "static_catalysts.json")
PORTFOLIO_FILE = os.path.join(BASE, "gem_inputs", "portfolio_all.json")


# ─────────────────────────── helpers ───────────────────────────
def _today() -> date:
    return date.today()


def _load_json(path: str, default: Any = None) -> Any:
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, path)


def _universe_tickers() -> List[str]:
    rows = _load_json(PORTFOLIO_FILE, [])
    if isinstance(rows, list):
        return [r.get("ticker") for r in rows if r.get("ticker")]
    return []


def _thesis_state(ticker: str) -> str:
    try:
        from thesis_guard import get_thesis
        return get_thesis(ticker)
    except Exception:
        return "intact"


# ─────────────────────────── yfinance base rates ───────────────────────────
def _yf_base_rate_earnings(ticker: str, n_events: int = 8) -> Optional[Dict[str, Any]]:
    """
    For each historical earnings date, measure close(T-1) → close(T+1) move.
    Returns base-rate distribution or None if yfinance unavailable / non-US.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None

    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is None or len(ed) == 0:
            return None
        # Past events only
        import pandas as pd
        ed = ed.dropna(how="all")
        now = datetime.now(ed.index.tz) if ed.index.tz else datetime.now()
        past = ed[ed.index < now].head(n_events)
        if past.empty:
            return None

        earliest = past.index.min() - timedelta(days=7)
        latest   = past.index.max() + timedelta(days=7)
        hist = t.history(
            start=earliest.strftime("%Y-%m-%d"),
            end=(latest + timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=False,
        )
        if hist.empty:
            return None
        # index to date for easier lookup
        hist = hist.copy()
        hist.index = hist.index.tz_localize(None) if hist.index.tz else hist.index

        moves = []
        for ts in past.index:
            d0 = ts.tz_convert(None) if ts.tz else ts
            d0 = d0.normalize()
            # find closest trading day ≤ d0 (T-1) and ≥ d0 (T+1)
            before = hist[hist.index <= d0]
            after  = hist[hist.index >  d0]
            if before.empty or after.empty:
                continue
            pre  = before.iloc[-1]["Close"]
            post = after.iloc[0]["Close"]
            # T+1: use the close AFTER the earnings-day close
            if len(after) >= 2:
                post = after.iloc[1]["Close"] if after.iloc[0]["Close"] == pre else after.iloc[0]["Close"]
            if pre and post and pre > 0:
                moves.append(round((post - pre) / pre * 100.0, 2))

        if not moves:
            return None
        moves = moves[:n_events]
        abs_moves = [abs(m) for m in moves]
        wins = sum(1 for m in moves if m > 0)
        return {
            "n": len(moves),
            "mean_abs_move_pct": round(sum(abs_moves) / len(abs_moves), 2),
            "mean_move_pct":     round(sum(moves) / len(moves), 2),
            "win_rate":          round(wins / len(moves), 3),
            "best_pct":          round(max(moves), 2),
            "worst_pct":         round(min(moves), 2),
            "moves":             moves,
            "source":            "yfinance earnings close-to-close T-1 vs T+1",
        }
    except Exception as exc:
        return {"error": str(exc), "source": "yfinance"}


def _yf_current_vs_ma(ticker: str) -> Optional[Dict[str, Any]]:
    """Compute current price vs 50-day MA and 200-day MA + recent volatility."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="250d", auto_adjust=False)
        if hist.empty:
            return None
        close = hist["Close"]
        ma50 = float(close.tail(50).mean())
        ma200 = float(close.tail(200).mean()) if len(close) >= 200 else float(close.mean())
        cur = float(close.iloc[-1])
        pct_vs_50  = round((cur - ma50)  / ma50  * 100, 2) if ma50  else 0
        pct_vs_200 = round((cur - ma200) / ma200 * 100, 2) if ma200 else 0
        # 30d realized vol (close-to-close)
        rets = close.pct_change().dropna().tail(30)
        vol30 = round(float(rets.std() * (252 ** 0.5) * 100), 2) if len(rets) else 0
        return {
            "current": round(cur, 2),
            "ma50":    round(ma50, 2),
            "ma200":   round(ma200, 2),
            "pct_vs_50":  pct_vs_50,
            "pct_vs_200": pct_vs_200,
            "vol30d_ann": vol30,
        }
    except Exception:
        return None


# ─────────────────────────── asymmetry + setup scoring ───────────────────────────
def _asymmetry_score(base: Optional[Dict[str, Any]],
                     static_direction: str = "",
                     rec_tone: str = "") -> int:
    """
    Returns -100..+100. Positive = bull-dominant event based on history + forward color.
    """
    score = 0
    if base and base.get("n", 0) >= 3:
        wr = base.get("win_rate", 0.5) or 0.5
        best = base.get("best_pct", 0) or 0
        worst = base.get("worst_pct", 0) or 0
        mean = base.get("mean_move_pct", 0) or 0
        # Win-rate component (-50..+50)
        score += int((wr - 0.5) * 100)
        # Payoff asymmetry (-30..+30) : if best > |worst|, bullish
        denom = max(abs(worst), 1e-6)
        ratio = best / denom
        if ratio >= 1.5:   score += 30
        elif ratio >= 1.1: score += 15
        elif ratio <= 0.7: score -= 15
        elif ratio <= 0.5: score -= 30
        # Mean move tilt (-20..+20)
        if mean > 3:   score += 20
        elif mean > 1: score += 10
        elif mean < -3: score -= 20
        elif mean < -1: score -= 10

    # Static event direction modifier
    if static_direction == "bull": score += 10
    elif static_direction == "bear": score -= 10
    # binary has no prior bias

    # Analyst tone modifier (from Finnhub rec_delta)
    tone_map = {
        "materially_more_bullish":   +15,
        "slightly_more_bullish":     +7,
        "stable":                     0,
        "slightly_less_bullish":     -7,
        "materially_less_bullish":   -15,
    }
    score += tone_map.get(rec_tone, 0)

    return max(-100, min(100, score))


def _setup_flag(price_ctx: Optional[Dict[str, Any]],
                attention: Optional[int],
                rec_tone: str,
                days_to_event: int,
                thesis: str) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    if thesis != "intact":
        reasons.append(f"thesis {thesis}")
        return ("THESIS_RISK", reasons)

    p50 = (price_ctx or {}).get("pct_vs_50", 0)
    if p50 >= 12 and rec_tone in ("materially_more_bullish", "slightly_more_bullish"):
        reasons.append(f"{p50:+.0f}% vs 50d + analysts {rec_tone.replace('_',' ')}")
        return ("ELEVATED_EXPECTATIONS", reasons)

    if p50 <= -8 and thesis == "intact":
        reasons.append(f"{p50:+.0f}% vs 50d, thesis intact")
        return ("UNDER_POSITIONED", reasons)

    if attention is not None and attention >= 85:
        reasons.append(f"attention {attention}/100 — retail crowded")
        return ("CROWDED", reasons)

    if attention is not None and attention <= 30 and 0 < days_to_event <= 10:
        reasons.append(f"attention {attention}/100 pre-event, quiet setup")
        return ("QUIET_PRE_EVENT", reasons)

    return ("NEUTRAL", reasons)


# ─────────────────────────── event assembly ───────────────────────────
def _finnhub_earnings_events(finn: Dict[str, Any],
                             horizon_days: int = 90) -> List[Dict[str, Any]]:
    events = []
    for tk, rec in finn.items():
        ne = rec.get("next_earnings") or {}
        d  = ne.get("date")
        if not d:
            continue
        try:
            edt = datetime.strptime(d, "%Y-%m-%d").date()
        except Exception:
            continue
        days = (edt - _today()).days
        if days < -2 or days > horizon_days:
            continue
        rec_tone = (rec.get("rec_delta") or {}).get("tone", "")
        events.append({
            "ticker": tk,
            "type":   "earnings",
            "date":   d,
            "days":   days,
            "title":  f"{tk} earnings",
            "thesis_sensitivity": "high",
            "expected_direction": "binary",
            "notes": ne.get("hour") or "",
            "_rec_tone": rec_tone,
            "_eps_estimate": ne.get("eps_estimate"),
        })
    return events


def _static_events(horizon_days: int = 120) -> List[Dict[str, Any]]:
    doc = _load_json(STATIC_FILE, {"events": []})
    events = []
    for ev in doc.get("events", []):
        d = ev.get("date")
        if not d:
            continue
        try:
            edt = datetime.strptime(d, "%Y-%m-%d").date()
        except Exception:
            continue
        days = (edt - _today()).days
        if days < -2 or days > horizon_days:
            continue
        events.append({
            "ticker": ev.get("ticker", ""),
            "type":   ev.get("type", "other"),
            "date":   d,
            "days":   days,
            "title":  ev.get("title", ""),
            "thesis_sensitivity": ev.get("thesis_sensitivity", "medium"),
            "expected_direction": ev.get("expected_direction", "binary"),
            "notes": ev.get("notes", ""),
            "_rec_tone": "",
            "_eps_estimate": None,
        })
    return events


# ─────────────────────────── portfolio concentration ───────────────────────────
def _concentration_warning(events: List[Dict[str, Any]]) -> List[str]:
    """Flag coordinated catalyst weeks (≥3 high-sensitivity events inside 10 days)."""
    out = []
    high = [e for e in events if e.get("thesis_sensitivity") == "high" and 0 <= e["days"] <= 30]
    high.sort(key=lambda x: x["days"])
    # Sliding 10-day window
    i = 0
    while i < len(high):
        window = [e for e in high if abs(e["days"] - high[i]["days"]) <= 10]
        if len(window) >= 3:
            tickers = sorted({e["ticker"] for e in window})
            # Only flag true multi-ticker clusters
            if len(tickers) >= 3:
                day_range = (min(e["days"] for e in window), max(e["days"] for e in window))
                out.append(
                    f"CLUSTER: {len(tickers)} high-sensitivity events in days "
                    f"+{day_range[0]}..+{day_range[1]} — {', '.join(tickers)}"
                )
            i += len(window)
        else:
            i += 1
    # De-dupe
    return list(dict.fromkeys(out))


# ─────────────────────────── main builder ───────────────────────────
def build_radar(tickers: Optional[List[str]] = None,
                use_trends: bool = True) -> Dict[str, Any]:
    finn = _load_json(FINNHUB_CACHE, {})
    if not tickers:
        tickers = _universe_tickers()
    tickers = [t.upper() for t in tickers]

    events = _finnhub_earnings_events(finn)
    events += _static_events()

    # Attention (optional)
    attention: Dict[str, Any] = {}
    if use_trends:
        try:
            from tools.attention_signal import attention_for_tickers
            attention = attention_for_tickers(tickers) or {}
        except Exception as exc:
            print(f"[RADAR] attention unavailable: {exc}")
            attention = {}

    # Enrich each event with base rate + setup + thesis state
    enriched = []
    _price_cache: Dict[str, Any] = {}
    _base_cache:  Dict[str, Any] = {}
    for ev in events:
        tk = ev["ticker"]
        rec_tone = ev.pop("_rec_tone", "")
        ev.pop("_eps_estimate", None)

        # base rate — only for earnings (US tickers with yfinance data)
        base = None
        if ev["type"] == "earnings" and tk != "MACRO":
            if tk not in _base_cache:
                _base_cache[tk] = _yf_base_rate_earnings(tk)
            base = _base_cache[tk]

        # price context (for setup)
        price_ctx = None
        if tk != "MACRO":
            if tk not in _price_cache:
                _price_cache[tk] = _yf_current_vs_ma(tk)
            price_ctx = _price_cache[tk]

        thesis = _thesis_state(tk) if tk != "MACRO" else "intact"
        att_score = None
        if tk in attention and attention[tk]:
            att_score = attention[tk].get("score")

        score = _asymmetry_score(base, ev.get("expected_direction", ""), rec_tone)
        flag, reasons = _setup_flag(price_ctx, att_score, rec_tone, ev["days"], thesis)

        enriched.append({
            **ev,
            "base_rate":        base,
            "price_context":    price_ctx,
            "attention_score":  att_score,
            "analyst_tone":     rec_tone,
            "thesis_state":     thesis,
            "asymmetry_score":  score,
            "setup_flag":       flag,
            "setup_reasons":    reasons,
        })

    enriched.sort(key=lambda x: x["days"])

    out = {
        "as_of":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "horizon_days": 90,
        "events":   enriched,
        "counts": {
            "total":     len(enriched),
            "next_7d":   sum(1 for e in enriched if 0 <= e["days"] <= 7),
            "next_14d":  sum(1 for e in enriched if 0 <= e["days"] <= 14),
            "next_30d":  sum(1 for e in enriched if 0 <= e["days"] <= 30),
            "under_positioned": sum(1 for e in enriched if e["setup_flag"] == "UNDER_POSITIONED"),
            "elevated":         sum(1 for e in enriched if e["setup_flag"] == "ELEVATED_EXPECTATIONS"),
            "quiet":            sum(1 for e in enriched if e["setup_flag"] == "QUIET_PRE_EVENT"),
            "thesis_risk":      sum(1 for e in enriched if e["setup_flag"] == "THESIS_RISK"),
        },
        "concentration_warnings": _concentration_warning(enriched),
    }
    _save_json(CACHE, out)
    print(f"[RADAR] wrote {len(enriched)} events → {CACHE}")
    print(f"[RADAR] next 7d={out['counts']['next_7d']}  14d={out['counts']['next_14d']}  "
          f"30d={out['counts']['next_30d']}  under-positioned={out['counts']['under_positioned']}  "
          f"elevated={out['counts']['elevated']}")
    for w in out["concentration_warnings"]:
        print(f"[RADAR] ⚠ {w}")
    return out


def main() -> int:
    argv = sys.argv[1:]
    use_trends = "--no-trends" not in argv
    argv = [a for a in argv if a != "--no-trends"]
    tickers = argv or None
    build_radar(tickers, use_trends=use_trends)
    return 0


if __name__ == "__main__":
    sys.exit(main())
