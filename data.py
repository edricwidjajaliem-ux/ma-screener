"""
Ticker universe and market data pulls for the M&A screener.
Handles currency conversion since SE Asia market caps come back
in local currency, not USD.
"""

import streamlit as st
import yfinance as yf
import pandas as pd

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
            "EV/EBITDA": info.get("enterpriseToEbitda"),
            "Revenue Growth (%)": info.get("revenueGrowth"),
            "Profit Margin (%)": info.get("profitMargins"),
            "Debt/Equity": info.get("debtToEquity"),
            "Current Price": info.get("currentPrice"),
        }
    except Exception:
        return None


@st.cache_data(ttl=300)
def load_data(universe):
    records = [get_company_data(t, c, cur) for t, (c, cur) in universe.items()]
    records = [r for r in records if r is not None]

    if not records:
        # yfinance returned nothing for every ticker — likely a temporary
        # block/rate-limit on this server's IP. Return an empty, correctly
        # shaped DataFrame so the app shows a clear message instead of crashing.
        return pd.DataFrame(columns=[
            "Ticker", "Name", "Country", "Sector", "Market Cap (local)",
            "Currency", "EV/EBITDA", "Revenue Growth (%)", "Profit Margin (%)",
            "Debt/Equity", "Current Price", "FX Rate", "Market Cap"
        ])

    df = pd.DataFrame(records)

    fx_rates = {cur: get_fx_rate(cur) for cur in df["Currency"].unique()}
    df["FX Rate"] = df["Currency"].map(fx_rates)
    df["Market Cap"] = df["Market Cap (local)"] * df["FX Rate"]

    df["Revenue Growth (%)"] = df["Revenue Growth (%)"] * 100
    df["Profit Margin (%)"] = df["Profit Margin (%)"] * 100
    df = df.dropna(subset=["Market Cap", "EV/EBITDA", "Revenue Growth (%)"])
    return df
