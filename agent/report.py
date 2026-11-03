"""Renders the buyer memo in plain Python, so table figures can only come from tool results."""

import datetime

from agent.schemas import AbilityToPay, BuyerResult, RunResult

NA = "not available"
FACTOR_LABELS = {
    "digital_asset_activity": "Digital asset activity",
    "target_line_activity": "Activity in target's line",
    "stated_priority": "Stated priority",
    "related_deal": "Related deal",
    "clear_obstacle": "Clear obstacle",
}


def money(value: float | None) -> str:
    if value is None:
        return NA
    for scale, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= scale:
            return f"${value / scale:,.1f}".removesuffix(".0") + suffix
    return f"${value:,.0f}"


def _pct_range(low: float, high: float) -> str:
    """One decimal normally, two below 1% so small deals don't read as 0.0%."""
    def shown(value: float, places: int) -> str:
        return "<0.01%" if value < 0.01 else f"{value:.{places}f}%"
    places = 2 if low < 1 else 1
    return f"{shown(low, places)}-{shown(high, places)}"


def pay_summary(buyer: BuyerResult) -> str:
    pay = buyer.ability_to_pay
    if pay is None or pay.basis == NA:
        return NA
    summary = f"{_pct_range(pay.pct_market_cap_low, pay.pct_market_cap_high)} of mkt cap"
    if pay.basis == "cash_coverage":
        summary += f"; cash covers {pay.cash_coverage_high:.1f}x-{pay.cash_coverage_low:.1f}x"
    return summary


def pay_summary_text(pay: AbilityToPay) -> str:
    """The sentence the model is told to copy, so ratios keep their units."""
    if pay.basis == NA:
        return NA
    low = "under 0.01" if pay.pct_market_cap_low < 0.01 else pay.pct_market_cap_low
    high = "under 0.01" if pay.pct_market_cap_high < 0.01 else pay.pct_market_cap_high
    text = f"A {money(pay.deal_low)} to {money(pay.deal_high)} deal is {low}% to {high}% of market cap"
    if pay.basis == "cash_coverage":
        text += (f"; reported cash covers {pay.cash_coverage_low}x of the low end and "
                 f"{pay.cash_coverage_high}x of the high end")
    return text + "."


