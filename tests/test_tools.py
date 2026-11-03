import json

import pytest

from agent import tools
from agent.tools import (ability_to_pay, extract_section, fetch_filing_excerpt, get_financials,
                         html_to_text, keyword_passages, _debt_equity_check)
from agent.verify import ledger_values, unsupported_numbers
from data import apply_filters

import pandas as pd


def test_ability_to_pay_corporate_uses_cash_coverage():
    pay = ability_to_pay({"market_cap": 40e9, "cash": 5e9, "balance_sheet_type": "corporate"}, 500e6, 1.5e9)
    assert pay.basis == "cash_coverage"
    assert pay.cash_coverage_high == 3.33
    assert pay.cash_coverage_low == 10.0
    assert pay.pct_market_cap_high == 3.75


def test_ability_to_pay_bank_never_treats_cash_as_capacity():
    pay = ability_to_pay({"market_cap": 900e9, "cash": 1.88e12, "balance_sheet_type": "bank_broker"}, 500e6, 1.5e9)
    assert pay.basis == "pct_market_cap"
    assert pay.cash is None and pay.cash_coverage_low is None
    assert "client and deposit" in pay.note


def test_ability_to_pay_without_deal_size_is_not_available():
    pay = ability_to_pay({"market_cap": 40e9, "cash": 5e9, "balance_sheet_type": "corporate"}, None, None)
    assert pay.basis == "not available"


@pytest.mark.parametrize("raw,debt,equity,status", [
    (49.4, 6.9e9, 14e9, "ok"),         # Yahoo reporting percent
    (0.49, 6.9e9, 14e9, "ok"),         # Yahoo reporting a ratio
    (3420.0, 6.9e9, 14e9, "mismatch"),
    (None, 6.9e9, 14e9, "not available"),
    (49.4, None, 14e9, "not available"),
])
def test_debt_equity_check(raw, debt, equity, status):
    assert _debt_equity_check(raw, debt, equity)["debt_to_equity_check"] == status


def test_get_financials_rejects_ticker_outside_universe():
    assert get_financials("NOTREAL")["status"] == "not_available"


def test_get_financials_withholds_ev_for_banks(monkeypatch):
    get_financials.cache_clear()

    class FakeTicker:
        info = {"longName": "State Street", "marketCap": 46e9, "enterpriseValue": -58e9, "totalCash": 160e9,
                "totalDebt": 52e9, "totalRevenue": 13e9, "debtToEquity": float("nan")}
        quarterly_balance_sheet = pd.DataFrame()

    monkeypatch.setattr(tools.yf, "Ticker", lambda ticker: FakeTicker())
    result = get_financials("STT")
    get_financials.cache_clear()
    assert result["enterprise_value"] is None
    assert result["enterprise_value_note"]
    assert result["yahoo_debt_to_equity_raw"] is None


def test_html_to_text_drops_xbrl_and_keeps_words_whole():
    html = ('<ix:header>us-gaap:CryptoAssetMember</ix:header><p>Our mission is ec<span>onomic</span> '
            'freedom</p><p><span>Item 1.</span> <span>Business</span></p>')
    text = html_to_text(html)
    assert "Crypto" not in text
    assert "economic freedom" in text
    assert "Item 1. Business" in text


def test_extract_section_skips_contents_page_and_page_headers():
    body = "Real business text. " * 200
    text = (f"Item 1. Business\nItem 1A. Risk Factors\n"  # table of contents
            f"Item 1. Business\n{body}\nItem 1. Business\nmore text\n"  # repeated page header
            f"Item 1A. Risk Factors\nRisks follow.")
    section = extract_section(text, r"item\s*1\.\s*business", r"item\s*1a\b")
    assert section.count("Real business text") == 200
    assert "more text" in section


def test_extract_section_treats_short_span_as_missing():
    text = "Item 7. Management incorporated by reference.\nItem 8. Financials"
    assert extract_section(text, r"item\s*7\.\s*management", r"item\s*8\b") is None


