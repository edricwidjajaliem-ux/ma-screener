"""Output models. The model writes Shortlist and BuyerAssessment; Python fills the rest."""

from typing import Literal

from pydantic import BaseModel, Field


class Shortlist(BaseModel):
    tickers: list[str] = Field(description="Buyers to research, highest priority first")
    reasoning: str = Field(description="1-2 sentences on how the shortlist was chosen")


Factor = Literal["digital_asset_activity", "target_line_activity", "stated_priority", "related_deal", "clear_obstacle"]


class Evidence(BaseModel):
    supports: Factor = Field(description="The factor this quote supports")
    citation: str = Field(description="The citation string of the filing result the quote came from")
    quote: str = Field(description="Copied word for word from that result, under 30 words, with no ellipses")


class BuyerAssessment(BaseModel):
    digital_asset_activity: bool = Field(description="The filing discloses digital asset activity by the buyer")
    target_line_activity: bool = Field(description="The filing discloses activity in the target's own line of business")
    stated_priority: bool = Field(description="The filing names the target's capability as a priority or gap")
    related_deal: bool = Field(description="The filing discloses an acquisition in the target's area")
    clear_obstacle: bool = Field(description="The filing states something that rules this deal out")
    rationale: str = Field(description="2-3 sentences")
    strategic_gap_addressed: str = Field(description="One sentence, or 'not available'")
    key_risks: list[str] = Field(description="2-4 short risks specific to this buyer")
    evidence: list[Evidence] = Field(description="At least one quote for each factor marked true")

    @property
    def fit_score(self) -> int:
        """Computed here, not by the model, so the same answers always give the same score."""
        if self.clear_obstacle:
            return 1
        if self.target_line_activity:
            return 5 if self.stated_priority and self.related_deal else 4
        return 3 if self.digital_asset_activity else 2

    def true_factors(self) -> set[str]:
        factors = ("digital_asset_activity", "target_line_activity", "stated_priority", "related_deal", "clear_obstacle")
        return {factor for factor in factors if getattr(self, factor)}


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
    latest_filing: str = "not available"
    sources: list[dict] = Field(default_factory=list)  # built by code from what was actually retrieved
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
