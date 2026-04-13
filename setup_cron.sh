#!/bin/bash
# MINERVA_GEM + Morning Brief crontab installer
# Run once on server: bash setup_cron.sh

CRON_FILE="/tmp/minerva_cron.txt"

# Export existing crontab (preserve all existing jobs)
crontab -l > "$CRON_FILE" 2>/dev/null || echo "" > "$CRON_FILE"

# Remove any old GEM lines to avoid duplicates
grep -v "run_gem_daily" "$CRON_FILE" > "${CRON_FILE}.tmp" && mv "${CRON_FILE}.tmp" "$CRON_FILE"

# Add MINERVA_GEM daily at 07:05 Berlin (UTC+2 in summer = 05:05 UTC)
echo "5 5 * * 1-5 cd /root/gods_plan && python run_gem_daily.py >> /var/log/gem_daily.log 2>&1" >> "$CRON_FILE"

# Install it
crontab "$CRON_FILE"
echo "Crontab installed. Current jobs:"
crontab -l
chmod +x setup_cron.sh