"""
Blog Monitor — Background thread that polls ranto28 RSS on a fixed interval.
When a new post is detected, sends an immediate Telegram alert + GPT analysis.
"""
import json as _jbl
import logging
import os
import time
import threading
import feedparser
import requests
from datetime import datetime

from config import BLOG_FETCH_INTERVAL_MINUTES, naver_blog_rss_list

logger = logging.getLogger("titan_k.blog_monitor")

CHECK_INTERVAL = max(60, int(BLOG_FETCH_INTERVAL_MINUTES) * 60)  # seconds; min 1 min

THEME_MAP = {
    "이란": ("Middle East Conflict", ["KTOS", "272210.KS", "NTR"], ["LMT", "XOM", "FLNG"]),
    "전쟁": ("War Premium", ["KTOS", "272210.KS"], ["LMT", "RTX", "NOC"]),
    "항공모함": ("Naval / Carrier Group", ["KTOS", "272210.KS"], ["LMT", "RTX", "NOC", "GD"]),
    "항모": ("Naval / Carrier Group", ["KTOS", "272210.KS"], ["LMT", "RTX", "NOC"]),
    "부시함": ("US Navy / Strike Group", ["KTOS", "272210.KS"], ["LMT", "RTX"]),
    "해협": ("Strait / Chokepoint Risk", ["KTOS", "NTR"], ["XOM", "URNM"]),
    "호르무즈": ("Strait / Energy Risk", ["NTR", "UEC"], ["XLE", "XOM"]),
    "대만": ("Taiwan Strait Tension", ["TSM", "1810.HK"], ["LMT", "RTX"]),
    "남중국해": ("South China Sea", ["KTOS"], ["LMT", "RTX"]),
    "NATO": ("Alliance / Defense", ["KTOS"], ["LMT", "RTX", "NOC"]),
    "LNG": ("LNG Shortage", ["NTR"], ["FLNG", "GLNG", "KSOE"]),
    "가스": ("Gas/Energy", ["NTR", "UEC"], ["FLNG", "LNG"]),
    "원자력": ("Nuclear Renaissance", ["UEC", "URNM", "OKLO", "UUUU"], ["CCJ", "NXE"]),
    "우라늄": ("Uranium", ["UEC", "URNM", "UUUU"], ["CCJ", "OKLO"]),
    "반도체": ("Semiconductor Cycle", ["TSM", "COHR", "AMAT"], ["ASML", "AMAT"]),
    "구리": ("Copper/EV Demand", ["FCX"], ["COPX", "SCCO"]),
    "방산": ("Defense Spending", ["KTOS", "272210.KS"], ["LMT", "RTX"]),
    "AI": ("AI Infrastructure", ["TSM", "PLTR", "NVDA", "VRT"], ["SMCI", "DELL"]),
    "파키스탄": ("Pakistan Development", [], ["USSM"]),
    "중동": ("Middle East", ["KTOS", "NTR"], ["XOM", "LMT"]),
    "인플레이션": ("Inflation Hedge", ["NTR", "IAU", "FCX"], ["GLD", "PDBC"]),
    # Quantum — any 양자 variant including 암호/통신/컴퓨터/얽힘 + ENG "quantum"
    "양자": ("Quantum Ecosystem", [], ["IONQ", "ARQQ", "LAES", "QUBT", "RGTI", "QBTS", "IBM", "GOOGL"]),
    "quantum": ("Quantum Ecosystem", [], ["IONQ", "ARQQ", "LAES", "QUBT", "RGTI", "QBTS", "IBM", "GOOGL"]),
    "양자암호": ("Quantum Cryptography / Secure Comms", [], ["ARQQ", "LAES", "QUBT", "IONQ"]),
    "양자통신": ("Quantum Communication", [], ["IONQ", "ARQQ", "LAES", "QUBT"]),
    "양자컴퓨터": ("Quantum Computing", [], ["IONQ", "RGTI", "QBTS", "QUBT", "IBM", "GOOGL"]),
    "핵융합": ("Fusion Power", [], ["BWXT", "FLUX", "GEV", "CCJ"]),
    "fusion": ("Fusion Power", [], ["BWXT", "FLUX", "GEV"]),
    "유전자": ("Gene Editing / Therapy", [], ["CRSP", "NTLA", "BEAM", "EDIT", "VERV"]),
    "crispr": ("Gene Editing / CRISPR", [], ["CRSP", "NTLA", "BEAM", "EDIT"]),
    "자율주행": ("Autonomous Driving", ["NVDA", "PLTR"], ["TSLA", "MBLY", "GOOGL"]),
    "로봇": ("Humanoid Robotics", ["NVDA"], ["TSLA", "ABB", "ISRG", "ESTC"]),
    "휴머노이드": ("Humanoid Robotics", ["NVDA"], ["TSLA", "ABB", "ISRG"]),
    "데이터센터": ("Data Center Power", ["VRT"], ["GEV", "ETN", "EMR", "FTAI"]),
    "전력망": ("Grid Modernization", ["VRT"], ["GEV", "ETN", "EMR", "QNTM"]),
    "비만": ("GLP-1 Obesity Drugs", [], ["NVO", "LLY", "PFE", "AZN"]),
    "GLP-1": ("GLP-1 Obesity Drugs", [], ["NVO", "LLY", "PFE"]),
    "스테이블코인": ("Stablecoin Rails", [], ["COIN", "V", "MA", "PYPL", "HOOD"]),
    "stablecoin": ("Stablecoin Rails", [], ["COIN", "V", "MA", "PYPL"]),
}

