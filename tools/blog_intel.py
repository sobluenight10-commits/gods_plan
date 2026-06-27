"""
BLOG INTEL — deep per-post analysis engine for ranto28 (메르).

The Korean financial blog ranto28 ("메르") is the user's core source of insight.
This module reads each new post and produces ONE rich, English-language analysis
object per post: a cause -> result -> what-comes-next storyline, a thorough
keyword map (including MINOR keywords connected to the core plot), cross-asset
investment takeaways, a ranked watch list (>= 5 tickers), out-of-the-box
"deeper story" connections, and a node/edge knowledge graph.

The output schema is a HARD CONTRACT — downstream modules consume `graph` and
`recommended_watch`. See `analyze_post_deep` for the exact shape.

Model tiering ("right weapon per task level"):
    - Light extraction (keywords / entities)  -> config.FAST_MODEL (gpt-4o-mini)
    - Deep synthesis (cause-chain, deeper story, recommendations)
                                              -> env BLOG_DEEP_MODEL
                                                 (defaults to config.FAST_MODEL)

Run standalone:
    python -m tools.blog_intel
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import config  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(BASE, "data")
INTEL_DIR = os.path.join(DATA_DIR, "blog_intel")
LATEST_OUT = os.path.join(DATA_DIR, "blog_intel_latest.json")
SEEN_FILE = os.path.join(DATA_DIR, "blog_intel_seen.json")
WEBROOT_OUT = "/var/www/html/blog_intel_latest.json"

BLOG_URL_FALLBACK = "https://blog.naver.com/ranto28"

# ── Models ────────────────────────────────────────────────────────────────────
EXTRACT_MODEL = config.FAST_MODEL
DEEP_MODEL = os.getenv("BLOG_DEEP_MODEL", "").strip() or config.FAST_MODEL

KEYWORD_TYPES = {
    "company", "ticker", "metal", "commodity", "bond", "currency",
    "country", "sector", "theme", "person", "policy", "technology",
    "event", "other",
}

EDGE_RELATIONS = {
    "input_to", "competitor_of", "supplier_to", "affected_by",
    "benefits_from", "part_of", "causes", "correlates_with",
}


# ══════════════════════════════════════════════════════════════════════════════
# LLM WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def _llm(model: str, system: str, user: str, tokens: int = 700) -> str:
    """Single LLM call. Catches ALL exceptions and returns "" on failure."""
    try:
        from openai import OpenAI

        client = OpenAI(api_key=config.OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.3,
            max_tokens=tokens,
        )
        out = resp.choices[0].message.content or ""
        return out.strip()
    except Exception:
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _post_id(url: str, title: str) -> str:
    """Stable 16-hex id keyed on url (preferred) or title."""
    basis = (url or "").split("?")[0].strip() or (title or "").strip()
    if not basis:
        basis = _now_iso()
    return hashlib.sha1(basis.encode("utf-8", errors="ignore")).hexdigest()[:16]


def portfolio_ticker_set() -> set:
    """All tickers OLYMPUS currently tracks (PORTFOLIO + WATCHLIST), upper-cased."""
    tickers: set = set()
    try:
        for _broker, positions in config.PORTFOLIO.items():
            for p in positions:
                t = str(p.get("ticker") or "").strip()
                if t:
                    tickers.add(t.upper())
    except Exception:
        pass
    try:
        for w in config.WATCHLIST:
            t = str(w.get("ticker") or "").strip()
            if t:
                tickers.add(t.upper())
    except Exception:
        pass
    return tickers


def _is_in_portfolio(ticker: str, holdings: Optional[set] = None) -> bool:
    if holdings is None:
        holdings = portfolio_ticker_set()
    return bool(ticker) and ticker.strip().upper() in holdings


def _strip_fences(text: str) -> str:
    """Remove ``` / ```json fences and surrounding noise."""
    if not text:
        return ""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9_]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _extract_first_json(text: str) -> Optional[Any]:
    """Robustly parse the first balanced {...} (or [...]) object from text."""
    if not text:
        return None
    cleaned = _strip_fences(text)
    # Fast path
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # Find first balanced object/array via bracket matching
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        if start < 0:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
    return None


def _finite(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except Exception:
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return v


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _as_str(x: Any, default: str = "") -> str:
    if x is None:
        return default
    if isinstance(x, str):
        return x.strip()
    try:
        return str(x).strip()
    except Exception:
        return default


def _as_list(x: Any) -> List[Any]:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _norm_type(t: Any) -> str:
    s = _as_str(t).lower()
    return s if s in KEYWORD_TYPES else "other"


def _norm_relation(r: Any) -> str:
    s = _as_str(r).lower().replace(" ", "_")
    return s if s in EDGE_RELATIONS else "correlates_with"


def _slug(label: str, fallback: str = "kw") -> str:
    s = re.sub(r"[^a-z0-9]+", "_", _as_str(label).lower()).strip("_")
    return s or fallback


# ══════════════════════════════════════════════════════════════════════════════
# LLM PROMPTS
# ══════════════════════════════════════════════════════════════════════════════

_EXTRACT_SYS = (
    "You are Minerva, an investment intelligence analyst. You read a Korean "
    "financial blog post (from ranto28 / 메르) and extract its concept map. "
    "The post is in Korean; you ALWAYS output in ENGLISH. Return STRICT JSON "
    "only — no prose, no markdown fences."
)

_EXTRACT_USER = """Extract the full concept map of this Korean blog post.

