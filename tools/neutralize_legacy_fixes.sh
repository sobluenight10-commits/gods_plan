#!/bin/bash
# One-shot cleanup for legacy "fix scripts" that hardcode April-14 liquidity
# values and would overwrite live FRED data if ever re-run. Renamed to
# `.disabled_YYYY-MM-DD` so the originals survive in case someone needs
# archaeology.

set -u
cd /root/gods_plan || exit 1

TS=$(date +%Y-%m-%d)

for f in x20think_steps.sh run_exact_master_fix.sh run_vs_pct_and_telegram_fix.sh server_complete_fix.sh olympus_master_fix.py; do
    if [ -f "$f" ]; then
        mv "$f" "${f}.disabled_${TS}"
        echo "neutralized ${f}"
    fi
done

# stray Apr-12 static file that predates the nginx /data/ alias.
if [ -f /var/www/html/data/directives.json ]; then
    rm -f /var/www/html/data/directives.json
    echo "removed /var/www/html/data/directives.json (stale Apr-12 static copy)"
fi

echo "--- disabled files ---"
ls -la *.disabled_${TS} 2>&1 || true
