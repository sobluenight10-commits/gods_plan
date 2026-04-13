"""
add_gem_markers.py — One-time setup script
Adds <!-- GEM_INJECT_START --> and <!-- GEM_INJECT_END --> markers
into OLYMPUS_UNIFIED.html just before the closing </body> tag.

Run ONCE: python add_gem_markers.py
After this, gem_injector.py can inject daily without manual HTML edits.
"""

from pathlib import Path
import shutil
from datetime import datetime

HTML_PATH = Path("/root/gods_plan/OLYMPUS_UNIFIED.html")
MARKER_START = "<!-- GEM_INJECT_START -->"
MARKER_END   = "<!-- GEM_INJECT_END -->"

def run():
    if not HTML_PATH.exists():
        print(f"ERROR: {HTML_PATH} not found.")
        return

    html = HTML_PATH.read_text(encoding="utf-8")

    # Already has markers?
    if MARKER_START in html:
        print("Markers already present. Nothing to do.")
        return

    # Backup
    backup = HTML_PATH.with_suffix(f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
    shutil.copy2(HTML_PATH, backup)
    print(f"Backup: {backup}")

    # Find §13 section header to inject AFTER it, or fall back to </body>
    inject_targets = [
        '<div id="section-13"',
        'id="earth-shifters"',
        'id="section13"',
        '<!-- §13',
        '<!-- SECTION 13',
        '</body>',
    ]

    inject_after = None
    for target in inject_targets:
        idx = html.find(target)
        if idx != -1:
            # Find end of that tag/line
            end = html.find('\n', idx)
            inject_after = end + 1
            print(f"Injecting after: '{target[:40]}'")
            break

    if inject_after is None:
        print("ERROR: Could not find injection point.")
        return

    marker_block = f"\n{MARKER_START}\n{MARKER_END}\n"
    new_html = html[:inject_after] + marker_block + html[inject_after:]

    HTML_PATH.write_text(new_html, encoding="utf-8")
    shutil.copy2(HTML_PATH, Path("/var/www/html/index.html"))
    print(f"Done. Markers added. Dashboard redeployed.")

if __name__ == "__main__":
    run()
