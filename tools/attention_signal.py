"""
attention_signal.py — Google Trends per-ticker retail attention.

Why this is an edge:
  Institutions run Bloomberg terminals and flow data. But almost nobody
  systematically tracks RETAIL ATTENTION per ticker on a 2-year baseline.
  Retail attention spikes often LEAD earnings moves on meme-sensitive names
  (PLTR, OKLO, UEC, NVDA, BEAM). With a 2-year baseline and weekly velocity
  we can flag: 'pre-earnings quiet' (good setup) vs 'pre-earnings crowded'
  (elevated expectations, likely to disappoint).

Output (returned by attention_for_tickers):
  { 'TICKER': {
      'current':       <raw 7d avg 0-100>,
      'baseline_4w':   <4-week avg before the current 7d>,
      'baseline_52w':  <52-week median>,
      'percentile_2y': 0-100    # current vs 2-yr history
      'slope_7d_pct':  +/- %    # 7d change vs previous 7d
      'score':         0-100    # composite attention score
    }, ... }

Also writes data/attention_signal.json for dashboard/debug use.

Requires pytrends (pip install pytrends). If pytrends is unavailable or the
API throttles (429), returns an empty dict and the caller gracefully degrades.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "data", "attention_signal.json")


# Map ticker → Google Trends query. For non-US we use company name because
# ticker alone is noisy (e.g. "000660.KS" won't match anything).
_QUERY_MAP: Dict[str, str] = {
    "NVDA":      "Nvidia stock",
    "PLTR":      "Palantir stock",
    "TSM":       "TSMC stock",
    "ASML":      "ASML stock",
    "AMAT":      "Applied Materials stock",
    "COHR":      "Coherent stock",
    "VRT":       "Vertiv stock",
    "OKLO":      "Oklo stock",
    "UEC":       "Uranium Energy",
    "URNM":      "Sprott Uranium ETF",
    "CCJ":       "Cameco",
    "UUUU":      "Energy Fuels stock",
    "CWEN":      "Clearway Energy",
    "KTOS":      "Kratos Defense",
    "RKLB":      "Rocket Lab",
    "ASTS":      "AST SpaceMobile",
    "PL":        "Planet Labs",
    "CRSP":      "CRISPR Therapeutics",
    "NTLA":      "Intellia stock",
    "BEAM":      "Beam Therapeutics",
    "REGN":      "Regeneron",
    "TMO":       "Thermo Fisher",
    "FCX":       "Freeport-McMoRan",
    "NTR":       "Nutrien",
    "IAU":       "iShares Gold",
    "ARKQ":      "ARKQ ETF",
    "BOTZ":      "BOTZ ETF",
    "MC.PA":     "LVMH stock",
    "000660.KS": "SK Hynix",
    "272210.KS": "Hanwha Aerospace",
    "1810.HK":   "Xiaomi",
}


def _percentile(series: List[float], value: float) -> int:
    if not series:
        return 50
    below = sum(1 for v in series if v < value)
    return int(round(below / len(series) * 100))


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


def attention_for_tickers(tickers: List[str],
                          timeframe: str = "today 5-y",
                          batch_size: int = 5,
                          sleep_between: float = 2.5) -> Dict[str, Any]:
    """
    Compute attention signal for given tickers. pytrends-backed.
    Returns {} if pytrends missing or first batch 429s (graceful degrade).
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        print("[ATTENTION] pytrends not installed — skipping attention signal")
        return {}

    out: Dict[str, Any] = {}

    queries: List[str] = []
    query_to_ticker: Dict[str, str] = {}
    for t in tickers:
        q = _QUERY_MAP.get(t)
        if not q:
            continue
        queries.append(q)
        query_to_ticker[q] = t

    if not queries:
        return {}

    try:
        pytrends = TrendReq(hl="en-US", tz=0, timeout=(6, 15), retries=2, backoff_factor=0.3)
    except Exception as exc:
        print(f"[ATTENTION] TrendReq init failed: {exc}")
        return {}

    # Process in batches of 5 (Google Trends limit)
    for i in range(0, len(queries), batch_size):
        batch = queries[i : i + batch_size]
        try:
            pytrends.build_payload(batch, timeframe=timeframe, geo="")
            df = pytrends.interest_over_time()
        except Exception as exc:
            print(f"[ATTENTION] batch {i} failed: {exc}")
            if i == 0:  # first batch total failure — bail early
                return out
            continue

        if df is None or df.empty:
            continue
        df = df.drop(columns=[c for c in df.columns if c == "isPartial"], errors="ignore")

        for q in batch:
            if q not in df.columns:
                continue
            series = df[q].astype(float).tolist()
            if len(series) < 10:
                continue
            # Last point is the "current" (weekly interest)
            current       = round(float(series[-1]), 2)
            baseline_4w   = round(sum(series[-5:-1]) / 4, 2) if len(series) >= 5 else current
            # Weekly series for 5y: 52*5 ≈ 260 points. Use last ~104 (2y) for percentile
            recent_2y     = series[-104:] if len(series) >= 104 else series
            baseline_52w  = round(sorted(series[-52:])[len(series[-52:]) // 2], 2) if len(series) >= 52 else current
            percentile_2y = _percentile(recent_2y, current)
            # Slope: current vs previous (7d vs prior 7d)
            prev = float(series[-2]) if len(series) >= 2 else current
            slope_pct = round(((current - prev) / prev * 100) if prev > 0 else 0, 1)

            # Composite score 0-100:
            #   40% percentile_2y + 30% slope_clip + 30% (current / baseline_52w clipped)
            slope_component = max(-50, min(50, slope_pct)) + 50  # 0-100
            ratio_component = 50 if baseline_52w == 0 else max(0, min(100, (current / baseline_52w) * 50))
            score = int(round(0.4 * percentile_2y + 0.3 * slope_component + 0.3 * ratio_component))

            tk = query_to_ticker[q]
            out[tk] = {
                "query":         q,
                "current":       current,
                "baseline_4w":   baseline_4w,
                "baseline_52w":  baseline_52w,
                "percentile_2y": percentile_2y,
                "slope_7d_pct":  slope_pct,
                "score":         score,
            }

        time.sleep(sleep_between)

    payload = {
        "as_of":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timeframe": timeframe,
        "tickers":  out,
    }
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"[ATTENTION] {len(out)}/{len(queries)} tickers scored → {CACHE}")
    return out


def main() -> int:
    _load_env()
    argv = sys.argv[1:]
    tickers = [a.upper() for a in argv] if argv else list(_QUERY_MAP.keys())
    result = attention_for_tickers(tickers)
    for tk, r in sorted(result.items(), key=lambda x: -(x[1] or {}).get("score", 0))[:15]:
        print(f"  {tk:<10} score={r['score']:>3}  "
              f"pct2y={r['percentile_2y']:>3}  slope={r['slope_7d_pct']:+.1f}%  "
              f"cur={r['current']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