# Theme-level pure-play fallback: when GPT returns STOCKS:NONE, surface top pure-play US names
# so the pre-alert system does not silently drop concept posts (e.g. quantum communication).
THEME_PUREPLAY_MAP = {
    "Quantum Ecosystem":            ["IONQ", "ARQQ", "LAES", "QUBT", "RGTI", "QBTS", "IBM", "GOOGL"],
    "Quantum Cryptography / Secure Comms": ["ARQQ", "LAES", "QUBT", "IONQ"],
    "Quantum Communication":        ["IONQ", "ARQQ", "LAES", "QUBT"],
    "Quantum Computing":            ["IONQ", "RGTI", "QBTS", "QUBT", "IBM", "GOOGL"],
    "Fusion Power":                 ["BWXT", "FLUX", "GEV", "CCJ"],
    "Gene Editing / Therapy":       ["CRSP", "NTLA", "BEAM", "EDIT", "VERV"],
    "Gene Editing / CRISPR":        ["CRSP", "NTLA", "BEAM", "EDIT"],
    "Humanoid Robotics":            ["TSLA", "ABB", "ISRG", "NVDA"],
    "Autonomous Driving":           ["TSLA", "MBLY", "NVDA", "GOOGL"],
    "Data Center Power":            ["VRT", "GEV", "ETN", "EMR"],
    "Grid Modernization":           ["GEV", "ETN", "EMR", "VRT"],
    "GLP-1 Obesity Drugs":          ["NVO", "LLY", "PFE"],
    "Stablecoin Rails":             ["COIN", "V", "MA", "PYPL", "HOOD"],
    "Uranium":                      ["UEC", "URNM", "UUUU", "CCJ"],
    "Nuclear Renaissance":          ["UEC", "URNM", "OKLO", "UUUU", "CCJ"],
    "Semiconductor Cycle":          ["TSM", "ASML", "AMAT", "KLAC", "LRCX"],
    "LNG Shortage":                 ["FLNG", "GLNG", "LNG"],
    "Copper/EV Demand":             ["FCX", "SCCO", "COPX"],
    "AI Infrastructure":            ["NVDA", "TSM", "PLTR", "VRT", "SMCI"],
    "Inflation Hedge":              ["IAU", "GLD", "NTR", "FCX"],
}


