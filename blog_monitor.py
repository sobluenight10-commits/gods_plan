"""
Blog Monitor — Background thread that polls ranto28 RSS on a fixed interval.
When a new post is detected, sends an immediate Telegram alert + GPT analysis.
"""
import logging
import os
import time
import threading
import feedparser
from datetime import datetime

from config import NAVER_RSS_URL, NAVER_BLOG_ID, BLOG_FETCH_INTERVAL_MINUTES

logger = logging.getLogger("titan_k.blog_monitor")

CHECK_INTERVAL = max(60, int(BLOG_FETCH_INTERVAL_MINUTES) * 60)  # seconds; min 1 min
_seen_urls: set = set()
_started = False


def _check_for_new_posts():
    """Poll RSS and return list of posts not seen before."""
    global _seen_urls
    new_posts = []
    try:
        feed = feedparser.parse(NAVER_RSS_URL)
        for entry in feed.entries[:10]:
            url = entry.get("link", "")
            if url in _seen_urls:
                continue
            _seen_urls.add(url)

            pub_date = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6])

            # RSS uses entry.link; we normalize to "url". Publish time → "date" (not "link"/"published").
            new_posts.append({
                "title": entry.get("title", "Untitled"),
                "url": url,
                "date": pub_date.strftime("%Y-%m-%d %H:%M") if pub_date else "",
            })
    except Exception as e:
        logger.error(f"RSS check failed: {e}")
    return new_posts


def _seed_seen():
    """On first run, mark all current posts as 'seen' so we don't spam."""
    global _seen_urls
    try:
        feed = feedparser.parse(NAVER_RSS_URL)
        for entry in feed.entries[:20]:
            _seen_urls.add(entry.get("link", ""))
        logger.info(f"Blog monitor seeded with {len(_seen_urls)} existing posts")
    except Exception as e:
        logger.error(f"Seed failed: {e}")


def _extract_and_register_tickers(post_content: str, post_title: str) -> None:
    """Extract tickers from blog post, classify into OLYMPUS sectors, alert GOD."""
    import json
    import re

    from analyzer import client
    from price_alert import _send_thesis_plain

    _VALID_SECTORS = frozenset({
        "INTELLIGENCE", "ENERGY", "SPACE", "BIO", "ROBOTICS", "INFRASTRUCTURE", "RADAR",
    })

    try:
        prompt = f"""You are Minerva, analyst for the OLYMPUS investment system.
Extract all stocks and companies mentioned in this Korean financial blog post.
For each stock, classify it into exactly ONE of these 7 sectors:

1. INTELLIGENCE — AI, semiconductors, quantum computing, neural interfaces, advanced memory
2. ENERGY — Uranium, nuclear, oil, gas, solid-state batteries
3. SPACE — Rockets, satellites, orbital infrastructure, lunar economy
4. BIO — CRISPR, gene editing, longevity, AI drug discovery
5. ROBOTICS — Humanoids, defense drones, autonomous systems, weapons
6. INFRASTRUCTURE — Photonics, data center power, semiconductor equipment, copper
7. RADAR — Geopolitical plays, commodities, macro trades, does not fit above 6

Return ONLY a JSON array. No explanation. Example:
[{{"ticker":"TSM","name":"TSMC","sector":"INTELLIGENCE"}},{{"ticker":"UEC","name":"Uranium Energy","sector":"ENERGY"}}]

Use US ticker format. Korean stocks: 005930.KS format.
If no stocks found return [].

Title: {post_title}
Content: {post_content[:2000]}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.2,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw, count=1)
            raw = re.sub(r"\s*```\s*$", "", raw)
        stocks = json.loads(raw)

        if not isinstance(stocks, list) or not stocks:
            return

        stocks = [
            s for s in stocks
            if isinstance(s, dict) and s.get("ticker") and str(s["ticker"]).strip()
        ]
        for s in stocks:
            sec = str(s.get("sector", "RADAR")).strip().upper()
            s["sector"] = sec if sec in _VALID_SECTORS else "RADAR"

        if not stocks:
            return

        cache_path = os.path.join(os.path.dirname(__file__), "data", "blog_tickers.json")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {"tickers": [], "by_sector": {}, "history": []}

        if "tickers" not in existing:
            existing["tickers"] = []
        if "by_sector" not in existing:
            existing["by_sector"] = {}
        if "history" not in existing:
            existing["history"] = []

        new_stocks = [s for s in stocks if s["ticker"] not in existing["tickers"]]

        if new_stocks:
            for s in new_stocks:
                existing["tickers"].append(s["ticker"])
                sector = s.get("sector", "RADAR")
                if sector not in existing["by_sector"]:
                    existing["by_sector"][sector] = []
                existing["by_sector"][sector].append({
                    "ticker": s["ticker"],
                    "name": s.get("name", ""),
                    "added": datetime.now().strftime("%Y-%m-%d"),
                    "source": post_title[:60],
                })

            existing["history"].append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "post": post_title[:60],
                "added": [s["ticker"] for s in new_stocks],
            })

            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)

            by_sector = {}
            for s in new_stocks:
                sec = s.get("sector", "RADAR")
                label = f"{s['ticker']} ({s.get('name', '')})"
                by_sector.setdefault(sec, []).append(label)

            sector_icons = {
                "INTELLIGENCE": "🧠", "ENERGY": "⚡", "SPACE": "🚀",
                "BIO": "🧬", "ROBOTICS": "🤖", "INFRASTRUCTURE": "🏗",
                "RADAR": "📡",
            }

            msg = f"📡 BLOG TICKER DETECTED\n"
            msg += f"Post: {post_title[:50]}\n\n"
            for sec, labels in by_sector.items():
                icon = sector_icons.get(sec, "📌")
                msg += f"{icon} {sec}: {', '.join(labels)}\n"
            msg += f"\nTotal blog watchlist: {len(existing['tickers'])} stocks"
            _send_thesis_plain(msg)

    except Exception as e:
        logger.warning(f"Ticker extraction failed: {e}")


def _send_alert(post: dict):
    """Send Telegram alert for a new blog post, with optional GPT summary."""
    from html import escape

    from analyzer import client
    from telegram_bot import send_telegram

    title = post.get("title", "")
    url = post.get("url", "")
    # _check_for_new_posts() sets "date"; allow "published" as alias for other callers
    date = post.get("date") or post.get("published", "")

    lines = [
        "📰 <b>NEW BLOG POST DETECTED</b>",
        "",
        f"📌 <b>{escape(title)}</b>",
        f"📅 {escape(date)}",
        f'🔗 <a href="{escape(url)}">{escape(url)}</a>' if url else "",
        "",
    ]

    try:
        from scraper import _fetch_post_content
        content = _fetch_post_content(url)
        if content and len(content) > 100:
            prompt = f"""You are Minerva, investment analyst for GOD's OLYMPUS system.
