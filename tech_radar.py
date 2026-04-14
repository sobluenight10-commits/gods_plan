"""
OLYMPUS Tech Radar — RSS ingest from major tech sources + HN search feeds.
Scores headlines for product/model/chip/AI launches, dedupes, writes directives + Telegram.

Keeps the system aware of externally announced tech without manual paste.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import feedparser
import requests

logger = logging.getLogger("titan_k.tech_radar")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SEEN_PATH = os.path.join(DATA_DIR, "tech_radar_seen.json")
PULSE_PATH = os.path.join(DATA_DIR, "tech_pulse.json")
DIRECTIVES_PATH = os.path.join(DATA_DIR, "directives.json")

try:
    from config import (
        TECH_RADAR_FEEDS,
        TECH_RADAR_INTERVAL_MINUTES,
        TECH_RADAR_SCORE_ALERT,
        TECH_RADAR_MAX_ITEMS,
        PORTFOLIO_TECH_TICKERS,
    )
except Exception:
    TECH_RADAR_INTERVAL_MINUTES = 30
    TECH_RADAR_SCORE_ALERT = 8
    TECH_RADAR_MAX_ITEMS = 24
    PORTFOLIO_TECH_TICKERS = (
        "TSM", "NVDA", "ASML", "AMD", "PLTR", "ARM", "INTC", "QCOM", "AVGO",
        "MU", "COHR", "VRT", "RKLB", "AMAT",
    )
    TECH_RADAR_FEEDS = []

# Default feed list if env empty — kept in code so repo self-documents; override via config.
_DEFAULT_FEEDS = [
    "https://hnrss.org/frontpage",
    "https://hnrss.org/newest?q=AI+OR+GPU+OR+LLM+OR+TSMC+OR+CUDA&count=20",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://arstechnica.com/feed/",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
]

_SIGNAL_WORDS: List[Tuple[str, int]] = [
    (r"\blaunch(?:es|ed|ing)?\b", 4),
    (r"\breleased?\b", 3),
    (r"\bannounc(?:es|ed|ing)\b", 3),
    (r"\bintroduces?\b", 3),
    (r"\bopen[- ]source[sd]?\b", 3),
    (r"\bgenerative\b", 2),
    (r"\bmodel\b", 1),
    (r"\bchip\b", 2),
    (r"\bgpu\b", 2),
    (r"\bcuda\b", 2),
    (r"\bllm\b", 2),
    (r"\btransformer\b", 2),
    (r"\bfusion\b", 2),
    (r"\bquantum\b", 2),
    (r"\bbreakthrough\b", 2),
    (r"\broadmap\b", 1),
    (r"\btsmc\b", 2),
    (r"\bnvidia\b", 2),
    (r"\basml\b", 2),
    (r"\b5nm\b|\b3nm\b|\b2nm\b", 3),
]

UA = (
    "Mozilla/5.0 (compatible; OLYMPUS-TechRadar/1.0; +https://github.com/) "
    "Python-requests"
)


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _feed_urls() -> List[str]:
    if TECH_RADAR_FEEDS and len(TECH_RADAR_FEEDS) > 0:
        return list(TECH_RADAR_FEEDS)
    return list(_DEFAULT_FEEDS)


def _score_entry(title: str, summary: str) -> Tuple[int, List[str]]:
    text = f"{title}\n{summary}".lower()
    score = 0
    hits: List[str] = []
    for pat, w in _SIGNAL_WORDS:
        if re.search(pat, text, re.I):
            score += w
            hits.append(pat.replace("\\b", "")[:32])
    for t in PORTFOLIO_TECH_TICKERS:
        if len(t) >= 2 and re.search(r"\b" + re.escape(t.lower()) + r"\b", text, re.I):
            score += 4
            hits.append(f"ticker:{t}")
    return score, hits


def _entry_id(link: str) -> str:
    return hashlib.sha256((link or "").encode()).hexdigest()[:20]


def _fetch_feed(url: str, timeout: int = 22) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.text


def run_tech_radar_scan(send_telegram_high: bool = True) -> Dict[str, Any]:
    """
    Poll feeds, update tech_pulse.json + directives.tech_radar, optional Telegram for high scores.
    """
    seen = _load_json(SEEN_PATH, {"ids": [], "alerted": {}})
    ids = set(seen.get("ids") or [])
    alerted = dict(seen.get("alerted") or {})

    new_items: List[Dict[str, Any]] = []
    for url in _feed_urls():
        try:
            xml = _fetch_feed(url)
        except Exception as e:
            logger.warning("tech_radar fetch %s: %s", url[:48], e)
            continue
        parsed = feedparser.parse(xml)
        host = urlparse(url).netloc or "feed"
        for e in parsed.entries[:40]:
            link = (getattr(e, "link", None) or "").strip()
            title = (getattr(e, "title", None) or "").strip()
            if not link or not title:
                continue
            eid = _entry_id(link)
            if eid in ids:
                continue
            summ = ""
            if e.get("summary"):
                summ = re.sub(r"<[^>]+>", "", str(e.summary))[:400]
            score, hits = _score_entry(title, summ)
            ids.add(eid)
            item = {
                "id": eid,
                "title": title,
                "link": link,
                "score": score,
                "hits": hits[:8],
                "source": host,
                "feed": url[:80],
                "summary": summ[:280],
                "seen_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            new_items.append(item)

    # merge new into pulse file (top by score)
    pulse = _load_json(PULSE_PATH, {"items": []})
    all_items: List[Dict] = list(pulse.get("items") or [])
    by_id = {x["id"]: x for x in all_items if x.get("id")}
    for it in new_items:
        by_id[it["id"]] = it
    merged = sorted(by_id.values(), key=lambda x: (-x.get("score", 0), x.get("seen_utc", "")))
    merged = merged[: max(TECH_RADAR_MAX_ITEMS * 2, 48)]

    out_pulse = {
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feeds_polled": len(_feed_urls()),
        "items": merged[:TECH_RADAR_MAX_ITEMS],
    }
    _save_json(PULSE_PATH, out_pulse)

    seen["ids"] = list(ids)[-8000:]
    _save_json(SEEN_PATH, seen)

    # directives
    d = _load_json(DIRECTIVES_PATH, {})
    d["tech_radar"] = {
        "updated_utc": out_pulse["updated_utc"],
        "headlines": [
            {"title": x["title"], "link": x["link"], "score": x["score"], "source": x["source"]}
            for x in out_pulse["items"][:12]
        ],
        "top_score": max((x.get("score", 0) for x in out_pulse["items"]), default=0),
        "engine": "tech_radar_v1",
    }
    si = d.get("system_intel") or {}
    si["tech_radar_engine"] = "v1"
    si["tech_radar_updated_utc"] = out_pulse["updated_utc"]
    d["system_intel"] = si
    _save_json(DIRECTIVES_PATH, d)

    # Telegram: only fresh high-signal not yet alerted
    if send_telegram_high and new_items:
        hot = [x for x in new_items if x.get("score", 0) >= TECH_RADAR_SCORE_ALERT]
        for x in sorted(hot, key=lambda z: -z.get("score", 0))[:3]:
            aid = x["id"]
            if alerted.get(aid):
                continue
            try:
                from telegram_bot import send_telegram

                send_telegram(
                    "🛰 <b>TECH RADAR — HIGH SIGNAL</b>\n"
                    f"Score <b>{x['score']}</b> · {x['source']}\n"
                    f"<b>{x['title'][:200]}</b>\n"
                    f"<a href=\"{x['link']}\">Open link</a>\n"
                    f"<i>{', '.join(x.get('hits', [])[:5])}</i>"
                )
                alerted[aid] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception as ex:
                logger.error("tech_radar telegram: %s", ex)
        seen["alerted"] = alerted
        seen["ids"] = list(ids)[-8000:]
        _save_json(SEEN_PATH, seen)

    logger.info("tech_radar: new=%s items stored=%s", len(new_items), len(out_pulse["items"]))
    return out_pulse