def classify_blog_theme(content: str, direct_tickers: list) -> dict:
    """
    Blog signal = direct tickers + macro theme inference.
    Returns full intelligence package.
    """
    import re

    detected_themes = []
    portfolio_confirmed = set()
    new_watchlist = set()
    content_lower = (content or "").lower()

    for keyword, (theme, confirms, watchlist) in THEME_MAP.items():
        if keyword == "AI":
            if not re.search(r"\bAI\b", content or "", re.I):
                continue
        elif keyword.lower() not in content_lower:
            continue
        detected_themes.append(theme)
        portfolio_confirmed.update(confirms)
        new_watchlist.update(watchlist)

    PORTFOLIO = {
        "TSM",
        "PLTR",
        "UEC",
        "URNM",
        "COHR",
        "1810.HK",
        "NTR",
        "RKLB",
        "PL",
        "TMO",
        "KTOS",
        "272210.KS",
        "ARKQ",
        "BOTZ",
        "VRT",
        "FCX",
        "IAU",
        "CWEN",
        "UUUU",
    }
    new_watchlist -= PORTFOLIO
    new_watchlist -= set(direct_tickers or [])

    detected_themes = list(dict.fromkeys(detected_themes))

    # Theme-level pure-play fallback (never let a concept post return STOCKS: NONE)
    pureplay_seen = []
    pureplay = []
    for th in detected_themes:
        for tk in THEME_PUREPLAY_MAP.get(th, []):
            if tk in pureplay_seen:
                continue
            if tk in (direct_tickers or []):
                continue
            pureplay_seen.append(tk)
            pureplay.append(tk)
    pureplay = pureplay[:8]

    return {
        "direct_tickers": list(direct_tickers or []),
        "themes": detected_themes,
        "portfolio_confirmed": list(portfolio_confirmed),
        "new_watchlist": list(new_watchlist),
        "theme_pureplay": pureplay,
        "action_summary": (
            f"Confirms: {', '.join(portfolio_confirmed) or 'none'} · "
            f"New watch: {', '.join(new_watchlist) or 'none'}"
            + (f" · Pureplay: {', '.join(pureplay)}" if pureplay else "")
        ),
    }
_started = False

_SEEN_CACHE = os.path.join(os.path.dirname(__file__), "data", "seen_blog_urls.json")

# US defense primes + macro names → Kiwoom / tactical · gold satellite overlay (not full portfolio)
_TACTICAL_SLEEVE_TICKERS = frozenset({
    "LMT", "NOC", "RTX", "GD", "LHX", "BA", "HII", "TXT", "KTOS", "AVAV", "CWEN",
})


