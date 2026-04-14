"""Financial Statement Analysis — quarterly fundamentals + trend detection.

For each ticker, pulls:
  - Revenue, gross/operating/net margins (last 4-8 quarters)
  - Free cash flow
  - Debt-to-equity, current ratio
  - Cash position
  - Trend: improving / declining / stable (per metric)
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from skills.base import SkillRunner, BERLIN

logger = logging.getLogger("olympus.skills.financial")


def _safe(val, default=None):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return default
    return val


def _pct(val, decimals=1):
    if val is None:
        return None
    return round(val * 100, decimals)


def _trend(series: List[Optional[float]]) -> str:
    """Determine trend from a list of values (newest first)."""
    valid = [v for v in series if v is not None]
    if len(valid) < 2:
        return "insufficient_data"
    recent_half = valid[:len(valid)//2] if len(valid) >= 4 else valid[:1]
    older_half = valid[len(valid)//2:] if len(valid) >= 4 else valid[1:]
    avg_recent = sum(recent_half) / len(recent_half)
    avg_older = sum(older_half) / len(older_half)
    if avg_older == 0:
        return "stable"
    change = (avg_recent - avg_older) / abs(avg_older)
    if change > 0.1:
        return "improving"
    if change < -0.1:
        return "declining"
    return "stable"


class FinancialAnalysis(SkillRunner):
    name = "fundamentals"

    def __init__(self, universe: Optional[Dict] = None):
        super().__init__()
        if universe is None:
            from fetch_data import UNIVERSE
            universe = UNIVERSE
        self.universe = universe

    def run_all(self, tickers: Optional[List[str]] = None) -> Dict[str, Any]:
        tickers = tickers or list(self.universe.keys())
        results = {}
        for tk in tickers:
            try:
                results[tk] = self.run_single(tk)
            except Exception as e:
                logger.warning(f"[fundamentals] {tk} failed: {e}")
                results[tk] = {"ticker": tk, "error": str(e)}
        output = {
            "run_date": datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M"),
            "total": len(results),
            "results": results,
        }
        self.save(output)
        return output

    def run_single(self, ticker: str) -> Dict[str, Any]:
        yft = self._yf_ticker(ticker)
        info = {}
        try:
            info = yft.info or {}
        except Exception:
            pass

        inc_data = self._get_quarterly_income(yft)
        bs_data = self._get_quarterly_bs(yft)
        cf_data = self._get_quarterly_cf(yft)

        revenue_series = [_safe(q.get("Total Revenue")) for q in inc_data[:8]]
        gross_margins = []
        op_margins = []
        net_margins = []
        for q in inc_data[:8]:
            rev = _safe(q.get("Total Revenue"), 0)
            gp = _safe(q.get("Gross Profit"), 0)
            oi = _safe(q.get("Operating Income"), 0)
            ni = _safe(q.get("Net Income"), 0)
            gross_margins.append(gp / rev if rev and rev > 0 else None)
            op_margins.append(oi / rev if rev and rev > 0 else None)
            net_margins.append(ni / rev if rev and rev > 0 else None)

        fcf_series = [_safe(q.get("Free Cash Flow")) for q in cf_data[:8]]

        latest_bs = bs_data[0] if bs_data else {}
        total_debt = abs(_safe(latest_bs.get("Total Debt"), 0))
        equity = abs(_safe(
            latest_bs.get("Total Stockholders Equity") or latest_bs.get("Stockholders Equity"), 1
        ))
        de_ratio = round(total_debt / equity, 2) if equity > 0 else None

        cash = _safe(latest_bs.get("Cash And Cash Equivalents"), 0)
        cash += _safe(latest_bs.get("Short Term Investments"), 0)

        current_assets = _safe(latest_bs.get("Current Assets"), 0)
        current_liab = _safe(latest_bs.get("Current Liabilities"), 1)
        current_ratio = round(current_assets / current_liab, 2) if current_liab > 0 else None

        rev_growth = []
        valid_revs = [r for r in revenue_series if r and r > 0]
        for i in range(len(valid_revs) - 1):
            rev_growth.append((valid_revs[i] - valid_revs[i+1]) / valid_revs[i+1])

        return {
            "ticker": ticker,
            "market_cap": info.get("marketCap"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "revenue": {
                "latest_q": revenue_series[0] if revenue_series else None,
                "series": [r for r in revenue_series if r],
                "qoq_growth": [round(g * 100, 1) for g in rev_growth[:4]] if rev_growth else [],
                "trend": _trend([r for r in revenue_series if r]),
            },
            "margins": {
                "gross": {
                    "latest": _pct(gross_margins[0]) if gross_margins else None,
                    "trend": _trend(gross_margins),
                },
                "operating": {
                    "latest": _pct(op_margins[0]) if op_margins else None,
                    "trend": _trend(op_margins),
                },
                "net": {
                    "latest": _pct(net_margins[0]) if net_margins else None,
                    "trend": _trend(net_margins),
                },
            },
            "cash_flow": {
                "latest_fcf": fcf_series[0] if fcf_series else None,
                "trend": _trend([f for f in fcf_series if f is not None]),
            },
            "balance_sheet": {
                "cash": cash,
                "total_debt": total_debt,
                "de_ratio": de_ratio,
                "current_ratio": current_ratio,
            },
            "valuation": {
                "pe_trailing": info.get("trailingPE"),
                "pe_forward": info.get("forwardPE"),
                "ps_ratio": info.get("priceToSalesTrailing12Months"),
                "pb_ratio": info.get("priceToBook"),
                "ev_ebitda": info.get("enterpriseToEbitda"),
            },
        }

    @staticmethod
    def _get_quarterly_income(yft) -> List[Dict]:
        try:
            df = yft.quarterly_income_stmt
            if df is not None and not df.empty:
                return [dict(df.iloc[:, i]) for i in range(min(8, df.shape[1]))]
        except Exception:
            pass
        return []

    @staticmethod
    def _get_quarterly_bs(yft) -> List[Dict]:
        try:
            df = yft.quarterly_balance_sheet
            if df is not None and not df.empty:
                return [dict(df.iloc[:, i]) for i in range(min(4, df.shape[1]))]
        except Exception:
            pass
        return []

    @staticmethod
    def _get_quarterly_cf(yft) -> List[Dict]:
        try:
            df = yft.quarterly_cashflow
            if df is not None and not df.empty:
                return [dict(df.iloc[:, i]) for i in range(min(8, df.shape[1]))]
        except Exception:
            pass
        return []
