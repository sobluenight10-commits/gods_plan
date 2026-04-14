"""Base class for all OLYMPUS skills."""
from __future__ import annotations

import json
import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytz

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RESULTS_DIR = DATA_DIR / "skill_results"
BERLIN = pytz.timezone("Europe/Berlin")

logger = logging.getLogger("olympus.skills")


class SkillRunner(ABC):
    """Abstract base for every skill module."""

    name: str = "base"

    def __init__(self):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def run_all(self, tickers: List[str]) -> Dict[str, Any]:
        """Run the skill for a list of tickers. Return structured results dict."""

    @abstractmethod
    def run_single(self, ticker: str) -> Dict[str, Any]:
        """Run the skill for a single ticker. Return structured result."""

    def save(self, results: Dict[str, Any], prefix: Optional[str] = None) -> Path:
        prefix = prefix or self.name
        today = datetime.now(BERLIN).strftime("%Y%m%d")
        path = RESULTS_DIR / f"{prefix}_{today}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"[{self.name}] Saved {path.name}")
        return path

    @staticmethod
    def load_latest(prefix: str) -> Optional[Dict[str, Any]]:
        if not RESULTS_DIR.exists():
            return None
        files = sorted(RESULTS_DIR.glob(f"{prefix}_*.json"), reverse=True)
        if not files:
            return None
        with open(files[0], encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _yf_ticker(ticker: str):
        import yfinance as yf
        return yf.Ticker(ticker)
