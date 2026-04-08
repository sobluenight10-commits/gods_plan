"""
Blog Monitor — Background thread that polls ranto28 RSS on a fixed interval.
When a new post is detected, sends an immediate Telegram alert + GPT analysis.
"""
import logging
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


def _send_alert(post: dict):
    """Send Telegram alert for a new blog post, with optional GPT summary."""
    from telegram_bot import send_telegram

    title = post.get("title", "")
    url = post.get("url", "")
    date = post.get("date", "")

    lines = [
        "📰 *NEW BLOG POST DETECTED*",
        "",
        f"📌 *{title}*",
        f"📅 {date}",
        f"🔗 {url}",
        "",
    ]

    # Try quick GPT analysis
    try:
        from scraper import _fetch_post_content
        content = _fetch_post_content(url)
        if content and len(content) > 100:
            from analyzer import analyze_post
            result = analyze_post({
                "title": title, "url": url, "date": date,
                "content": content, "source": "ranto28",
            })
            if not result.get("error"):
                insight = result.get("investment_insight", "")
                signal = result.get("watch_signal", "")
                keywords = ", ".join(result.get("keywords", [])[:5])
                companies = result.get("companies", [])

                lines.append(f"💡 *Insight:* {insight}")
                lines.append(f"📊 *Signal:* {signal}")
                lines.append(f"🔑 *Keywords:* {keywords}")

                if companies:
                    lines.append("")
                    lines.append("🏢 *Companies mentioned:*")
                    for c in companies[:5]:
                        gem = "💎" if c.get("hidden_gem") else ""
                        lines.append(
                            f"  {gem} {c.get('name','')} ({c.get('ticker','N/A')}) "
                            f"— Score: {c.get('titan_k_score','?')}/10 "
                            f"| {c.get('sentiment','').upper()}"
                        )
            else:
                lines.append("⚠️ GPT analysis failed — check manually")
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
