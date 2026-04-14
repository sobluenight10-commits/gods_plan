"""Risk Screener — 9-dimension risk scoring for every portfolio stock.

Dimensions (each scored 0-9):
  1. Revenue Concentration  — single-customer / single-segment dependency
  2. Profitability Trend    — margin direction (improving / declining / volatile)
  3. Balance Sheet Leverage  — debt-to-equity, interest coverage
  4. Cash Runway            — quarters of cash remaining at current burn
  5. Revenue Volatility     — QoQ variance over last 8 quarters
  6. Valuation Cushion      — how much downside to fair value (P/E vs growth)
  7. Liquidity Risk         — avg daily volume, bid-ask, market cap
  8. Sector Cyclicality     — macro sensitivity of the sector
  9. Catalyst Dependency    — binary event risk (FDA, contracts, launches)

Scoring: 0 = no risk, 9 = critical risk.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from skills.base import SkillRunner, BERLIN

logger = logging.getLogger("olympus.skills.risk")

SECTOR_CYCLICALITY = {
    "Intelligence": 5, "Energy": 6, "Space": 7, "Bio": 8,
    "Robotics": 5, "Infra": 4, "Global": 5, "Locked": 3, "Tactical": 3,
}

CATALYST_TICKERS = {
    "OKLO": 8, "BEAM": 9, "NTLA": 8, "CRSP": 7, "ASTS": 8,
    "RKLB": 6, "PL": 5, "IONQ": 7,
}


def _safe_div(a, b, default=0.0):
    try:
        if b is None or b == 0:
            return default
        return float(a) / float(b)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


def _clamp(val, lo=0, hi=9):
    return max(lo, min(hi, int(round(val))))


class RiskScreener(SkillRunner):
    name = "risk"

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
                logger.warning(f"[risk] {tk} failed: {e}")
                results[tk] = self._empty(tk, str(e))
        summary = self._build_summary(results)
        output = {
            "run_date": datetime.now(BERLIN).strftime("%Y-%m-%d %H:%M"),
            "total": len(results),
            "results": results,
            "summary": summary,
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

        bs = self._get_balance_sheet(yft)
        inc = self._get_income(yft)
        cf = self._get_cashflow(yft)

        scores = {}
        narratives = {}

        s, n = self._score_revenue_concentration(ticker, info)
        scores["revenue_concentration"] = s
        narratives["revenue_concentration"] = n

        s, n = self._score_profitability_trend(inc)
        scores["profitability_trend"] = s
        narratives["profitability_trend"] = n

        s, n = self._score_balance_sheet(bs, info)
        scores["balance_sheet_leverage"] = s
        narratives["balance_sheet_leverage"] = n

        s, n = self._score_cash_runway(bs, cf)
        scores["cash_runway"] = s
        narratives["cash_runway"] = n

        s, n = self._score_revenue_volatility(inc)
        scores["revenue_volatility"] = s
        narratives["revenue_volatility"] = n

        s, n = self._score_valuation_cushion(info)
        scores["valuation_cushion"] = s
        narratives["valuation_cushion"] = n

        s, n = self._score_liquidity_risk(info)
        scores["liquidity_risk"] = s
        narratives["liquidity_risk"] = n

        sector = self.universe.get(ticker, {}).get("sector", "Global")
        s = SECTOR_CYCLICALITY.get(sector, 5)
        scores["sector_cyclicality"] = s
        narratives["sector_cyclicality"] = f"Sector '{sector}' cyclicality rating: {s}/9"

        s = CATALYST_TICKERS.get(ticker, 3)
        scores["catalyst_dependency"] = s
        narratives["catalyst_dependency"] = (
            f"Binary event risk: {s}/9" +
            (" (pre-revenue / clinical)" if s >= 7 else "")
        )

        total = sum(scores.values())
        avg = round(total / len(scores), 1) if scores else 0
        critical = [k for k, v in scores.items() if v >= 7]

        return {
            "ticker": ticker,
            "scores": scores,
            "narratives": narratives,
            "total_risk": total,
            "avg_risk": avg,
            "critical_risks": critical,
            "risk_level": (
                "CRITICAL" if avg >= 6 else
                "HIGH" if avg >= 4.5 else
                "MODERATE" if avg >= 3 else
                "LOW"
            ),
        }

    def _empty(self, ticker: str, error: str) -> Dict:
        dims = [
            "revenue_concentration", "profitability_trend", "balance_sheet_leverage",
            "cash_runway", "revenue_volatility", "valuation_cushion",
            "liquidity_risk", "sector_cyclicality", "catalyst_dependency",
        ]
        return {
            "ticker": ticker,
            "scores": {d: 5 for d in dims},
            "narratives": {d: f"Data unavailable: {error}" for d in dims},
            "total_risk": 45,
            "avg_risk": 5.0,
            "critical_risks": [],
            "risk_level": "UNKNOWN",
        }

    # ── Dimension scorers ────────────────────────────────────────────────────

    def _score_revenue_concentration(self, ticker: str, info: Dict) -> tuple:
        gov_tickers = {"PL", "KTOS", "PLTR", "RKLB"}
        if ticker in gov_tickers:
            return 7, "High government revenue dependency — contract cancellation risk"
        sector = info.get("sector", "")
        if "Defense" in sector or "Aerospace" in sector:
            return 6, f"Sector '{sector}' typically has concentrated customer base"
        return 3, "Diversified revenue base assumed"

    def _score_profitability_trend(self, inc: List[Dict]) -> tuple:
        if len(inc) < 2:
            return 5, "Insufficient quarterly data"
        margins = []
        for q in inc[:8]:
            rev = q.get("Total Revenue", 0) or 0
            ni = q.get("Net Income", 0) or 0
            if rev > 0:
                margins.append(ni / rev)
        if len(margins) < 2:
            return 5, "Insufficient margin data"
        recent = margins[0]
        older = margins[-1]
        if recent < 0 and older < 0:
            if recent < older:
                return 8, f"Losses widening: {recent:.1%} vs {older:.1%}"
            return 6, f"Unprofitable but improving: {recent:.1%} vs {older:.1%}"
        if recent < 0:
            return 7, f"Turned unprofitable: {recent:.1%}"
        if recent < older * 0.7:
            return 6, f"Margin declining: {recent:.1%} from {older:.1%}"
        if recent > older * 1.1:
            return 2, f"Margin improving: {recent:.1%} from {older:.1%}"
        return 4, f"Margin stable around {recent:.1%}"

    def _score_balance_sheet(self, bs: List[Dict], info: Dict) -> tuple:
        if not bs:
            return 5, "No balance sheet data"
        latest = bs[0]
        total_debt = abs(latest.get("Total Debt", 0) or 0)
        equity = latest.get("Total Stockholders Equity") or latest.get("Stockholders Equity", 0)
        equity = abs(equity) if equity else 0
        de_ratio = _safe_div(total_debt, equity, default=999)
        if de_ratio > 5:
            return 9, f"Extreme leverage: D/E = {de_ratio:.1f}"
        if de_ratio > 2:
            return 7, f"High leverage: D/E = {de_ratio:.1f}"
        if de_ratio > 1:
            return 5, f"Moderate leverage: D/E = {de_ratio:.1f}"
        if de_ratio > 0.5:
            return 3, f"Conservative leverage: D/E = {de_ratio:.1f}"
        return 1, f"Minimal debt: D/E = {de_ratio:.1f}"

    def _score_cash_runway(self, bs: List[Dict], cf: List[Dict]) -> tuple:
        if not bs:
            return 5, "No data"
        cash = bs[0].get("Cash And Cash Equivalents", 0) or 0
        cash += bs[0].get("Short Term Investments", 0) or 0
        if not cf:
            return 4 if cash > 0 else 7, f"Cash: ${cash/1e6:.0f}M, no CF data"
        fcf = cf[0].get("Free Cash Flow", 0) or 0
        if fcf >= 0:
            return 1, f"FCF positive (${fcf/1e6:.0f}M), cash ${cash/1e6:.0f}M"
        burn_q = abs(fcf)
        if burn_q == 0:
            return 3, f"Cash ${cash/1e6:.0f}M, zero burn"
        quarters = cash / burn_q
        if quarters < 4:
            return 9, f"Critical: {quarters:.0f}Q runway at current burn"
        if quarters < 8:
            return 6, f"Tight: {quarters:.0f}Q runway"
        if quarters < 16:
            return 3, f"Comfortable: {quarters:.0f}Q runway"
        return 1, f"Strong: {quarters:.0f}Q+ runway"

    def _score_revenue_volatility(self, inc: List[Dict]) -> tuple:
        revs = []
        for q in inc[:8]:
            r = q.get("Total Revenue", 0)
            if r and r > 0:
                revs.append(r)
        if len(revs) < 4:
            return 5, "Insufficient revenue history"
        qoq_changes = []
        for i in range(len(revs) - 1):
            chg = (revs[i] - revs[i+1]) / revs[i+1] if revs[i+1] != 0 else 0
            qoq_changes.append(chg)
        avg_chg = sum(abs(c) for c in qoq_changes) / len(qoq_changes)
        if avg_chg > 0.3:
            return 8, f"Highly volatile revenue: avg QoQ swing {avg_chg:.0%}"
        if avg_chg > 0.15:
            return 5, f"Moderate volatility: avg QoQ swing {avg_chg:.0%}"
        if avg_chg > 0.08:
            return 3, f"Stable revenue: avg QoQ swing {avg_chg:.0%}"
        return 1, f"Very stable: avg QoQ swing {avg_chg:.0%}"

    def _score_valuation_cushion(self, info: Dict) -> tuple:
        pe = info.get("forwardPE") or info.get("trailingPE")
        growth = info.get("revenueGrowth") or info.get("earningsGrowth")
        if pe is None:
            return 5, "No P/E data — pre-earnings or ETF"
        if pe < 0:
            return 7, f"Negative P/E ({pe:.1f}) — unprofitable"
        if growth and growth > 0:
            peg = pe / (growth * 100) if growth * 100 > 0 else 999
            if peg < 1:
                return 2, f"PEG {peg:.1f} — cheap relative to growth"
            if peg < 2:
                return 4, f"PEG {peg:.1f} — fairly valued"
            return 7, f"PEG {peg:.1f} — expensive relative to growth"
        if pe > 80:
            return 8, f"P/E {pe:.0f} — extreme multiple"
        if pe > 40:
            return 6, f"P/E {pe:.0f} — high multiple"
        if pe > 20:
            return 3, f"P/E {pe:.0f} — reasonable"
        return 1, f"P/E {pe:.0f} — cheap"

    def _score_liquidity_risk(self, info: Dict) -> tuple:
        mcap = info.get("marketCap", 0) or 0
        vol = info.get("averageVolume", 0) or 0
        if mcap > 50e9:
            return 1, f"Mega-cap (${mcap/1e9:.0f}B)"
        if mcap > 10e9:
            return 2, f"Large-cap (${mcap/1e9:.0f}B)"
        if mcap > 2e9:
            return 4, f"Mid-cap (${mcap/1e9:.1f}B)"
        if mcap > 500e6:
            return 6, f"Small-cap (${mcap/1e6:.0f}M)"
        if mcap > 0:
            return 8, f"Micro-cap (${mcap/1e6:.0f}M)"
        return 5, "Market cap unavailable"

    # ── Data helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _get_balance_sheet(yft) -> List[Dict]:
        try:
            df = yft.quarterly_balance_sheet
            if df is not None and not df.empty:
                return [dict(df.iloc[:, i]) for i in range(min(4, df.shape[1]))]
        except Exception:
            pass
        return []

    @staticmethod
    def _get_income(yft) -> List[Dict]:
        try:
            df = yft.quarterly_income_stmt
            if df is not None and not df.empty:
                return [dict(df.iloc[:, i]) for i in range(min(8, df.shape[1]))]
        except Exception:
            pass
        return []

    @staticmethod
    def _get_cashflow(yft) -> List[Dict]:
        try:
            df = yft.quarterly_cashflow
            if df is not None and not df.empty:
                return [dict(df.iloc[:, i]) for i in range(min(4, df.shape[1]))]
        except Exception:
            pass
        return []

    # ── Summary builder ──────────────────────────────────────────────────────

    def _build_summary(self, results: Dict) -> Dict:
        critical = []
        high = []
        moderate = []
        low = []
        for tk, r in results.items():
            level = r.get("risk_level", "UNKNOWN")
            entry = {"ticker": tk, "avg_risk": r.get("avg_risk", 5), "critical_risks": r.get("critical_risks", [])}
            if level == "CRITICAL":
                critical.append(entry)
            elif level == "HIGH":
                high.append(entry)
            elif level == "MODERATE":
                moderate.append(entry)
            else:
                low.append(entry)

        for lst in [critical, high, moderate, low]:
            lst.sort(key=lambda x: x["avg_risk"], reverse=True)

        return {
            "critical": critical,
            "high": high,
            "moderate": moderate,
            "low": low,
            "portfolio_avg_risk": round(
                sum(r.get("avg_risk", 5) for r in results.values()) / max(len(results), 1), 1
            ),
        }