def _merge_tactical_sleeve(existing: dict, stocks: list, post_title: str) -> dict:
    """Merge blog-mentioned macro/defense watchlist for Master Matrix · Tactical · Gold satellite."""
    ts = existing.get("tactical_sleeve")
    if not isinstance(ts, list):
        ts = []
    by_t = {}
    for x in ts:
        if isinstance(x, dict) and x.get("ticker"):
            by_t[str(x["ticker"]).upper().strip()] = x

    for s in stocks:
        if not isinstance(s, dict):
            continue
        t = str(s.get("ticker") or "").strip().upper()
        name = (s.get("name") or "").strip()
        if t in ("", "UNKNOWN", "?", "NONE"):
            t = ""
        sec = str(s.get("sector", "RADAR")).strip().upper()
        try:
            sc = int(s.get("titan_k_score") or s.get("score") or 7)
        except (TypeError, ValueError):
            sc = 7
        sc = min(10, max(1, sc))
        # Include: defense primes, ROBOTICS sector (defense), or explicit macro flag
        macro = s.get("macro_overlay") or s.get("tactical_sleeve")
        include = bool(
            (t and t in _TACTICAL_SLEEVE_TICKERS)
            or sec == "ROBOTICS"
            or macro is True
            or (isinstance(macro, str) and macro.lower() in ("true", "1", "yes"))
        )
        if not t and name:
            # Name-only (e.g. Chinese listing TBD)
            key = "NAME:" + name[:40]
            by_t[key] = {
                "ticker": "",
                "name": name,
                "score": sc,
                "source_post": post_title[:100],
                "updated": datetime.now().strftime("%Y-%m-%d"),
                "note": "Ticker TBD — map HK/A-share when identified",
            }
            continue
        if not t or not include:
            continue
        by_t[t] = {
            "ticker": t,
            "name": name or t,
            "score": sc,
            "source_post": post_title[:100],
            "updated": datetime.now().strftime("%Y-%m-%d"),
            "note": "Blog · Kiwoom / macro overlay — exit sleeve watch",
        }

    merged = sorted(by_t.values(), key=lambda z: (-int(z.get("score") or 0), z.get("ticker") or ""))
    existing["tactical_sleeve"] = merged[:16]
    existing["tactical_sleeve_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    return existing


def _norm_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return ""
    u = url.replace("m.blog.naver.com", "blog.naver.com")
    u = u.split("?")[0].split("#")[0].rstrip("/")
    return u


def _load_seen() -> set:
    try:
        with open(_SEEN_CACHE, encoding="utf-8") as f:
            data = _jbl.load(f)
        if isinstance(data, list):
            return {_norm_url(u) for u in data if isinstance(u, str) and _norm_url(u)}
    except Exception:
        pass
    return set()


def _save_seen(s: set) -> None:
    try:
        os.makedirs(os.path.dirname(_SEEN_CACHE), exist_ok=True)
        tmp = _SEEN_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _jbl.dump(sorted(s), f, ensure_ascii=False, indent=2)
        os.replace(tmp, _SEEN_CACHE)
    except Exception:
        pass


_seen_urls: set = _load_seen()


def _fetch_rss_xml(rss_url: str):
    """Fetch RSS XML via requests (Naver blocks feedparser's built-in HTTP)."""
    try:
        r = requests.get(
            rss_url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 OLYMPUS/1.0"},
        )
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.warning("RSS HTTP fetch failed (%s): %s", rss_url[:48], e)
        return None


def _check_for_new_posts():
    """Poll all configured RSS feeds; return posts not seen before (URL-deduped)."""
    global _seen_urls
    new_posts = []
    try:
        for rss_url in naver_blog_rss_list():
            xml = _fetch_rss_xml(rss_url)
            if not xml:
                continue
            feed = feedparser.parse(xml)
            for entry in feed.entries[:10]:
                url = _norm_url(entry.get("link", ""))
                if not url:
                    continue
                if url in _seen_urls:
                    continue
                _seen_urls.add(url)
                _save_seen(_seen_urls)

                pub_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6])

                new_posts.append({
                    "title": entry.get("title", "Untitled"),
                    "url": url,
                    "date": pub_date.strftime("%Y-%m-%d %H:%M") if pub_date else "",
                    "feed": rss_url[:60],
                })
    except Exception as e:
        logger.error(f"RSS check failed: {e}")
    return new_posts


def _seed_seen():
    """On first run (empty seen set), mark current RSS posts as seen so we don't spam."""
    global _seen_urls
    if _seen_urls:
        logger.info("Blog monitor resumed with %s URLs on disk — no RSS re-seed", len(_seen_urls))
        return
    try:
        for rss_url in naver_blog_rss_list():
            xml = _fetch_rss_xml(rss_url)
            if not xml:
                continue
            feed = feedparser.parse(xml)
            for entry in feed.entries[:20]:
                url = _norm_url(entry.get("link", ""))
                if url:
                    _seen_urls.add(url)
                    _save_seen(_seen_urls)
        logger.info("Blog monitor first seed: %s existing posts marked seen", len(_seen_urls))
    except Exception as e:
        logger.error(f"Seed failed: {e}")


def _extract_and_register_tickers(post_content: str, post_title: str) -> None:
    """Extract tickers from blog post, classify into OLYMPUS sectors, alert GOD."""
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
5. ROBOTICS — Humanoids, defense drones, autonomous systems, weapons, prime defense contractors (LMT, NOC, RTX…)
6. INFRASTRUCTURE — Photonics, data center power, semiconductor equipment, copper
7. RADAR — Geopolitical plays, commodities, macro trades, does not fit above 6

Also set:
- "titan_k_score": integer 1–10 (conviction / relevance to the post; defense primes in a war/carrier headline = 7–9).
- If the company has no US ticker (e.g. Chinese shipping), use "ticker": null, "name": "Full company name", "listing_unknown": true.

