"""Tools the agent can call. Missing data comes back as status not_available, never a guess."""

import datetime
import functools
import math
import os
import re
import time

import requests
import yfinance as yf
from bs4 import BeautifulSoup

from agent.schemas import AbilityToPay
from data import BUYER_UNIVERSE, apply_filters, load_buyers

MAX_EXCERPT_CHARS = 24_000  # about 6k tokens at 4 chars per token
EDGAR_PAUSE_SECONDS = 0.15  # SEC allows 10 requests per second

SEP = r"\s*[.:—–-]?\s*"
HEADINGS = {
    "10-K": {
        "business": (rf"item\s*1{SEP}business", r"item\s*1a\b"),
        "risk_factors": (rf"item\s*1a{SEP}risk\s+factors", r"item\s*1b\b|item\s*1c\b|item\s*2\b"),
        "mdna": (rf"item\s*7{SEP}management", r"item\s*7a\b|item\s*8\b"),
    },
    "10-Q": {
        "risk_factors": (rf"item\s*1a{SEP}risk\s+factors", rf"item\s*2{SEP}unregistered|item\s*5\b|item\s*6\b"),
        "mdna": (rf"item\s*2{SEP}management", r"item\s*3\b|item\s*4\b"),
    },
}
# 10-Ks have no M&A strategy section, so these pull passages from the whole filing.
KEYWORDS = {
    "ma_strategy": r"\b(acquisitions?|acquired|acquire|mergers?|business combinations?|inorganic)\b",
    "digital_assets": r"\b(digital assets?|crypto\w*|bitcoin|stablecoins?|tokeniz\w+|blockchain)\b",
}
SECTIONS = ["business", "risk_factors", "mdna", "liquidity", "ma_strategy", "digital_assets"]


def _with_backoff(fn, attempts=3, base_delay=1.0):
    """Retry transient data-source failures, waiting 1s then 2s."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay * 2 ** attempt)


def _not_available(reason: str, **extra) -> dict:
    return {"status": "not_available", "reason": reason, **extra}


def _number(value) -> float | None:
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    return None


def get_candidates(segments: list[str] | None = None, min_market_cap_b: float | None = None,
                   max_market_cap_b: float | None = None) -> dict:
    """Filter the buyer universe with the same logic as the screener sidebar."""
    df = load_buyers()
    if df.empty:
        return _not_available("Market data source returned nothing")
    filtered = apply_filters(df, market_cap_range=(min_market_cap_b or 0, max_market_cap_b or 1e6))
    if segments:
        filtered = filtered[filtered["Segment"].isin(segments)]
    if filtered.empty:
        return _not_available("No buyers match these criteria")
    return {
        "status": "ok",
        "citation": f"Yahoo Finance via yfinance, pulled {datetime.date.today()}",
        "candidates": [
            {"ticker": row["Ticker"], "name": row["Name"], "segment": row["Segment"],
             "market_cap": _number(row["Market Cap"])}
            for _, row in filtered.iterrows()
        ],
    }


def _statement_value(statement, *labels) -> float | None:
    if statement is None or statement.empty:
        return None
    for label in labels:
        if label in statement.index:
            for value in statement.loc[label]:
                number = _number(value)
                if number is not None:
                    return number
    return None


def _debt_equity_check(yahoo_raw: float | None, debt: float | None, equity: float | None) -> dict:
    """Recompute D/E from the balance sheet, since Yahoo's ratio mixes percent and ratio units."""
    recomputed = debt / equity if debt is not None and equity else None
    if recomputed is None or yahoo_raw is None:
        status = "not available"
    else:
        agrees = any(abs(c - recomputed) <= 0.15 * abs(recomputed) for c in (yahoo_raw, yahoo_raw / 100))
        status = "ok" if agrees else "mismatch"
    return {
        "yahoo_debt_to_equity_raw": yahoo_raw,
        "debt_to_equity_recomputed": round(recomputed, 2) if recomputed is not None else None,
        "debt_to_equity_check": status,
    }


@functools.lru_cache(maxsize=64)
def get_financials(ticker: str) -> dict:
    """USD financials for a US-listed buyer. EV is withheld for banks and brokers."""
    if ticker not in BUYER_UNIVERSE:
        return _not_available(f"{ticker} is not in the buyer universe")
    segment, balance_sheet = BUYER_UNIVERSE[ticker]
    stock = yf.Ticker(ticker)
    info = _with_backoff(lambda: stock.info) or {}
    market_cap = _number(info.get("marketCap"))
    if market_cap is None:
        return _not_available(f"No market data returned for {ticker}")

    statement = _with_backoff(lambda: stock.quarterly_balance_sheet)
    debt = _statement_value(statement, "Total Debt")
    equity = _statement_value(statement, "Stockholders Equity", "Common Stock Equity")
    is_bank_broker = balance_sheet == "bank_broker"
    return {
        "status": "ok",
        "citation": f"Yahoo Finance via yfinance, pulled {datetime.date.today()}",
        "ticker": ticker,
        "name": info.get("longName") or ticker,
        "segment": segment,
        "balance_sheet_type": balance_sheet,
        "market_cap": market_cap,
        "cash": _number(info.get("totalCash")),
        "total_debt": _number(info.get("totalDebt")),
        "revenue": _number(info.get("totalRevenue")),
        "enterprise_value": None if is_bank_broker else _number(info.get("enterpriseValue")),
        "enterprise_value_note": "not meaningful for banks and brokers" if is_bank_broker else "",
        "cash_note": "includes client and deposit funding, not deal capacity" if is_bank_broker else "",
        **_debt_equity_check(_number(info.get("debtToEquity")), debt, equity),
    }


