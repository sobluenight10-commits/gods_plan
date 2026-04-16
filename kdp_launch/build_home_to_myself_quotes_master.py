"""
Merge per-range quote line files into home_to_myself_quotes_MASTER.json.
Line format per file: NNN<TAB>text (no leading number+dot in text).
Run from repo root: python kdp_launch/build_home_to_myself_quotes_master.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DIR = Path(__file__).resolve().parent
META_PATH = DIR / "quote_books_meta.json"
OUT_PATH = DIR / "home_to_myself_quotes_MASTER.json"

# Optional fragment files: filename -> (start_id, end_id) inclusive
FRAGMENTS = [
    ("quotes_src/001-180.txt", 1, 180),
    ("quotes_src/181-240.txt", 181, 240),
    ("quotes_src/241-360.txt", 241, 360),
    ("quotes_src/361-450.txt", 361, 450),
    ("quotes_src/451-540.txt", 451, 540),
    ("quotes_src/541-630.txt", 541, 630),
    ("quotes_src/631-720.txt", 631, 720),
    ("quotes_src/721-810.txt", 721, 810),
    ("quotes_src/811-900.txt", 811, 900),
    ("quotes_src/901-990.txt", 901, 990),
    ("quotes_src/991-1080.txt", 991, 1080),
]


def load_meta():
    meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    books = meta["books"]
    by_id = {}
    for b in books:
        lo, hi = b["quote_range"]
        for qid in range(lo, hi + 1):
            by_id[qid] = {
                "volume": b["volume"],
                "month": b["month"],
                "theme": b["theme"],
            }
    return meta, by_id


def book_start(volume: int, meta) -> int:
    for b in meta["books"]:
        if b["volume"] == volume:
            return b["quote_range"][0]
    raise KeyError(volume)


def day_and_slot(book_start_id: int, qid: int) -> tuple[int, str]:
    off = qid - book_start_id
    day = off // 3 + 1
    slot = "ABC"[off % 3]
    return day, slot


def parse_file(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    raw = path.read_text(encoding="utf-8")
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if not m:
            m = re.match(r"^(\d+)\.\s*(.+)$", line)
        if not m:
            continue
        qid = int(m.group(1))
        text = m.group(2).strip()
        out[qid] = text
    return out


def main():
    meta, by_id = load_meta()
    merged: dict[int, str] = {}
    for rel, lo, hi in FRAGMENTS:
        p = DIR / rel
        if not p.exists():
            print(f"skip missing {rel}")
            continue
        part = parse_file(p)
        for qid in range(lo, hi + 1):
            if qid in part:
                merged[qid] = part[qid]
        # sanity: count
        missing = [i for i in range(lo, hi + 1) if i not in part]
        if missing:
            print(f"WARN {rel}: missing ids {missing[:5]}{'...' if len(missing) > 5 else ''}")

    quotes_out = []
    for qid in range(1, 1081):
        info = by_id[qid]
        vol = info["volume"]
        bs = book_start(vol, meta)
        day, slot = day_and_slot(bs, qid)
        entry = {
            "id": qid,
            "text": merged.get(qid),
            "volume": vol,
            "month": info["month"],
            "theme": info["theme"],
            "day_in_volume": day,
            "slot": slot,
            "slot_key": f"DAY_{day}_{slot}",
        }
        quotes_out.append(entry)

    payload = {
        "schema": meta["schema"],
        "generated_by": "build_home_to_myself_quotes_master.py",
        "total_quotes": 1080,
        "populated_count": sum(1 for q in quotes_out if q["text"]),
        "quotes": quotes_out,
    }
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH} populated={payload['populated_count']}/1080")


if __name__ == "__main__":
    main()