Return ONLY a JSON array. No explanation. Example:
[{{"ticker":"LMT","name":"Lockheed Martin","sector":"ROBOTICS","titan_k_score":8}},{{"ticker":null,"name":"Shanghai Shihanlun Shipping","sector":"RADAR","listing_unknown":true,"titan_k_score":7}}]

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
        stocks = _jbl.loads(raw)

        if not isinstance(stocks, list) or not stocks:
            return

        cleaned = []
        for s in stocks:
            if not isinstance(s, dict):
                continue
            tk = s.get("ticker")
            if tk is None or (isinstance(tk, str) and not str(tk).strip()):
                if s.get("listing_unknown") or s.get("name"):
                    cleaned.append(s)
                continue
            cleaned.append(s)
        stocks = cleaned
        if not stocks:
            return

        for s in stocks:
            sec = str(s.get("sector", "RADAR")).strip().upper()
            s["sector"] = sec if sec in _VALID_SECTORS else "RADAR"
            tk = s.get("ticker")
            if tk is not None and str(tk).strip():
                s["ticker"] = str(tk).strip().upper()

        cache_path = os.path.join(os.path.dirname(__file__), "data", "blog_tickers.json")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                existing = _jbl.load(f)
        except Exception:
            existing = {"tickers": [], "by_sector": {}, "history": []}

        if "tickers" not in existing:
            existing["tickers"] = []
        if "by_sector" not in existing:
            existing["by_sector"] = {}
        if "history" not in existing:
            existing["history"] = []

        existing = _merge_tactical_sleeve(existing, stocks, post_title)

        new_stocks = [
            s for s in stocks
            if s.get("ticker") and str(s["ticker"]).strip() and s["ticker"] not in existing["tickers"]
        ]

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

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                _jbl.dump(existing, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("blog_tickers.json write failed: %s", e)

        if new_stocks:

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
            direct = [s["ticker"] for s in new_stocks]
            bt3 = classify_blog_theme(post_content[:4000], direct)
            msg += f"\n\n🌍 THEME: {', '.join(bt3['themes']) or '—'}"
            msg += f"\n✅ CONFIRMS: {', '.join(bt3['portfolio_confirmed']) or 'none'}"
            msg += f"\n🔍 NEW WATCH: {', '.join(bt3['new_watchlist']) or 'none'}"
            _send_thesis_plain(msg)

    except Exception as e:
        logger.warning(f"Ticker extraction failed: {e}")


def _send_alert(post: dict):
    """Send Telegram alert for a new blog post, with optional GPT summary."""
    import re
    from html import escape

    from analyzer import client
    from telegram_bot import send_telegram

    title = post.get("title", "")
    url = post.get("url", "")
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
            prompt = f"""IMPORTANT: Always respond in ENGLISH regardless of the blog post language.
You are Minerva, investment analyst for GOD's OLYMPUS pre-alert system.
This is a PRE-ALERT for a sophisticated investor. NEVER return STOCKS: NONE
when the post discusses an identifiable investment theme — instead, list the
top publicly-traded US PURE-PLAY companies for that theme, ranked by directness.

Return ONLY this exact format (no extra prose, no code fences):

📰 [3-5 word English title]
🔑 [2-3 core keywords separated by ·]
📊 SO WHAT: [1 sentence — exact market impact]
🎯 STOCKS: [ticker1, ticker2, ticker3]    ← up to 6 US tickers; write NONE only if the post is purely non-investment (e.g. personal anecdote).
🧭 INFERRED: true|false                   ← true if tickers were inferred from theme (not explicitly named in the post), false if the post names them.
⏱ TIMING: [BUY NOW / WATCH / AVOID / HOLD]
🎯 THEME: [the specific investment theme, e.g. "Quantum Communication / KeyGen"]

Then OPTIONALLY a single line starting with "📈 ESTIMATES:" only if the post gives concrete price targets, levels, revenue, or clear quantitative basis. If you cannot price it with real context, DO NOT output the 📈 line at all. Do NOT print "INSUFFICIENT DATA" or placeholders.

Concept → pure-play hints (non-exhaustive, use freely):
- Quantum communication / 양자통신 / QKD → IONQ, ARQQ, LAES, QUBT, IBM, GOOGL
- Quantum computing / 양자컴퓨터 → IONQ, RGTI, QBTS, QUBT, IBM, GOOGL
- Post-quantum cryptography / 양자암호 → ARQQ, LAES, QUBT
- Fusion / 핵융합 → BWXT, FLUX, GEV
- CRISPR / gene editing / 유전자 → CRSP, NTLA, BEAM, EDIT, VERV
- Humanoid / 휴머노이드 / 로봇 → TSLA, ABB, ISRG, NVDA
- Grid / 전력망 / data center power → VRT, GEV, ETN, EMR
- GLP-1 / 비만 → NVO, LLY, PFE
- Stablecoin / 스테이블코인 → COIN, V, MA, PYPL, HOOD
- Nuclear / 원자력 / 우라늄 → UEC, URNM, OKLO, CCJ, UUUU

Blog post:
Title: {post.get('title')}
Content: {content[:1800]}
"""
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=800,
            )
            gpt_text = (response.choices[0].message.content or "").strip()
            # Strip stray "INSUFFICIENT DATA" or placeholder ESTIMATES lines
            gpt_text = re.sub(
                r"^\s*📈\s*ESTIMATES[^\n]*(INSUFFICIENT|\$X|\[price\])[^\n]*\n?",
                "",
                gpt_text,
                flags=re.IGNORECASE | re.MULTILINE,
            )
            tickers_gpt = []
            mstk = re.search(r"🎯 STOCKS:\s*([^\n]+)", gpt_text)
            if mstk:
                raw_t = (mstk.group(1) or "").strip()
                if raw_t.upper() != "NONE":
                    tickers_gpt = [
                        x.strip().upper()
                        for x in re.split(r"[,，]", raw_t)
                        if x.strip() and x.strip().upper() != "NONE"
                    ]
            bt = classify_blog_theme(
                (content or "") + "\n" + title + "\n" + (gpt_text or ""),
                tickers_gpt,
            )
            # Fallback: if GPT returned NONE but we detected pure-play themes, patch STOCKS line
            if not tickers_gpt and bt.get("theme_pureplay"):
                pp = bt["theme_pureplay"][:5]
                gpt_text = re.sub(
                    r"🎯 STOCKS:\s*NONE",
                    f"🎯 STOCKS: {', '.join(pp)}\n🧭 INFERRED: true (theme pure-plays · OLYMPUS fallback)",
                    gpt_text,
                    count=1,
                    flags=re.IGNORECASE,
                )
                tickers_gpt = pp
            if gpt_text:
                lines.append(escape(gpt_text))
            else:
                lines.append("⚠️ GPT returned empty — check manually")
            if bt.get("themes") or bt.get("portfolio_confirmed") or bt.get("new_watchlist") or bt.get("theme_pureplay"):
                lines.append("")
                lines.append(
                    f"🌍 <b>THEME:</b> {escape(', '.join(bt['themes']) or 'none')}"
                )
                lines.append(
                    f"✅ <b>CONFIRMS IN PORTFOLIO:</b> "
                    f"{escape(', '.join(bt['portfolio_confirmed']) or 'none')}"
                )
                lines.append(
                    f"🔍 <b>NEW WATCHLIST CANDIDATES:</b> "
                    f"{escape(', '.join(bt['new_watchlist']) or 'none')}"
                )
                if bt.get("theme_pureplay"):
                    lines.append(
                        f"🎯 <b>THEME PURE-PLAYS:</b> "
                        f"{escape(', '.join(bt['theme_pureplay']))}"
                    )
            _extract_and_register_tickers(content, post.get("title", "") or title)
        else:
            lines.append("⚠️ Could not fetch content — check manually")
            bt2 = classify_blog_theme(title, [])
            if bt2.get("themes"):
                lines.append("")
                lines.append(f"🌍 <b>THEME:</b> {escape(', '.join(bt2['themes']))}")
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
