"""
thesis_guard.py — MINERVA ACTION CHANGE RULE ENFORCER

THE RULE (permanently encoded):
Before changing any stock's thesis status, a company-specific
event must be provided. Sector sentiment, price drops, analyst
opinions, and valuation concerns are NOT valid triggers.

This module is the single source of truth for all thesis states.
It is imported by action_logic.py and olympus_engine.py.
It cannot be bypassed except by explicit force=True (GOD only).

VALID THESIS-CHANGE TRIGGERS:
  intact -> wounded:
    - earnings_miss_guidance_cut
    - contract_cancelled
    - contract_terminated
    - fda_rejection
    - partnership_cancelled
    - nih_funding_cut_quantified
    - key_customer_departed_confirmed
    - management_fraud_confirmed
    - sec_investigation_opened

  wounded -> dead:
    - bankruptcy_filed
    - core_contract_cancelled_gt10pct_revenue
    - fraud_confirmed_by_regulator
    - technology_failure_confirmed
    - delisted

  wounded/dead -> intact:
    - thesis_confirmed_by_earnings
    - contract_reinstated
    - sec_cleared
    - management_replaced_clean

INVALID TRIGGERS (these must NEVER change thesis):
  - price_dropping
  - analyst_downgrade
  - valuation_too_high (P/S, P/E, EV/EBITDA concerns)
  - insider_selling_routine
  - sector_peers_dropping
  - macro_fear
  - short_seller_report_unconfirmed
  - bearish_article_read
  - reflexivity_concern
  - institutional_rotation
  - technical_breakdown (200-day MA break)
"""

import json
import os
import time
from typing import Optional

_HISTORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data", "thesis_history.json"
)

VALID_TRIGGERS = {
    "intact_to_wounded": [
        "earnings_miss_guidance_cut",
        "contract_cancelled",
        "contract_terminated",
        "fda_rejection",
        "partnership_cancelled",
        "nih_funding_cut_quantified",
        "key_customer_departed_confirmed",
        "management_fraud_confirmed",
        "sec_investigation_opened",
    ],
    "wounded_to_dead": [
        "bankruptcy_filed",
        "core_contract_cancelled_gt10pct_revenue",
        "fraud_confirmed_by_regulator",
        "technology_failure_confirmed",
        "delisted",
    ],
    "to_intact": [
        "thesis_confirmed_by_earnings",
        "contract_reinstated",
        "sec_cleared",
        "management_replaced_clean",
        "guidance_raised",
        "initial_entry",
    ],
}

INVALID_TRIGGERS = [
    "price_dropping",
    "analyst_downgrade",
    "valuation_too_high",
    "insider_selling_routine",
    "sector_peers_dropping",
    "macro_fear",
    "short_seller_report_unconfirmed",
    "bearish_article_read",
    "reflexivity_concern",
    "institutional_rotation",
    "technical_breakdown",
    "p_s_ratio_concern",
    "p_e_ratio_concern",
    "free_cash_flow_negative",
]


def load_history() -> dict:
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_history(history: dict) -> None:
    os.makedirs(os.path.dirname(_HISTORY_FILE), exist_ok=True)
    with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)


def get_thesis(ticker: str) -> str:
    """Get current authoritative thesis for a ticker. Default: intact."""
    history = load_history()
    return history.get(ticker, {}).get("thesis", "intact")


def get_last_event(ticker: str) -> str:
    """Get the company event that last changed the thesis."""
    history = load_history()
    return history.get(ticker, {}).get("last_event", "unknown")


def _is_valid_trigger(current: str, new: str, event: str) -> bool:
    """Check if event is valid for this direction of thesis change."""
    if current == new:
        return True
    if new == "intact":
        return event in VALID_TRIGGERS["to_intact"]
    if current == "intact" and new == "wounded":
        return event in VALID_TRIGGERS["intact_to_wounded"]
    if current == "wounded" and new == "dead":
        return event in VALID_TRIGGERS["wounded_to_dead"]
    if current == "intact" and new == "dead":
        # Skipping wounded -> requires dead-level event
        return event in VALID_TRIGGERS["wounded_to_dead"]
    return False


