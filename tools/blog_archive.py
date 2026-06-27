"""
BLOG ARCHIVE — full historical corpus of the ranto28 (메르) Naver blog.

Two stages, decoupled so the expensive one is optional:

  STAGE 1 — RAW (cheap, no LLM):
    Enumerate EVERY post via Naver's PostTitleListAsync pagination API
    (~2400+ posts), fetch each post's full text, and store into a SQLite
    database  data/blog_archive.db  (table `posts`). Fully resumable — re-running
    only fetches posts not already stored. A JSONL mirror and a small
    blog_archive_index.json (counts/progress) are written for portability and the
    dashboard.

  STAGE 2 — ANALYZE (optional, LLM, batched):
    Pull N oldest un-analyzed rows, run tools.blog_intel.analyze_post_deep on each,
    accumulate into the knowledge graph (tools.knowledge_graph), mark analyzed.
    This lets GOD grow the graph from the whole archive in controlled, low-cost
    batches instead of one huge run.

CLI:
    python3 -m tools.blog_archive enumerate                 # list-only, prints total
    python3 -m tools.blog_archive fetch [--limit N] [--sleep 0.5]
    python3 -m tools.blog_archive status
    python3 -m tools.blog_archive analyze --limit 25
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

try:
    from config import NAVER_BLOG_ID
except Exception:
    NAVER_BLOG_ID = "ranto28"

DATA_DIR = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA_DIR, "blog_archive.db")
JSONL_PATH = os.path.join(DATA_DIR, "blog_archive.jsonl")
INDEX_PATH = os.path.join(DATA_DIR, "blog_archive_index.json")
WEBROOT_INDEX = "/var/www/html/blog_archive_index.json"

LIST_URL = "https://blog.naver.com/PostTitleListAsync.naver"
COUNT_PER_PAGE = 30
REQUEST_TIMEOUT = 12

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Referer": f"https://blog.naver.com/{NAVER_BLOG_ID}",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── DB ──────────────────────────────────────────────────────────────────────
def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            log_no      TEXT PRIMARY KEY,
            title       TEXT,
            post_date   TEXT,
            url         TEXT,
            content     TEXT,
            char_len    INTEGER DEFAULT 0,
            listed_at   TEXT,
            fetched_at  TEXT,
            analyzed_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def _post_url(log_no: str) -> str:
    return f"https://m.blog.naver.com/{NAVER_BLOG_ID}/{log_no}"


# ── STAGE 1a: enumerate the full post list ────────────────────────────────────
def _decode_list_field(raw: str) -> List[str]:
    """PostTitleListAsync returns fields as comma-joined, single-quoted, often
    HTML-entity/URL-encoded strings. Decode robustly into a clean list."""
    if not raw:
        return []
    s = raw.replace("&#39;", "'").replace("&quot;", '"')
    # Split on ',' that separates quoted items: items look like 'value','value'
    parts = re.findall(r"'([^']*)'", s)
    if not parts:
        parts = [p for p in s.split(",") if p]
    out = []
    for p in parts:
        try:
            out.append(urllib.parse.unquote(p).strip())
        except Exception:
            out.append(p.strip())
    return out


def _fetch_list_page(page: int) -> Tuple[List[Dict[str, str]], int]:
    """Return (rows, total_count) for one PostTitleListAsync page."""
    params = {
        "blogId": NAVER_BLOG_ID,
        "viewdate": "",
        "currentPage": str(page),
        "categoryNo": "0",
        "parentCategoryNo": "",
        "countPerPage": str(COUNT_PER_PAGE),
    }
    r = requests.get(LIST_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    text = r.text.strip()
    # Naver sometimes prefixes/suffixes; isolate the JSON object.
    if not text.startswith("{"):
        m = re.search(r"\{[\s\S]*\}", text)
        text = m.group(0) if m else text
    # Naver's payload is INVALID JSON: pagingHtml contains \' (backslash-quote),
    # which json.loads rejects. Repair the illegal escape before parsing.
    text = text.replace("\\'", "'")
    try:
        data = json.loads(text)
    except Exception:
        # Last resort: regex out the three parallel lists.
        data = {
            "logNoList": (re.search(r'"logNoList"\s*:\s*"([^"]*)"', text) or [None, ""])[1],
            "titleList": (re.search(r'"titleList"\s*:\s*"([^"]*)"', text) or [None, ""])[1],
            "addDateList": (re.search(r'"addDateList"\s*:\s*"([^"]*)"', text) or [None, ""])[1],
            "totalCount": (re.search(r'"totalCount"\s*:\s*"?(\d+)"?', text) or [None, "0"])[1],
        }

    total = 0
    try:
        total = int(str(data.get("totalCount") or data.get("totalcount") or 0).replace(",", ""))
    except Exception:
        total = 0

    rows: List[Dict[str, str]] = []
    # Modern shape: postList array of dicts.
    post_list = data.get("postList")
    if isinstance(post_list, list) and post_list:
        for it in post_list:
            if not isinstance(it, dict):
                continue
            log_no = str(it.get("logNo") or it.get("logno") or "").strip()
            if not log_no:
                continue
            title = urllib.parse.unquote(str(it.get("title") or "")).strip()
            add_date = str(it.get("addDate") or it.get("adddate") or "").strip()
            rows.append({"log_no": log_no, "title": title, "post_date": add_date})
        return rows, total

    # Legacy shape: three parallel comma-joined lists.
    log_nos = _decode_list_field(str(data.get("logNoList") or ""))
    titles = _decode_list_field(str(data.get("titleList") or ""))
    dates = _decode_list_field(str(data.get("addDateList") or ""))
    for i, log_no in enumerate(log_nos):
        log_no = log_no.strip()
        if not log_no:
            continue
        rows.append({
            "log_no": log_no,
            "title": titles[i] if i < len(titles) else "",
            "post_date": dates[i] if i < len(dates) else "",
        })
    return rows, total


def enumerate_all(max_pages: int = 400, sleep: float = 0.25) -> Tuple[List[Dict[str, str]], int]:
    """Walk every list page; return (all_rows, total_count)."""
    seen: set = set()
    all_rows: List[Dict[str, str]] = []
    total = 0
    page = 1
    empty_streak = 0
    while page <= max_pages:
        try:
            rows, t = _fetch_list_page(page)
        except Exception as exc:
            print(f"[archive] list page {page} failed: {exc}")
            empty_streak += 1
            if empty_streak >= 3:
                break
            time.sleep(1.0)
            page += 1
            continue
        if t:
            total = t
        new = 0
        for r in rows:
            if r["log_no"] in seen:
                continue
            seen.add(r["log_no"])
            all_rows.append(r)
            new += 1
        if new == 0:
            empty_streak += 1
            if empty_streak >= 2:
                break
        else:
            empty_streak = 0
        if total and len(all_rows) >= total:
            break
        page += 1
        time.sleep(sleep)
    return all_rows, total


def sync_list(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Enumerate the blog and upsert list metadata (no content) into the DB."""
    rows, total = enumerate_all()
    now = _now_iso()
    inserted = 0
    for r in rows:
        cur = conn.execute("SELECT log_no FROM posts WHERE log_no=?", (r["log_no"],))
        if cur.fetchone():
            continue
        conn.execute(
            "INSERT INTO posts (log_no, title, post_date, url, content, char_len, listed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (r["log_no"], r["title"], r["post_date"], _post_url(r["log_no"]), "", 0, now),
        )
        inserted += 1
    conn.commit()
    return {"listed": len(rows), "total_reported": total, "newly_listed": inserted}