Analyze this blog post and return ONLY this format, nothing else:

📰 [3-5 word title]
🔑 [2-3 core keywords separated by ·]
📊 SO WHAT: [1 sentence — exact market impact]
🎯 STOCKS: [ticker1, ticker2] or NONE
⏱ TIMING: [BUY NOW / WATCH / AVOID / HOLD]
📈 IF RELEVANT — 1M: $X · 6M: $X · 1Y: $X · 5Y: $X

Blog post:
Title: {post.get('title')}
Content: {content[:1500]}
"""
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )
            gpt_text = (response.choices[0].message.content or "").strip()
            if gpt_text:
                lines.append(escape(gpt_text))
            else:
                lines.append("⚠️ GPT returned empty — check manually")
            _extract_and_register_tickers(content, post.get("title", "") or title)
        else:
            lines.append("⚠️ Could not fetch content — check manually")
    except Exception as e:
        logger.error(f"Alert analysis error: {e}")
        lines.append("⚠️ Analysis skipped")

    send_telegram("\n".join(lines))
    logger.info(f"Alert sent: {title[:60]}")


def _monitor_loop():
    """Background loop: check RSS every CHECK_INTERVAL seconds."""
    _seed_seen()
    logger.info(f"Blog monitor active. Checking every {CHECK_INTERVAL // 60} min.")

    while True:
        time.sleep(CHECK_INTERVAL)
        try:
            new_posts = _check_for_new_posts()
            if new_posts:
                logger.info(f"New posts detected: {len(new_posts)}")
                for post in new_posts:
                    _send_alert(post)
        except Exception as e:
            logger.error(f"Monitor loop error: {e}")


def start_blog_monitor():
    """Start blog monitor in a daemon thread. Safe to call multiple times."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Thread(target=_monitor_loop, daemon=True, name="blog_monitor")
    t.start()
    logger.info("Blog monitor thread started")
