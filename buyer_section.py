"""The AI buyer analysis section, kept apart so it can render when market data is down."""

import os
import pathlib

import pandas as pd
import streamlit as st

from agent.agent import run_buyer_analysis
from agent.report import buyer_detail, buyer_rows, render_memo


def setting(name):
    return os.environ.get(name) or st.secrets.get(name, "")


def render_buyer_section():
    st.divider()
    st.subheader("AI Buyer Analysis")
    st.caption("Builds a ranked map of public buyers for a target, from SEC filings and market data. Screened does not mean confirmed: this is not evidence that any company is interested.")

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
