# CLAUDE.md — US + SE Asia M&A Screener

## What this is
Cross-border M&A screener (US, Indonesia, Singapore, Malaysia, Thailand) built by Edric, a UC Berkeley junior (Economics) recruiting for US investment banking. It is his main IB recruiting project, so he must be able to defend every decision in an interview. Explain the *why* of every change. Live app: https://edric-ma-screener.streamlit.app. Repo: https://github.com/edricwidjajaliem-ux/ma-screener

## Stack
Python 3.13, Streamlit, yfinance, pandas, anthropic SDK (model `claude-sonnet-4-6` for memos).

## Architecture
- `app.py`: Streamlit UI. Sidebar filters, results table, CSV export, deal memo section.
- `data.py`: `UNIVERSE` (ticker -> (country, currency), 38 tickers), `get_fx_rate`, `get_company_data`, `load_data`. All `@st.cache_data(ttl=300)`.
- `memo.py`: `generate_deal_memo(company_row, api_key)` single Claude call.
- Secrets: `ANTHROPIC_API_KEY` in `.streamlit/secrets.toml` locally (gitignored) and in Streamlit Cloud Secrets. Never hardcode or commit.

## Key decisions (do not re-litigate; execute)
- Mid-cap focus ($10B-$200B default), since mega-caps are unlikely targets.
- SE Asia market cap and revenue come back in local currency. Convert to USD via `USD{CCY}=X` before filtering.
- Philippines excluded: no reliable yfinance PSE coverage. Stated honestly in README.
- Total Revenue is display-only (no slider) on purpose.
- Wording: "screened" does not mean "confirmed target". Keep this caveat in the UI and README.
- Markdown `$` is escaped (`\$`) before `st.markdown`, or Streamlit renders LaTeX.

## Known gotchas
- yfinance `debtToEquity` has inconsistent units (percent vs ratio). It caused a wrong AI memo claim (AKRA showed 34.2x; real figure about 1.26x total liabilities/equity, verified against the annual report).
- `enterpriseToEbitda` is glitchy for some tickers (PGAS, ADRO, MEDC).
- Streamlit Cloud shared IPs can get rate-limited by Yahoo. `load_data` returns an empty DataFrame and `app.py` shows an error rather than crashing.
- `memo.py` still uses `$` for the price on non-USD tickers and the heading "Why It's an Attractive Acquisition Target". Both are known, minor, worth fixing.
- Use `pip3` on Mac.

## Preferences
- Direct, blunt, concise, structured.
- Minimal code comments (must not look AI-written). No docstring bloat.
- Explain each decision briefly so he can defend it.
- Keep him executing; do not let him spiral on "is it big enough".

## Agent roadmap (the current task)
Goal: add real AI agents to the screener, with a story he can defend in interviews.

1. **Memo verification agent (do first).** Replace the single-shot memo with a tool-using loop (Anthropic tool use). Tools: `get_balance_sheet(ticker)`, `get_income_statement(ticker)`, `get_peer_multiples(ticker)`. The agent recomputes D/E and EV/EBITDA from statements, flags any mismatch with the yfinance ratio, and writes the memo from verified numbers. This directly fixes the AKRA D/E problem and is the strongest interview story.
2. **Watch agent (phase 2).** Streamlit only runs when the page is visited, so "live updates" need a scheduler: GitHub Actions cron -> snapshot the screened set to a JSON file in the repo -> diff against the last snapshot -> Claude summarizes what entered or left the screen and why -> notify (email or Slack webhook). Needs storage and secrets in GitHub Actions.
3. Later: sector/peer comps agent; EDGAR filings retrieval for US names.

Build order: put the agent in its own module (`agent.py`), keep `memo.py` as fallback, and add a toggle in `app.py`. Log tool calls so the reasoning is visible in the UI.

## Not in the repo
AKRA memo PDF, AKRA annual report, old `ma_screener_app.py` and `ma_screener_starter.py` (obsolete).
