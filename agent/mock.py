"""Dry-run stand-ins: a scripted API client and fictional companies. No credits, no network."""

import json
import re
from types import SimpleNamespace


def _financials(ticker, name, segment, sheet, market_cap, cash, debt, revenue, ev):
    is_bank = sheet == "bank_broker"
    return {
        "status": "ok", "citation": "Fixture data, not real", "ticker": ticker, "name": name, "segment": segment,
        "balance_sheet_type": sheet, "market_cap": market_cap, "cash": cash, "total_debt": debt, "revenue": revenue,
        "enterprise_value": None if is_bank else ev,
        "enterprise_value_note": "not meaningful for banks and brokers" if is_bank else "",
        "cash_note": "includes client and deposit funding, not deal capacity" if is_bank else "",
        "yahoo_debt_to_equity_raw": 50.0, "debt_to_equity_recomputed": 0.5, "debt_to_equity_check": "ok",
    }


FIXTURES = {
    "AAA": _financials("AAA", "Fixture Exchange Co", "Exchange", "corporate", 40e9, 5e9, 2e9, 6e9, 37e9),
    "BBB": _financials("BBB", "Fixture Custody Bank", "Custody bank", "bank_broker", 30e9, 100e9, 20e9, 12e9, None),
    "CCC": _financials("CCC", "Fixture Payments Inc", "Payments", "corporate", 20e9, 1e9, 3e9, 8e9, 22e9),
}


def fixture_candidates(segments=None, min_market_cap_b=None, max_market_cap_b=None):
    return {"status": "ok", "citation": "Fixture data, not real", "candidates": [
        {"ticker": t, "name": f["name"], "segment": f["segment"], "market_cap": f["market_cap"]}
        for t, f in FIXTURES.items()
    ]}


def fixture_financials(ticker):
    return FIXTURES.get(ticker) or {"status": "not_available", "reason": f"No fixture for {ticker}"}


FIXTURE_TEXT = "is expanding its digital asset services and completed 2 acquisitions in this area."


def fixture_filing(ticker, section, form="10-K"):
    date = "2026-10-01" if form == "10-Q" else "2026-02-01"
    return {
        "status": "ok", "form": form, "filing_date": date, "citation": f"{ticker} {form} fixture, section: {section}",
        "url": "fixture", "truncated": False, "excerpt": f"{ticker} {FIXTURE_TEXT}",
    }


FIXTURE_TOOLS = {
    "get_candidates": fixture_candidates,
    "get_financials": fixture_financials,
    "fetch_filing_excerpt": fixture_filing,
}


ALL_FACTORS = ("digital_asset_activity", "target_line_activity", "stated_priority", "related_deal", "clear_obstacle")
FIXTURE_FACTORS = {
    "AAA": ["digital_asset_activity", "target_line_activity"],
    "BBB": ["digital_asset_activity", "target_line_activity", "stated_priority", "related_deal"],
    "CCC": [],
}


def _response(blocks, stop_reason):
    usage = SimpleNamespace(input_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=1000, output_tokens=150)
    return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=usage)


def text_response(text):
    return _response([SimpleNamespace(type="text", text=text)], "end_turn")


def tool_response(name, args, tool_id="toolu_mock"):
    return _response([SimpleNamespace(type="tool_use", id=tool_id, name=name, input=args)], "tool_use")


class DryRunClient:
    """Replays the shortlist and buyer flows using the message history to pick each step."""

    def __init__(self):
        self.messages = self

    def create(self, **kwargs):
        history = kwargs["messages"]
        turn = sum(1 for m in history if m["role"] == "assistant")
        first = history[0]["content"]
        if "Shortlist at most" in first:
            if turn == 0:
                return tool_response("get_candidates", {"segments": None, "min_market_cap_b": None, "max_market_cap_b": None})
            return text_response(json.dumps({"tickers": list(FIXTURES), "reasoning": "Fixture shortlist for testing."}))
        ticker = re.search(r"\((\w+)\)\.$", first).group(1)
        if turn == 0:
            return tool_response("get_financials", {"ticker": ticker})
        if turn == 1:
            return tool_response("fetch_filing_excerpt", {"ticker": ticker, "section": "digital_assets", "form": "10-Q"})
        factors = FIXTURE_FACTORS[ticker]
        return text_response(json.dumps({
            **{factor: factor in factors for factor in ALL_FACTORS},
            "rationale": f"The fixture filing says {ticker} is expanding its digital asset services.",
            "strategic_gap_addressed": "Adds regulated custody in this fixture scenario.",
            "key_risks": ["Fixture integration risk", "Fixture regulatory risk"],
            "evidence": [{"supports": factor, "citation": f"{ticker} 10-Q fixture, section: digital_assets",
                          "quote": FIXTURE_TEXT} for factor in factors],
        }))
