"""
Obsidian-style accumulating knowledge graph from blog analyses.

The module upserts nodes and edges from analysis payloads, tracks post-level
idempotency, recomputes graph importance, and derives a ticker watchlist.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "knowledge_graph.json")
WEBROOT_PATH = "/var/www/html/knowledge_graph.json"

NODE_TYPES = [
    "company",
    "ticker",
    "metal",
    "commodity",
    "bond",
    "currency",
    "country",
    "sector",
    "theme",
    "person",
    "policy",
    "technology",
    "event",
    "other",
]
NODE_TYPE_SET = set(NODE_TYPES)

PRIVATE_PROCESSED_KEY = "_processed_posts"
PRIVATE_WATCH_KEY = "_watch_relevance"


# ══════════════════════════════════════════════════════════════════════════════
# SEMANTIC ONTOLOGY — deterministic cross-post linking.
# The per-post LLM only links concepts it sees together in ONE post; relatives
# that recur across posts (Samsung & TSMC, CPI & the Fed) otherwise stay islands.
# This ontology re-derives those structural links on every recompute so the map
# reads like the real world: same-sector names cluster, macro drivers interlink.
# ══════════════════════════════════════════════════════════════════════════════

# One macro cluster: CPI / inflation / rates / FOMC / Fed / liquidity / bonds all
# belong to the same causal web and are linked together.
_MACRO_ALIASES = [
    "fed", "federal reserve", "fomc", "powell", "jerome powell", "fed chair",
    "interest rate", "interest rates", "rate cut", "rate hike", "monetary policy",
    "cpi", "inflation", "pce", "ppi", "disinflation", "deflation",
    "liquidity", "net liquidity", "quantitative easing", "quantitative tightening",
    "qe", "qt", "reverse repo", "rrp", "tga", "bank reserves", "balance sheet",
    "treasury", "treasuries", "bond", "bonds", "bond yield", "yield", "yields",
    "10-year", "10y", "credit spread", "recession", "gdp", "unemployment",
    "payrolls", "jobs report", "dollar", "dxy",
    # inflation MEASURES belong to the macro web (a method of evaluating CPI/PCE
    # is not a lone island — GOD: "Trimmed Averages is a method, why alone?").
    "trimmed average", "trimmed averages", "trimmed mean", "core cpi", "core pce",
    "supercore", "median cpi", "sticky cpi", "breakeven", "inflation expectations",
]

# Each sector: member nodes get linked to one another (or to a hub if large).
_SECTOR_GROUPS: Dict[str, List[str]] = {
    "semiconductors": [
        "semiconductor", "semiconductors", "chip", "chips", "foundry", "wafer",
        "tsmc", "taiwan semiconductor", "samsung", "samsung electronics",
        "sk hynix", "hynix", "nvidia", "nvda", "asml", "applied materials", "amat",
        "micron", "intel", "broadcom", "avgo", "qualcomm", "arm", "hbm", "dram",
        "nand", "lithography", "euv", "wf6", "tungsten",
    ],
    "uranium_nuclear": [
        "uranium", "nuclear", "enrichment", "reactor", "smr", "uec", "cameco",
        "ccj", "oklo", "centrus", "leu", "yellowcake", "sprott", "urnm",
    ],
    "ai_compute": [
        "artificial intelligence", "ai infrastructure", "ai capex", "data center",
        "datacenter", "gpu", "accelerator", "llm", "large language model", "compute",
        "hyperscaler", "openai", "anthropic", "palantir", "pltr",
    ],
    "space": [
        "space", "spacex", "rocket", "satellite", "launch", "rocket lab", "rklb",
        "planet labs", "starlink", "constellation",
        # GOD: "Volume Constraints — isn't this related to Launch Capacity?"
        "launch capacity", "launch cadence", "volume constraint", "volume constraints",
        "payload", "reusability", "launch vehicle", "space data center",
    ],
    "defense": [
        "defense", "defence", "missile", "drone", "munition", "kratos", "ktos",
        "aerovironment", "avav", "hanwha", "lockheed", "raytheon", "weapon",
    ],
    "energy_power": [
        "power grid", "electricity", "utility", "grid", "transmission",
        "natural gas", "lng", "solar", "wind", "renewable", "vertiv", "vrt",
    ],
    "biotech": [
        "biotech", "gene editing", "crispr", "mrna", "clinical trial", "oncology",
        "regeneron", "regn", "beam", "ntla", "crsp", "fda",
    ],
    "battery_ev": [
        "battery", "lithium", "solid-state", "electric vehicle", "tesla", "tsla",
        "byd", "cathode", "anode",
    ],
    "critical_minerals": [
        "copper", "rare earth", "rare earths", "gallium", "germanium", "cobalt",
        "nickel", "graphite", "critical mineral", "critical minerals", "freeport",
        "fcx",
    ],
    # GOD: "Netanyahu, Economic Corridor — isn't this related to IMEC?"
    "imec_corridor": [
        "imec", "india-middle east-europe", "india middle east europe",
        "economic corridor", "trade corridor", "netanyahu", "israel", "saudi arabia",
        "uae", "red sea", "suez", "belt and road", "bri",
    ],
    # GOD: "SEC — isn't this related to Hynix and ADR?" Filings/listings web.
    "filings_listings": [
        "sec", "securities and exchange commission", "adr",
        "american depositary receipt", "american depositary", "ipo", "listing",
        "relisting", "nasdaq", "nyse", "form 4", "8-k", "10-k", "10-q", "20-f",
        "prospectus", "s-1", "delisting", "dual listing",
    ],
}


# ══════════════════════════════════════════════════════════════════════════════
# CANONICAL ENTITY ALIASING — collapse SYNONYMS of the SAME entity into ONE node.
# (e.g. "Taiwan Semiconductor Manufacturing Company" / "TSMC" / "TSM" -> one node.)
# This is distinct from the ontology above: ontology LINKS related entities with
# edges; this MERGES different names of a single entity so the map isn't littered
# with duplicate islands. Conservative on purpose — only true synonyms, never
# merely-related concepts (CPI and inflation stay separate; they get LINKED).
# ══════════════════════════════════════════════════════════════════════════════
_CANON_ENTITIES: List[Tuple[str, str, str, List[str]]] = [
    ("tsmc", "TSMC", "ticker", ["tsmc", "tsm", "taiwan semiconductor", "taiwan semiconductor manufacturing"]),
    ("samsung", "Samsung Electronics", "company", ["samsung electronics", "samsung"]),
    ("sk_hynix", "SK Hynix", "company", ["sk hynix", "hynix", "000660"]),
    ("nvidia", "NVIDIA", "ticker", ["nvidia", "nvda"]),
    ("broadcom", "Broadcom", "ticker", ["broadcom", "avgo"]),
    ("alphabet", "Alphabet (Google)", "ticker", ["alphabet", "googl", "google"]),
    ("microsoft", "Microsoft", "ticker", ["microsoft", "msft"]),
    ("applied_materials", "Applied Materials", "ticker", ["applied materials", "amat"]),
    ("asml", "ASML", "ticker", ["asml"]),
    ("micron", "Micron", "ticker", ["micron technology", "micron"]),
    ("intel", "Intel", "ticker", ["intel"]),
    ("palantir", "Palantir", "ticker", ["palantir", "pltr"]),
    ("tesla", "Tesla", "ticker", ["tesla", "tsla"]),
    ("oklo", "Oklo", "ticker", ["oklo"]),
    ("uranium_energy", "Uranium Energy", "ticker", ["uranium energy", "uec"]),
    ("cameco", "Cameco", "ticker", ["cameco", "ccj"]),
    ("rocket_lab", "Rocket Lab", "ticker", ["rocket lab", "rklb"]),
    ("planet_labs", "Planet Labs", "ticker", ["planet labs"]),
    ("spacex", "SpaceX", "company", ["spacex", "space x"]),
    ("kratos", "Kratos Defense", "ticker", ["kratos", "ktos"]),
    ("regeneron", "Regeneron", "ticker", ["regeneron", "regn"]),
    ("nutrien", "Nutrien", "ticker", ["nutrien", "ntr"]),
    ("coherent", "Coherent", "ticker", ["coherent", "cohr"]),
    ("federal_reserve", "Federal Reserve", "policy", ["federal reserve", "the fed", "fed reserve"]),
]


def _canon_resolve(node_id: str, label: str, ntype: str) -> Optional[Tuple[str, str, str]]:
    """Return (canonical_id, canonical_label, canonical_type) if this node is a
    known synonym of a canonical entity, else None."""
    text = f"{node_id} {label}".lower()
    toks = set(re.findall(r"[a-z0-9]+", text))
    for cid, clabel, ctype, aliases in _CANON_ENTITIES:
        for a in aliases:
            if (" " in a and a in text) or (" " not in a and a in toks):
                return cid, clabel, ctype
    return None


def _norm_key(s: Any) -> str:
    """Aggressive dedup key: lowercase, drop ALL non-alphanumerics. So 'S.E.C.',
    'SEC', 'sec' and 'S E C' collapse; 'AI/Compute', 'AI - Compute' collapse."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _collapse_nodes(
    node_by_id: Dict[str, Dict[str, Any]],
    edge_by_key: Dict[Tuple[str, str], Dict[str, Any]],
    remap: Dict[str, str],
) -> int:
    """Merge each old_id -> canon_id (canon must already exist), rewiring edges.
    Sums weights/mentions, unions tickers/posts, keeps target label/summary."""
    remap = {o: c for o, c in remap.items() if o != c and c in node_by_id}
    if not remap:
        return 0
    for old_id, cid in remap.items():
        if old_id not in node_by_id:
            continue
        old = node_by_id.pop(old_id)
        tgt = node_by_id[cid]
        tgt["weight"] = _safe_int(tgt.get("weight"), 0) + _safe_int(old.get("weight"), 0)
        tgt["mentions"] = _safe_int(tgt.get("mentions"), 0) + _safe_int(old.get("mentions"), 0)
        if not tgt.get("summary"):
            tgt["summary"] = old.get("summary", "")
        tgt["tickers"] = sorted({*(tgt.get("tickers") or []), *(old.get("tickers") or [])})
        tgt["posts"] = list(dict.fromkeys([*(tgt.get("posts") or []), *(old.get("posts") or [])]))[-20:]

    def _rid(x: str) -> str:
        return remap.get(x, x)

    new_edges: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (a, b), e in edge_by_key.items():
        na, nb = _rid(a), _rid(b)
        if not na or not nb or na == nb:
            continue
        k = _edge_key(na, nb)
        if k in new_edges:
            new_edges[k]["weight"] = _safe_int(new_edges[k].get("weight"), 0) + _safe_int(e.get("weight"), 1)
        else:
            e2 = dict(e)
            e2["source"], e2["target"] = k[0], k[1]
            new_edges[k] = e2
    edge_by_key.clear()
    edge_by_key.update(new_edges)
    return len(remap)


