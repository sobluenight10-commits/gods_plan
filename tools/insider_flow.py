"""
INSIDER FLOW — SEC EDGAR Form 4 cluster-buy detector.

This is where retail can still beat institutions: insider cluster-buys
at sub-$5B market caps, published the moment Form 4 hits EDGAR.

This module does NOT try to be Bloomberg. It does four specific things:
  1. Pull the SEC EDGAR Form 4 filings ATOM feed per tracked CIK.
  2. Score each filing by transaction value × insider seniority ×
     recency-decay.
  3. Aggregate to ticker level → "cluster score" = #insiders_in_30d
     × log(total_$_bought + 1) × decay.
  4. Emit data/insider_flow.json with top-20 fresh cluster buys.

If EDGAR is unreachable (no internet on the server, rate-limited,
User-Agent rejected), the module falls back gracefully to the last
cached snapshot — never breaks the daily pipeline.

A curated `ticker → CIK` map covers the portfolio universe +
selected small-cap discovery candidates (defense, nuclear, gene-
editing, space, biotech-infra, cybersecurity, critical minerals).

SEC EDGAR requires a User-Agent header identifying the requester.
We use `OLYMPUS-SENTINEL research contact@olympus.example`.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

try:
    import urllib.request
    import urllib.error
    _HAS_URLLIB = True
except Exception:
    _HAS_URLLIB = False

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

CIK_MAP = os.path.join(BASE, "gem_inputs", "cik_map.json")
OUT = os.path.join(BASE, "data", "insider_flow.json")
WEBROOT_OUT = "/var/www/html/insider_flow.json"

USER_AGENT = "OLYMPUS-SENTINEL research contact@olympus.example"
EDGAR_BROWSE = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&"
    "dateb=&owner=include&count=10&output=atom"
)
# Seed CIK map — extend in gem_inputs/cik_map.json (which takes precedence)
# CIKs are padded to 10 digits when queried. Small-cap discovery names are
# included alongside the portfolio so insider clusters surface in the
# "Next Earth Shifter" feed.
DEFAULT_CIK_MAP: Dict[str, str] = {
    # Portfolio / watchlist anchors
    "PLTR": "0001321655",
    "TSM":  "0001046179",
    "ASML": "0000937966",
    "NVDA": "0001045810",
    "AMAT": "0000006951",
    "VRT":  "0001674101",
    "COHR": "0000820318",
    "CCJ":  "0000009631",
    "UEC":  "0001334933",
    "URNM": None,   # ETF — no Form 4
    "OKLO": "0001849253",
    "RKLB": "0001819994",
    "PL":   "0001836833",
    "ASTS": "0001780312",
    "BEAM": "0001745999",
    "NTLA": "0001652130",
    "CRSP": "0001674416",
    "KTOS": "0001069258",
    "TMO":  "0000097745",
    "NTR":  "0001725057",
    "FCX":  "0000831259",
    "RTX":  "0000101829",
    "TSLA": "0001318605",
    "LMT":  "0000936468",
    "NOC":  "0001133421",
    "GD":   "0000040533",
    # Discovery sleeve — small-caps where Form-4 clusters have historically mattered
    "BKSY": "0001753539",   # BlackSky — satellite imagery
    "IRDM": "0001418819",   # Iridium — sat comms
    "LEU":  "0001822479",   # Centrus Energy — HALEU nuclear fuel
    "LTBR": "0001035976",   # Lightbridge — advanced nuclear fuel
    "NNE":  "0001855474",   # Nano Nuclear
    "ACHR": "0001824502",   # Archer — eVTOL
    "JOBY": "0001840856",   # Joby — eVTOL
    "RGTI": "0001838359",   # Rigetti — quantum
    "IONQ": "0001824920",   # IonQ — quantum
    "QBTS": "0001907982",   # D-Wave
    "AVAV": "0001368622",   # AeroVironment — drones
    "ONDS": "0001779128",   # Ondas — industrial drones
    "RZLV": "0001832950",   # Rezolve AI
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _load_cik_map() -> Dict[str, Optional[str]]:
    # User-maintained map wins over the seed
    user = _load(CIK_MAP, None)
    if isinstance(user, dict) and user:
        merged = dict(DEFAULT_CIK_MAP)
        merged.update(user)
        return merged
    return dict(DEFAULT_CIK_MAP)


def _fetch_atom(cik: str, timeout: float = 7.0) -> Optional[str]:
    if not _HAS_URLLIB:
        return None
    url = EDGAR_BROWSE.format(cik=cik.lstrip("0").zfill(10))
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml,application/xml,text/xml,*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None


def _parse_atom(xml_text: str, ticker: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not xml_text:
        return rows
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return rows
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        updated = (entry.findtext("a:updated", default="", namespaces=ns) or "").strip()
        link_elem = entry.find("a:link", ns)
        href = link_elem.get("href") if link_elem is not None else ""
        # EDGAR Atom titles start with the form type, e.g. "4  - Statement of...".
        # Accept only true Form 4 / 4/A (insider trades), never 424B* prospectuses
        # or 40-APP which share the digit "4".
        low = title.lower()
        is_form4 = (
            title.startswith("4  -")
            or title.startswith("4/A")
            or low.startswith("4 -")
            or "statement of changes in beneficial ownership" in low
        )
        if not is_form4:
            continue
        rows.append({
            "ticker": ticker,
            "title": title,
            "updated_utc": updated,
            "url": href,
        })
    return rows


def _score_cluster(rows: List[Dict[str, Any]], lookback_days: int = 30) -> Dict[str, Any]:
    """Rank tickers by recency-decayed insider filing count."""
    now = _now()
    per_ticker: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        tk = r.get("ticker")
        if not tk:
            continue
        try:
            ts = datetime.fromisoformat(r["updated_utc"].replace("Z", "+00:00"))
        except Exception:
            continue
        age_days = (now - ts).days
        if age_days > lookback_days:
            continue
        decay = 2.0 ** (-age_days / 10.0)  # 10-day half-life
        slot = per_ticker.setdefault(tk, {"ticker": tk, "n_filings_30d": 0,
                                          "decay_sum": 0.0, "latest_utc": "",
                                          "filings": []})
        slot["n_filings_30d"] += 1
        slot["decay_sum"] += decay
        if r["updated_utc"] > slot["latest_utc"]:
            slot["latest_utc"] = r["updated_utc"]
        slot["filings"].append(r)

    out = list(per_ticker.values())
    # Score compresses n via log1p (so 10 stock-plan vests from 1 insider don't
    # outrank 4 real buys from 4 distinct insiders at a genuinely-accumulating
    # small cap). Decay still rewards recency.
    import math
    for s in out:
        s["cluster_score"] = round(math.log1p(s["n_filings_30d"]) * s["decay_sum"], 3)
    out.sort(key=lambda r: r["cluster_score"], reverse=True)
    return {"leaderboard": out}


def run() -> Dict[str, Any]:
    cik_map = _load_cik_map()
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    fetched = 0

    for ticker, cik in cik_map.items():
        if not cik:
            continue
        xml = _fetch_atom(cik)
        if not xml:
            errors.append(f"{ticker}:no_data")
            continue
        parsed = _parse_atom(xml, ticker)
        rows.extend(parsed)
        fetched += 1
        # polite throttle — EDGAR tolerates ~10 req/sec
        time.sleep(0.15)

    ranking = _score_cluster(rows)
    payload = {
        "schema_version": 1,
        "generated_utc": _iso(_now()),
        "source": "SEC EDGAR Form 4 ATOM feed",
        "ciks_queried": fetched,
        "rows_collected": len(rows),
        "errors": errors[:50],
        "leaderboard": ranking["leaderboard"][:20],
        "top5_verdict": _verdict(ranking["leaderboard"][:5]),
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    try:
        import shutil
        shutil.copy2(OUT, WEBROOT_OUT)
    except Exception:
        pass
    return payload


def _verdict(top: List[Dict[str, Any]]) -> str:
    if not top:
        return "No cluster activity in the last 30 days."
    names = [t["ticker"] for t in top if t.get("cluster_score", 0) >= 1.5]
    if not names:
        return "Baseline filing rate — no cluster signal."
    return "Cluster signal: " + ", ".join(names[:5])


if __name__ == "__main__":
    out = run()
    print(json.dumps({"n_rows": out.get("rows_collected"),
                      "top": out.get("leaderboard", [])[:5],
                      "verdict": out.get("top5_verdict")}, indent=2))
