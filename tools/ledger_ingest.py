"""
ledger_ingest.py — parse free-form journal prose (Google Keep style) into
structured thesis_ledger decisions using GPT-4o-mini.

Usage
  # dry-run (preview what GPT extracts)
  python3 tools/ledger_ingest.py - < journal.txt
  python3 tools/ledger_ingest.py journal.txt

  # commit after you've reviewed
  python3 tools/ledger_ingest.py journal.txt --commit

  # interactive (y/N per decision)
  python3 tools/ledger_ingest.py journal.txt --interactive

Journal format is free-form. Helpful cues (not required):
  - Date at top of entry ("Apr 20:" or "2026-04-20")
  - Ticker symbols in ALL CAPS or parens
  - Numbers for price/target/stop
  - Words like "felt / feel / afraid / FOMO / calm / conviction" — extracted as FEEL
  - Words like "learned / I realized / next time" — extracted as LEARN

Entry separator: a blank line or `---` between entries. Parser is resilient:
  one big blob also works, it'll split on date/ticker headers.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from typing import Any, Dict, List, Optional

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from thesis_ledger import add_decision, add_note, VALID_ACTIONS  # noqa: E402


def _load_env() -> None:
    env_path = os.path.join(BASE, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_VALID = sorted(list(VALID_ACTIONS) + ["HOLD"])
SCHEMA_PROMPT = f"""You are OLYMPUS Ledger Parser.
Extract structured investment decisions from the user's personal journal prose.

Return ONLY a JSON array (no prose around it). Each element:
{{
  "ticker": "UPPERCASE_SYMBOL",
  "action": "one of {_VALID}",
  "price": number or null,
  "date": "YYYY-MM-DD" (default today if missing),
  "thesis": "what the investor believes (1-2 sentences, investor's own framing)",
  "catalyst": "named event/signal that matters (if mentioned), else empty string",
  "horizon": "1Y|3Y|5Y|10Y or empty string",
  "conviction": integer 1-10 (infer from language: 'just a bit'=4, 'solid'=7, 'highest conviction'=9),
  "target": number or null,
  "stop_loss": number or null,
  "exit_criteria": "when would the investor exit (if written), else empty",
  "thesis_type": "short tag like ai_infra/energy_uranium/space_defense/robotics_defense/biotech/semis/general",
  "feel": "1-4 words describing emotional state (e.g. 'calm conviction', 'FOMO', 'anxious', 'excited', 'regret', 'doubt'). Extract only if the writer literally mentions a feeling.",
  "learn": "the lesson or reflection the writer extracted (one sentence, their own words summarized). Empty if none.",
  "raw_note": "the original excerpt for this decision (verbatim, <300 chars)"
}}

Rules:
  - Produce one JSON object per decision. A journal entry may contain multiple.
  - STAY / HOLD means the writer actively decided to NOT trade — still a decision.
  - If ticker is missing, skip the entry (do not guess tickers).
  - If price is missing but the writer says 'at the dip' without a number, set price=null.
  - Dates like 'today', 'yesterday' → resolve against provided TODAY.
  - If the writer uses non-English/Korean, translate the thesis/learn to English.
  - Extract feel literally — do not invent an emotion if none is stated.
