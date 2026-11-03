"""
Ticker universe and market data pulls for the M&A screener.
Handles currency conversion since SE Asia market caps come back
in local currency, not USD.
"""

import datetime
import json
import pathlib

import streamlit as st
import yfinance as yf
import pandas as pd

SNAPSHOT_PATH = pathlib.Path(__file__).parent / "snapshots" / "screener_snapshot.json"

# Ticker universe, tagged by country and currency.
# US caps are already in USD. SE Asia caps are in local currency
# and get converted before any filtering happens.
UNIVERSE = {
    "DE":   ("United States", "USD"), "HON": ("United States", "USD"),
    "ROK":  ("United States", "USD"), "PWR": ("United States", "USD"),
    "FTV":  ("United States", "USD"), "TDY": ("United States", "USD"),
    "AME":  ("United States", "USD"), "PEP": ("United States", "USD"),
    "LULU": ("United States", "USD"), "YUM": ("United States", "USD"),
    "EL":   ("United States", "USD"), "DXCM": ("United States", "USD"),
    "ZBH":  ("United States", "USD"), "STE": ("United States", "USD"),
    "WAT":  ("United States", "USD"), "AJG": ("United States", "USD"),
    "RJF":  ("United States", "USD"), "SEIC": ("United States", "USD"),
    "EQT":  ("United States", "USD"), "AVY": ("United States", "USD"),

    "BBCA.JK": ("Indonesia", "IDR"), "TLKM.JK": ("Indonesia", "IDR"),
    "ASII.JK": ("Indonesia", "IDR"), "UNVR.JK": ("Indonesia", "IDR"),
    "ICBP.JK": ("Indonesia", "IDR"), "PTBA.JK": ("Indonesia", "IDR"),
    "AKRA.JK": ("Indonesia", "IDR"), "TOWR.JK": ("Indonesia", "IDR"),

    "D05.SI": ("Singapore", "SGD"), "O39.SI": ("Singapore", "SGD"),
    "U11.SI": ("Singapore", "SGD"), "C6L.SI": ("Singapore", "SGD"),

    "1155.KL": ("Malaysia", "MYR"), "5225.KL": ("Malaysia", "MYR"),
    "6012.KL": ("Malaysia", "MYR"),

    "PTT.BK": ("Thailand", "THB"), "CPALL.BK": ("Thailand", "THB"),
    "AOT.BK": ("Thailand", "THB"),
}

# Fewer live rows than this means Yahoo is blocking us, not that the market changed.
MIN_LIVE_ROWS = len(UNIVERSE) // 2

# Potential acquirers for crypto/fintech targets: ticker -> (segment, balance sheet type).
# "bank_broker" cash includes client and deposit funding, so it can't be read as
# money available for a deal. BNY trades as BNY on Yahoo (formerly BK).
BUYER_UNIVERSE = {
    "COIN": ("Crypto-native", "corporate"),
    "HOOD": ("Retail broker", "bank_broker"),
    "SCHW": ("Retail broker", "bank_broker"),
    "IBKR": ("Retail broker", "bank_broker"),
    "CME":  ("Exchange", "corporate"),
    "ICE":  ("Exchange", "corporate"),
    "PYPL": ("Payments", "corporate"),
    "XYZ":  ("Payments", "corporate"),
    "MA":   ("Payments", "corporate"),
    "STT":  ("Custody bank", "bank_broker"),
    "NTRS": ("Custody bank", "bank_broker"),
    "BNY":  ("Custody bank", "bank_broker"),
    "JPM":  ("Global bank", "bank_broker"),
    "GS":   ("Global bank", "bank_broker"),
    "BLK":  ("Asset manager", "corporate"),
}


@st.cache_data(ttl=300)
def get_fx_rate(currency):
    """USD per 1 unit of local currency. USD itself is 1.0 (no conversion needed)."""
    if currency == "USD":
        return 1.0
    try:
        pair = yf.Ticker(f"USD{currency}=X")
        rate = pair.info.get("regularMarketPrice")
        return 1 / rate if rate else None
    except Exception:
        return None


@st.cache_data(ttl=300)
def get_company_data(ticker, country, currency):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return {
            "Ticker": ticker,
            "Name": info.get("longName"),
            "Country": country,
            "Sector": info.get("sector"),
            "Market Cap (local)": info.get("marketCap"),
            "Currency": currency,
            "Total Revenue (local)": info.get("totalRevenue"),
            "EV/EBITDA": info.get("enterpriseToEbitda"),
            "Revenue Growth (%)": info.get("revenueGrowth"),
            "Profit Margin (%)": info.get("profitMargins"),
            "Debt/Equity": info.get("debtToEquity"),
            "Current Price": info.get("currentPrice"),
        }
    except Exception:
        return None


