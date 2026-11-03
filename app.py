import streamlit as st
import datetime
import pandas as pd

from buyer_section import render_buyer_section
from data import UNIVERSE, apply_filters, load_with_fallback
from memo import generate_deal_memo

st.set_page_config(page_title="Cross-Border M&A Screener", layout="wide")
st.title("US + SE Asia M&A Screener")
st.caption("Screening US, Indonesia, Singapore, Malaysia, and Thailand companies for a financial profile common among acquisition candidates — not a confirmed target list.")

col_title, col_refresh = st.columns([4, 1])
with col_refresh:
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()

with st.spinner("Pulling live market data..."):
    df, snapshot_date = load_with_fallback(UNIVERSE)

if df.empty:
    st.error("Unable to pull market data right now (Yahoo Finance may be temporarily rate-limiting this server). Try clicking Refresh in a minute.")
    # The sample memo is a static file, so a Yahoo block shouldn't take it down too.
    render_buyer_section()
    st.stop()

if snapshot_date:
    st.warning(f"Live market data is unavailable (Yahoo Finance may be temporarily rate-limiting this server). Showing saved data from {snapshot_date}, so figures may be out of date. Try clicking Refresh in a minute.")
else:
    st.caption(f"Last updated: {datetime.datetime.now().strftime('%b %d, %Y %I:%M %p')} — market caps shown in USD. Data refreshes every 5 minutes, or click Refresh above.")

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

st.sidebar.caption("Banks and similar financials skip EV/EBITDA, margin and debt/equity. They use these two filters instead:")

max_price_to_book = st.sidebar.slider(
    "Max P/B (financials)", min_value=0.0, max_value=10.0, value=3.0, step=0.1
)

min_roe = st.sidebar.slider(
    "Min ROE (%) (financials)", min_value=0, max_value=30, value=10
)

sectors = st.sidebar.multiselect(
    "Sector (leave empty = all)",
    options=sorted(df["Sector"].dropna().unique().tolist())
)

# Apply filters
filtered = apply_filters(
    df, market_cap_range, max_ev_ebitda, min_revenue_growth,
    min_profit_margin, max_debt_equity, countries, sectors,
    max_price_to_book, min_roe
)

# Results table
st.subheader(f"Screened Results ({len(filtered)} companies)")

display_cols = ["Ticker", "Name", "Country", "Sector", "Market Cap", "Total Revenue",
                 "EV/EBITDA", "Revenue Growth (%)", "Profit Margin (%)",
                 "Debt/Equity", "P/B", "ROE (%)", "Current Price", "Currency", "Valuation Basis"]
display_df = filtered[display_cols].copy()
display_df["Market Cap"] = display_df["Market Cap"].apply(lambda x: f"${x/1e9:,.1f}B")
display_df["Total Revenue"] = display_df["Total Revenue"].apply(
    lambda x: f"${x/1e9:,.2f}B" if pd.notna(x) else "n/a"
)
display_df["EV/EBITDA"] = display_df["EV/EBITDA"].apply(lambda x: f"{x:.1f}x" if pd.notna(x) else "n.m.")
display_df["Revenue Growth (%)"] = display_df["Revenue Growth (%)"].apply(lambda x: f"{x:.1f}%")
display_df["Profit Margin (%)"] = display_df["Profit Margin (%)"].apply(lambda x: f"{x:.1f}%")
display_df["Debt/Equity"] = display_df.apply(
    lambda row: f"{row['Debt/Equity']:.1f}" if row["Valuation Basis"] != "book" and pd.notna(row["Debt/Equity"]) else "n.m.", axis=1
)
display_df["P/B"] = display_df["P/B"].apply(lambda x: f"{x:.1f}x" if pd.notna(x) else "n/a")
display_df["ROE (%)"] = display_df["ROE (%)"].apply(lambda x: f"{x:.1f}%" if pd.notna(x) else "n/a")
display_df["Current Price"] = display_df.apply(
    lambda row: f"{row['Current Price']:,.2f} {row['Currency']}", axis=1
)
display_df = display_df.drop(columns=["Currency", "Valuation Basis"])

st.dataframe(
    display_df,
    width="stretch",
    hide_index=True,
    column_config={
        "Name": st.column_config.TextColumn("Name", width="large"),
        "Ticker": st.column_config.TextColumn("Ticker", width="small"),
        "Country": st.column_config.TextColumn("Country", width="small"),
        "Sector": st.column_config.TextColumn("Sector", width="medium"),
    }
)

# Download button
csv = display_df.to_csv(index=False).encode("utf-8")
st.download_button(
    "📥 Download results as CSV",
    data=csv,
    file_name="ma_screener_results.csv",
    mime="text/csv"
)

# AI deal memo
st.divider()
st.subheader("AI Deal Memo Generator")
if snapshot_date:
    st.caption(f"Memos use the saved data from {snapshot_date}.")

# Read from Streamlit secrets — see .streamlit/secrets.toml locally, or Settings > Secrets on Streamlit Cloud
ANTHROPIC_API_KEY = st.secrets.get("ANTHROPIC_API_KEY", "")

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
                    memo_text = generate_deal_memo(company_row, ANTHROPIC_API_KEY)
                    memo_text = memo_text.replace("$", "\\$")
                    st.markdown(memo_text)
                except Exception as e:
                    st.error(f"Error generating memo: {e}")
else:
    st.info("No companies match your current filters — adjust the sliders above.")

render_buyer_section()
