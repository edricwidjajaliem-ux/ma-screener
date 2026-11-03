"""Output models. The model writes Shortlist and BuyerAssessment; Python fills the rest."""

from pydantic import BaseModel, Field


class Shortlist(BaseModel):
    tickers: list[str] = Field(description="Buyers to research, highest priority first")
    reasoning: str = Field(description="1-2 sentences on how the shortlist was chosen")


class BuyerAssessment(BaseModel):
    fit_score: int = Field(ge=1, le=5, description="Strategic fit, per the system prompt rubric")
    rationale: str = Field(description="2-3 sentences")
    strategic_gap_addressed: str = Field(description="One sentence, or 'not available'")
    key_risks: list[str] = Field(description="2-4 short risks specific to this buyer")
    sources: list[str] = Field(description="The citation strings of the tool results relied on")


class AbilityToPay(BaseModel):
    basis: str  # cash_coverage, pct_market_cap, or not available
    deal_low: float | None = None
    deal_high: float | None = None
    cash: float | None = None
    cash_coverage_low: float | None = None  # cash / deal_low
    cash_coverage_high: float | None = None  # cash / deal_high
    pct_market_cap_low: float | None = None
    pct_market_cap_high: float | None = None
    note: str = ""


class BuyerResult(BaseModel):
    ticker: str
    name: str = "not available"
    segment: str = "not available"
    status: str = "ok"  # ok, failed, or skipped
    error: str = ""
    assessment: BuyerAssessment | None = None
    ability_to_pay: AbilityToPay | None = None
    financials: dict = Field(default_factory=dict)
    unverified_numbers: list[str] = Field(default_factory=list)
    iterations: int = 0


class RunResult(BaseModel):
    run_id: str
    target: str
    model: str
    dry_run: bool = False
    deal_low: float | None = None
    deal_high: float | None = None
    shortlist_reasoning: str = ""
    buyers: list[BuyerResult] = Field(default_factory=list)
    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    log_path: str = ""