TITLE: {title}
DATE: {date}

CONTENT:
{content}

Return STRICT JSON with this shape:
{{
  "title_en": "English translation of the title",
  "keywords": [
    {{
      "label": "Display name (English)",
      "type": "company|ticker|metal|commodity|bond|currency|country|sector|theme|person|policy|technology|event|other",
      "importance": 0.0,
      "summary": "A thorough mini-summary IN ENGLISH of this concept and WHY it matters to the post's core plot. Include MINOR keywords too, each with a real summary.",
      "related": ["label of another keyword it connects to", "..."]
    }}
  ]
}}

Rules:
- Capture 8-20 keywords. INCLUDE minor keywords that are connected to the core plot.
- importance is 0..1 (1 = central to the thesis).
- Every keyword needs a real, specific summary — never empty.
- Output English only. Strict JSON only."""


_SYNTH_SYS = (
    "You are Minerva, a surgical, visionary investment analyst writing for a "
    "single sophisticated investor. You read a Korean financial blog post (from "
    "ranto28 / 메르) and produce a deep, English-language synthesis: the causal "
    "story, cross-asset takeaways, a ranked watch list, and out-of-the-box "
    "adjacent connections. You ALWAYS output in ENGLISH. Return STRICT JSON only."
)

_SYNTH_USER = """Deeply analyze this Korean blog post and return STRICT JSON.

TITLE: {title}
DATE: {date}

KNOWN KEYWORDS (already extracted, for grounding):
{keywords}

CONTENT:
{content}

Return STRICT JSON with this shape:
{{
  "short_summary": {{
    "cause": "Root driver — 1-2 sentences.",
    "result": "Observable result.",
    "what_comes_next": "Forward-looking / second-order implication.",
    "one_line": "cause -> result -> what comes next (single punchy line)"
  }},
  "investment_takeaways": {{
    "stocks": ["takeaway", "..."],
    "metals": [{{"name": "gold|silver|copper|uranium|aluminum|...", "view": "bullish/bearish + why"}}],
    "bonds": ["takeaway on sovereign/credit"],
    "fx": ["takeaway"],
    "commodities": ["takeaway"]
  }},
  "recommended_watch": [
    {{"ticker": "TICKER", "name": "Company", "relevance": 0, "thesis": "why relevant to THIS post", "asset_class": "equity|etf|commodity"}}
  ],
  "deeper_story": ["out-of-the-box adjacent connection that broadens the investor's thinking", "..."],
  "graph_edges": [
    {{"source": "keyword label", "target": "keyword label", "relation": "input_to|competitor_of|supplier_to|affected_by|benefits_from|part_of|causes|correlates_with", "weight": 3}}
  ]
}}

