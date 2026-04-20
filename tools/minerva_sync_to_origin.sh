#!/usr/bin/env bash
# Minerva: make ~/gods_plan identical to origin/master (GitHub). Run on server only.
set -euo pipefail
REPO="${1:-$HOME/gods_plan}"
cd "$REPO"
echo "[minerva_sync] repo=$REPO"
git fetch origin master
# Drop untracked files/dirs that are not gitignored (ignored paths like data/ stay)
git clean -fd
git reset --hard origin/master
git status -sb
echo "[minerva_sync] OK — HEAD matches origin/master"
# Live dashboard
if [[ -f OLYMPUS_UNIFIED.html ]]; then
  cp OLYMPUS_UNIFIED.html /var/www/html/index.html
  systemctl restart minerva
  echo "[minerva_sync] DEPLOYED OLYMPUS + minerva restarted"
fi
