"""
ATLAS DB — turn blog intelligence into a STATISTICAL database (tidy/long).

Rationale (per the data-model directive): Obsidian/markdown and nested JSON are
great for reading and graphing, but useless for statistics (frequency, corr,
regression, event studies). The fix is not a format — it is the DATA MODEL:
normalized TIDY/LONG tables where one variable = one column, one observation =
one row. The decisive operation is the "explode": one article with a list of
keywords becomes one row per (article x keyword) pair.

Layered design:
    JSON (ingest, flexible)  ->  EXPLODE  ->  tidy CSV/Parquet  ->  DuckDB
    (analysis: corr / regr_slope / window) ->  { pandas stats, Obsidian views }

Tables produced (all long/tidy, joinable on post_id / date / ticker):
    articles      one row per post    — the document grain
    mentions      one row per (post x keyword)   — the explode; analysis grain
    watch         one row per (post x ticker)     — recommended watch tickers
    edges         one row per (post x edge)        — directional concept links
    cooccurrence  one row per (keyword_a x keyword_b) — QUANTIFIED correlation

Engine: DuckDB if installed (embedded, single-file, SQL + corr/regr built in).
Falls back to pure-stdlib CSV when DuckDB is absent — schema is identical.

CLI:
    python3 -m tools.atlas_db --sample 7      # build tidy tables from last 7 days, print schema+preview
    python3 -m tools.atlas_db --all           # build from every per-post analysis on disk
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE, "data")
INTEL_DIR = os.path.join(DATA_DIR, "blog_intel")
LATEST = os.path.join(DATA_DIR, "blog_intel_latest.json")
DB_DIR = os.path.join(DATA_DIR, "atlas_db")
SAMPLE_OUT = os.path.join(DATA_DIR, "atlas_db_sample.json")
WEBROOT_SAMPLE = "/var/www/html/atlas_db_sample.json"

# ── Column contracts (the "what columns / types" GOD asked to review) ──────────
SCHEMA: Dict[str, List[Tuple[str, str]]] = {
    "articles": [
        ("post_id", "TEXT"), ("date", "DATE"), ("analyzed_at", "TIMESTAMP"),
        ("title", "TEXT"), ("url", "TEXT"),
        ("cause", "TEXT"), ("result", "TEXT"), ("what_comes_next", "TEXT"),
        ("one_line", "TEXT"), ("n_keywords", "INTEGER"), ("n_watch", "INTEGER"),
    ],
    "mentions": [
        ("post_id", "TEXT"), ("date", "DATE"), ("keyword_id", "TEXT"),
        ("keyword_label", "TEXT"), ("type", "TEXT"), ("importance", "DOUBLE"),
        ("summary", "TEXT"),
    ],
    "watch": [
        ("post_id", "TEXT"), ("date", "DATE"), ("ticker", "TEXT"), ("name", "TEXT"),
        ("relevance", "INTEGER"), ("in_portfolio", "BOOLEAN"),
        ("asset_class", "TEXT"), ("thesis", "TEXT"),
    ],
    "edges": [
        ("post_id", "TEXT"), ("date", "DATE"), ("source", "TEXT"),
        ("target", "TEXT"), ("relation", "TEXT"), ("weight", "INTEGER"),
    ],
    "cooccurrence": [
        ("keyword_a", "TEXT"), ("keyword_b", "TEXT"), ("n_articles", "INTEGER"),
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_str(x: Any) -> str:
    return "" if x is None else str(x).strip()


def _date_of(a: Dict[str, Any]) -> str:
    """Best-effort YYYY-MM-DD: published date, else analyzed_at date."""
    for key in ("published", "date", "analyzed_at"):
        v = _as_str(a.get(key))
        if len(v) >= 10 and v[4] == "-" and v[7] == "-":
            return v[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ── LOAD analyses ──────────────────────────────────────────────────────────────

def _load_analyses(days: Optional[int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    # Per-post files (the durable corpus)
    for path in sorted(glob.glob(os.path.join(INTEL_DIR, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                a = json.load(f)
            pid = _as_str(a.get("post_id"))
            if pid and pid not in seen:
                seen.add(pid)
                rows.append(a)
        except Exception:
            continue
    # Aggregate latest (covers brand-new posts not yet split to files)
    try:
        with open(LATEST, encoding="utf-8") as f:
            agg = json.load(f)
        for a in agg.get("analyses", []):
            pid = _as_str(a.get("post_id"))
            if pid and pid not in seen:
                seen.add(pid)
                rows.append(a)
    except Exception:
        pass
    if days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = [a for a in rows if _date_of(a) >= cutoff] or rows  # never empty-out
    return rows


# ── EXPLODE into tidy tables ─────────────────────────────────────────────────

def explode(analyses: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    articles, mentions, watch, edges = [], [], [], []
    pair_articles: Dict[Tuple[str, str], set] = {}

    for a in analyses:
        pid = _as_str(a.get("post_id"))
        if not pid:
            continue
        d = _date_of(a)
        ss = a.get("short_summary") or {}
        kws = a.get("keywords") or []
        wl = a.get("recommended_watch") or []
        articles.append({
            "post_id": pid, "date": d, "analyzed_at": _as_str(a.get("analyzed_at")),
            "title": _as_str(a.get("title")), "url": _as_str(a.get("url")),
            "cause": _as_str(ss.get("cause")), "result": _as_str(ss.get("result")),
            "what_comes_next": _as_str(ss.get("what_comes_next")),
            "one_line": _as_str(ss.get("one_line")),
            "n_keywords": len(kws), "n_watch": len(wl),
        })

        kw_ids_in_post: List[str] = []
        for kw in kws:
            if not isinstance(kw, dict):
                continue
            kid = _as_str(kw.get("id")) or _as_str(kw.get("label"))
            if not kid:
                continue
            kw_ids_in_post.append(kid)
            mentions.append({
                "post_id": pid, "date": d, "keyword_id": kid,
                "keyword_label": _as_str(kw.get("label")) or kid,
                "type": _as_str(kw.get("type")) or "other",
                "importance": round(float(kw.get("importance") or 0.0), 4),
                "summary": _as_str(kw.get("summary"))[:500],
            })

        for w in wl:
            if not isinstance(w, dict):
                continue
            tk = _as_str(w.get("ticker")).upper()
            if not tk:
                continue
            watch.append({
                "post_id": pid, "date": d, "ticker": tk,
                "name": _as_str(w.get("name")) or tk,
                "relevance": int(w.get("relevance") or 0),
                "in_portfolio": bool(w.get("in_portfolio")),
                "asset_class": _as_str(w.get("asset_class")) or "equity",
                "thesis": _as_str(w.get("thesis"))[:500],
            })

        g = a.get("graph") or {}
        for e in (g.get("edges") or []):
            if not isinstance(e, dict):
                continue
            s, t = _as_str(e.get("source")), _as_str(e.get("target"))
            if not s or not t:
                continue
            edges.append({
                "post_id": pid, "date": d, "source": s, "target": t,
                "relation": _as_str(e.get("relation")) or "related",
                "weight": int(e.get("weight") or 1),
            })

        # Co-occurrence: every unordered keyword pair within this article.
        for kw_a, kw_b in combinations(sorted(set(kw_ids_in_post)), 2):
            pair_articles.setdefault((kw_a, kw_b), set()).add(pid)

    cooccurrence = [
        {"keyword_a": a, "keyword_b": b, "n_articles": len(pids)}
        for (a, b), pids in sorted(pair_articles.items(), key=lambda kv: -len(kv[1]))
    ]
    return {"articles": articles, "mentions": mentions, "watch": watch,
            "edges": edges, "cooccurrence": cooccurrence}


# ── WRITE tidy CSV (git-friendly, identical schema with/without DuckDB) ────────

def write_csv(tables: Dict[str, List[Dict[str, Any]]]) -> None:
    os.makedirs(DB_DIR, exist_ok=True)
    for name, cols in SCHEMA.items():
        rows = tables.get(name, [])
        path = os.path.join(DB_DIR, f"{name}.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow([c for c, _ in cols])
            for r in rows:
                w.writerow([r.get(c, "") for c, _ in cols])


def try_duckdb_load() -> Optional[Dict[str, Any]]:
    """If duckdb is installed, load the CSVs and run a couple of stat demos."""
    try:
        import duckdb  # type: ignore
    except Exception:
        return None
    try:
        con = duckdb.connect(os.path.join(DB_DIR, "atlas.duckdb"))
        for name in SCHEMA:
            csv_path = os.path.join(DB_DIR, f"{name}.csv").replace("\\", "/")
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM read_csv_auto('{csv_path}', header=true)")
        top_kw = con.execute(
            "SELECT keyword_label, COUNT(*) n FROM mentions GROUP BY 1 ORDER BY n DESC LIMIT 8"
        ).fetchall()
        top_pairs = con.execute(
            "SELECT keyword_a, keyword_b, n_articles FROM cooccurrence ORDER BY n_articles DESC LIMIT 8"
        ).fetchall()
        top_tickers = con.execute(
            "SELECT ticker, COUNT(*) n, ROUND(AVG(relevance),1) avg_rel FROM watch GROUP BY 1 ORDER BY n DESC, avg_rel DESC LIMIT 8"
        ).fetchall()
        con.close()
        return {"engine": "duckdb", "top_keywords": top_kw,
                "top_cooccurrence": top_pairs, "top_tickers": top_tickers}
    except Exception as exc:
        return {"engine": "duckdb", "error": str(exc)}


def _fallback_stats(tables: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    kw = Counter(r["keyword_label"] for r in tables["mentions"])
    tk = Counter(r["ticker"] for r in tables["watch"])
    pairs = [(r["keyword_a"], r["keyword_b"], r["n_articles"]) for r in tables["cooccurrence"][:8]]
    return {"engine": "stdlib",
            "top_keywords": kw.most_common(8),
            "top_cooccurrence": pairs,
            "top_tickers": tk.most_common(8)}


def build(days: Optional[int]) -> Dict[str, Any]:
    analyses = _load_analyses(days)
    tables = explode(analyses)
    write_csv(tables)
    stats = try_duckdb_load() or _fallback_stats(tables)

    sample = {
        "generated_at": _now(),
        "window_days": days,
        "n_articles": len(tables["articles"]),
        "schema": {name: [{"column": c, "type": t} for c, t in cols] for name, cols in SCHEMA.items()},
        "row_counts": {name: len(tables[name]) for name in SCHEMA},
        "sample_rows": {
            "articles": tables["articles"][:3],
            "mentions": tables["mentions"][:8],
            "watch": tables["watch"][:8],
            "cooccurrence": tables["cooccurrence"][:8],
        },
        "stats_demo": stats,
    }
    with open(SAMPLE_OUT, "w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False, indent=2, default=str)
    try:
        if os.path.isdir(os.path.dirname(WEBROOT_SAMPLE)):
            import shutil
            shutil.copy2(SAMPLE_OUT, WEBROOT_SAMPLE)
    except Exception:
        pass
    return sample


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=None, help="restrict to last N days")
    ap.add_argument("--all", action="store_true", help="use the full corpus on disk")
    args = ap.parse_args()
    days = None if args.all else (args.sample if args.sample is not None else 7)
    out = build(days)
    print(json.dumps({
        "engine": out["stats_demo"].get("engine"),
        "n_articles": out["n_articles"],
        "row_counts": out["row_counts"],
        "top_keywords": out["stats_demo"].get("top_keywords"),
        "top_cooccurrence": out["stats_demo"].get("top_cooccurrence"),
        "top_tickers": out["stats_demo"].get("top_tickers"),
    }, ensure_ascii=False, indent=2, default=str))
