#!/bin/bash
set -euo pipefail
cd /root/gods_plan
systemctl restart minerva
git add -A
if ! git diff --cached --quiet; then
  git commit --trailer "Made-with: Cursor" -m "complete fix: liq, dupe rows, VIX, PLTR action, Lesson08, brief v2 live prices"
else
  echo "No staged changes to commit"
fi
git push
echo "=== HARD REFRESH http://5.189.176.185 ==="