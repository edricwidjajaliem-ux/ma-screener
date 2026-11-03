import streamlit as st
import datetime
import os
import pathlib
import pandas as pd

from agent.agent import run_buyer_analysis
from agent.report import buyer_detail, buyer_rows, render_memo
from data import UNIVERSE, apply_filters, load_data
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
filtered = apply_filters(
    df, market_cap_range, max_ev_ebitda, min_revenue_growth,
    min_profit_margin, max_debt_equity, countries, sectors
)

# Results table
st.subheader(f"Screened Results ({len(filtered)} companies)")

display_cols = ["Ticker", "Name", "Country", "Sector", "Market Cap", "Total Revenue",
                 "EV/EBITDA", "Revenue Growth (%)", "Profit Margin (%)",
                 "Debt/Equity", "Current Price", "Currency"]
display_df = filtered[display_cols].copy()
display_df["Market Cap"] = display_df["Market Cap"].apply(lambda x: f"${x/1e9:,.1f}B")
display_df["Total Revenue"] = display_df["Total Revenue"].apply(
    lambda x: f"${x/1e9:,.2f}B" if pd.notna(x) else "n/a"
)
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

# AI buyer analysis
st.divider()
st.subheader("AI Buyer Analysis")
st.caption("Builds a ranked map of public buyers for a target, from SEC filings and market data. Screened does not mean confirmed: this is not evidence that any company is interested.")


def setting(name):
    return os.environ.get(name) or st.secrets.get(name, "")


# Off unless ENABLE_AGENT is set, so visitors to the public URL can't spend API credits.
if str(setting("ENABLE_AGENT")).lower() != "true":
    st.info("Live runs are turned off on the public app. Here is a sample output from a real run.")
    sample = pathlib.Path("docs/sample_buyer_memo.md")
    if sample.exists():
        with st.expander("Sample buyer memo"):
            st.markdown(sample.read_text().replace("$", "\\$"))
else:
    target = st.text_input("Target description", placeholder="mid-size crypto custody company, US-based")
    col_low, col_high, col_buyers = st.columns(3)
    deal_low = col_low.number_input("Deal size assumption, low ($M)", min_value=0.0, value=None, step=100.0)
    deal_high = col_high.number_input("Deal size assumption, high ($M)", min_value=0.0, value=None, step=100.0)
    max_buyers = col_buyers.slider("Max buyers", min_value=3, max_value=15, value=10)
    dry_run = st.checkbox("Dry run (fictional data, no API credits)")

    if st.button("🤖 Run AI buyer analysis"):
        if not target:
            st.warning("Enter a target description first.")
        elif not dry_run and not (setting("ANTHROPIC_API_KEY") and setting("SEC_USER_AGENT")):
            st.warning("Set ANTHROPIC_API_KEY and SEC_USER_AGENT in your environment or Streamlit secrets.")
        else:
            for name in ("ANTHROPIC_API_KEY", "SEC_USER_AGENT", "MODEL_NAME"):
                if setting(name):
                    os.environ[name] = str(setting(name))
            col_tokens, col_cost = st.columns(2)
            tokens_metric, cost_metric = col_tokens.empty(), col_cost.empty()
            activity = st.empty()

            def show_progress(record, state):
                tokens_metric.metric("Tokens used", f"{state.total_tokens:,}")
                cost = "not available" if state.cost_usd is None else f"${state.cost_usd:.4f}"
                cost_metric.metric("Estimated cost", cost)
                if record["event"] == "tool_call":
                    activity.caption(f"{record['label']}: {record['tool']} {record['args']}")

            with st.spinner("Researching buyers..."):
                try:
                    st.session_state["buyer_run"] = run_buyer_analysis(
                        target,
                        deal_low=deal_low * 1e6 if deal_low else None,
                        deal_high=deal_high * 1e6 if deal_high else None,
                        max_buyers=max_buyers,
                        dry_run=dry_run,
                        on_event=show_progress,
                    )
                except Exception as e:
                    st.error(f"Buyer analysis failed: {e}")

    run = st.session_state.get("buyer_run")
    if run:
        cost = "not available" if run.cost_usd is None else f"${run.cost_usd:.4f}"
        total = run.input_tokens + run.cache_write_tokens + run.cache_read_tokens + run.output_tokens
        st.caption(f"Run {run.run_id}: {total:,} tokens, estimated cost {cost}, model {run.model}. Log: {run.log_path}")
        if run.dry_run:
            st.warning("Dry run: fictional companies and figures.")
        if not run.buyers:
            st.info("No buyers were assessed in this run.")
        else:
            st.dataframe(pd.DataFrame(buyer_rows(run.buyers)).astype(str), use_container_width=True, hide_index=True)
            st.caption("n.m. = not meaningful. * = reported cash includes client and deposit funding, so it is not deal capacity.")
            for rank, buyer in enumerate(run.buyers, 1):
                fit = f"fit {buyer.assessment.fit_score}/5" if buyer.assessment else buyer.status
                with st.expander(f"{rank}. {buyer.name} ({buyer.ticker}): {fit}"):
                    st.markdown(buyer_detail(rank, buyer).replace("$", "\\$"))
            st.download_button("📥 Download memo", data=render_memo(run), file_name=f"buyer_memo_{run.run_id}.md", mime="text/markdown")