def apply_filters(df, market_cap_range=None, max_ev_ebitda=None, min_revenue_growth=None,
                  min_profit_margin=None, max_debt_equity=None, countries=None, sectors=None):
    """Shared by the sidebar and the agent. A None filter is skipped. Market cap range is in $B."""
    filtered = df
    if market_cap_range is not None:
        filtered = filtered[
            (filtered["Market Cap"] >= market_cap_range[0] * 1_000_000_000) &
            (filtered["Market Cap"] <= market_cap_range[1] * 1_000_000_000)
        ]
    if max_ev_ebitda is not None:
        filtered = filtered[filtered["EV/EBITDA"] <= max_ev_ebitda]
    if min_revenue_growth is not None:
        filtered = filtered[filtered["Revenue Growth (%)"] >= min_revenue_growth]
    if min_profit_margin is not None:
        filtered = filtered[filtered["Profit Margin (%)"] >= min_profit_margin]
    if max_debt_equity is not None:
        filtered = filtered[filtered["Debt/Equity"] <= max_debt_equity]
    if countries:
        filtered = filtered[filtered["Country"].isin(countries)]
    if sectors:
        filtered = filtered[filtered["Sector"].isin(sectors)]
    return filtered


@st.cache_data(ttl=300)
def load_buyers():
    """Buyer universe without load_data's dropna: most banks and brokers have no EV/EBITDA."""
    records = [get_company_data(t, "United States", "USD") for t in BUYER_UNIVERSE]
    df = _build_frame([r for r in records if r is not None])
    if df.empty:
        return df
    df["Segment"] = df["Ticker"].map(lambda t: BUYER_UNIVERSE[t][0])
    df["Balance Sheet"] = df["Ticker"].map(lambda t: BUYER_UNIVERSE[t][1])
    return df.dropna(subset=["Market Cap"])


@st.cache_data(ttl=300)
def load_data(universe):
    records = [get_company_data(t, c, cur) for t, (c, cur) in universe.items()]
    records = [r for r in records if r is not None]
    df = _build_frame(records)
    if df.empty:
        return df
    return df.dropna(subset=["Market Cap", "EV/EBITDA", "Revenue Growth (%)"])


def _build_frame(records):
    if not records:
        # yfinance returned nothing for every ticker — likely a temporary
        # block/rate-limit on this server's IP. Return an empty, correctly
        # shaped DataFrame so the app shows a clear message instead of crashing.
        return pd.DataFrame(columns=[
            "Ticker", "Name", "Country", "Sector", "Market Cap (local)",
            "Currency", "Total Revenue (local)", "EV/EBITDA", "Revenue Growth (%)", "Profit Margin (%)",
            "Debt/Equity", "Current Price", "FX Rate", "Market Cap", "Total Revenue"
        ])

    df = pd.DataFrame(records)

    fx_rates = {cur: get_fx_rate(cur) for cur in df["Currency"].unique()}
    df["FX Rate"] = df["Currency"].map(fx_rates)
    df["Market Cap"] = df["Market Cap (local)"] * df["FX Rate"]
    df["Total Revenue"] = df["Total Revenue (local)"] * df["FX Rate"]

    df["Revenue Growth (%)"] = df["Revenue Growth (%)"] * 100
    df["Profit Margin (%)"] = df["Profit Margin (%)"] * 100
    return df


def save_snapshot(df, path=SNAPSHOT_PATH):
    path.parent.mkdir(exist_ok=True)
    rows = json.loads(df.to_json(orient="records"))
    payload = {"as_of": datetime.date.today().isoformat(), "rows": rows}
    path.write_text(json.dumps(payload, indent=1) + "\n")


def load_snapshot(path=SNAPSHOT_PATH):
    """Returns (DataFrame, as_of date string), or an empty frame if the file is missing or unreadable."""
    try:
        payload = json.loads(path.read_text())
        return pd.DataFrame(payload["rows"]), payload["as_of"]
    except (OSError, ValueError, KeyError):
        return pd.DataFrame(), None


def load_with_fallback(universe):
    """Live data when Yahoo responds, otherwise the saved snapshot. A date in the result means saved data."""
    live = load_data(universe)
    if len(live) >= MIN_LIVE_ROWS:
        return live, None
    saved, as_of = load_snapshot()
    if saved.empty:
        return live, None
    return saved, as_of