Rules:
- recommended_watch MUST contain >= 5 entries, ranked by relevance (0..100 int) descending, most relevant to the summary first. Use real, liquid tickers.
- deeper_story: 2-4 genuinely non-obvious adjacent connections.
- graph_edges: connect the known keywords with directional relations.
- Output English only. Strict JSON only."""


# ══════════════════════════════════════════════════════════════════════════════
# CORE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

def _post_content(post: Dict) -> str:
    return _as_str(post.get("content")) or _as_str(post.get("summary"))


def _post_url(post: Dict) -> str:
    return (
        _as_str(post.get("url"))
        or _as_str(post.get("link"))
        or BLOG_URL_FALLBACK
    )


def _normalize_keywords(raw: Any) -> List[Dict]:
    out: List[Dict] = []
    used_ids: set = set()
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        label = _as_str(item.get("label")) or _as_str(item.get("id")) or "Unknown"
        kid = _slug(_as_str(item.get("id")) or label)
        base_id = kid
        n = 2
        while kid in used_ids:
            kid = f"{base_id}_{n}"
            n += 1
        used_ids.add(kid)
        related = [_slug(r) for r in _as_list(item.get("related") or item.get("related_core")) if _as_str(r)]
        out.append({
            "id": kid,
            "label": label,
            "type": _norm_type(item.get("type")),
            "importance": round(_clamp(_finite(item.get("importance"), 0.3), 0.0, 1.0), 3),
            "summary": _as_str(item.get("summary")) or f"{label}: referenced in the post.",
            "related_core": related,
        })
    return out


def _normalize_watch(raw: Any, holdings: set) -> List[Dict]:
    out: List[Dict] = []
    seen: set = set()
    for item in _as_list(raw):
        if not isinstance(item, dict):
            continue
        ticker = _as_str(item.get("ticker")).upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        ac = _as_str(item.get("asset_class")).lower()
        if ac not in ("equity", "etf", "commodity"):
            ac = "equity"
        out.append({
            "ticker": ticker,
            "name": _as_str(item.get("name")) or ticker,
            "relevance": int(round(_clamp(_finite(item.get("relevance"), 50), 0, 100))),
            "in_portfolio": _is_in_portfolio(ticker, holdings),
            "thesis": _as_str(item.get("thesis")) or "Relevant to this post.",
            "asset_class": ac,
        })
    out.sort(key=lambda w: w["relevance"], reverse=True)
    return out


def _fallback_watch(holdings: set, existing: List[Dict]) -> List[Dict]:
    """Pad recommended_watch to >= 5 using config holdings, ranked best-effort."""
    have = {w["ticker"] for w in existing}
    pads: List[Dict] = []
    try:
        rows = []
        for _broker, positions in config.PORTFOLIO.items():
            for p in positions:
                rows.append((str(p.get("ticker") or "").upper(), str(p.get("name") or ""),
                             int(p.get("score") or 0), str(p.get("thesis") or "")))
        for w in config.WATCHLIST:
            rows.append((str(w.get("ticker") or "").upper(), str(w.get("name") or ""),
                         int(w.get("score") or 0), str(w.get("entry") or "")))
        rows.sort(key=lambda r: r[2], reverse=True)
        for tk, nm, score, thesis in rows:
            if not tk or tk in have:
                continue
            have.add(tk)
            pads.append({
                "ticker": tk,
                "name": nm or tk,
                "relevance": int(_clamp(40 + score * 4, 0, 100)),
                "in_portfolio": _is_in_portfolio(tk, holdings),
                "thesis": thesis or "Core OLYMPUS holding — monitor for read-through.",
                "asset_class": "equity",
            })
    except Exception:
        pass
    return pads


def _build_graph(keywords: List[Dict], raw_edges: Any) -> Dict:
    nodes = [
        {"id": k["id"], "label": k["label"], "type": k["type"], "summary": k["summary"][:240]}
        for k in keywords
    ]
    label_to_id = {k["label"].lower(): k["id"] for k in keywords}
    id_set = {k["id"] for k in keywords}

    def _resolve(ref: Any) -> Optional[str]:
        s = _as_str(ref)
        if not s:
            return None
        if s in id_set:
            return s
        sl = _slug(s)
        if sl in id_set:
            return sl
        return label_to_id.get(s.lower())

    edges: List[Dict] = []
    seen_pairs: set = set()
    for e in _as_list(raw_edges):
        if not isinstance(e, dict):
            continue
        src = _resolve(e.get("source"))
        tgt = _resolve(e.get("target"))
        if not src or not tgt or src == tgt:
            continue
        rel = _norm_relation(e.get("relation"))
        key = (src, tgt, rel)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        edges.append({
            "source": src,
            "target": tgt,
            "relation": rel,
            "weight": int(round(_clamp(_finite(e.get("weight"), 2), 1, 5))),
        })

    # Derive edges from related_core when the LLM gave none
    if not edges:
        for k in keywords:
            for rel_ref in k.get("related_core", []):
                tgt = _resolve(rel_ref)
                if tgt and tgt != k["id"]:
                    key = (k["id"], tgt, "correlates_with")
                    if key not in seen_pairs:
                        seen_pairs.add(key)
                        edges.append({
                            "source": k["id"],
                            "target": tgt,
                            "relation": "correlates_with",
                            "weight": 2,
                        })
    return {"nodes": nodes, "edges": edges}


def _empty_takeaways() -> Dict:
    return {"stocks": [], "metals": [], "bonds": [], "fx": [], "commodities": []}


def _normalize_takeaways(raw: Any) -> Dict:
    out = _empty_takeaways()
    if not isinstance(raw, dict):
        return out
    for key in ("stocks", "bonds", "fx", "commodities"):
        out[key] = [_as_str(x) for x in _as_list(raw.get(key)) if _as_str(x)]
    metals: List[Dict] = []
    for m in _as_list(raw.get("metals")):
        if isinstance(m, dict):
            name = _as_str(m.get("name"))
            view = _as_str(m.get("view"))
            if name or view:
                metals.append({"name": name or "metal", "view": view})
        elif _as_str(m):
            metals.append({"name": _as_str(m), "view": ""})
    out["metals"] = metals
    return out


def analyze_post_deep(post: Dict) -> dict:
    """Run the deep analysis pipeline on ONE post and return the schema object.

    Never raises — on any failure a minimal valid object is returned.
    """
    holdings = portfolio_ticker_set()
    url = _post_url(post)
    raw_title = _as_str(post.get("title")) or "Untitled"
    published = _as_str(post.get("date")) or _as_str(post.get("published"))
    content = _post_content(post)
    pid = _post_id(url, raw_title)

    # ── Stage 1: light extraction (keywords) ──────────────────────────────────
    extract_raw = ""
    if content and len(content) >= 30:
        extract_raw = _llm(
            EXTRACT_MODEL,
            _EXTRACT_SYS,
            _EXTRACT_USER.format(title=raw_title, date=published or "?", content=content[:6000]),
            tokens=1200,
        )
    extract_obj = _extract_first_json(extract_raw) if extract_raw else None
    extract_obj = extract_obj if isinstance(extract_obj, dict) else {}

    title_en = _as_str(extract_obj.get("title_en")) or raw_title
    keywords = _normalize_keywords(extract_obj.get("keywords"))

    # ── Stage 2: deep synthesis ───────────────────────────────────────────────
    kw_brief = "; ".join(f"{k['label']} ({k['type']})" for k in keywords[:24]) or "none extracted"
    synth_raw = ""
    if content and len(content) >= 30:
        synth_raw = _llm(
            DEEP_MODEL,
            _SYNTH_SYS,
            _SYNTH_USER.format(
                title=title_en, date=published or "?",
                keywords=kw_brief, content=content[:6000],
            ),
            tokens=1600,
        )
    synth_obj = _extract_first_json(synth_raw) if synth_raw else None
    synth_obj = synth_obj if isinstance(synth_obj, dict) else {}

    ss_raw = synth_obj.get("short_summary")
    ss_raw = ss_raw if isinstance(ss_raw, dict) else {}
    short_summary = {
        "cause": _as_str(ss_raw.get("cause")),
        "result": _as_str(ss_raw.get("result")),
        "what_comes_next": _as_str(ss_raw.get("what_comes_next")),
        "one_line": _as_str(ss_raw.get("one_line")),
    }
    if not short_summary["one_line"]:
        parts = [short_summary["cause"], short_summary["result"], short_summary["what_comes_next"]]
        joined = " -> ".join(p for p in parts if p)
        short_summary["one_line"] = joined or title_en

    takeaways = _normalize_takeaways(synth_obj.get("investment_takeaways"))

    watch = _normalize_watch(synth_obj.get("recommended_watch"), holdings)
    if len(watch) < 5:
        watch.extend(_fallback_watch(holdings, watch))
    watch.sort(key=lambda w: w["relevance"], reverse=True)

    deeper_story = [_as_str(x) for x in _as_list(synth_obj.get("deeper_story")) if _as_str(x)]
    if not deeper_story:
        deeper_story = [
            "No adjacent connections surfaced — re-read the post manually for second-order plays.",
        ]
    deeper_story = deeper_story[:4]

    graph = _build_graph(keywords, synth_obj.get("graph_edges"))

    analysis = {
        "post_id": pid,
        "url": url,
        "title": title_en,
        "published": published,
        "analyzed_at": _now_iso(),
        "short_summary": short_summary,
        "keywords": keywords,
        "investment_takeaways": takeaways,
        "recommended_watch": watch,
        "deeper_story": deeper_story,
        "graph": graph,
        "models_used": {"extract": EXTRACT_MODEL, "synthesize": DEEP_MODEL},
    }
    return _sanitize(analysis)


def _sanitize(obj: Any) -> Any:
    """Recursively replace NaN/Infinity with finite values; keep JSON-safe."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
        return obj
    return obj


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM FORMATTING
# ══════════════════════════════════════════════════════════════════════════════

