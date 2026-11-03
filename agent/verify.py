"""Number check: every figure in the model's text must trace back to a tool result."""

import re

NUMBER = re.compile(
    r"(?<![\w.,])(?P<dollar>\$)?(?P<whole>\d{1,3}(?:,\d{3})+|\d+)(?P<decimal>\.\d+)?"
    r"\s*(?P<unit>%|percent\b|x\b|trillion\b|billion\b|million\b|thousand\b|[TBMK]\b)?"
)
SCALES = {"trillion": 1e12, "T": 1e12, "billion": 1e9, "B": 1e9, "million": 1e6, "M": 1e6,
          "thousand": 1e3, "K": 1e3}


def _parse(text: str) -> list[dict]:
    claims = []
    for match in NUMBER.finditer(text):
        decimal = match["decimal"] or ""
        value = float(match["whole"].replace(",", "") + decimal)
        claims.append({
            "text": match.group(0).strip(),
            "value": value,
            "places": len(decimal) - 1 if decimal else 0,
            "unit": match["unit"],
            "dollar": bool(match["dollar"]),
        })
    return claims


def _is_financial_figure(claim: dict) -> bool:
    """Bare small integers and years ("3 segments", "10-K", "2025") aren't treated as figures."""
    if claim["dollar"] or claim["unit"] or claim["places"]:
        return True
    return claim["value"] >= 100 and not 1900 <= claim["value"] <= 2100


def ledger_values(tool_result: str) -> set[float]:
    """Every number in a tool result, also scaled for "in thousands"/"in millions" tables and percents."""
    values = set()
    # Results are JSON, so a line break before a figure is a literal \n that would hide it from the regex.
    for claim in _parse(tool_result.replace("\\n", " ")):
        value = claim["value"] * SCALES.get(claim["unit"], 1)
        values.update({value, value * 1e3, value * 1e6, value * 100})
    return values


def unsupported_numbers(text: str, ledger: set[float]) -> list[str]:
    """Figures in text that don't match any ledger value at the precision they were written."""
    unsupported = []
    for claim in _parse(text):
        if not _is_financial_figure(claim):
            continue
        scale = SCALES.get(claim["unit"], 1)
        if not any(round(value / scale, claim["places"]) == claim["value"] for value in ledger):
            unsupported.append(claim["text"])
    return unsupported