def ability_to_pay(financials: dict, deal_low: float | None, deal_high: float | None) -> AbilityToPay:
    """Cash coverage for corporates, deal size as % of market cap for everyone."""
    if not deal_low or not deal_high:
        return AbilityToPay(basis="not available", note="No deal size assumption was provided")
    market_cap = financials.get("market_cap")
    if not market_cap:
        return AbilityToPay(basis="not available", deal_low=deal_low, deal_high=deal_high,
                            note="Buyer market cap not available")
    result = AbilityToPay(
        basis="pct_market_cap", deal_low=deal_low, deal_high=deal_high,
        pct_market_cap_low=round(deal_low / market_cap * 100, 2),
        pct_market_cap_high=round(deal_high / market_cap * 100, 2),
    )
    cash = financials.get("cash")
    if financials.get("balance_sheet_type") == "bank_broker":
        result.note = "Cash coverage omitted: reported cash includes client and deposit funding"
    elif cash is None:
        result.note = "Cash not available"
    else:
        result.basis = "cash_coverage"
        result.cash = cash
        result.cash_coverage_low = round(cash / deal_low, 2)
        result.cash_coverage_high = round(cash / deal_high, 2)
    return result


def _edgar_get(url: str) -> requests.Response:
    user_agent = os.environ.get("SEC_USER_AGENT")
    if not user_agent:
        raise RuntimeError("SEC_USER_AGENT is not set")

    def fetch():
        time.sleep(EDGAR_PAUSE_SECONDS)
        response = requests.get(url, headers={"User-Agent": user_agent}, timeout=30)
        response.raise_for_status()
        return response

    return _with_backoff(fetch)


@functools.lru_cache(maxsize=1)
def _ticker_to_cik() -> dict:
    rows = _edgar_get("https://www.sec.gov/files/company_tickers.json").json().values()
    return {row["ticker"]: row["cik_str"] for row in rows}


def html_to_text(html: str) -> str:
    """Plain text with one line per block. Inline tags are removed so words and sentences stay whole."""
    soup = BeautifulSoup(html, "html.parser")
    for hidden in soup.find_all("ix:header"):  # XBRL metadata, full of terms like crypto asset members
        hidden.decompose()
    for tag in soup.find_all(lambda t: t.name in {"span", "font", "a", "b", "i", "u", "em", "strong", "sup", "sub"}
                             or t.name.startswith("ix:")):
        tag.unwrap()
    soup.smooth()
    return re.sub(r"[ \t\xa0]+", " ", soup.get_text("\n"))


@functools.lru_cache(maxsize=32)
def _filing_text(url: str) -> str:
    return html_to_text(_edgar_get(url).text)


def _annual_report_exhibit(base_url: str, accession: str) -> str | None:
    """Some banks, like BNY, put most of the 10-K in an Exhibit 13 annual report.

    File names don't reveal this (BNY's is bk-20251231_d2.htm), so read the type from the filing index.
    """
    index = BeautifulSoup(_edgar_get(f"{base_url}/{accession}-index.htm").text, "html.parser")
    for row in index.find_all("tr"):
        cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
        if any(cell.startswith("EX-13") for cell in cells):
            link = row.find("a", href=re.compile(r"\.html?$"))
            if link:
                return f"{base_url}/{link['href'].rsplit('/', 1)[-1]}"
    return None


@functools.lru_cache(maxsize=32)
def _latest_filing(cik: int, form: str) -> dict | None:
    recent = _edgar_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()["filings"]["recent"]
    for i, filed_form in enumerate(recent["form"]):
        if filed_form == form:
            accession = recent["accessionNumber"][i]
            base_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
            return {
                "form": form,
                "filing_date": recent["filingDate"][i],
                "url": f"{base_url}/{recent['primaryDocument'][i]}",
                "exhibit_url": _annual_report_exhibit(base_url, accession) if form == "10-K" else None,
            }
    return None


def extract_section(text: str, start: str, end: str, min_chars: int = 1500) -> str | None:
    """Longest span from a line-start heading to the next section's heading.

    Table of contents entries give short spans, so the longest wins. Repeated page headers
    share one end, so the earliest start is kept. Below min_chars the section is treated as
    missing, usually incorporated by reference.
    """
    starts = [m.start() for m in re.finditer(rf"(?im)^\s*(?:{start})", text)]
    ends = [m.start() for m in re.finditer(rf"(?im)^\s*(?:{end})", text)]
    earliest_start_by_end = {}
    for s in starts:
        following = next((e for e in ends if e > s), len(text))
        earliest_start_by_end.setdefault(following, s)
    spans = [(e - s, s, e) for e, s in earliest_start_by_end.items()]
    if not spans or max(spans)[0] < min_chars:
        return None
    _, s, e = max(spans)
    return text[s:e]


