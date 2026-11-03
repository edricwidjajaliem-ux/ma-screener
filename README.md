# US + SE Asia M&A Screener

**Live app:** [edric-ma-screener.streamlit.app](https://edric-ma-screener.streamlit.app)

A cross-border M&A screening tool covering the US, Indonesia, Singapore, Malaysia, and Thailand, with an AI-generated preliminary deal memo for any company that clears the filters, plus an AI agent that builds a ranked buyer map for a target.

## Why I built this

Most screening tools stop at the US or treat Southeast Asia as an afterthought. I wanted something that covers both — screening for companies with a financial profile common among acquisition candidates (reasonable valuation, growth, manageable leverage) across five markets, with currency-adjusted comparisons so a $2B Indonesian company and a $2B US company are actually being compared on equal footing.

## What it does

- Screens 35+ companies across five markets on market cap, total revenue, EV/EBITDA, revenue growth, profit margin, and debt/equity
- Converts every market cap and revenue figure to USD using live FX rates, since SE Asia figures come back in local currency
- Filters by geography and sector
- Generates a preliminary screening memo (company overview, why it's attractive, key risks, valuation range) via the Claude API for any company in the filtered results
- Exports results as CSV
- Falls back to a dated copy of the screener data when Yahoo Finance blocks the server, and labels it as saved data
- Builds a ranked buyer universe for a target description using an AI agent ([sample memo](docs/sample_buyer_memo.md))

## Screenshots

![Screener filters and results](screenshots/screener-view.png)
![Generated deal memo](screenshots/deal-memo.png)

## AI buyer analysis

Give it a target such as "mid-size crypto custody company, US-based" and a deal size assumption. It shortlists buyers from a curated universe of 15 public US companies, researches each one in SEC filings, scores strategic fit, and writes a sourced memo.

```mermaid
flowchart TD
    A[Target description + deal size assumption] --> B[Shortlist loop]
    B -->|get_candidates| C[BUYER_UNIVERSE + apply_filters]
    B --> D[Up to 10 tickers, checked against the universe]
    D --> E[One tool-use loop per buyer, max 12 iterations]
    E -->|get_financials| F[Yahoo Finance via yfinance]
    E -->|fetch_filing_excerpt| G[SEC EDGAR 10-K / 10-Q]
    E --> H{Final JSON passes the number check?}
    H -->|No, first failure| E
    H -->|Yes, or flagged after one correction| I[Python adds table figures and ability to pay]
    I --> J[Rank by fit, then deal size vs market cap]
    J --> K[Memo + Streamlit results]
    E -. every tool call and token count .-> L[runs/run-id.jsonl]
```

### How it's built

| File | What it does |
|---|---|
| `agent/agent.py` | The hand-written tool-use loop, token cap, retries, cost tracking, and CLI |
| `agent/tools.py` | `get_candidates`, `get_financials`, `fetch_filing_excerpt`, and the ability-to-pay math |
| `agent/verify.py` | The number check |
| `agent/schemas.py` | Pydantic models for the output |
| `agent/report.py` | Renders the memo in plain Python, with no LLM call |
| `agent/mock.py` | Scripted API client and fictional companies for `--dry-run` |

### Decisions

- **A separate buyer universe.** The screener's universe has almost no crypto or fintech buyers, and its target filters would remove them anyway. Most banks and brokers have no EV/EBITDA on Yahoo, and `load_data` drops those rows. Both paths share `apply_filters`.
- **Figures in the table never come from the model.** Python fills them directly from tool results.
- **A number check on the model's text.** Every figure must appear in a tool result at the precision written. A failure gets one correction, and if it still fails, the memo flags it in place.
- **Banks and brokers are treated differently.** Their reported cash includes client and deposit funding (JPM shows $1.88T), and Yahoo's EV can be negative (STT at -$58B). The memo marks EV as not meaningful and sizes the deal as a percent of market cap instead of cash coverage.
- **Debt/equity is recomputed from the balance sheet.** Yahoo's ratio mixes percent and ratio units, which caused a wrong figure in an earlier memo. Mismatches appear in the memo's limitations section.
- **Deal size comes from the user and is labeled as an assumption.** A text description contains no valuation, so without an input the memo says "not available".
- **The agent can't research the wrong company.** Each loop is bound to its ticker in code, because a live run tried BNY's old ticker (BK) from memory. A buyer with no filing text gets no fit score, so a data gap doesn't read as a poor fit.
- **Prompt caching** covers the tools and system prompt across buyers, plus the growing conversation within each loop. Buyers run one at a time so later buyers can read what the first one cached.
- **Off on the public app.** Live runs need `ENABLE_AGENT=true`, so visitors can't spend API credits. The public app shows the sample memo instead.

### Limitations

- **Public US buyers only.** Private acquirers such as Ripple, Stripe, Kraken and Fidelity can be among the most relevant buyers for a crypto target, and they have no EDGAR filings or market data. A hand-entered private-buyer list, clearly labeled as manual, is planned for v2.
- **The number check proves a figure exists in a tool result, not that it was used correctly.** A figure could match by coincidence or be misread. Bare integers under 100 and years aren't checked.
- **Citations are model-reported** and aren't independently verified yet.
- **Filings can be months old.** Recent deals and news aren't captured, because web search is off in v1.
- **Fit scores are model judgment.** In testing, scores for the same buyer moved by a point between runs and between models. Use them to sort, not as precise ratings.
- **Filing parsing is heuristic.** A section that can't be located returns "not available" rather than a guess. JPM's MD&A and BNY's risk factors currently can't be located as sections, though keyword-based passages still work for both.
- "Screened" does not mean a buyer is interested. This is a first-pass map, not a substitute for diligence.

## Tech stack

Python, Pandas, Streamlit, yFinance, Claude API (Anthropic), SEC EDGAR, Pydantic

## Limitations

- Saved data is only as fresh as the last refresh, and the app shows its date. Yahoo blocks shared Streamlit Cloud IPs at times, so the snapshot in `snapshots/` is refreshed from a local machine
- Data refreshes every 5 minutes; market fundamentals like EV/EBITDA don't move meaningfully within that window, but live share prices may lag slightly
- Philippines (PSE) is excluded — no reliable free data source found via yFinance
- The AI-generated memo is a first-pass draft based only on the metrics shown; it is not a substitute for real diligence, filings review, or comparable transaction analysis
- "Screened" means a company fits a common financial profile for acquisition candidates — not that it is an actual, confirmed target

## Running locally

```bash
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml`:
```toml
ANTHROPIC_API_KEY = "your-key-here"

# Only for AI buyer analysis
ENABLE_AGENT = "true"
SEC_USER_AGENT = "your-app-name your-email@example.com"
```

Then run:
```bash
streamlit run app.py
```

To update the saved data the app falls back on, run this and commit the result. It leaves the file alone if Yahoo returns too few companies.

```bash
python refresh_snapshot.py
```

### Running the agent from the command line

These read `ANTHROPIC_API_KEY` and `SEC_USER_AGENT` from your environment. `MODEL_NAME` defaults to `claude-haiku-5-5`, and `MAX_RUN_TOKENS` defaults to 1,000,000.

```bash
python -m agent.agent "mid-size crypto custody company, US-based" --deal-low 500 --deal-high 1500
```

To test without spending API credits, using a mock API and fictional companies:

```bash
python -m agent.agent "mid-size crypto custody company, US-based" --deal-low 500 --deal-high 1500 --dry-run
```

To run the tests:

```bash
python -m pytest
```