# ── STAGE 1b: fetch full content ──────────────────────────────────────────────
def _fetch_full_content(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    selectors = [
        "div.se-main-container", "div.__se_component_area",
        "div.post-view", "div#post-area", "div.sect_dsc",
        "div[class*='post_ct']", "article",
    ]
    content = ""
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            content = el.get_text(separator="\n", strip=True)
            break
    if not content:
        paras = soup.select("p, span.se-text-paragraph")
        content = "\n".join(p.get_text(strip=True) for p in paras if len(p.get_text(strip=True)) > 8)
    return content.strip()


def fetch_pending(conn: sqlite3.Connection, limit: Optional[int] = None, sleep: float = 0.4) -> Dict[str, Any]:
    """Fetch content for posts that have none yet. Resumable."""
    q = "SELECT log_no, url FROM posts WHERE content IS NULL OR content='' ORDER BY listed_at"
    if limit:
        q += f" LIMIT {int(limit)}"
    pending = conn.execute(q).fetchall()
    ok = 0
    fail = 0
    for i, (log_no, url) in enumerate(pending, 1):
        try:
            content = _fetch_full_content(url)
            conn.execute(
                "UPDATE posts SET content=?, char_len=?, fetched_at=? WHERE log_no=?",
                (content, len(content), _now_iso(), log_no),
            )
            ok += 1
        except Exception as exc:
            fail += 1
            print(f"[archive] fetch {log_no} failed: {exc}")
        if i % 25 == 0:
            conn.commit()
            _write_index(conn)
            print(f"[archive] fetched {i}/{len(pending)} (ok={ok} fail={fail})")
        time.sleep(sleep)
    conn.commit()
    _export_jsonl(conn)
    _write_index(conn)
    return {"attempted": len(pending), "ok": ok, "fail": fail}


# ── Exports / status ──────────────────────────────────────────────────────────
def _counts(conn: sqlite3.Connection) -> Dict[str, int]:
    total = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    fetched = conn.execute("SELECT COUNT(*) FROM posts WHERE content!='' AND content IS NOT NULL").fetchone()[0]
    analyzed = conn.execute("SELECT COUNT(*) FROM posts WHERE analyzed_at IS NOT NULL").fetchone()[0]
    return {"listed": total, "fetched": fetched, "analyzed": analyzed}


def _write_index(conn: sqlite3.Connection) -> None:
    idx = {"updated_at": _now_iso(), **_counts(conn)}
    try:
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, indent=2)
        if os.path.isdir(os.path.dirname(WEBROOT_INDEX)):
            import shutil
            shutil.copy2(INDEX_PATH, WEBROOT_INDEX)
    except Exception:
        pass


