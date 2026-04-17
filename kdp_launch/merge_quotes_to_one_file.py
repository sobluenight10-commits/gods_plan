"""
Merge kdp_launch/quotes_src/*.txt fragments into one ordered master file (IDs 1–1080).

Input files (optional each): 001-180.txt, 181-240.txt, … — same line format as before:
  181 Your aphorism text
  181. Your aphorism text

Output (always written next to this script):
  home_to_myself_quotes_1_1080_MERGED.txt  — one line per ID, stable order
  home_to_myself_quotes_MASTER.json        — {"1": "...", ...} for tools

Missing IDs get a placeholder so you can search/replace or fill later.

Run from repo root:
  python kdp_launch/merge_quotes_to_one_file.py
Or from kdp_launch:
  python merge_quotes_to_one_file.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

DIR = Path(__file__).resolve().parent
QUOTES_SRC = DIR / "quotes_src"

# Must match build_30_days.py fragment ranges
FRAGMENTS: list[tuple[str, int, int]] = [
    ("001-180.txt", 1, 180),
    ("181-240.txt", 181, 240),
    ("241-360.txt", 241, 360),
    ("361-450.txt", 361, 450),
    ("451-540.txt", 451, 540),
    ("541-630.txt", 541, 630),
    ("631-720.txt", 631, 720),
    ("721-810.txt", 721, 810),
    ("811-900.txt", 811, 900),
    ("901-990.txt", 901, 990),
    ("991-1080.txt", 991, 1080),
]

PLACEHOLDER = "[Quote #{id} — add text or add fragment file under quotes_src/]"


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


def load_all() -> dict[int, str]:
    merged: dict[int, str] = {}
    for fname, lo, hi in FRAGMENTS:
        p = QUOTES_SRC / fname
        if not p.is_file():
            continue
        part = parse_file(p)
        for qid in range(lo, hi + 1):
            if qid in part:
                merged[qid] = part[qid]
    return merged


def main() -> None:
    merged = load_all()
    missing: list[int] = []
    lines_out: list[str] = []
    json_obj: dict[str, str] = {}

    for qid in range(1, 1081):
        text = merged.get(qid)
        if not text:
            missing.append(qid)
            text = PLACEHOLDER.format(id=qid)
        lines_out.append(f"{qid} {text}")
        json_obj[str(qid)] = text

    txt_path = DIR / "home_to_myself_quotes_1_1080_MERGED.txt"
    json_path = DIR / "home_to_myself_quotes_MASTER.json"

    header = (
        f"# HOME TO MYSELF — merged quote bank 1–1080\n"
        f"# built {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%MZ')}\n"
        f"# populated: {1080 - len(missing)}/1080\n"
    )
    if missing:
        header += f"# missing IDs ({len(missing)}): {missing[:30]}{'…' if len(missing) > 30 else ''}\n"
    header += "#\n"

    txt_path.write_text(header + "\n".join(lines_out) + "\n", encoding="utf-8")
    json_path.write_text(
        json.dumps(json_obj, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Sources scanned: {QUOTES_SRC}")
    print(f"IDs with text: {1080 - len(missing)}/1080")
    if missing:
        print(f"Missing count: {len(missing)} (placeholders in output)")
    print(f"Wrote {txt_path.name}")
    print(f"Wrote {json_path.name}")


if __name__ == "__main__":
    main()