"""


def _gpt_parse(text: str, today: str) -> List[Dict[str, Any]]:
    _load_env()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    except Exception as exc:
        print(f"[INGEST] OpenAI client unavailable: {exc}")
        return []

    if not os.environ.get("OPENAI_API_KEY"):
        print("[INGEST] OPENAI_API_KEY missing in .env")
        return []

    msg = [
        {"role": "system", "content": SCHEMA_PROMPT},
        {"role": "user", "content": f"TODAY: {today}\n\nJOURNAL:\n{text.strip()}\n\nReturn ONLY the JSON array."},
    ]
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=msg,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        print(f"[INGEST] GPT call failed: {exc}")
        return []

    # GPT may wrap in {"decisions": [...]} even with response_format; handle both.
    try:
        obj = json.loads(raw)
    except Exception:
        # Try to salvage an array
        m = re.search(r"\[[\s\S]*\]", raw)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        print("[INGEST] could not parse GPT response as JSON:")
        print(raw[:400])
        return []

    if isinstance(obj, list):
        return obj
    # Accept common wrappers
    for key in ("decisions", "entries", "records", "items", "results"):
        if key in obj and isinstance(obj[key], list):
            return obj[key]
    # Single dict case
    if isinstance(obj, dict) and obj.get("ticker"):
        return [obj]
    return []


def _print_parsed(rows: List[Dict[str, Any]]) -> None:
    for i, r in enumerate(rows, 1):
        tk = r.get("ticker", "?")
        act = r.get("action", "?")
        px = r.get("price")
        dt = r.get("date", "?")
        conv = r.get("conviction", 5)
        feel = r.get("feel") or "—"
        learn = r.get("learn") or ""
        thesis = (r.get("thesis") or "")[:120]
        print(f"\n  [{i}] {dt}  {act:4}  {tk:<10} @ {px}  conv {conv}/10  feel: {feel}")
        if thesis:
            print(f"       thesis: {thesis}")
        if learn:
            print(f"       learn : {learn[:120]}")


def _confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
        return ans in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False


def commit(rows: List[Dict[str, Any]], *, interactive: bool) -> int:
    n = 0
    for r in rows:
        tk = (r.get("ticker") or "").upper().strip()
        if not tk:
            continue
        if interactive:
            tag = f"{r.get('date','?')} {r.get('action','?')} {tk} @ {r.get('price')}"
            if not _confirm(f"  commit? {tag} [y/N] "):
                print(f"  [skip] {tag}")
                continue
        try:
            add_decision(
                tk,
                r.get("action") or "BUY",
                r.get("price") if r.get("price") is not None else 0.0,
                thesis=r.get("thesis") or "(imported from journal)",
                catalyst=r.get("catalyst") or "",
                horizon=r.get("horizon") or "1Y",
                conviction=int(r.get("conviction") or 5),
                target=r.get("target"),
                stop_loss=r.get("stop_loss"),
                exit_criteria=r.get("exit_criteria") or "",
                thesis_type=r.get("thesis_type") or "",
                when=r.get("date"),
                feel=r.get("feel") or "",
                learn=r.get("learn") or "",
                raw_note=r.get("raw_note") or "",
            )
            n += 1
            print(f"  [ok] {tk} {r.get('action')}")
        except Exception as exc:
            print(f"  [err] {tk}: {exc}")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(prog="ledger_ingest")
    ap.add_argument("path", nargs="?", default="-", help="file path, or '-' for stdin")
    ap.add_argument("--commit", action="store_true", help="write parsed decisions to the ledger")
    ap.add_argument("--interactive", action="store_true", help="y/N prompt per decision")
    args = ap.parse_args()

    if args.path == "-" or not os.path.exists(args.path):
        if args.path != "-":
            print(f"[INGEST] file not found, reading stdin instead: {args.path}")
        text = sys.stdin.read()
    else:
        with open(args.path, encoding="utf-8") as f:
            text = f.read()
    if not text.strip():
        print("[INGEST] empty input")
        return 1

    today = date.today().isoformat()
    rows = _gpt_parse(text, today)
    if not rows:
        print("[INGEST] no decisions extracted")
        return 2

    print(f"[INGEST] parsed {len(rows)} decisions from journal:")
    _print_parsed(rows)

    if args.commit or args.interactive:
        n = commit(rows, interactive=args.interactive)
        print(f"\n[INGEST] committed {n}/{len(rows)} decisions to thesis_ledger.")
        # Publish to webroot so dashboard picks it up immediately
        try:
            from tools.publish_ledger import main as _pub
            _pub()
        except Exception:
            pass
    else:
        print(f"\n[INGEST] dry-run only — re-run with --commit to save.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