def _esc(text: str) -> str:
    s = _as_str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_telegram(analysis: dict) -> str:
    """Rich, scannable Telegram chapter (HTML). Kept under ~3500 chars."""
    if not isinstance(analysis, dict):
        return ""
    title = _esc(analysis.get("title") or "Untitled")
    ss = analysis.get("short_summary") or {}
    one_line = _esc(ss.get("one_line") or "")

    lines: List[str] = []
    lines.append(f"📖 <b>{title}</b>")
    if one_line:
        lines.append(f"🧭 {one_line}")
    lines.append("")

    # Cause / result / next
    cause = _esc(ss.get("cause") or "")
    result = _esc(ss.get("result") or "")
    nxt = _esc(ss.get("what_comes_next") or "")
    if cause:
        lines.append(f"<b>Cause:</b> {cause}")
    if result:
        lines.append(f"<b>Result:</b> {result}")
    if nxt:
        lines.append(f"<b>Next:</b> {nxt}")
    lines.append("")

    # Asset-class takeaways
    tk = analysis.get("investment_takeaways") or {}
    takeaway_lines: List[str] = []
    stocks = [_esc(x) for x in _as_list(tk.get("stocks"))][:2]
    if stocks:
        takeaway_lines.append("• <b>Stocks:</b> " + " / ".join(stocks))
    metals = tk.get("metals") or []
    if metals:
        m0 = metals[0] if isinstance(metals[0], dict) else {}
        nm = _esc(m0.get("name") or "metal")
        vw = _esc(m0.get("view") or "")
        takeaway_lines.append(f"• <b>Metals:</b> {nm} — {vw}".rstrip(" —"))
    for key, label in (("bonds", "Bonds"), ("fx", "FX"), ("commodities", "Commodities")):
        vals = [_esc(x) for x in _as_list(tk.get(key))]
        if vals:
            takeaway_lines.append(f"• <b>{label}:</b> {vals[0]}")
    if takeaway_lines:
        lines.append("<b>💰 Takeaways</b>")
        lines.extend(takeaway_lines)
        lines.append("")

    # Watch tickers (>=5)
    watch = analysis.get("recommended_watch") or []
    if watch:
        lines.append("<b>🎯 Watch</b>")
        for w in watch[:7]:
            if not isinstance(w, dict):
                continue
            tkr = _esc(w.get("ticker") or "?")
            rel = int(_finite(w.get("relevance"), 0))
            star = " ⭐" if w.get("in_portfolio") else ""
            thesis = _esc(w.get("thesis") or "")
            if len(thesis) > 90:
                thesis = thesis[:87] + "..."
            lines.append(f"• <b>{tkr}</b> ({rel}){star} — {thesis}")
        lines.append("")

    # Deeper story (top bullet)
    deeper = [_esc(x) for x in _as_list(analysis.get("deeper_story"))]
    if deeper:
        lines.append("<b>🔭 Deeper story</b>")
        lines.append(f"• {deeper[0]}")
        lines.append("")

    # Link
    url = (analysis.get("url") or BLOG_URL_FALLBACK).replace("&", "&amp;")
    lines.append(f"🔗 <a href=\"{url}\">Read original</a>")

    text = "\n".join(lines)
    if len(text) > 3500:
        text = text[:3490].rstrip() + "\n…"
    return text


