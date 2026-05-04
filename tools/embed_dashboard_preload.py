"""Write latest pipeline JSON into OLYMPUS_UNIFIED.html as an inline blob.

GitHub Pages and file:// cannot fetch http://5.189.176.185 (mixed content if
the page is https). Browsers also block passive loads in some cases. The HTML
carries a self-contained snapshot so Strike / Heads-Up render everywhere;
fetch still refreshes when same-origin or CORS succeeds.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(BASE, "OLYMPUS_UNIFIED.html")

Keys = [
    "strike_cards",
    "strike_radar",
    "strike_plan",
    "heads_up",
    "point_a_scan",
    "point_b_scan",
]


def _sanitize(x):
    """JSON has no NaN/Infinity — invalid JSON breaks JSON.parse in the browser."""
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        return x
    if isinstance(x, dict):
        return {k: _sanitize(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_sanitize(v) for v in x]
    return x


def _load_data(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def run(html_path: str | None = None) -> dict:
    path = html_path or HTML
    payload = {}
    for key in Keys:
        val = _load_data(os.path.join(BASE, "data", f"{key}.json"))
        if val is not None:
            payload[key] = val

    if not payload:
        inner = "{}"
        print("[embed_dashboard_preload] no JSON files found — leaving preload empty", file=sys.stderr)
    else:
        payload = _sanitize(payload)
        inner = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        inner = inner.replace("<", "\\u003c")

    with open(path, encoding="utf-8") as f:
        html = f.read()

    pat = re.compile(
        r'(<script\s+type="application/json"\s+id="olympus-dashboard-preload"\s*>)'
        r"[\s\S]*?"
        r"(</script>)",
        re.IGNORECASE,
    )

    def _repl(m):
        return m.group(1) + "\n" + inner + "\n" + m.group(2)

    html_new, n = pat.subn(_repl, html, count=1)
    if not n:
        print("[embed_dashboard_preload] marker script#olympus-dashboard-preload not found", file=sys.stderr)
        return {"ok": False, "bytes": 0}

    with open(path, "w", encoding="utf-8") as f:
        f.write(html_new)
    print(f"[embed_dashboard_preload] wrote {len(inner)} bytes into {os.path.basename(path)}")
    return {"ok": True, "bytes": len(inner)}


if __name__ == "__main__":
    run()
