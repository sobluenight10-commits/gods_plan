"""News & Sentiment Monitor — multi-source sector sentiment scoring.

Sources:
  1. ranto28 Naver RSS (existing)
  2. Yahoo Finance news per ticker
  3. Google News RSS sector feeds

Outputs per-sector sentiment scores: -100 (bearish) to +100 (bullish)
and a ticker-level news summary.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from skills.base import SkillRunner, BERLIN

logger = logging.getLogger("olympus.skills.sentiment")

SECTOR_MAP = {
    "PLTR": "Intelligence", "TSM": "Intelligence", "000660.KS": "Intelligence",
    "NVDA": "Intelligence", "1810.HK": "Intelligence", "ASML": "Infra",
    "AMAT": "Infra", "COHR": "Infra",
    "UEC": "Energy", "URNM": "Energy", "CCJ": "Energy", "OKLO": "Energy",
    "UUUU": "Energy", "CWEN": "Energy",
    "RKLB": "Space", "PL": "Space", "ASTS": "Space",
    "BEAM": "Bio", "NTLA": "Bio", "CRSP": "Bio", "TMO": "Bio",
    "KTOS": "Defense", "272210.KS": "Defense",
    "ARKQ": "Robotics", "BOTZ": "Robotics",
    "VRT": "Infra", "NTR": "Global", "FCX": "Global",
    "MC.PA": "Luxury", "IAU": "Tactical",
}

BULLISH_KEYWORDS = [
    "upgrade", "beat", "beats", "raised", "raises", "outperform", "strong",
    "growth", "surge", "record", "breakout", "rally", "bullish", "buy",
    "expansion", "exceeded", "approval", "partnership", "contract",
    "backlog", "milestone", "breakthrough",
]

BEARISH_KEYWORDS = [
    "downgrade", "miss", "misses", "cut", "cuts", "warning", "weak",
    "decline", "crash", "selloff", "bearish", "sell", "layoff",
    "bankruptcy", "default", "investigation", "lawsuit", "delay",
    "recall", "loss", "losses", "dilution", "headwinds",
]


def _score_headline(headline: str) -> int:
    """Score a headline: positive for bullish, negative for bearish."""
    h = headline.lower()
    score = 0
    for kw in BULLISH_KEYWORDS:
        if kw in h:
            score += 1
    for kw in BEARISH_KEYWORDS:
        if kw in h:
            score -= 1
    return max(-3, min(3, score))


class NewsSentiment(SkillRunner):
    name = "sentiment"

    def __init__(self, universe: Optional[Dict] = None):
        super().__init__()
        if universe is None:
            from fetch_data import UNIVERSE
            universe = UNIVERSE
        self.universe = universe

    def run_all(self, tickers: Optional[List[str]] = None) -> Dict[str, Any]:
        tickers = tickers or list(self.universe.keys())
        ticker_news = {}
        sector_scores = {}

        ranto = self._fetch_ranto28()
        yahoo = self._fetch_yahoo_news(tickers)
        google = self._fetch_google_sector_news()

        for tk in tickers:
            items = []
            for src in [ranto, yahoo, google]:
                items.extend([n for n in src if tk in n.get("tickers", [])])
            ticker_news[tk] = {
                "count": len(items),
                "headlines": [n["title"] for n in items[:5]],
                "net_sentiment": sum(n.get("score", 0) for n in items),
            }

        for tk in tickers:
            sector = SECTOR_MAP.get(tk, "Other")
            if sector not in sector_scores:
                sector_scores[sector] = {"total": 0, "count": 0, "tickers": []}
            ns = ticker_news[tk]["net_sentiment"]
            sector_scores[sector]["total"] += ns
            sector_scores[sector]["count"] += 1
            sector_scores[sector]["tickers"].append(tk)

        for sec in sector_scores:
            cnt = sector_scores[sec]["count"]
            sector_scores[sec]["avg_sentiment"] = (
                round(sector_scores[sec]["total"] / cnt, 1) if cnt > 0 else 0
            )
            raw = sector_scores[sec]["avg_sentiment"]
            sector_scores[sec]["signal"] = (
                "BULLISH" if raw > 1 else "BEARISH" if raw < -1 else "NEUTRAL"
            )

        output = {
            "run_date": datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M"),
            "total_tickers": len(tickers),
            "total_articles": sum(t["count"] for t in ticker_news.values()),
            "ticker_news": ticker_news,
            "sector_sentiment": sector_scores,
        }
        self.save(output)
        return output

    def run_single(self, ticker: str) -> Dict[str, Any]:
        yahoo = self._fetch_yahoo_news([ticker])
        items = [n for n in yahoo if ticker in n.get("tickers", [])]
        return {
            "ticker": ticker,
            "count": len(items),
            "headlines": [n["title"] for n in items[:10]],
            "net_sentiment": sum(n.get("score", 0) for n in items),
        }

    def _fetch_ranto28(self) -> List[Dict]:
        try:
            from fetch_data import get_ranto28
            posts = get_ranto28()
            results = []
            for p in posts:
                tickers = p.get("affected_tickers", [])
                score = _score_headline(p.get("title", ""))
                results.append({
                    "source": "ranto28",
                    "title": p.get("title", ""),
                    "tickers": tickers,
                    "score": score,
                    "date": p.get("date", ""),
                })
            return results
        except Exception as e:
            logger.warning(f"ranto28 fetch failed: {e}")
            return []

    def _fetch_yahoo_news(self, tickers: List[str]) -> List[Dict]:
        results = []
        try:
            import yfinance as yf
        except ImportError:
            return results

        for tk in tickers:
            try:
                t = yf.Ticker(tk)
                news = t.news or []
                for item in news[:5]:
                    title = item.get("title", "")
                    score = _score_headline(title)
                    results.append({
                        "source": "yahoo",
                        "title": title,
                        "tickers": [tk],
                        "score": score,
                        "date": "",
                    })
            except Exception:
                continue
        return results

    def _fetch_google_sector_news(self) -> List[Dict]:
        """Fetch sector-level news from Google News RSS."""
        results = []
        sector_queries = {
            "Energy": "uranium+nuclear+energy",
            "Intelligence": "artificial+intelligence+semiconductor",
            "Space": "space+launch+satellite",
            "Bio": "gene+therapy+biotech",
            "Defense": "defense+drones+military",
        }
        try:
            import requests
        except ImportError:
            return results

        for sector, query in sector_queries.items():
            try:
                url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
                r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                if not r.ok:
                    continue
                items = re.findall(r"<item>(.*?)</item>", r.text, re.DOTALL)
                for item in items[:5]:
                    title_m = re.search(r"<title>(.*?)</title>", item)
                    title = title_m.group(1).strip() if title_m else ""
                    title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title)
                    score = _score_headline(title)
                    sector_tickers = [
                        tk for tk, sec in SECTOR_MAP.items() if sec == sector
                    ]
                    results.append({
                        "source": "google",
                        "title": title,
                        "tickers": sector_tickers,
                        "score": score,
                        "date": "",
                    })
            except Exception:
                continue
        return results
