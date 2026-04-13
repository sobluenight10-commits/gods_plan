#!/bin/bash
# MINERVA_GEM Auto-Inject Pipeline Installer
# Run ONCE on server: bash setup_gem_pipeline.sh
# Installs crontab for both run_gem_daily.py (07:05) and gem_injector.py (07:06)

set -e

SCRIPT_DIR="/root/gods_plan"
LOG_DIR="/var/log"
CRON_TMP="/tmp/minerva_cron_new.txt"

echo "=== MINERVA_GEM Pipeline Installer ==="
echo "Script dir: $SCRIPT_DIR"

# Export current crontab
crontab -l > "$CRON_TMP" 2>/dev/null || echo "" > "$CRON_TMP"

# Strip old GEM lines
grep -v "run_gem_daily\|gem_injector" "$CRON_TMP" > "${CRON_TMP}.clean" && mv "${CRON_TMP}.clean" "$CRON_TMP"

# Berlin summer = UTC+2 → 07:05 Berlin = 05:05 UTC
# Berlin winter = UTC+1 → 07:05 Berlin = 06:05 UTC
# Using 05:05 UTC (summer). Adjust to 06:05 in October.
cat >> "$CRON_TMP" << 'CRONEOF'
# MINERVA_GEM — daily GEM scoring (07:05 Berlin summer)
5 5 * * 1-5 cd /root/gods_plan && python run_gem_daily.py >> /var/log/gem_daily.log 2>&1
# MINERVA_GEM — auto-inject into dashboard (07:06 Berlin summer)
6 5 * * 1-5 cd /root/gods_plan && python gem_injector.py >> /var/log/gem_inject.log 2>&1
CRONEOF

crontab "$CRON_TMP"
echo ""
echo "=== Crontab installed ==="
crontab -l
echo ""
echo "=== Log files will appear at ==="
echo "  /var/log/gem_daily.log"
echo "  /var/log/gem_inject.log"
echo ""
echo "=== Test run (optional) ==="
echo "  cd $SCRIPT_DIR && python run_gem_daily.py && python gem_injector.py"