def test_keyword_passages_returns_none_without_hits():
    assert keyword_passages("nothing relevant", r"\bcrypto\b") is None
    assert "bitcoin" in keyword_passages("we hold bitcoin in custody", r"\bbitcoin\b")


def test_fetch_filing_empty_result_is_not_available(monkeypatch):
    monkeypatch.setattr(tools, "_ticker_to_cik", lambda: {"XYZ": 1})
    monkeypatch.setattr(tools, "_latest_filing", lambda cik, form: {
        "form": form, "filing_date": "2026-02-01", "url": "u", "exhibit_url": None})
    monkeypatch.setattr(tools, "_filing_text", lambda url: "No relevant words here.")
    result = fetch_filing_excerpt("XYZ", "digital_assets")
    assert result["status"] == "not_available"
    assert "2026-02-01" in result["citation"]


def test_fetch_filing_truncates_to_token_budget(monkeypatch):
    monkeypatch.setattr(tools, "_ticker_to_cik", lambda: {"XYZ": 1})
    monkeypatch.setattr(tools, "_latest_filing", lambda cik, form: {
        "form": form, "filing_date": "2026-02-01", "url": "u", "exhibit_url": None})
    monkeypatch.setattr(tools, "_filing_text", lambda url: "bitcoin custody text " * 5000)
    result = fetch_filing_excerpt("XYZ", "digital_assets")
    assert result["truncated"] is True
    assert len(result["excerpt"]) == tools.MAX_EXCERPT_CHARS


def test_fetch_filing_without_user_agent_raises_rather_than_sending_anonymous(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    with pytest.raises(RuntimeError, match="SEC_USER_AGENT"):
        tools._edgar_get("https://www.sec.gov/files/company_tickers.json")


def test_apply_filters_skips_none_and_excludes_nan():
    df = pd.DataFrame({"Market Cap": [20e9, 300e9], "EV/EBITDA": [10.0, float("nan")], "Country": ["US", "US"]})
    assert len(apply_filters(df)) == 2
    assert len(apply_filters(df, market_cap_range=(10, 200))) == 1
    assert len(apply_filters(df, max_ev_ebitda=20)) == 1


@pytest.mark.parametrize("claim", [
    "Cash of $8.8B", "cash of $8.8 billion", "$9B of cash", "market cap of 36,492,341,248",
    "growth of -34.2%", "coverage of 3.33x",
])
def test_number_check_accepts_rounded_tool_figures(claim):
    ledger = ledger_values('{"cash": 8820883456.0, "market_cap": 36492341248, "growth": -0.342, "coverage": 3.33}')
    assert unsupported_numbers(claim, ledger) == []


@pytest.mark.parametrize("claim", ["Cash of $9.4B", "paid $2.1 billion", "margin of 47%", "1,234 customers"])
def test_number_check_flags_fabricated_figures(claim):
    ledger = ledger_values('{"cash": 8820883456.0}')
    assert len(unsupported_numbers(claim, ledger)) == 1


def test_number_check_accepts_filing_tables_in_millions():
    assert unsupported_numbers("revenue of $6.2B", ledger_values("Revenue (in millions) 6,200")) == []


@pytest.mark.parametrize("text", ["the 10-K filed in 2026", "Item 1A", "3 segments", "Q3 results", "over 12 months"])
def test_number_check_ignores_non_financial_numbers(text):
    assert unsupported_numbers(text, set()) == []


def test_number_check_reads_figures_after_json_escaped_line_breaks():
    # Regression: a live run flagged Coinbase's real $3.57B consideration as unsupported.
    result = json.dumps({"excerpt": "(in thousands):\nClass A common stock\n3,573,092\nTotal\n$\n12,221"})
    ledger = ledger_values(result)
    assert unsupported_numbers("stock worth $3.57 billion and $12,221", ledger) == []