def _merge_canonical(
    node_by_id: Dict[str, Dict[str, Any]],
    edge_by_key: Dict[Tuple[str, str], Dict[str, Any]],
) -> int:
    """Collapse known synonym nodes into their canonical node (TSMC == Taiwan
    Semiconductor Manufacturing Company). Idempotent."""
    remap: Dict[str, str] = {}
    for nid in list(node_by_id.keys()):
        node = node_by_id[nid]
        canon = _canon_resolve(nid, str(node.get("label") or ""), str(node.get("type") or ""))
        if canon and canon[0] != nid:
            cid, clabel, ctype = canon
            if cid not in node_by_id:
                node_by_id[cid] = {
                    "id": cid, "label": clabel, "type": ctype, "weight": 0, "degree": 0,
                    "weighted_degree": 0, "centrality": 0.0, "mentions": 0,
                    "first_seen": node.get("first_seen") or _now_iso(),
                    "last_seen": node.get("last_seen") or _now_iso(),
                    "summary": node.get("summary", ""), "tickers": [], "posts": [],
                }
            else:
                node_by_id[cid]["label"] = clabel
                node_by_id[cid]["type"] = ctype
            remap[nid] = cid
    return _collapse_nodes(node_by_id, edge_by_key, remap)


def _merge_by_normalized_key(
    node_by_id: Dict[str, Dict[str, Any]],
    edge_by_key: Dict[Tuple[str, str], Dict[str, Any]],
) -> int:
    """General dedup: collapse nodes whose labels are identical after stripping
    case + punctuation (abbreviation/'/'/'-'/Capital variants). Keeps the
    highest-weight, longest-label node as canonical."""
    groups: Dict[str, List[str]] = {}
    for nid, node in node_by_id.items():
        key = _norm_key(node.get("label") or nid) or _norm_key(nid)
        if key:
            groups.setdefault(key, []).append(nid)
    remap: Dict[str, str] = {}
    for _key, ids in groups.items():
        if len(ids) < 2:
            continue
        canon = max(ids, key=lambda i: (
            _safe_int(node_by_id[i].get("weight"), 0),
            len(str(node_by_id[i].get("label") or "")),
        ))
        for i in ids:
            if i != canon:
                remap[i] = canon
    return _collapse_nodes(node_by_id, edge_by_key, remap)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _node_text(node: Dict[str, Any]) -> str:
    return f"{node.get('id', '')} {node.get('label', '')}".lower()