def _clean(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def buyer_rows(buyers: list[BuyerResult]) -> list[dict]:
    rows = []
    for rank, buyer in enumerate(buyers, 1):
        fin = buyer.financials
        cash = money(fin.get("cash"))
        if fin.get("cash_note") and fin.get("cash") is not None:
            cash += "*"
        rows.append({
            "#": rank,
            "Buyer": f"{_clean(buyer.name)} ({buyer.ticker})",
            "Segment": buyer.segment,
            "Fit (1-5)": buyer.assessment.fit_score if buyer.assessment else buyer.status,
            "Latest filing": buyer.latest_filing,
            "Mkt cap": money(fin.get("market_cap")),
            "Cash": cash,
            "Debt": money(fin.get("total_debt")),
            "Revenue": money(fin.get("revenue")),
            "EV": "n.m." if fin.get("enterprise_value_note") else money(fin.get("enterprise_value")),
            "Ability to pay": pay_summary(buyer),
        })
    return rows


def buyer_table(buyers: list[BuyerResult]) -> str:
    rows = buyer_rows(buyers)
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
    lines += ["| " + " | ".join(str(value) for value in row.values()) + " |" for row in rows]
    return "\n".join(lines)


def _source_line(source: dict) -> str:
    if not source["url"].startswith("http"):
        return source["citation"]
    line = f"[{source['citation']}]({source['url']})"
    if source.get("exhibit_url"):
        line += f" and its [annual report exhibit]({source['exhibit_url']})"
    return line


def buyer_detail(rank: int, buyer: BuyerResult) -> str:
    lines = [f"### {rank}. {buyer.name} ({buyer.ticker})"]
    if buyer.assessment is None:
        lines.append(f"Assessment {buyer.status}: {buyer.error or NA}")
        return "\n\n".join(lines)
    a = buyer.assessment
    lines.append(f"**Fit: {a.fit_score}/5.** {a.rationale}")
    lines.append(f"**Strategic gap addressed:** {a.strategic_gap_addressed}")
    pay = buyer.ability_to_pay
    pay_note = f" {pay.note}." if pay and pay.note else ""
    lines.append(f"**Ability to pay:** {pay_summary(buyer)}.{pay_note}")
    lines.append("**Key risks:**\n" + "\n".join(f"- {risk}" for risk in a.key_risks))
    lines.append("**Fit factors (score calculated by code):** " + "; ".join(
        f"{label}: {'yes' if getattr(a, factor) else 'no'}" for factor, label in FACTOR_LABELS.items()))
    if a.evidence:
        lines.append("**Evidence (each quote checked word for word against the filing):**\n" + "\n".join(
            f'- {FACTOR_LABELS[item.supports]}: "{_clean(item.quote)}" ({item.citation})' for item in a.evidence))
    sources = [_source_line(source) for source in buyer.sources]
    lines.append("**Sources:**\n" + ("\n".join(f"- {source}" for source in sources) or f"- {NA}"))
    if buyer.unverified_numbers:
        lines.append("**Check failed. Verify these before use:**\n"
                     + "\n".join(f"- {_clean(problem)}" for problem in buyer.unverified_numbers))
    return "\n\n".join(lines)


def _data_notes(buyers: list[BuyerResult]) -> list[str]:
    notes = []
    for buyer in buyers:
        fin = buyer.financials
        if fin.get("debt_to_equity_check") == "mismatch":
            notes.append(f"{buyer.ticker}: Yahoo debt/equity ({fin.get('yahoo_debt_to_equity_raw')}) does not match "
                         f"the balance sheet recomputation ({fin.get('debt_to_equity_recomputed')}x).")
    return notes


def render_memo(run: RunResult) -> str:
    today = datetime.date.today().strftime("%B %d, %Y")
    deal = (f"{money(run.deal_low)} to {money(run.deal_high)}, an assumption entered by the user and not a valuation"
            if run.deal_low and run.deal_high else NA)
    parts = []
    if run.dry_run:
        parts.append("> **DRY RUN. Fictional fixture companies and figures, not real data.**")
    parts += [
        "# Buyer Universe Memo",
        f"**Target:** {run.target}  \n**Deal size:** {deal}  \n**Date:** {today}  \n**Model:** {run.model}",
        "*Screened does not mean confirmed. This is a first-pass map built from public filings and market data. "
        "It is not evidence that any company is interested in this target, and it does not replace diligence.*",
        "## Buyer Universe",
    ]
    if run.shortlist_reasoning:
        parts.append(run.shortlist_reasoning)
    if not run.buyers:
        parts.append("No buyers were assessed in this run.")
    else:
        parts.append(buyer_table(run.buyers))
        parts.append("n.m. = not meaningful. * = reported cash includes client and deposit funding, so it is not "
                     "deal capacity. Ranked by fit score, then by deal size relative to market cap.")
        parts.append("## Buyer Detail")
        parts += [buyer_detail(rank, buyer) for rank, buyer in enumerate(run.buyers, 1)]

    parts.append("## Scope and Limitations")
    limits = [
        "Public US buyers only. Private acquirers such as Ripple, Stripe, Kraken and Fidelity can be among the most "
        "relevant buyers for a crypto target, and they are not covered because they have no EDGAR filings or market data.",
        "Figures in the table are filled by code from Yahoo Finance. Figures in the text passed an automated check "
        "that they appear in a tool result, which does not prove they were interpreted correctly.",
        "Sources are built by code from filings actually retrieved, and quotes were checked word for word against "
        "them. That shows the words are in the filing, not that the inference drawn from them is right.",
        "Filing text comes from each buyer's latest 10-K and 10-Q. Events after the date in the Latest filing column "
        "are not captured, so check recent news before relying on any buyer's status.",
        "Code calculates fit scores from yes/no factors the model answers from the filings. Those answers are still "
        "model judgment, so use the scores to sort, not as precise ratings.",
        *_data_notes(run.buyers),
    ]
    parts.append("\n".join(f"- {limit}" for limit in limits))

    cost = NA if run.cost_usd is None else f"${run.cost_usd:.4f}"
    parts.append(f"*Run {run.run_id}. Tokens: {run.input_tokens:,} input, {run.cache_write_tokens:,} cache write, "
                 f"{run.cache_read_tokens:,} cache read, {run.output_tokens:,} output. Estimated cost: {cost}.*")
    return "\n\n".join(parts) + "\n"
