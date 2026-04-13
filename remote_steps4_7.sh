#!/bin/bash
set -euo pipefail
cd ~/gods_plan
python3 step4_god_scores_pltr.py
python3 run_gem_daily.py
python3 gem_injector.py
python3 step6_verify_pltr_action.py
cp OLYMPUS_UNIFIED.html /var/www/html/index.html
git add -A
if ! git diff --cached --quiet; then
  git commit --trailer "Made-with: Cursor" -m "fix: PLTR action DIP_WATCH, remove duplicate Intel rows"
else
  echo "No staged changes for commit"
fi
git push
systemctl restart minerva
echo "=== ALL FIXES DEPLOYED ==="