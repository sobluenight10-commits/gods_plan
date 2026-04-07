"""
🔱 OLYMPUS — SEC Form 4 Insider Monitor
Free real-time signal: when insiders at GOD's portfolio companies buy shares,
Minerva alerts immediately via Telegram.

Form 4 = insider transactions filed with SEC within 2 business days.
Insider buying is one of the highest-conviction free signals available.
Insider selling = ignore (tax, diversification). Insider buying = signal.

Runs as part of the news pulse cycle — no extra cron needed.
Called from battle_rhythm.py run_news_pulse() every 2 hours.
"""

import requests
import json
import os
import logging
from datetime import datetime, timedelta
from typing import List, Dict

logger = logging.getLogger("titan_k.insider")

SEC_FORM4_URL = "https://efts.sec.gov/LATEST/search-index?q=%22form+4%22&dateRange=custom&startdt={start}&enddt={end}&forms=4"
SEC_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&forms=4&dateRange=custom&startdt={start}&enddt={end}"
SEC_RSS_BASE   = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=5&search_text=&output=atom"

INSIDER_CACHE_PATH = os.path.join("data", "insider_cache.json")

# CIK mapping for GOD's portfolio (SEC Central Index Key)
# Only US-listed stocks have SEC filings
PORTFOLIO_CIK = {
    "PLTR":  "0001321655",
    "IONQ":  "0001840292",
    "UEC":   "0001334978",
    "URNM":  "0001524814",
    "RKLB":  "0001819989",
    "ASTS":  "0001836935",
    "CRSP":  "0001674930",
    "NTLA":  "0001576354",
    "BEAM":  "0001785599",
    "KTOS":  "0001069258",
    "AVAV":  "0001028918",
    "COHR":  "0000021510",
    "TMO":   "0000097745",
    "AMAT":  "0000796343",
    "NTR":   "0001725057",
    "FCX":   "0000831259",
    "VRT":   "0001739942",
    "OKLO":  "0001849821",
    "CCJ":   "0000016160",
    "NVDA":  "0001045810",
    "TSM":   "0001046179",
    "ARKQ":  "0001779374",
}


def _load_cache() -> Dict:
    if os.path.exists(INSIDER_CACHE_PATH):
        try:
            with open(INSIDER_CACHE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen_accessions": [], "last_check": None}


def _save_cache(cache: Dict):
    os.makedirs("data", exist_ok=True)
    with open(INSIDER_CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


def _fetch_form4_for_ticker(ticker: str, cik: str, days_back: int = 2) -> List[Dict]:
    """Fetch recent Form 4 filings for a specific company from SEC EDGAR."""
    filings = []
    headers = {
        "User-Agent": "OLYMPUS Investment System contact@olympus.ai",
        "Accept": "application/json",
    }

    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    url = f"https://efts.sec.gov/LATEST/search-index?q=%22{cik}%22&forms=4&dateRange=custom&startdt={start_date}&enddt={end_date}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return filings

        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])

        for hit in hits[:5]:
            source = hit.get("_source", {})
            accession = hit.get("_id", "")
            filed = source.get("file_date", "")
            entity = source.get("entity_name", "")
            form_type = source.get("form_type", "")

            if form_type != "4":
                continue

            filings.append({
                "ticker": ticker,
                "accession": accession,
                "filed": filed,
                "entity": entity,
                "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=4&dateb=&owner=include&count=5",
            })

    except Exception as e:
        logger.debug(f"SEC fetch failed for {ticker}: {e}")

    return filings


