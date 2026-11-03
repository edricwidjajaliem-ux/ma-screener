# CLAUDE.md — US + SE Asia M&A Screener

## What this is
Cross-border M&A screener (US, Indonesia, Singapore, Malaysia, Thailand) built by Edric, a UC Berkeley junior (Economics) recruiting for US investment banking. It is his main IB recruiting project, so he must be able to defend every decision in an interview. Explain the *why* of every change. Live app: https://edric-ma-screener.streamlit.app. Repo: https://github.com/edricwidjajaliem-ux/ma-screener

## Stack
Python 3.13, Streamlit, yfinance, pandas, anthropic SDK (model `claude-sonnet-4-6` for memos).

## Architecture
- `app.py`: Streamlit UI. Sidebar filters, results table, CSV export, deal memo section.
- `data.py`: `UNIVERSE` (ticker -> (country, currency), 38 tickers), `get_fx_rate`, `get_company_data`, `load_data`. All `@st.cache_data(ttl=300)`.
- `memo.py`: `generate_deal_memo(company_row, api_key)` single Claude call.
- `agent/`: buyer analysis. `agent.py` (loop, caps, CLI), `tools.py`, `verify.py` (number check), `schemas.py`, `report.py` (memo, no LLM), `mock.py` (dry run). `data.py` also holds `BUYER_UNIVERSE`, `load_buyers`, and `apply_filters`.
- Secrets: `ANTHROPIC_API_KEY` in `.streamlit/secrets.toml` locally (gitignored) and in Streamlit Cloud Secrets. Never hardcode or commit. The agent also reads `SEC_USER_AGENT`, `MODEL_NAME` (default `claude-haiku-5-5`), `MAX_RUN_TOKENS`, and `ENABLE_AGENT` (leave off on the public app).

## Key decisions (do not re-litigate; execute)
- Mid-cap focus ($10B-$200B default), since mega-caps are unlikely targets.
- SE Asia market cap and revenue come back in local currency. Convert to USD via `USD{CCY}=X` before filtering.
- Philippines excluded: no reliable yfinance PSE coverage. Stated honestly in README.
- Total Revenue is display-only (no slider) on purpose.
- Wording: "screened" does not mean "confirmed target". Keep this caveat in the UI and README.
- Markdown `$` is escaped (`\$`) before `st.markdown`, or Streamlit renders LaTeX.

## Known gotchas
- yfinance `debtToEquity` has inconsistent units (percent vs ratio). It caused a wrong AI memo claim (AKRA showed 34.2x; real figure about 1.26x total liabilities/equity, verified against the annual report).
- `get_financials` recomputes D/E from the balance sheet and flags mismatches with Yahoo's ratio. That is the current answer to the AKRA problem, for buyers only; the target memo in `memo.py` still uses Yahoo's ratio.
- `enterpriseToEbitda` is glitchy for some tickers (PGAS, ADRO, MEDC).
- Streamlit Cloud shared IPs can get rate-limited by Yahoo. `load_with_fallback` then uses `snapshots/screener_snapshot.json` and `app.py` shows its date. It also falls back below `MIN_LIVE_ROWS`, so a partial block can't silently shrink the screen. The error only shows if the snapshot is unusable too. Refresh locally with `python refresh_snapshot.py`, then commit. The buyer agent has no snapshot and needs live Yahoo data.
- `memo.py` still uses `$` for the price on non-USD tickers and the heading "Why It's an Attractive Acquisition Target". Both are known, minor, worth fixing.
- Yahoo's cash and EV aren't meaningful for banks and brokers (JPM cash $1.88T, STT EV -$58B). They are tagged `bank_broker` in `BUYER_UNIVERSE` and sized by % of market cap.
- BNY trades as `BNY` on Yahoo, not `BK`. The model recalled `BK` from memory, so buyer loops force the ticker in code.
- BNY keeps most 10-K content in an Exhibit 13 with an uninformative file name. `_annual_report_exhibit` finds it from the filing index.
- SEC EDGAR returns 403 without a contact email in the User-Agent.
- Haiku 5.5 costs 5x per request when a prompt is over 100k tokens. `request_cost` handles it; the largest prompt seen so far was about 27k.
- Use `pip3` on Mac.

## Preferences
- Direct, blunt, concise, structured.
- Minimal code comments (must not look AI-written). No docstring bloat.
- Explain each decision briefly so he can defend it.
- Keep him executing; do not let him spiral on "is it big enough".

## Agent roadmap
Goal: real AI agents in the screener, with a story he can defend in interviews.

1. **Buyer analysis agent (built).** `agent/`: target description -> ranked public buyer map with sourced memo. Python fills table figures, and a number check runs on the model's text. The D/E recompute and mismatch flag from the earlier memo verification plan live in `get_financials`.
2. **Next for buyers (v2).** Hand-entered private-buyer list (Ripple, Stripe, Kraken, Fidelity), clearly labeled as manual and not from filings. Citation verification, which was cut from v1. Optional `web_search`, off in v1.
3. **Memo verification for targets.** Apply the same D/E recompute to `memo.py`, keeping it as the fallback, so the AKRA-style error is fixed for screened targets too.
4. **Watch agent.** Streamlit only runs when the page is visited, so "live updates" need a scheduler: GitHub Actions cron -> snapshot the screened set to a JSON file in the repo -> diff against the last snapshot -> Claude summarizes what entered or left the screen and why -> notify (email or Slack webhook). Needs storage and secrets in GitHub Actions.
5. Later: sector/peer comps agent.

## Not in the repo
AKRA memo PDF, AKRA annual report, old `ma_screener_app.py` and `ma_screener_starter.py` (obsolete).
