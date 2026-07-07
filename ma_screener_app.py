import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

st.set_page_config(page_title="Cross-Border M&A Screener", layout="wide")
st.title("🔎 US + SE Asia M&A Screener")
st.caption("Screening potential acquisition targets across US, Indonesia, Singapore, Malaysia, and Thailand.")

# Ticker universe, tagged by country and currency.
# US caps are already in USD. SE Asia caps are in local currency
# and get converted below before any filtering happens.
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
tickers = list(UNIVERSE.keys())

# Data pull
@st.cache_data(ttl=86400)
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

@st.cache_data(ttl=86400)
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

@st.cache_data(ttl=86400)
def load_data(universe):
    records = [get_company_data(t, c, cur) for t, (c, cur) in universe.items()]
    records = [r for r in records if r is not None]
    df = pd.DataFrame(records)

    fx_rates = {cur: get_fx_rate(cur) for cur in df["Currency"].unique()}
    df["FX Rate"] = df["Currency"].map(fx_rates)
    df["Market Cap"] = df["Market Cap (local)"] * df["FX Rate"]

    df["Revenue Growth (%)"] = df["Revenue Growth (%)"] * 100
    df["Profit Margin (%)"] = df["Profit Margin (%)"] * 100
    df = df.dropna(subset=["Market Cap", "EV/EBITDA", "Revenue Growth (%)"])
    return df

col_title, col_refresh = st.columns([4, 1])
with col_refresh:
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()

with st.spinner("Pulling live market data..."):
    df = load_data(UNIVERSE)

st.caption(f"Last updated: {datetime.datetime.now().strftime('%b %d, %Y %I:%M %p')} — market caps shown in USD. Data auto-refreshes daily, or click Refresh above.")

# Sidebar filters
st.sidebar.header("Screening Filters")

countries = st.sidebar.multiselect(
    "Geography (leave empty = all)",
    options=sorted(df["Country"].unique().tolist())
)

market_cap_range = st.sidebar.slider(
    "Market Cap ($B)",
    min_value=0, max_value=250,
    value=(10, 200), step=5
)

max_ev_ebitda = st.sidebar.slider(
    "Max EV/EBITDA", min_value=0, max_value=50, value=20
)

min_revenue_growth = st.sidebar.slider(
    "Min Revenue Growth (%)", min_value=-20, max_value=50, value=5
)

min_profit_margin = st.sidebar.slider(
    "Min Profit Margin (%)", min_value=-20, max_value=50, value=10
)

max_debt_equity = st.sidebar.slider(
    "Max Debt/Equity", min_value=0, max_value=400, value=150
)

sectors = st.sidebar.multiselect(
    "Sector (leave empty = all)",
    options=sorted(df["Sector"].dropna().unique().tolist())
)

# Apply filters
filtered = df[
    (df["Market Cap"] >= market_cap_range[0] * 1_000_000_000) &
    (df["Market Cap"] <= market_cap_range[1] * 1_000_000_000) &
    (df["EV/EBITDA"] <= max_ev_ebitda) &
    (df["Revenue Growth (%)"] >= min_revenue_growth) &
    (df["Profit Margin (%)"] >= min_profit_margin) &
    (df["Debt/Equity"] <= max_debt_equity)
]

if countries:
    filtered = filtered[filtered["Country"].isin(countries)]

if sectors:
    filtered = filtered[filtered["Sector"].isin(sectors)]

# Results table
st.subheader(f"Screened Results ({len(filtered)} companies)")

display_cols = ["Ticker", "Name", "Country", "Sector", "Market Cap",
                 "EV/EBITDA", "Revenue Growth (%)", "Profit Margin (%)",
                 "Debt/Equity", "Current Price"]
display_df = filtered[display_cols].copy()
display_df["Market Cap"] = display_df["Market Cap"].apply(lambda x: f"${x/1e9:,.1f}B")
display_df["EV/EBITDA"] = display_df["EV/EBITDA"].apply(lambda x: f"{x:.1f}x")
display_df["Revenue Growth (%)"] = display_df["Revenue Growth (%)"].apply(lambda x: f"{x:.1f}%")
display_df["Profit Margin (%)"] = display_df["Profit Margin (%)"].apply(lambda x: f"{x:.1f}%")
display_df["Debt/Equity"] = display_df["Debt/Equity"].apply(lambda x: f"{x:.1f}")
display_df["Current Price"] = display_df["Current Price"].apply(lambda x: f"{x:,.2f}")

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Name": st.column_config.TextColumn("Name", width="large"),
        "Ticker": st.column_config.TextColumn("Ticker", width="small"),
        "Country": st.column_config.TextColumn("Country", width="small"),
        "Sector": st.column_config.TextColumn("Sector", width="medium"),
    }
)

# Download button
csv = filtered.to_csv(index=False).encode("utf-8")
st.download_button(
    "📥 Download results as CSV",
    data=csv,
    file_name="ma_screener_results.csv",
    mime="text/csv"
)

# AI deal memo
st.divider()
st.subheader("AI Deal Memo Generator")

import anthropic

# Read from Streamlit secrets — see .streamlit/secrets.toml locally, or Settings > Secrets on Streamlit Cloud
ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", "")

def generate_deal_memo(company_row):
    """
    Takes a single filtered company's data and asks Claude to write
    a structured one-page deal memo. Kept to Sonnet-tier model —
    plenty capable for this, and cheap.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are a junior M&A analyst preparing a preliminary
screening memo for the deal team. Write a concise, one-page memo for
the following company, based only on the data provided. Do not
invent facts not in the data.

Company: {company_row['Name']} ({company_row['Ticker']})
Sector: {company_row['Sector']}
Market Cap: ${company_row['Market Cap']/1e9:.1f}B
EV/EBITDA: {company_row['EV/EBITDA']:.1f}x
Revenue Growth: {company_row['Revenue Growth (%)']:.1f}%
Profit Margin: {company_row['Profit Margin (%)']:.1f}%
Debt/Equity: {company_row['Debt/Equity']:.1f}
Current Price: ${company_row['Current Price']:.2f}

Structure the memo with these sections:
1. Company Overview (2-3 sentences)
2. Why It's an Attractive Acquisition Target (bullet points, tied to the metrics above)
3. Key Risks (bullet points)
4. Preliminary Valuation Range (based on the EV/EBITDA multiple, reason through a rough range)

Keep it tight and professional — this is a screening memo, not a full report."""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text

if not filtered.empty:
    selected_ticker = st.selectbox(
        "Select a company for a deal memo:",
        filtered["Ticker"].tolist()
    )

    if st.button("📝 Generate Deal Memo"):
        if not ANTHROPIC_API_KEY:
            st.warning("No API key found. Add ANTHROPIC_API_KEY to your Streamlit secrets to enable this.")
        else:
            company_row = filtered[filtered["Ticker"] == selected_ticker].iloc[0]
            with st.spinner(f"Generating memo for {selected_ticker}..."):
                try:
                    memo_text = generate_deal_memo(company_row)
                    memo_text = memo_text.replace("$", "\\$")
                    st.markdown(memo_text)
                except Exception as e:
                    st.error(f"Error generating memo: {e}")
else:
    st.info("No companies match your current filters — adjust the sliders above.")
