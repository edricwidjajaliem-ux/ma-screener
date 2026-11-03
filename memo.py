"""
Deal memo generation via the Claude API. Takes a screened company's
metrics and produces a preliminary M&A screening memo.
"""

import anthropic


def build_prompt(company_row):
    # Banks use book value metrics, since EV/EBITDA and debt/equity don't work when debt funds the business.
    is_book = company_row.get("Valuation Basis") == "book"
    if is_book:
        metrics = f"""Price/Book: {company_row['P/B']:.1f}x
Return on Equity: {company_row['ROE (%)']:.1f}%"""
        valuation = "based on the Price/Book multiple and Return on Equity, reason through a rough range"
        risk_note = (" For a bank or similar financial company, note as a general consideration that deals "
                     "need regulatory approval and that foreign ownership rules may apply, to be checked "
                     "for this market.")
    else:
        metrics = f"""EV/EBITDA: {company_row['EV/EBITDA']:.1f}x
Debt/Equity: {company_row['Debt/Equity']:.1f}"""
        valuation = "based on the EV/EBITDA multiple, reason through a rough range"
        risk_note = ""

    return f"""You are a junior M&A analyst preparing a preliminary
screening memo for the deal team. Write a concise, one-page memo for
the following company, based only on the data provided. Do not
invent facts not in the data.

Company: {company_row['Name']} ({company_row['Ticker']})
Sector: {company_row['Sector']}
Market Cap: ${company_row['Market Cap']/1e9:.1f}B
{metrics}
Revenue Growth: {company_row['Revenue Growth (%)']:.1f}%
Profit Margin: {company_row['Profit Margin (%)']:.1f}%
Current Price: {company_row['Current Price']:,.2f} {company_row['Currency']}

Structure the memo with these sections:
1. Company Overview (2-3 sentences)
2. Why It's an Attractive Acquisition Target (bullet points, tied to the metrics above)
3. Key Risks (bullet points){risk_note}
4. Preliminary Valuation Range ({valuation})

Keep it tight and professional — this is a screening memo, not a full report."""


def generate_deal_memo(company_row, api_key):
    """
    Takes a single filtered company's data and asks Claude to write
    a structured one-page deal memo. Kept to Sonnet-tier model —
    plenty capable for this, and cheap.
    """
    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": build_prompt(company_row)}]
    )
    return message.content[0].text