# ══════════════════════════════════════════════════════════════════════════════
# DEDUP STATE
# ══════════════════════════════════════════════════════════════════════════════

def _load_seen() -> Dict[str, Any]:
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_seen(seen: Dict[str, Any]) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            json.dump(seen, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# FETCH
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_posts(limit: int, days_back: int) -> List[Dict]:
    """Fetch latest posts via scraper if importable, else battle_rhythm fallback."""
    try:
        import scraper

        posts = scraper.fetch_blog_posts(days_back=days_back, max_posts=limit)
        if posts:
            return posts[:limit]
    except Exception:
        pass

    # Fallback: battle_rhythm._fetch_blog returns a formatted string, not dicts.
    # Best-effort parse into post dicts so analyze_post_deep still has content.
    try:
        import battle_rhythm

        blob = battle_rhythm._fetch_blog()
        if blob and isinstance(blob, str):
            chunks = [c.strip() for c in blob.split("\n\n") if c.strip()]
            posts: List[Dict] = []
            for chunk in chunks[:limit]:
                title_m = re.search(r"<b>(.*?)</b>", chunk)
                url_m = re.search(r"URL:\s*(\S+)", chunk)
                body = re.sub(r"<[^>]+>", " ", chunk)
                posts.append({
                    "title": (title_m.group(1).strip() if title_m else chunk[:80]),
                    "url": (url_m.group(1).strip() if url_m else BLOG_URL_FALLBACK),
                    "content": body.strip(),
                    "summary": body.strip(),
                    "date": "",
                })
            return posts
    except Exception:
        pass
    return []


# ══════════════════════════════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════════════════════════════

def run(limit: int = 3, days_back: int = 3, send_telegram: bool = False) -> dict:
    """Fetch latest posts, analyze each, persist, optionally Telegram-notify new ones.

    Returns the aggregate dict {"generated_at": ISO, "analyses": [...]}.
    """
    os.makedirs(INTEL_DIR, exist_ok=True)
    seen = _load_seen()

    posts = _fetch_posts(limit, days_back)
    analyses: List[dict] = []
    new_analyses: List[dict] = []

    for post in posts:
        try:
            analysis = analyze_post_deep(post)
        except Exception:
            continue
        pid = analysis.get("post_id") or _post_id(_post_url(post), _as_str(post.get("title")))
        is_new = pid not in seen

        # Persist per-post JSON
        try:
            with open(os.path.join(INTEL_DIR, f"{pid}.json"), "w", encoding="utf-8") as f:
                json.dump(analysis, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        analyses.append(analysis)
        if is_new:
            new_analyses.append(analysis)
            seen[pid] = {
                "title": analysis.get("title"),
                "analyzed_at": analysis.get("analyzed_at"),
                "url": analysis.get("url"),
            }

    aggregate = {"generated_at": _now_iso(), "analyses": analyses}

    # Write aggregate
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LATEST_OUT, "w", encoding="utf-8") as f:
            json.dump(aggregate, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    # Mirror to webroot if present
    try:
        if os.path.isdir(os.path.dirname(WEBROOT_OUT)):
            shutil.copy2(LATEST_OUT, WEBROOT_OUT)
    except Exception:
        pass

    _save_seen(seen)

    # Telegram for NEW posts
    if send_telegram and new_analyses:
        try:
            import telegram_bot

            for analysis in new_analyses:
                msg = format_telegram(analysis)
                if msg:
                    telegram_bot.send_telegram(msg)
        except Exception:
            pass

    return aggregate


if __name__ == "__main__":
    print(json.dumps(run(limit=2, send_telegram=False), ensure_ascii=False)[:2000])