def _export_jsonl(conn: sqlite3.Connection) -> None:
    try:
        rows = conn.execute(
            "SELECT log_no, title, post_date, url, char_len FROM posts WHERE content!='' ORDER BY post_date"
        ).fetchall()
        with open(JSONL_PATH, "w", encoding="utf-8") as f:
            for log_no, title, post_date, url, clen in rows:
                f.write(json.dumps({
                    "log_no": log_no, "title": title, "date": post_date,
                    "url": url, "char_len": clen,
                }, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── STAGE 2: analyze a batch into the knowledge graph ─────────────────────────
def analyze_batch(conn: sqlite3.Connection, limit: int = 25) -> Dict[str, Any]:
    from tools import blog_intel
    from tools import knowledge_graph
    rows = conn.execute(
        "SELECT log_no, title, post_date, url, content FROM posts "
        "WHERE analyzed_at IS NULL AND content!='' AND content IS NOT NULL "
        "ORDER BY post_date LIMIT ?",
        (int(limit),),
    ).fetchall()
    done = 0
    for log_no, title, post_date, url, content in rows:
        post = {"title": title, "url": url, "date": post_date, "content": content}
        try:
            analysis = blog_intel.analyze_post_deep(post)
            knowledge_graph.update_from_analysis(analysis)
            conn.execute("UPDATE posts SET analyzed_at=? WHERE log_no=?", (_now_iso(), log_no))
            done += 1
        except Exception as exc:
            print(f"[archive] analyze {log_no} failed: {exc}")
    conn.commit()
    if done:
        knowledge_graph.run()  # recompute + publish (semantic links included)
    _write_index(conn)
    return {"analyzed_now": done, "remaining": _counts(conn)["fetched"] - _counts(conn)["analyzed"]}


# ── CLI ───────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(prog="blog_archive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("enumerate")
    pf = sub.add_parser("fetch")
    pf.add_argument("--limit", type=int, default=None)
    pf.add_argument("--sleep", type=float, default=0.4)
    sub.add_parser("status")
    pa = sub.add_parser("analyze")
    pa.add_argument("--limit", type=int, default=25)
    args = ap.parse_args()

    conn = _connect()
    if args.cmd == "enumerate":
        info = sync_list(conn)
        print(json.dumps({**info, **_counts(conn)}, ensure_ascii=False, indent=2))
    elif args.cmd == "fetch":
        if _counts(conn)["listed"] == 0:
            print("[archive] empty list — running enumerate first")
            print(json.dumps(sync_list(conn), ensure_ascii=False))
        info = fetch_pending(conn, limit=args.limit, sleep=args.sleep)
        print(json.dumps({**info, **_counts(conn)}, ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        print(json.dumps({"updated_at": _now_iso(), **_counts(conn)}, ensure_ascii=False, indent=2))
    elif args.cmd == "analyze":
        print(json.dumps(analyze_batch(conn, limit=args.limit), ensure_ascii=False, indent=2))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
