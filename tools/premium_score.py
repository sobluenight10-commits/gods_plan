"""
OLYMPUS Premium Score (OPS) — relative richness vs sector peer basket.

OPS = 0.5 * (stock P/S ÷ median peer P/S) * 100
    + 0.5 * (stock fwd P/E ÷ median peer fwd P/E) * 100

Missing half → 50 neutral contribution. Caps per leg 150 → OPS max 300.
Bands: <80 CHEAP · 80–120 FAIR · 120–180 PREMIUM · >180 EXTREME

Run: python3 tools/premium_score.py
Writes data/premium_scores.json (copy to webroot via olympus_daily).
"""
from __future__ import annotations

import json
import os
import sys
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "data", "premium_scores.json")

# Peers by OLYMPUS sector label (fetch_data.UNIVERSE "sector" field)
SECTOR_PEERS: Dict[str, List[str]] = {
    "Intelligence": ["NVDA", "AMD", "AVGO", "QCOM", "INTC"],
    "Energy": ["CCJ", "UUUU", "UEC"],
    "Space": ["RKLB", "LMT", "NOC"],
    "Bio": ["BEAM", "CRSP", "REGN", "VRTX"],
    "Infra": ["AMAT", "LRCX", "KLAC", "ASML"],
    "Robotics": ["LMT", "RTX", "GD", "AVAV"],
    "Global": ["NTR", "FCX", "MOS", "VALE"],
    "Locked": ["ASML", "SAP", "ORCL"],
    "Tactical": ["GLD", "IAU"],
}

OPS_BANDS = [
    (80, "CHEAP", "Potential Soros gap vs sector — confirm thesis + catalyst."),
    (120, "FAIR", "Aligned with sector multiples."),
    (180, "PREMIUM", "Growth must justify; size smaller; prefer dips only."),
    (9999, "EXTREME", "Multiple extreme vs peers — 'dip' may be fair value compression."),
]


def _yf_info(ticker: str) -> Dict[str, Any]:
    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info or {}
        ps = info.get("priceToSalesTrailing12Months") or info.get("priceToSales")
        pe = info.get("forwardPE")
        if pe is not None and (pe <= 0 or pe > 5000):
            pe = None
        if ps is not None and ps <= 0:
            ps = None
        return {"ps": ps, "pe": pe}
    except Exception:
        return {"ps": None, "pe": None}


def _med(vals: List[Optional[float]]) -> Optional[float]:
    good = [float(v) for v in vals if v is not None and float(v) > 0]
    if len(good) < 1:
        return None
    return float(median(good))


def _leg(stock: Optional[float], peer_med: Optional[float]) -> float:
    if stock is None or peer_med is None or peer_med <= 0:
        return 50.0
    ratio = float(stock) / float(peer_med)
    return max(0.0, min(150.0, ratio * 50.0))


def _band(ops: float) -> Tuple[str, str]:
    for cap, name, hint in OPS_BANDS:
        if ops < cap:
            return name, hint
    return "EXTREME", OPS_BANDS[-1][2]


def compute_ops(ticker: str, sector: str) -> Dict[str, Any]:
    peers = SECTOR_PEERS.get(sector, ["SPY"])
    if ticker in peers:
        peers = [p for p in peers if p != ticker]

    infos = [_yf_info(ticker)] + [_yf_info(p) for p in peers]
    ps_med = _med([x["ps"] for x in infos[1:]])
    pe_med = _med([x["pe"] for x in infos[1:]])
    s_ps, s_pe = infos[0]["ps"], infos[0]["pe"]
    leg_ps = _leg(s_ps, ps_med)
    leg_pe = _leg(s_pe, pe_med)
    ops = round(leg_ps + leg_pe, 1)
    band, hint = _band(ops)
    return {
        "ticker": ticker,
        "sector": sector,
        "ops": ops,
        "band": band,
        "hint": hint,
        "stock_ps": s_ps,
        "stock_fwd_pe": s_pe,
        "peer_median_ps": ps_med,
        "peer_median_fwd_pe": pe_med,
        "leg_ps": round(leg_ps, 1),
        "leg_pe": round(leg_pe, 1),
        "peers_used": peers[:8],
    }


def build_all() -> Dict[str, Any]:
    from fetch_data import UNIVERSE

    rows = []
    for tk, meta in UNIVERSE.items():
        sec = meta.get("sector") or "Global"
        row = compute_ops(tk, sec)
        rows.append(row)
    rows.sort(key=lambda r: -r["ops"])
    return {
        "version": 1,
        "formula": "OPS = leg_ps + leg_pe; leg = min(150, (stock/med_peer)*50); missing leg = 50",
        "tickers": {r["ticker"]: r for r in rows},
        "ranked": rows,
    }


def main():
    payload = build_all()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT} ({len(payload['ranked'])} tickers)")
    top = payload["ranked"][:5]
    for r in top:
        print(f"  {r['ticker']:10s} OPS {r['ops']:6.1f} {r['band']:8s} {r['hint'][:50]}")


if __name__ == "__main__":
    main()
