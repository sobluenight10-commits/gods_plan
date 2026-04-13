#!/bin/bash
set -euo pipefail
cd ~/gods_plan

pip install numpy --break-system-packages --quiet

python3 -c "from minerva_gem import evaluate; print('v4 import OK')"

python3 run_gem_daily.py
python3 gem_injector.py

python3 verify_pltr_step5.py

python3 olympus_html_patch.py

cp OLYMPUS_UNIFIED.html /var/www/html/index.html
systemctl restart minerva
echo "=== v4 HESTON LIVE ==="