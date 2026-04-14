#!/bin/bash
set -e
cd /root/gods_plan

echo "=== DEPLOY V8: 40/40/20 weights + 9-tier GEM Score + ranto fix ==="

# Pull latest from feature branch
git fetch origin
git checkout feat/ranto28-rss-blog-engine-upgrade
git reset --hard origin/feat/ranto28-rss-blog-engine-upgrade
echo "[OK] Code pulled"

# Verify key changes
echo ""
echo "--- Verifying weight change ---"
grep "WW, WN, WB" minerva_gem.py | head -1
echo "--- Verifying GEM Score function exists ---"
grep "def _gem_score" minerva_gem.py | head -1
echo "--- Verifying output_factory is UTF-8 ---"
file output_factory.py
echo ""

# TEST 1: Run GEM daily
echo "=== TEST 1: Run GEM + OLYMPUS pipeline ==="
python3 run_gem_daily.py 2>&1 | tail -5
echo ""
python3 olympus_daily.py 2>&1
echo ""

# Check grade distribution
echo "=== GRADE DISTRIBUTION ==="
python3 _check_grades.py 2>&1
echo ""

# Check ranto28 blog detection
echo "=== RANTO28 BLOG DETECTION ==="
python3 _test_rss.py 2>&1
echo ""

# TEST 2: Idempotency
echo "=== TEST 2: Idempotency check ==="
python3 run_gem_daily.py 2>&1 | tail -3
python3 olympus_daily.py 2>&1 | head -5
echo ""

# Deploy to web root
echo "=== DEPLOYING TO WEB ROOT ==="
cp OLYMPUS_UNIFIED.html /var/www/html/OLYMPUS_UNIFIED.html
cp data/dashboard_state.json /var/www/html/data/dashboard_state.json
systemctl restart minerva
echo "[OK] Deployed and minerva restarted"

echo ""
echo "=== DEPLOY V8 COMPLETE ==="
