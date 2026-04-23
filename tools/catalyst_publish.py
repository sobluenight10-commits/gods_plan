"""catalyst_publish.py — ship data/catalyst_radar.json to the public webroot."""
from __future__ import annotations
import os
import shutil

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(BASE, "data", "catalyst_radar.json")
DST  = "/var/www/html/catalyst_radar.json"


def main() -> int:
    if not os.path.exists(SRC):
        print(f"[PUBLISH] source missing: {SRC}")
        return 1
    try:
        shutil.copy2(SRC, DST)
        print(f"[PUBLISH] catalyst_radar.json → {DST}")
        return 0
    except PermissionError:
        print(f"[PUBLISH] permission denied copying to {DST} (run as root on server)")
        return 2
    except FileNotFoundError:
        # Not on the server (no /var/www/html). OK locally.
        print(f"[PUBLISH] webroot missing — local environment, skipping")
        return 0
    except Exception as exc:
        print(f"[PUBLISH] error: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