def _tokenize(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", text))


def _alias_hit(alias: str, text: str, tokens: set) -> bool:
    """Multiword/hyphenated aliases match as substrings; single tokens must match
    a whole word (so 'arm' hits 'Arm Holdings' but not 'alarm')."""
    if " " in alias or "-" in alias:
        return alias in text
    return alias in tokens


def _group_member_ids(node_by_id: Dict[str, Dict[str, Any]], aliases: List[str]) -> List[str]:
    out: List[str] = []
    for nid, node in node_by_id.items():
        text = _node_text(node)
        toks = _tokenize(text)
        if any(_alias_hit(a, text, toks) for a in aliases):
            out.append(nid)
    return out


def _set_semantic_edge(
    edge_by_key: Dict[Tuple[str, str], Dict[str, Any]],
    a: str, b: str, relation: str, now: str,
) -> None:
    if not a or not b or a == b:
        return
    k = _edge_key(a, b)
    if k in edge_by_key:
        return  # a real (post-derived) edge already connects these — leave it
    edge_by_key[k] = {
        "source": k[0], "target": k[1], "weight": 2,
        "relation": relation, "last_seen": now, "kind": "semantic",
    }


def _link_group(
    node_by_id: Dict[str, Dict[str, Any]],
    edge_by_key: Dict[Tuple[str, str], Dict[str, Any]],
    ids: List[str], relation: str, now: str,
) -> None:
    ids = sorted(set(ids))
    if len(ids) < 2:
        return
    if len(ids) > 14:
        # Large cluster: star to the heaviest member to bound edge count.
        hub = max(ids, key=lambda i: _safe_int(node_by_id.get(i, {}).get("weight"), 0))
        for nid in ids:
            _set_semantic_edge(edge_by_key, hub, nid, relation, now)
        return
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            _set_semantic_edge(edge_by_key, ids[i], ids[j], relation, now)


def _add_semantic_links(
    node_by_id: Dict[str, Dict[str, Any]],
    edge_by_key: Dict[Tuple[str, str], Dict[str, Any]],
) -> int:
    """Add deterministic ontology edges. Returns count added. Idempotent: callers
    must drop existing kind=='semantic' edges first."""
    before = len(edge_by_key)
    now = _now_iso()
    _link_group(node_by_id, edge_by_key, _group_member_ids(node_by_id, _MACRO_ALIASES), "macro", now)
    for name, aliases in _SECTOR_GROUPS.items():
        _link_group(node_by_id, edge_by_key, _group_member_ids(node_by_id, aliases), f"sector:{name}", now)
    return len(edge_by_key) - before


def _parse_iso(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return _now_iso()
    raw = value.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return _now_iso()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        out = int(value)
        return out
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if out != out:  # NaN guard
            return default
        if out in (float("inf"), float("-inf")):
            return default
        return out
    except Exception:
        return default


def _default_graph() -> Dict[str, Any]:
    return {
        "updated_at": _now_iso(),
        "stats": {"n_nodes": 0, "n_edges": 0, "n_posts": 0},
        "node_types": list(NODE_TYPES),
        "nodes": [],
        "edges": [],
        "top_nodes": [],
        "watchlist": [],
        PRIVATE_PROCESSED_KEY: [],
        PRIVATE_WATCH_KEY: {},
    }


def _normalize_graph(raw: Any) -> Dict[str, Any]:
    g = _default_graph()
    if not isinstance(raw, dict):
        return g

    g["updated_at"] = _parse_iso(raw.get("updated_at"))
    g["node_types"] = list(NODE_TYPES)
    g["nodes"] = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    g["edges"] = raw.get("edges") if isinstance(raw.get("edges"), list) else []
    g["top_nodes"] = raw.get("top_nodes") if isinstance(raw.get("top_nodes"), list) else []
    g["watchlist"] = raw.get("watchlist") if isinstance(raw.get("watchlist"), list) else []

    processed = raw.get(PRIVATE_PROCESSED_KEY)
    g[PRIVATE_PROCESSED_KEY] = list(processed) if isinstance(processed, list) else []
    if len(g[PRIVATE_PROCESSED_KEY]) > 2000:
        g[PRIVATE_PROCESSED_KEY] = g[PRIVATE_PROCESSED_KEY][-2000:]

    watch_meta = raw.get(PRIVATE_WATCH_KEY)
    g[PRIVATE_WATCH_KEY] = watch_meta if isinstance(watch_meta, dict) else {}

    stats = raw.get("stats")
    if isinstance(stats, dict):
        g["stats"] = {
            "n_nodes": _safe_int(stats.get("n_nodes"), 0),
            "n_edges": _safe_int(stats.get("n_edges"), 0),
            "n_posts": _safe_int(stats.get("n_posts"), len(g[PRIVATE_PROCESSED_KEY])),
        }
    else:
        g["stats"] = {"n_nodes": len(g["nodes"]), "n_edges": len(g["edges"]), "n_posts": len(g[PRIVATE_PROCESSED_KEY])}
    return g


def _atomic_json_write(path: str, payload: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _node_index(g: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for n in g.get("nodes", []):
        if isinstance(n, dict):
            nid = str(n.get("id") or "").strip()
            if nid:
                out[nid] = n
    return out


def _edge_key(a: str, b: str) -> Tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _edge_index(g: Dict[str, Any]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for e in g.get("edges", []):
        if not isinstance(e, dict):
            continue
        s = str(e.get("source") or "").strip()
        t = str(e.get("target") or "").strip()
        if not s or not t or s == t:
            continue
        out[_edge_key(s, t)] = e
    return out


def _append_post(posts: Any, post_id: str) -> List[str]:
    out: List[str] = list(posts) if isinstance(posts, list) else []
    if post_id and post_id not in out:
        out.append(post_id)
    if len(out) > 20:
        out = out[-20:]
    return out


def _normalize_ticker(raw: Any) -> str:
    if not isinstance(raw, str):
        return ""
    return raw.strip().upper()


def _normalize_node_type(raw_type: Any) -> str:
    t = str(raw_type or "").strip().lower()
    return t if t in NODE_TYPE_SET else "other"


def _upsert_node(
    node_by_id: Dict[str, Dict[str, Any]],
    node_id: str,
    *,
    label: str = "",
    ntype: str = "other",
    summary: str = "",
    analyzed_at: str,
    post_id: str,
    increment_weight: int = 1,
    attach_ticker: Optional[str] = None,
) -> Dict[str, Any]:
    # Redirect known synonyms onto their canonical node at write time.
    _canon = _canon_resolve(node_id, label, ntype)
    if _canon:
        node_id, label, ntype = _canon[0], _canon[1], _canon[2]
    if node_id not in node_by_id:
        node_by_id[node_id] = {
            "id": node_id,
            "label": label or node_id,
            "type": _normalize_node_type(ntype),
            "weight": 0,
            "degree": 0,
            "weighted_degree": 0,
            "centrality": 0.0,
            "mentions": 0,
            "first_seen": analyzed_at,
            "last_seen": analyzed_at,
            "summary": summary or "",
            "tickers": [],
            "posts": [post_id] if post_id else [],
        }
    node = node_by_id[node_id]

    if label:
        node["label"] = label
    node["type"] = _normalize_node_type(ntype or node.get("type"))
    if summary:
        node["summary"] = summary

    node["weight"] = _safe_int(node.get("weight"), 0) + max(0, increment_weight)
    node["mentions"] = _safe_int(node.get("mentions"), 0) + max(0, increment_weight)

    first_seen = _parse_iso(node.get("first_seen"))
    last_seen = _parse_iso(node.get("last_seen"))
    if analyzed_at < first_seen:
        node["first_seen"] = analyzed_at
    else:
        node["first_seen"] = first_seen
    if analyzed_at > last_seen:
        node["last_seen"] = analyzed_at
    else:
        node["last_seen"] = last_seen

    node["posts"] = _append_post(node.get("posts"), post_id)

    ticks = node.get("tickers")
    if not isinstance(ticks, list):
        ticks = []
    if attach_ticker:
        t = _normalize_ticker(attach_ticker)
        if t and t not in ticks:
            ticks.append(t)
    node["tickers"] = sorted({t for t in ticks if isinstance(t, str) and t.strip()})
    return node


def _upsert_edge(
    edge_by_key: Dict[Tuple[str, str], Dict[str, Any]],
    source: str,
    target: str,
    *,
    relation: str = "related",
    analyzed_at: str,
    increment_weight: int = 1,
) -> None:
    if not source or not target or source == target:
        return
    k = _edge_key(source, target)
    if k not in edge_by_key:
        edge_by_key[k] = {
            "source": k[0],
            "target": k[1],
            "weight": 0,
            "relation": relation or "related",
            "last_seen": analyzed_at,
        }
    edge = edge_by_key[k]
    edge["weight"] = _safe_int(edge.get("weight"), 0) + max(1, _safe_int(increment_weight, 1))
    if relation:
        edge["relation"] = relation
    edge["last_seen"] = analyzed_at


def _best_label_match(label: str, candidates: List[Tuple[str, str]]) -> Optional[str]:
    if not label:
        return None
    needle = label.strip().lower()
    if not needle:
        return None
    for ticker, name in candidates:
        if needle == ticker.lower():
            return ticker
        if needle == (name or "").strip().lower():
            return ticker
    for ticker, name in candidates:
        low_name = (name or "").lower()
        if needle in low_name or low_name in needle:
            return ticker
    return None


def ticker_for_label(label: Any) -> Optional[str]:
    """Best-effort map label/company text to configured ticker."""
    if not isinstance(label, str):
        return None
    try:
        import config  # type: ignore
    except Exception:
        return None

    candidates: List[Tuple[str, str]] = []
    portfolio = getattr(config, "PORTFOLIO", {})
    if isinstance(portfolio, dict):
        for positions in portfolio.values():
            if not isinstance(positions, list):
                continue
            for p in positions:
                if not isinstance(p, dict):
                    continue
                tk = _normalize_ticker(p.get("ticker"))
                nm = str(p.get("name") or "")
                if tk:
                    candidates.append((tk, nm))
    watchlist = getattr(config, "WATCHLIST", [])
    if isinstance(watchlist, list):
        for w in watchlist:
            if not isinstance(w, dict):
                continue
            tk = _normalize_ticker(w.get("ticker"))
            nm = str(w.get("name") or "")
            if tk:
                candidates.append((tk, nm))

    seen: set = set()
    uniq_candidates: List[Tuple[str, str]] = []
    for ticker, name in candidates:
        if ticker in seen:
            continue
        seen.add(ticker)
        uniq_candidates.append((ticker, name))
    return _best_label_match(label, uniq_candidates)


def load_graph() -> Dict[str, Any]:
    """Load graph JSON from disk and normalize shape."""
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return _normalize_graph(raw)
    except Exception:
        return _default_graph()


def save_graph(g: Dict[str, Any]) -> None:
    """Persist graph JSON atomically to data/knowledge_graph.json."""
    payload = _normalize_graph(g)
    payload["updated_at"] = _now_iso()
    _atomic_json_write(DATA_PATH, payload)


def _choose_related_keyword_ids(analysis: Dict[str, Any]) -> List[str]:
    keywords = analysis.get("keywords")
    if not isinstance(keywords, list):
        return []
    related: List[str] = []
    scored: List[Tuple[float, str]] = []
    for kw in keywords:
        if not isinstance(kw, dict):
            continue
        kid = str(kw.get("id") or "").strip()
        if not kid:
            continue
        rc = kw.get("related_core")
        if isinstance(rc, list):
            for rid in rc:
                rid_s = str(rid or "").strip()
                if rid_s:
                    related.append(rid_s)
        scored.append((_safe_float(kw.get("importance"), 0.0), kid))
    if related:
        return list(dict.fromkeys(related))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_ids = [kid for _, kid in scored[:5]]
    return list(dict.fromkeys(top_ids))


def _apply_analysis_to_graph(g: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(analysis, dict):
        return g

    post_id = str(analysis.get("post_id") or "").strip()
    if not post_id:
        return g
    processed = g.get(PRIVATE_PROCESSED_KEY)
    if not isinstance(processed, list):
        processed = []
        g[PRIVATE_PROCESSED_KEY] = processed
    if post_id in processed:
        return g

    analyzed_at = _parse_iso(analysis.get("analyzed_at"))
    node_by_id = _node_index(g)
    edge_by_key = _edge_index(g)
    watch_meta = g.get(PRIVATE_WATCH_KEY)
    if not isinstance(watch_meta, dict):
        watch_meta = {}
        g[PRIVATE_WATCH_KEY] = watch_meta

    graph_block = analysis.get("graph")
    graph_nodes = graph_block.get("nodes") if isinstance(graph_block, dict) and isinstance(graph_block.get("nodes"), list) else []
    graph_edges = graph_block.get("edges") if isinstance(graph_block, dict) and isinstance(graph_block.get("edges"), list) else []
    keyword_rows = analysis.get("keywords") if isinstance(analysis.get("keywords"), list) else []
    rec_watch = analysis.get("recommended_watch") if isinstance(analysis.get("recommended_watch"), list) else []

    # 1) Graph nodes from explicit graph payload (+1 each appearance).
    for raw in graph_nodes:
        if not isinstance(raw, dict):
            continue
        nid = str(raw.get("id") or "").strip()
        if not nid:
            continue
        lbl = str(raw.get("label") or nid).strip()
        ntype = _normalize_node_type(raw.get("type"))
        summary = str(raw.get("summary") or "").strip()
        mapped_ticker = ticker_for_label(lbl) or (nid.upper() if ntype == "ticker" else None)
        _upsert_node(
            node_by_id,
            nid,
            label=lbl,
            ntype=ntype,
            summary=summary,
            analyzed_at=analyzed_at,
            post_id=post_id,
            increment_weight=1,
            attach_ticker=mapped_ticker,
        )

    # 2) Keyword mentions: upsert/increment +1 each mention.
    for kw in keyword_rows:
        if not isinstance(kw, dict):
            continue
        kid = str(kw.get("id") or "").strip()
        if not kid:
            continue
        lbl = str(kw.get("label") or kid).strip()
        ntype = _normalize_node_type(kw.get("type"))
        summary = str(kw.get("summary") or "").strip()
        mapped_ticker = ticker_for_label(lbl) or (kid.upper() if ntype == "ticker" else None)
        _upsert_node(
            node_by_id,
            kid,
            label=lbl,
            ntype=ntype,
            summary=summary,
            analyzed_at=analyzed_at,
            post_id=post_id,
            increment_weight=1,
            attach_ticker=mapped_ticker,
        )

    # 3) Explicit graph edges.
    for raw in graph_edges:
        if not isinstance(raw, dict):
            continue
        s = str(raw.get("source") or "").strip()
        t = str(raw.get("target") or "").strip()
        rel = str(raw.get("relation") or "related").strip() or "related"
        inc = _safe_int(raw.get("weight"), 1)
        if not s or not t:
            continue
        if s not in node_by_id:
            _upsert_node(node_by_id, s, analyzed_at=analyzed_at, post_id=post_id, increment_weight=1)
        if t not in node_by_id:
            _upsert_node(node_by_id, t, analyzed_at=analyzed_at, post_id=post_id, increment_weight=1)
        _upsert_edge(edge_by_key, s, t, relation=rel, analyzed_at=analyzed_at, increment_weight=inc)

    # 4) Recommended watch ticker nodes + relevance memory.
    related_ids = _choose_related_keyword_ids(analysis)
    for rw in rec_watch:
        if not isinstance(rw, dict):
            continue
        ticker = _normalize_ticker(rw.get("ticker"))
        if not ticker:
            continue
        name = str(rw.get("name") or ticker).strip()
        relevance = max(0, min(100, _safe_int(rw.get("relevance"), 0)))
        thesis = str(rw.get("thesis") or "").strip()
        asset_class = str(rw.get("asset_class") or "equity").strip()

        node = _upsert_node(
            node_by_id,
            ticker,
            label=name,
            ntype="ticker",
            summary=thesis,
            analyzed_at=analyzed_at,
            post_id=post_id,
            increment_weight=1,
            attach_ticker=ticker,
        )
        node["type"] = "ticker"
        if ticker not in node.get("tickers", []):
            node["tickers"] = sorted(set(node.get("tickers", []) + [ticker]))

        wm = watch_meta.get(ticker)
        if not isinstance(wm, dict):
            wm = {"name": name, "relevance_sum": 0, "mentions": 0, "last_thesis": "", "asset_class": asset_class}
            watch_meta[ticker] = wm
        wm["name"] = name or wm.get("name") or ticker
        wm["relevance_sum"] = _safe_int(wm.get("relevance_sum"), 0) + relevance
        wm["mentions"] = _safe_int(wm.get("mentions"), 0) + 1
        if thesis:
            wm["last_thesis"] = thesis
        wm["asset_class"] = asset_class or wm.get("asset_class") or "equity"
        wm["last_seen"] = analyzed_at

        # Implicit ticker -> related keyword edges.
        for rid in related_ids:
            if rid == ticker:
                continue
            if rid not in node_by_id:
                _upsert_node(node_by_id, rid, analyzed_at=analyzed_at, post_id=post_id, increment_weight=1)
            # Attach ticker reference to related node.
            _upsert_node(
                node_by_id,
                rid,
                analyzed_at=analyzed_at,
                post_id=post_id,
                increment_weight=0,
                attach_ticker=ticker,
            )
            _upsert_edge(
                edge_by_key,
                ticker,
                rid,
                relation="recommended_with",
                analyzed_at=analyzed_at,
                increment_weight=1,
            )

    g["nodes"] = sorted(node_by_id.values(), key=lambda n: str(n.get("id") or ""))
    g["edges"] = sorted(edge_by_key.values(), key=lambda e: (str(e.get("source") or ""), str(e.get("target") or "")))
    processed.append(post_id)
    if len(processed) > 2000:
        g[PRIVATE_PROCESSED_KEY] = processed[-2000:]
    g["updated_at"] = _now_iso()
    return g


def update_from_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert ONE analysis payload into graph storage (idempotent by post_id)."""
    g = load_graph()
    g = _apply_analysis_to_graph(g, analysis)
    save_graph(g)
    return g


def recompute(g: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute degrees, centrality, top nodes, stats, and derived watchlist."""
    g = _normalize_graph(g)
    node_by_id = _node_index(g)
    edge_by_key = _edge_index(g)
    watch_meta = g.get(PRIVATE_WATCH_KEY)
    if not isinstance(watch_meta, dict):
        watch_meta = {}
        g[PRIVATE_WATCH_KEY] = watch_meta

    # Collapse synonym duplicates into canonical entities FIRST (TSMC == Taiwan
    # Semiconductor Manufacturing Company), rewiring edges onto the canonical id.
    _merge_canonical(node_by_id, edge_by_key)
    # Then a general dedup pass: any remaining nodes whose labels match after
    # stripping case + punctuation (S.E.C./SEC, AI/Compute vs AI-Compute) collapse.
    _merge_by_normalized_key(node_by_id, edge_by_key)

    # Regenerate semantic ontology edges fresh (drop stale ones first so their
    # fixed weight never compounds across repeated recompute() calls).
    for k in [k for k, e in edge_by_key.items() if isinstance(e, dict) and e.get("kind") == "semantic"]:
        del edge_by_key[k]
    _add_semantic_links(node_by_id, edge_by_key)

    degree_count: Dict[str, int] = defaultdict(int)
    weighted_degree: Dict[str, int] = defaultdict(int)
    neighbors: Dict[str, Dict[str, int]] = defaultdict(dict)

    # Build undirected adjacency and weighted degrees.
    for (a, b), edge in edge_by_key.items():
        w = max(1, _safe_int(edge.get("weight"), 1))
        degree_count[a] += 1
        degree_count[b] += 1
        weighted_degree[a] += w
        weighted_degree[b] += w
        neighbors[a][b] = neighbors[a].get(b, 0) + w
        neighbors[b][a] = neighbors[b].get(a, 0) + w

    max_wdeg = 0
    for nid in node_by_id:
        max_wdeg = max(max_wdeg, weighted_degree.get(nid, 0))

    for nid, node in node_by_id.items():
        node["degree"] = degree_count.get(nid, 0)
        node["weighted_degree"] = weighted_degree.get(nid, 0)
        if max_wdeg > 0:
            c = node["weighted_degree"] / float(max_wdeg)
        else:
            c = 0.0
        if c != c or c in (float("inf"), float("-inf")):
            c = 0.0
        node["centrality"] = round(max(0.0, min(1.0, c)), 6)
        node["weight"] = max(0, _safe_int(node.get("weight"), 0))
        node["mentions"] = max(0, _safe_int(node.get("mentions"), node.get("weight", 0)))
        node["type"] = _normalize_node_type(node.get("type"))

        ticks = node.get("tickers")
        if not isinstance(ticks, list):
            ticks = []
        normalized_ticks = sorted({_normalize_ticker(t) for t in ticks if _normalize_ticker(t)})
        # If this node is itself a ticker-like label, attach it.
        if node["type"] == "ticker":
            nid_t = _normalize_ticker(node.get("id"))
            if nid_t:
                normalized_ticks = sorted(set(normalized_ticks + [nid_t]))
        mapped_from_label = ticker_for_label(str(node.get("label") or ""))
        if mapped_from_label:
            normalized_ticks = sorted(set(normalized_ticks + [mapped_from_label]))
        node["tickers"] = normalized_ticks
        node["posts"] = _append_post(node.get("posts"), "")

    # Top nodes by centrality, then weighted_degree, then mentions.
    ranked_nodes = sorted(
        node_by_id.values(),
        key=lambda n: (
            -_safe_float(n.get("centrality"), 0.0),
            -_safe_int(n.get("weighted_degree"), 0),
            -_safe_int(n.get("mentions"), 0),
            str(n.get("id") or ""),
        ),
    )
    top_nodes = []
    for n in ranked_nodes[:25]:
        top_nodes.append(
            {
                "id": str(n.get("id") or ""),
                "label": str(n.get("label") or n.get("id") or ""),
                "type": _normalize_node_type(n.get("type")),
                "centrality": round(_safe_float(n.get("centrality"), 0.0), 6),
            }
        )

    # Build watchlist candidates from node tickers, ticker nodes, and rec metadata.
    ticker_scores: Dict[str, Dict[str, Any]] = {}

    def touch_ticker(tk: str, default_name: str = "") -> Dict[str, Any]:
        t = _normalize_ticker(tk)
        if not t:
            return {}
        if t not in ticker_scores:
            ticker_scores[t] = {
                "ticker": t,
                "name": default_name or t,
                "score": 0.0,
                "linked_nodes": defaultdict(float),
                "reason_bits": [],
            }
        elif default_name and ticker_scores[t]["name"] == t:
            ticker_scores[t]["name"] = default_name
        return ticker_scores[t]

    for node in node_by_id.values():
        nid = str(node.get("id") or "")
        nlabel = str(node.get("label") or nid)
        ncentral = _safe_float(node.get("centrality"), 0.0)
        nweight = _safe_int(node.get("weight"), 0)
        nwdeg = _safe_int(node.get("weighted_degree"), 0)
        ntype = _normalize_node_type(node.get("type"))

        mapped_ticks: List[str] = []
        if ntype == "ticker":
            mapped_ticks.append(_normalize_ticker(nid) or _normalize_ticker(nlabel))
        mapped_ticks.extend([_normalize_ticker(t) for t in node.get("tickers", []) if isinstance(t, str)])
        maybe = ticker_for_label(nlabel)
        if maybe:
            mapped_ticks.append(maybe)
        mapped_ticks = sorted({t for t in mapped_ticks if t})

        for tk in mapped_ticks:
            row = touch_ticker(tk, nlabel if ntype == "ticker" else "")
            if not row:
                continue
            row["score"] += (ncentral * 60.0) + (nweight * 2.0) + (nwdeg * 1.0)
            row["linked_nodes"][nid] += max(1.0, ncentral * 10.0)

            neigh = neighbors.get(nid, {})
            for nn, w in sorted(neigh.items(), key=lambda kv: kv[1], reverse=True)[:5]:
                row["linked_nodes"][nn] += float(w)

    for tk, meta in watch_meta.items():
        row = touch_ticker(tk, str(meta.get("name") or tk))
        if not row:
            continue
        rel_sum = _safe_int(meta.get("relevance_sum"), 0)
        rel_n = max(1, _safe_int(meta.get("mentions"), 0))
        rel_avg = rel_sum / float(rel_n)
        row["score"] += rel_avg * 1.5
        thesis = str(meta.get("last_thesis") or "").strip()
        if thesis:
            row["reason_bits"].append(thesis)

    watch_rows: List[Dict[str, Any]] = []
    for tk, row in ticker_scores.items():
        linked = row.get("linked_nodes")
        linked_nodes = []
        if isinstance(linked, dict):
            linked_nodes = [nid for nid, _ in sorted(linked.items(), key=lambda kv: kv[1], reverse=True)[:5] if nid != tk]
        reason_bits = row.get("reason_bits", [])
        if not reason_bits:
            neighbor_labels = []
            for nid in linked_nodes[:2]:
                n = node_by_id.get(nid)
                if n:
                    neighbor_labels.append(str(n.get("label") or nid))
            if neighbor_labels:
                reason = f"Linked to {', '.join(neighbor_labels)}"
            else:
                reason = "High graph centrality and co-occurrence"
        else:
            reason = reason_bits[-1][:180]

        score = round(max(0.0, _safe_float(row.get("score"), 0.0)), 4)
        watch_rows.append(
            {
                "ticker": tk,
                "name": str(row.get("name") or tk),
                "score": score,
                "reason": reason,
                "linked_nodes": linked_nodes,
            }
        )

    watch_rows.sort(key=lambda r: (-_safe_float(r.get("score"), 0.0), r.get("ticker", "")))
    watch_rows = watch_rows[:15]

    g["nodes"] = sorted(node_by_id.values(), key=lambda n: str(n.get("id") or ""))
    g["edges"] = sorted(edge_by_key.values(), key=lambda e: (str(e.get("source") or ""), str(e.get("target") or "")))
    g["top_nodes"] = top_nodes
    g["watchlist"] = watch_rows
    g["stats"] = {
        "n_nodes": len(g["nodes"]),
        "n_edges": len(g["edges"]),
        "n_posts": len(g.get(PRIVATE_PROCESSED_KEY, [])) if isinstance(g.get(PRIVATE_PROCESSED_KEY), list) else 0,
    }
    g["updated_at"] = _now_iso()
    return g


def backfill(analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Apply analyses in chronological order, recompute, and save."""
    g = load_graph()
    safe_analyses = analyses if isinstance(analyses, list) else []
    sortable: List[Tuple[str, int, Dict[str, Any]]] = []
    for idx, item in enumerate(safe_analyses):
        if isinstance(item, dict):
            sortable.append((_parse_iso(item.get("analyzed_at")), idx, item))
    sortable.sort(key=lambda x: (x[0], x[1]))
    for _, _, analysis in sortable:
        g = _apply_analysis_to_graph(g, analysis)
    g = recompute(g)
    save_graph(g)
    return g


def publish() -> None:
    """Mirror graph JSON to webroot when /var/www/html exists."""
    webroot_dir = os.path.dirname(WEBROOT_PATH)
    if os.path.isdir(webroot_dir) and os.path.isfile(DATA_PATH):
        try:
            shutil.copy2(DATA_PATH, WEBROOT_PATH)
        except Exception:
            return


def run(analyses: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Main execution entrypoint.
    - analyses provided: upsert each analysis, recompute, save, publish.
    - analyses omitted: recompute existing graph, save, publish.
    """
    if analyses is not None:
        g = backfill(analyses)
    else:
        g = recompute(load_graph())
        save_graph(g)
    publish()
    return g


if __name__ == "__main__":
    synthetic = {
        "post_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")[-16:],
        "url": "https://example.com/post",
        "title": "Synthetic Macro-Ticker Link",
        "analyzed_at": _now_iso(),
        "short_summary": {"one_line": "Copper demand and AI infra signal a watch candidate."},
        "keywords": [
            {
                "id": "copper_demand",
                "label": "Copper Demand",
                "type": "commodity",
                "importance": 0.92,
                "summary": "Copper demand rises with grid and data-center buildout.",
                "related_core": ["ai_infra", "power_grid"],
            },
            {
                "id": "ai_infra",
                "label": "AI Infrastructure",
                "type": "theme",
                "importance": 0.89,
                "summary": "AI capex drives heavy infra demand.",
                "related_core": ["power_grid"],
            },
        ],
        "recommended_watch": [
            {
                "ticker": "PLTR",
                "name": "Palantir",
                "relevance": 88,
                "in_portfolio": True,
                "thesis": "Beneficiary of enterprise AI deployment cycle.",
                "asset_class": "equity",
            }
        ],
        "graph": {
            "nodes": [
                {"id": "ai_infra", "label": "AI Infrastructure", "type": "theme", "summary": "Capex super-cycle"},
                {"id": "power_grid", "label": "Power Grid", "type": "sector", "summary": "Grid bottlenecks matter"},
                {"id": "copper_demand", "label": "Copper Demand", "type": "commodity", "summary": "Input constraint"},
            ],
            "edges": [
                {"source": "ai_infra", "target": "power_grid", "relation": "depends_on", "weight": 3},
                {"source": "power_grid", "target": "copper_demand", "relation": "drives", "weight": 2},
            ],
        },
    }

    # End-to-end local demo: update once, recompute, and print compact output.
    update_from_analysis(synthetic)
    graph = run()
    preview = {
        "stats": graph.get("stats", {}),
        "top_nodes": graph.get("top_nodes", [])[:5],
        "watchlist": graph.get("watchlist", [])[:5],
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))
