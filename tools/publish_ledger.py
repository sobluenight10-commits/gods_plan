"""publish_ledger.py — copy data/thesis_ledger.json to /var/www/html/ledger.json
so the OLYMPUS dashboard can fetch it via /ledger.json."""
from __future__ import annotations
import os, shutil, sys, json
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(BASE, "data", "thesis_ledger.json")
DEST = "/var/www/html/ledger.json"


def main() -> int:
    if not os.path.exists(SRC):
        # Write an empty ledger so dashboard gets a clean response instead of 404
        empty = {"decisions": [], "meta": {"created": datetime.now().isoformat(timespec="seconds"),
                                            "last_written": datetime.now().isoformat(timespec="seconds")}}
        try:
            with open(DEST, "w", encoding="utf-8") as f:
                json.dump(empty, f, indent=2)
            os.chmod(DEST, 0o644)
            print(f"[publish_ledger] wrote empty stub to {DEST}")
        except Exception as exc:
            print(f"[publish_ledger] could not write stub: {exc}")
        return 0
    try:
        shutil.copy2(SRC, DEST)
        os.chmod(DEST, 0o644)
        print(f"[publish_ledger] {SRC} -> {DEST}")
        return 0
    except Exception as exc:
        print(f"[publish_ledger] failed: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