def keyword_passages(text: str, pattern: str, radius: int = 500) -> str | None:
    """Merge the text around keyword hits, keep the densest passages, return in filing order."""
    hits = [m.start() for m in re.finditer(pattern, text, flags=re.I)]
    if not hits:
        return None
    windows = []
    for hit in hits:
        low, high = max(0, hit - radius), hit + radius
        if windows and low <= windows[-1][1]:
            windows[-1][1] = high
            windows[-1][2] += 1
        else:
            windows.append([low, high, 1])
    kept, used = [], 0
    for window in sorted(windows, key=lambda w: w[2] / (w[1] - w[0]), reverse=True):
        if used >= MAX_EXCERPT_CHARS:
            break
        kept.append(window)
        used += window[1] - window[0]
    return "\n[...]\n".join(text[w[0]:w[1]] for w in sorted(kept))


def _liquidity(text: str, form: str) -> str | None:
    start, end = HEADINGS[form]["mdna"]
    mdna = extract_section(text, start, end)
    if mdna:
        match = re.search(r"(?im)^\s*liquidity(\s+and\s+[\w ]+)?\s*$", mdna)
        if match:
            return mdna[match.start():]
    return keyword_passages(text, r"\bliquidity\b")


def fetch_filing_excerpt(ticker: str, section: str, form: str = "10-K") -> dict:
    """Return one section of the latest 10-K or 10-Q, truncated to about 6k tokens."""
    if section not in SECTIONS:
        return _not_available(f"Unknown section {section}")
    cik = _ticker_to_cik().get(ticker)
    if cik is None:
        return _not_available(f"{ticker} has no SEC filer record")
    filing = _latest_filing(cik, form)
    if filing is None:
        return _not_available(f"No {form} on EDGAR for {ticker}")

    text = _filing_text(filing["url"])
    if filing["exhibit_url"]:
        text += "\n" + _filing_text(filing["exhibit_url"])
    citation = f"{ticker} {form} filed {filing['filing_date']}, section: {section}"
    dated = {"form": form, "filing_date": filing["filing_date"], "citation": citation, "url": filing["url"]}
    if filing["exhibit_url"]:
        dated["exhibit_url"] = filing["exhibit_url"]  # the excerpt may come from here, so a reader needs this link too
    if section in KEYWORDS:
        excerpt = keyword_passages(text, KEYWORDS[section])
    elif section == "liquidity":
        excerpt = _liquidity(text, form)
    elif section in HEADINGS[form]:
        excerpt = extract_section(text, *HEADINGS[form][section])
    else:
        return _not_available(f"{section} is not a {form} section", **dated)
    if not excerpt:
        return _not_available(
            f"{section} not found in the main {form} document; it may be incorporated by reference",
            **dated,
        )
    excerpt = re.sub(r"\s*\n\s*", "\n", excerpt).strip()
    return {
        "status": "ok",
        **dated,
        "truncated": len(excerpt) > MAX_EXCERPT_CHARS,
        "excerpt": excerpt[:MAX_EXCERPT_CHARS],
    }


SEGMENT_NAMES = sorted({segment for segment, _ in BUYER_UNIVERSE.values()})

GET_CANDIDATES_DEF = {
    "name": "get_candidates",
    "description": "List public buyers from the curated universe, optionally filtered by segment and market cap in $B.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "segments": {"type": ["array", "null"], "items": {"type": "string", "enum": SEGMENT_NAMES}},
            "min_market_cap_b": {"type": ["number", "null"]},
            "max_market_cap_b": {"type": ["number", "null"]},
        },
        "required": ["segments", "min_market_cap_b", "max_market_cap_b"],
        "additionalProperties": False,
    },
}
GET_FINANCIALS_DEF = {
    "name": "get_financials",
    "description": ("Market cap, cash, debt, revenue, EV and a recomputed debt/equity check for a buyer, "
                    "in USD, plus deal_context with precomputed deal size ratios."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"ticker": {"type": "string"}},
        "required": ["ticker"],
        "additionalProperties": False,
    },
}
FETCH_FILING_DEF = {
    "name": "fetch_filing_excerpt",
    "description": ("Text from the buyer's latest SEC filing, up to about 6k tokens. business, risk_factors "
                    "and mdna are filing sections; liquidity is the MD&A liquidity discussion; ma_strategy "
                    "and digital_assets are passages matching those topics from anywhere in the filing."),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string"},
            "section": {"type": "string", "enum": SECTIONS},
            "form": {"type": "string", "enum": ["10-K", "10-Q"]},
        },
        "required": ["ticker", "section", "form"],
        "additionalProperties": False,
    },
}

LIVE_TOOLS = {
    "get_candidates": get_candidates,
    "get_financials": get_financials,
    "fetch_filing_excerpt": fetch_filing_excerpt,
}
