#!/bin/bash
set -euo pipefail
cd /root/gods_plan
git add -A
git commit --trailer "Made-with: Cursor" -m 'fix: liquidity $2368B, VIX 19.12, dupe rows, PLTR DIP WATCH, Lesson08'
git push
echo "=== HARD REFRESH http://5.189.176.185 NOW ==="