def _parse_transaction_detail(accession: str) -> Dict:
    """
    Parse the actual Form 4 XML to get transaction type and shares.
    Returns dict with: transaction_code, shares, price_per_share, acquired_or_disposed
    """
    # Convert accession number to URL format
    acc_clean = accession.replace("-", "")
    if len(acc_clean) < 18:
        return {}

    cik_part = acc_clean[:10].lstrip("0")
    acc_formatted = f"{acc_clean[:10]}-{acc_clean[10:12]}-{acc_clean[12:]}"
    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_part}/{acc_clean}/{acc_formatted}.xml"

    headers = {"User-Agent": "OLYMPUS Investment System contact@olympus.ai"}

    try:
        resp = requests.get(xml_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {}

        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.content)

        # Extract non-derivative transactions (actual stock purchases)
        transactions = []
        for trans in root.findall(".//nonDerivativeTransaction"):
            code_el = trans.find(".//transactionCode")
            shares_el = trans.find(".//transactionShares/value")
            price_el = trans.find(".//transactionPricePerShare/value")
            aod_el = trans.find(".//transactionAcquiredDisposedCode/value")

            if code_el is not None and shares_el is not None:
                transactions.append({
                    "code": code_el.text,              # P=Purchase, S=Sale, etc.
                    "shares": shares_el.text,
                    "price": price_el.text if price_el is not None else "?",
                    "acquired": aod_el.text if aod_el is not None else "?",  # A=Acquired, D=Disposed
                })

        # Also get insider name
        name_el = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
        title_el = root.find(".//reportingOwner/reportingOwnerRelationship/officerTitle")

        return {
            "transactions": transactions,
            "insider_name": name_el.text if name_el is not None else "Unknown",
            "insider_title": title_el.text if title_el is not None else "",
        }

    except Exception as e:
        logger.debug(f"Form 4 XML parse failed: {e}")
        return {}


def scan_insider_filings() -> List[Dict]:
    """
    Main entry point. Scans all portfolio tickers for new Form 4 BUY transactions.
    Returns list of actionable insider buy signals.
    Returns empty list if no new buys found.
    """
    cache = _load_cache()
    seen = set(cache.get("seen_accessions", []))
    signals = []

    for ticker, cik in PORTFOLIO_CIK.items():
        filings = _fetch_form4_for_ticker(ticker, cik, days_back=3)

        for filing in filings:
            acc = filing["accession"]
            if acc in seen:
                continue

            # Parse the actual transaction
            detail = _parse_transaction_detail(acc)
            if not detail:
                seen.add(acc)
                continue

            # Filter: only insider BUYS (code P = Purchase, A = Acquired)
            buys = [
                t for t in detail.get("transactions", [])
                if t.get("code") == "P" or t.get("acquired") == "A"
            ]

            if buys:
                total_shares = sum(
                    float(b.get("shares", 0)) for b in buys
                    if b.get("shares", "").replace(".", "").isdigit()
                )
                avg_price = buys[0].get("price", "?") if buys else "?"

                signals.append({
                    "ticker": ticker,
                    "insider": detail.get("insider_name", "Unknown"),
                    "title": detail.get("insider_title", ""),
                    "shares": total_shares,
                    "price": avg_price,
                    "filed": filing["filed"],
                    "url": filing["url"],
                })
                logger.info(f"Insider BUY: {ticker} · {detail.get('insider_name')} · {total_shares} shares @ ${avg_price}")

            seen.add(acc)

    # Update cache
    cache["seen_accessions"] = list(seen)[-500:]  # keep last 500
    cache["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save_cache(cache)

    return signals


def format_insider_telegram(signals: List[Dict]) -> str:
    """Format insider buy signals for Telegram."""
    if not signals:
        return ""

    lines = ["🔍 <b>INSIDER BUYING DETECTED</b>"]
    lines.append("SEC Form 4 · Free signal · High conviction\n")

    for s in signals:
        ticker = s["ticker"]
        insider = s["insider"]
        title = s["title"]
        shares = f"{int(s['shares']):,}" if s["shares"] else "?"
        price = s["price"]
        filed = s["filed"]

        role = f" ({title})" if title else ""
        lines.append(
            f"<b>{ticker}</b> · {insider}{role}\n"
            f"  Bought {shares} shares @ ${price}\n"
            f"  Filed: {filed} · <a href=\"{s['url']}\">SEC filing</a>\n"
        )

    lines.append("💡 Insider buying = highest-conviction free signal.")
    lines.append("Scale-Aware Rule: no paid flow needed at current dry powder level.")

    return "\n".join(lines)
