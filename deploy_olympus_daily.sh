#!/bin/bash
set -euo pipefail
cd /root/gods_plan

git pull
pip install yfinance --break-system-packages --quiet

python3 olympus_daily.py

crontab -l | grep -v 'run_gem_daily\|gem_injector\|battle_rhythm\|morning_brief\|olympus_daily' > /tmp/c.txt
echo "0 5 * * 1-5 cd /root/gods_plan && python3 olympus_daily.py >> /var/log/olympus_daily.log 2>&1" >> /tmp/c.txt
crontab /tmp/c.txt

echo "Pipeline live. Next run 07:00 Berlin tomorrow."