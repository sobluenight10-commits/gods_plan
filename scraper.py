"""
🔱 titan_K v2 — Multi-Source Scraper (Upgraded)
Fetches from multiple sources with timeouts, retries, and concurrent fetching.

Sources:
  1. ranto28 Naver Blog (primary — Korean investment analysis)
  2. Yahoo Finance news for portfolio tickers
  3. Naver Finance / Google News KR (Korean market)
"""
import re
import logging
import concurrent.futures
from datetime import datetime, timedelta
from typing import List, Dict
from functools import partial

import requests
import feedparser
from bs4 import BeautifulSoup

from config import NAVER_BLOG_ID, naver_blog_rss_list

logger = logging.getLogger("titan_k.scraper")

# ── Constants ─────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT = 10  # seconds per request (was 15 — too slow)
MAX_CONTENT_LENGTH = 4000  # chars per article for GPT (was 8000 — token waste)
MAX_WORKERS = 4  # concurrent fetches

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 1: ranto28 Naver Blog
# ══════════════════════════════════════════════════════════════════════════════

def fetch_blog_posts(days_back: int = 1, max_posts: int = 5) -> List[Dict]:
    """Fetch ranto28 blog posts with timeout and retry."""
    posts = []
    cutoff = datetime.now() - timedelta(days=days_back)

    for attempt in range(2):
        try:
            posts = _fetch_rss(cutoff, max_posts)
            if posts:
                logger.info(f"RSS: {len(posts)} posts (attempt {attempt + 1})")
                break
        except Exception as e:
            logger.warning(f"RSS attempt {attempt + 1} failed: {e}")

    if not posts:
        try:
            posts = _fetch_scrape(cutoff, max_posts)
            logger.info(f"Scrape fallback: {len(posts)} posts")
        except Exception as e:
            logger.error(f"Scrape fallback failed: {e}")

    if posts:
        posts = _fetch_contents_parallel(posts)

    return posts


def _fetch_rss(cutoff: datetime, max_posts: int) -> List[Dict]:
    """Parse all configured Naver RSS feeds (primary + BLOG_EXTRA_RSS_URLS), merge, dedupe."""
    posts = []
    src_label = NAVER_BLOG_ID or "ranto28"
    for rss_url in naver_blog_rss_list():
        try:
            r = requests.get(rss_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            feed = feedparser.parse(r.text)
        except Exception as e:
            logger.warning("RSS fetch %s: %s", rss_url[:48], e)
            continue
        for entry in feed.entries[:max_posts * 3]:
            pub_date = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6])
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                pub_date = datetime(*entry.updated_parsed[:6])

            if pub_date and pub_date < cutoff:
                continue

            url = entry.get("link", "")
            if "redirect" in url:
                url = re.sub(r".*redirect.*url=", "", url)

            posts.append({
                "title": entry.get("title", "Untitled"),
                "url": url,
                "date": pub_date.strftime("%Y-%m-%d") if pub_date else "",
                "summary": _clean_html(entry.get("summary", "")),
                "content": "",
                "source": src_label,
            })

    seen = set()
    out = []
    for p in posts:
        u = (p.get("url") or "").split("?")[0]
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(p)
        if len(out) >= max_posts:
            break
    return out


def _fetch_scrape(cutoff: datetime, max_posts: int) -> List[Dict]:
    """Scrape blog directly with mobile URL."""
    posts = []
    mobile_url = f"https://m.blog.naver.com/{NAVER_BLOG_ID}"

    try:
        resp = requests.get(mobile_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Mobile blog fetch failed: {e}")
        return posts

    soup = BeautifulSoup(resp.text, "html.parser")
    links = soup.select("a[href*='logNo'], a.title_link, a.link__iGhSW, a.pcol2, a[class*='title']")

    for link in links[:max_posts]:
        href = link.get("href", "")
        title = link.get_text(strip=True)

        if not href or not title or len(title) < 4:
            continue

        if href.startswith("/"):
            href = f"https://m.blog.naver.com{href}"
        elif not href.startswith("http"):
            href = f"https://m.blog.naver.com/{NAVER_BLOG_ID}/{href}"

        posts.append({
            "title": title, "url": href,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "summary": "", "content": "", "source": "ranto28",
        })

    return posts


def _fetch_contents_parallel(posts: List[Dict]) -> List[Dict]:
    """Fetch article content concurrently."""
    def _fetch_one(post):
        if post.get("content"):
            return post
        try:
            post["content"] = _fetch_post_content(post["url"])
        except Exception as e:
            logger.warning(f"Content fetch failed for {post.get('title', '?')[:40]}: {e}")
            post["content"] = post.get("summary", "")
        return post

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(_fetch_one, posts))
    return results


