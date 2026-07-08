import streamlit as st
import datetime

from data import UNIVERSE, load_data
from memo import generate_deal_memo

st.set_page_config(page_title="Cross-Border M&A Screener", layout="wide")
st.title("US + SE Asia M&A Screener")
st.caption("Screening US, Indonesia, Singapore, Malaysia, and Thailand companies for a financial profile common among acquisition candidates — not a confirmed target list.")

col_title, col_refresh = st.columns([4, 1])
with col_refresh:
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()

with st.spinner("Pulling live market data..."):
    df = load_data(UNIVERSE)

if df.empty:
    st.error("Unable to pull market data right now (Yahoo Finance may be temporarily rate-limiting this server). Try clicking Refresh in a minute.")
    st.stop()

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
                 "Debt/Equity", "Current Price", "Currency"]
display_df = filtered[display_cols].copy()
display_df["Market Cap"] = display_df["Market Cap"].apply(lambda x: f"${x/1e9:,.1f}B")
display_df["EV/EBITDA"] = display_df["EV/EBITDA"].apply(lambda x: f"{x:.1f}x")
display_df["Revenue Growth (%)"] = display_df["Revenue Growth (%)"].apply(lambda x: f"{x:.1f}%")
display_df["Profit Margin (%)"] = display_df["Profit Margin (%)"].apply(lambda x: f"{x:.1f}%")
display_df["Debt/Equity"] = display_df["Debt/Equity"].apply(lambda x: f"{x:.1f}")
display_df["Current Price"] = display_df.apply(
    lambda row: f"{row['Current Price']:,.2f} {row['Currency']}", axis=1
)
display_df = display_df.drop(columns=["Currency"])

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
