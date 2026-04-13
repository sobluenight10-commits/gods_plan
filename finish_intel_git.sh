#!/bin/bash
set -euo pipefail
cd ~/gods_plan
git add OLYMPUS_UNIFIED.html
git commit --trailer "Made-with: Cursor" -m "fix: remove 2 duplicate INTELLIGENCE cat-band rows"
git push
echo "=== DUPLICATE FIX DEPLOYED ==="