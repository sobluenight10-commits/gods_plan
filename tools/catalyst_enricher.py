"""
catalyst_enricher.py — Finnhub-powered per-ticker catalyst layer.

Produces: data/finnhub_catalysts.json with, per US-listed ticker:

  {
    "TICKER": {
      "as_of": "2026-04-20T22:05:00+00:00",
      "next_earnings": { "date": "2026-05-28", "eps_estimate": 5.12, "days_away": 38 } | null,
      "earnings_trend": { "beats_last4": 4, "avg_surprise_pct": 2.35, "last_surprise_pct": 3.62 } | null,
      "rec_delta":      { "strongBuy": +0, "buy": +0, "hold": -1, "sell": +0, "tone": "slightly_less_bullish" } | null,
      "quote":          { "c": 202.06, "dp": 0.19 } | null
    },
    ...
  }

Free-tier friendly (60 req/min). Sleeps 1.1s between calls. Caches 4h TTL.
Non-US tickers (.KS, .HK, .PA, .T, etc.) are skipped — we keep these for the
qualitative matrix thesis only.

Usage (in order of preference):
  python3 tools/catalyst_enricher.py           # daily enrich (uses portfolio+watchlist)
  python3 tools/catalyst_enricher.py NVDA PLTR # ad-hoc
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "data", "finnhub_catalysts.json")
FINNHUB = "https://finnhub.io/api/v1"
TTL_HOURS = 4.0
RATE_SLEEP = 1.1  # seconds between HTTP calls (well under 60/min)

# Non-US suffixes we skip on free tier (supported but not in our GEM plan)
NON_US_SUFFIXES = (".KS", ".KQ", ".HK", ".T", ".PA", ".DE", ".L", ".AS", ".MI", ".SW", ".SS", ".SZ", ".TO", ".MC")


def _load_env() -> None:
    env_path = os.path.join(BASE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def _key() -> str:
    k = os.environ.get("FINNHUB_API_KEY", "")
    if not k:
        print("[CATALYST] FINNHUB_API_KEY missing — aborting enrich")
        sys.exit(2)
    return k


def _call(path: str, **params) -> Optional[Any]:
    params["token"] = _key()
    try:
        r = requests.get(f"{FINNHUB}{path}", params=params, timeout=12)
        if r.status_code == 429:
            print("[CATALYST] 429 rate limit — sleeping 30s")
            time.sleep(30)
            r = requests.get(f"{FINNHUB}{path}", params=params, timeout=12)
        if not r.ok:
            if r.status_code not in (403, 404):
                print(f"[CATALYST] {path} {params.get('symbol','')} HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as exc:
        print(f"[CATALYST] {path} error: {exc}")
        return None


def _is_us(ticker: str) -> bool:
    return not any(ticker.upper().endswith(s) for s in NON_US_SUFFIXES)


def _next_earnings(tk: str) -> Optional[Dict[str, Any]]:
    today = date.today()
    data = _call(
        "/calendar/earnings",
        symbol=tk,
        **{"from": today.isoformat(), "to": (today + timedelta(days=90)).isoformat()},
    )
    if not data:
        return None
    rows = data.get("earningsCalendar") or []
    if not rows:
        return None
    rows.sort(key=lambda x: x.get("date") or "9999-12-31")
    r = rows[0]
    try:
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        return {
            "date": r["date"],
            "eps_estimate": r.get("epsEstimate"),
            "revenue_estimate": r.get("revenueEstimate"),
            "hour": r.get("hour", ""),
            "days_away": (d - today).days,
        }
    except Exception:
        return None


def _earnings_trend(tk: str) -> Optional[Dict[str, Any]]:
    data = _call("/stock/earnings", symbol=tk)
    if not data:
        return None
    rows = data if isinstance(data, list) else []
    rows = [r for r in rows if r.get("actual") is not None and r.get("estimate")]
    rows = rows[:4]
    if not rows:
        return None
    beats = sum(1 for r in rows if r["actual"] > r["estimate"])
    surps = [r.get("surprisePercent") or 0 for r in rows]
    last = rows[0]
    return {
        "beats_last4": beats,
        "sample_size": len(rows),
        "avg_surprise_pct": round(sum(surps) / len(surps), 2) if surps else 0,
        "last_surprise_pct": round(last.get("surprisePercent") or 0, 2),
        "last_period": last.get("period"),
    }


def _rec_delta(tk: str) -> Optional[Dict[str, Any]]:
    data = _call("/stock/recommendation", symbol=tk)
    if not data or not isinstance(data, list) or len(data) < 2:
        return None
    cur, prev = data[0], data[1]
    delta = {k: (cur.get(k, 0) or 0) - (prev.get(k, 0) or 0) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    pos = delta["strongBuy"] + delta["buy"]
    neg = delta["hold"] + delta["sell"] + delta["strongSell"]
    if pos - neg >= 3:
        tone = "materially_more_bullish"
    elif pos - neg >= 1:
        tone = "slightly_more_bullish"
    elif neg - pos >= 3:
        tone = "materially_less_bullish"
    elif neg - pos >= 1:
        tone = "slightly_less_bullish"
    else:
        tone = "stable"
    return {
        "current_period": cur.get("period"),
        "prev_period": prev.get("period"),
        **delta,
        "tone": tone,
        "total_analysts": (cur.get("strongBuy", 0) + cur.get("buy", 0) + cur.get("hold", 0) + cur.get("sell", 0) + cur.get("strongSell", 0)),
        "buy_ratio": round(
            ((cur.get("strongBuy", 0) + cur.get("buy", 0)) /
             max(1, (cur.get("strongBuy", 0) + cur.get("buy", 0) + cur.get("hold", 0) + cur.get("sell", 0) + cur.get("strongSell", 0)))),
            2,
        ),
    }


def _quote(tk: str) -> Optional[Dict[str, Any]]:
    data = _call("/quote", symbol=tk)
    if not data or not data.get("c"):
        return None
    return {"c": data.get("c"), "dp": data.get("dp"), "d": data.get("d")}


def enrich_one(tk: str) -> Optional[Dict[str, Any]]:
    if not _is_us(tk):
        return None
    out: Dict[str, Any] = {"as_of": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    out["quote"] = _quote(tk);         time.sleep(RATE_SLEEP)
    out["next_earnings"] = _next_earnings(tk); time.sleep(RATE_SLEEP)
    out["earnings_trend"] = _earnings_trend(tk); time.sleep(RATE_SLEEP)
    out["rec_delta"] = _rec_delta(tk); time.sleep(RATE_SLEEP)
    return out


def _load_cache() -> Dict[str, Any]:
    if not os.path.exists(CACHE):
        return {}
    try:
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(d: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    tmp = CACHE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
    os.replace(tmp, CACHE)


def _is_fresh(rec: Dict[str, Any]) -> bool:
    ts = rec.get("as_of", "")
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - then) < timedelta(hours=TTL_HOURS)
    except Exception:
        return False


def _portfolio_tickers() -> List[str]:
    path = os.path.join(BASE, "gem_inputs", "portfolio_all.json")
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        return [r["ticker"] for r in rows if r.get("ticker")]
    except Exception:
        return []


def enrich_all(tickers: Optional[List[str]] = None, force: bool = False) -> Dict[str, Any]:
    _load_env()
    if not tickers:
        tickers = _portfolio_tickers()
    cache = _load_cache()
    n_new = n_skip = 0
    for tk in tickers:
        if not _is_us(tk):
            continue
        if not force and tk in cache and _is_fresh(cache[tk]):
            n_skip += 1
            continue
        rec = enrich_one(tk)
        if rec:
            cache[tk] = rec
            n_new += 1
            print(f"  [+] {tk}  earnings={rec.get('next_earnings',{}).get('date') if rec.get('next_earnings') else '—'}  "
                  f"rec={rec.get('rec_delta',{}).get('tone') if rec.get('rec_delta') else '—'}")
    _save_cache(cache)
    print(f"[CATALYST] enriched {n_new}, cached-skip {n_skip} → {CACHE}")
    return cache


def main() -> int:
    argv = sys.argv[1:]
    force = "--force" in argv
    argv = [a for a in argv if a != "--force"]
    tickers = argv or None
    enrich_all(tickers, force=force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