def _fetch_post_content(url: str) -> str:
    """Fetch article text with timeout and selector fallbacks."""
    mobile_url = url.replace("blog.naver.com", "m.blog.naver.com")

    resp = requests.get(mobile_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    selectors = [
        "div.se-main-container", "div.__se_component_area",
        "div.post-view", "div#post-area",
        "div.sect_dsc", "div[class*='post_ct']", "article",
    ]

    content = ""
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            content = el.get_text(separator="\n", strip=True)
            break

    if not content:
        paragraphs = soup.select("p, span.se-text-paragraph")
        content = "\n".join(
            p.get_text(strip=True) for p in paragraphs
            if len(p.get_text(strip=True)) > 10
        )

    if len(content) > MAX_CONTENT_LENGTH:
        content = content[:MAX_CONTENT_LENGTH] + "\n[... truncated]"

    return content


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 2: Yahoo Finance News (for portfolio tickers)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_yahoo_news(tickers: List[str], max_per_ticker: int = 2) -> List[Dict]:
    """Fetch recent news headlines from Yahoo Finance."""
    all_news = []

    def _fetch_ticker_news(ticker: str) -> List[Dict]:
        items = []
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            news = stock.news or []
            for article in news[:max_per_ticker]:
                title = article.get("title", "")
                link = article.get("link", "")
                publisher = article.get("publisher", "")
                pub_time = article.get("providerPublishTime")
                date_str = ""
                if pub_time:
                    date_str = datetime.fromtimestamp(pub_time).strftime("%Y-%m-%d")

                if title:
                    items.append({
                        "title": title, "url": link,
                        "date": date_str,
                        "summary": f"[{publisher}] {title}",
                        "content": title,
                        "source": f"yahoo_{ticker}",
                        "ticker": ticker,
                    })
        except Exception as e:
            logger.warning(f"Yahoo news failed for {ticker}: {e}")
        return items

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        results = list(executor.map(_fetch_ticker_news, tickers))

    for items in results:
        all_news.extend(items)

    logger.info(f"Yahoo news: {len(all_news)} articles for {len(tickers)} tickers")
    return all_news


# ══════════════════════════════════════════════════════════════════════════════
# SOURCE 3: Naver Finance / Google News KR
# ══════════════════════════════════════════════════════════════════════════════

def fetch_naver_finance_news(max_articles: int = 5) -> List[Dict]:
    """Fetch Korean market news."""
    posts = []

    # Try Naver Finance API
    try:
        url = "https://m.stock.naver.com/api/news/list?category=mainnews&page=1&pageSize=10"
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            items = data if isinstance(data, list) else data.get("items", data.get("news", []))
            for item in items[:max_articles]:
                title = item.get("title", "") or item.get("tit", "")
                link = item.get("url", "") or item.get("link", "")
                if title:
                    posts.append({
                        "title": _clean_html(title), "url": link,
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "summary": _clean_html(title),
                        "content": _clean_html(title),
                        "source": "naver_finance",
                    })
    except Exception as e:
        logger.warning(f"Naver Finance news failed: {e}")

    # Fallback: Google News KR
    if not posts:
        try:
            feed = feedparser.parse(
                "https://news.google.com/rss/search?q=주식+시장&hl=ko&gl=KR&ceid=KR:ko"
            )
            for entry in feed.entries[:max_articles]:
                posts.append({
                    "title": entry.get("title", ""), "url": entry.get("link", ""),
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "summary": _clean_html(entry.get("summary", "")),
                    "content": entry.get("title", ""),
                    "source": "google_news_kr",
                })
        except Exception as e:
            logger.warning(f"Google News KR fallback failed: {e}")

    logger.info(f"KR news: {len(posts)} articles")
    return posts


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED FETCH (all sources)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_all_sources(days_back: int = 1, portfolio_tickers: List[str] = None) -> Dict:
    """Fetch from all sources concurrently with hard timeouts."""
    if portfolio_tickers is None:
        from config import get_all_tickers
        portfolio_tickers = get_all_tickers()

    news_tickers = [
        t for t in portfolio_tickers
        if not t.endswith(".KS") and not t.endswith(".PA")
        and t not in ("IAU", "URNM", "CWEN")
    ][:8]

    results = {"blog_posts": [], "yahoo_news": [], "kr_news": []}

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        blog_future = executor.submit(fetch_blog_posts, days_back, 5)
        yahoo_future = executor.submit(fetch_yahoo_news, news_tickers, 2)
        kr_future = executor.submit(fetch_naver_finance_news, 5)

        try:
            results["blog_posts"] = blog_future.result(timeout=30)
        except Exception as e:
            logger.error(f"Blog fetch timed out: {e}")

        try:
            results["yahoo_news"] = yahoo_future.result(timeout=20)
        except Exception as e:
            logger.error(f"Yahoo news timed out: {e}")

        try:
            results["kr_news"] = kr_future.result(timeout=15)
        except Exception as e:
            logger.error(f"KR news timed out: {e}")

    total = sum(len(v) for v in results.values())
    logger.info(f"All sources: {total} total "
                f"(blog:{len(results['blog_posts'])} "
                f"yahoo:{len(results['yahoo_news'])} "
                f"kr:{len(results['kr_news'])})")
    return results


# ══════════════════════════════════════════════════════════════════════════════
# LEGACY COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════════

def fetch_posts(days_back: int = 1, max_posts: int = 10) -> List[Dict]:
    """Legacy wrapper — backward compatible."""
    return fetch_blog_posts(days_back=days_back, max_posts=max_posts)


def _clean_html(html_text: str) -> str:
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()