def validate(
    ticker: str,
    proposed_thesis: str,
    company_event: str = "",
    force: bool = False,
) -> dict:
    """
    Validate a proposed thesis change.

    Returns:
        {
          "allowed": bool,
          "authoritative_thesis": str,   # what the system should USE
          "reason": str,
          "previous": str,
          "blocked": bool,
          "warning": str  # human-readable warning if blocked
        }
    """
    history = load_history()
    record = history.get(ticker, {})
    current = record.get("thesis", "intact")

    # No change — always pass
    if current == proposed_thesis:
        return {
            "allowed": True,
            "authoritative_thesis": current,
            "reason": "No change",
            "previous": current,
            "blocked": False,
            "warning": "",
        }

    # Force override — GOD manual only
    if force:
        _record(ticker, proposed_thesis, f"FORCE:{company_event}", history)
        return {
            "allowed": True,
            "authoritative_thesis": proposed_thesis,
            "reason": f"Force override: {company_event}",
            "previous": current,
            "blocked": False,
            "warning": "WARNING: Force override used — verify with GOD",
        }

    # Invalid trigger check
    if company_event and company_event in INVALID_TRIGGERS:
        return {
            "allowed": False,
            "authoritative_thesis": current,  # REVERT to current
            "reason": (
                f"BLOCKED: '{company_event}' is an invalid trigger. "
                f"Thesis remains {current}."
            ),
            "previous": current,
            "blocked": True,
            "warning": (
                f"BLOCKED MINERVA ACTION CHANGE RULE VIOLATED\n"
                f"Ticker: {ticker}\n"
                f"Attempted: {current} -> {proposed_thesis}\n"
                f"Trigger: {company_event} (INVALID)\n"
                f"Thesis remains: {current}\n"
                f"Valid triggers for this change: "
                + str(_get_valid_list(current, proposed_thesis))
            ),
        }

    # No event provided
    if not company_event:
        return {
            "allowed": False,
            "authoritative_thesis": current,
            "reason": (
                f"BLOCKED: No company event provided for "
                f"{ticker} {current}->{proposed_thesis}. "
                f"Thesis remains {current}."
            ),
            "previous": current,
            "blocked": True,
            "warning": (
                f"BLOCKED MINERVA ACTION CHANGE RULE VIOLATED\n"
                f"Ticker: {ticker}\n"
                f"Attempted: {current} -> {proposed_thesis}\n"
                f"No company event provided.\n"
                f"Thesis remains: {current}\n"
                f"Valid triggers: "
                + str(_get_valid_list(current, proposed_thesis))
            ),
        }

    # Valid trigger check
    if not _is_valid_trigger(current, proposed_thesis, company_event):
        return {
            "allowed": False,
            "authoritative_thesis": current,
            "reason": (
                f"BLOCKED: '{company_event}' is not a valid trigger "
                f"for {current}->{proposed_thesis}. Thesis remains {current}."
            ),
            "previous": current,
            "blocked": True,
            "warning": (
                f"BLOCKED MINERVA ACTION CHANGE RULE VIOLATED\n"
                f"Ticker: {ticker} | Change: {current}->{proposed_thesis}\n"
                f"Event '{company_event}' not valid for this direction.\n"
                f"Valid triggers: "
                + str(_get_valid_list(current, proposed_thesis))
            ),
        }

    # All checks passed — record and allow
    _record(ticker, proposed_thesis, company_event, history)
    return {
        "allowed": True,
        "authoritative_thesis": proposed_thesis,
        "reason": f"{current}->{proposed_thesis} via {company_event}",
        "previous": current,
        "blocked": False,
        "warning": "",
    }


def _get_valid_list(current: str, new: str) -> list:
    if new == "intact":
        return VALID_TRIGGERS["to_intact"]
    if current == "intact" and new == "wounded":
        return VALID_TRIGGERS["intact_to_wounded"]
    if current in ("intact", "wounded") and new == "dead":
        return VALID_TRIGGERS["wounded_to_dead"]
    return []


def _record(ticker: str, thesis: str, event: str, history: dict) -> None:
    if ticker not in history:
        history[ticker] = {"thesis": "intact", "history": []}
    prev = history[ticker].get("thesis", "intact")
    history[ticker]["thesis"] = thesis
    history[ticker]["last_event"] = event
    history[ticker]["timestamp"] = time.strftime("%Y-%m-%d %H:%M")
    history[ticker].setdefault("history", []).append({
        "from": prev,
        "to": thesis,
        "event": event,
        "timestamp": time.strftime("%Y-%m-%d %H:%M"),
    })
    history[ticker]["history"] = history[ticker]["history"][-20:]
    save_history(history)


def report_all() -> str:
    """Return formatted thesis status for all tracked tickers."""
    history = load_history()
    lines = ["THESIS STATUS — OLYMPUS UNIVERSE", "=" * 40]
    for ticker, rec in sorted(history.items()):
        t = rec.get("thesis", "intact")
        e = rec.get("last_event", "?")
        ts = rec.get("timestamp", "?")
        icon = "[OK]" if t == "intact" else "[WND]" if t == "wounded" else "[DEAD]"
        lines.append(f"{icon} {ticker:<12} {t.upper():<10} {e} ({ts})")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report_all())
    print()

    tests = [
        ("KTOS_T", "wounded", "earnings_miss_guidance_cut", False, True),
        ("KTOS_T", "wounded", "valuation_too_high", False, False),
        ("PLTR_T", "wounded", "", False, False),
        ("TMO_T",  "wounded", "price_dropping", False, False),
        ("FCX_T",  "dead",    "manual_review", True,  True),
        ("TSM_T",  "intact",  "", False, True),
    ]

    def _reset(tk: str) -> None:
        h = load_history()
        h[tk] = {"thesis": "intact", "last_event": "test",
                 "timestamp": "2026-01-01", "history": []}
        save_history(h)

    print("SELF-TEST:")
    all_pass = True
    for ticker, new_t, event, force, expected in tests:
        # Reset test ticker to intact before each case so the proposed
        # change is genuinely evaluated (no short-circuit on "no change").
        _reset(ticker)
        result = validate(ticker, new_t, event, force)
        ok = result["allowed"] == expected
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  [{status}] {ticker} -> {new_t} via '{event}' force={force}")
        if not ok:
            print(f"    Expected allowed={expected}, got {result['allowed']}")
            print(f"    Reason: {result['reason']}")

    print(f"\n{'ALL PASS' if all_pass else 'ISSUES FOUND'}")

    h = load_history()
    for tk in ["KTOS_T", "PLTR_T", "TMO_T", "FCX_T", "TSM_T"]:
        h.pop(tk, None)
    save_history(h)
