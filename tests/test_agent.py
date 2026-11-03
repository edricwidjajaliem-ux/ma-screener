import json
from types import SimpleNamespace

import anthropic
import pytest

from agent import agent as agent_module
from agent.agent import (AgentError, BudgetExceeded, RunState, assess_buyer, rank_buyers, request_cost,
                         run_buyer_analysis, run_loop)
from agent.mock import FIXTURE_TOOLS, text_response, tool_response
from agent.report import pay_summary, pay_summary_text, render_memo
from agent.schemas import BuyerAssessment, BuyerResult
from agent.tools import FETCH_FILING_DEF, GET_FINANCIALS_DEF, ability_to_pay


class ScriptedClient:
    """Returns the given responses in order, or raises one if it's an exception."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


FACTORS = ("digital_asset_activity", "target_line_activity", "stated_priority", "related_deal", "clear_obstacle")
QUOTE = "is expanding its digital asset services"
CITATION = "AAA 10-Q fixture, section: digital_assets"


def assessment_json(rationale="The filing describes custody activity.", true=("digital_asset_activity",), evidence=None):
    if evidence is None:
        evidence = [{"supports": factor, "citation": CITATION, "quote": QUOTE} for factor in true]
    return json.dumps({**{factor: factor in true for factor in FACTORS}, "rationale": rationale,
                       "strategic_gap_addressed": "Adds custody.", "key_risks": ["Integration"], "evidence": evidence})


FETCH_10Q = {"ticker": "AAA", "section": "digital_assets", "form": "10-Q"}


@pytest.fixture
def state(tmp_path):
    return RunState(model="claude-haiku-5-5", max_tokens=1_000_000, log_path=tmp_path / "run.jsonl")


def log_events(state):
    return [json.loads(line) for line in state.log_path.read_text().splitlines()]


def loop(client, state, check=None, max_iterations=12):
    from agent.agent import _check_assessment
    return run_loop(client, state, "AAA", "system", "user", [GET_FINANCIALS_DEF, FETCH_FILING_DEF],
                    FIXTURE_TOOLS, (500e6, 1.5e9), BuyerAssessment, check or _check_assessment,
                    max_iterations=max_iterations)


def api_error(cls, status):
    return cls("error", response=SimpleNamespace(request=None, status_code=status, headers={}), body=None)


def test_loop_executes_tools_and_returns_validated_answer(state):
    client = ScriptedClient(tool_response("get_financials", {"ticker": "AAA"}), text_response(assessment_json()))
    parsed, iterations, flagged = loop(client, state)
    assert parsed.fit_score == 3 and iterations == 2 and flagged == []
    sent = client.calls[1]["messages"]
    assert sent[1]["role"] == "assistant"
    tool_result = sent[2]["content"][0]
    assert tool_result["type"] == "tool_result" and tool_result["tool_use_id"] == "toolu_mock"
    assert "deal_context" in tool_result["content"]


def test_loop_caches_tools_and_system_prompt(state):
    client = ScriptedClient(text_response(assessment_json()))
    loop(client, state)
    call = client.calls[0]
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["cache_control"] == {"type": "ephemeral"}


def test_loop_returns_tool_exception_to_model_as_error(state):
    tools = {"get_financials": lambda ticker: 1 / 0}
    client = ScriptedClient(tool_response("get_financials", {"ticker": "AAA"}), text_response(assessment_json()))
    run_loop(client, state, "AAA", "system", "user", [GET_FINANCIALS_DEF], tools, (None, None), BuyerAssessment)
    assert client.calls[1]["messages"][2]["content"][0]["is_error"] is True


def test_iteration_cap_forces_answer_then_fails(state):
    responses = [tool_response("get_financials", {"ticker": "AAA"}) for _ in range(3)]
    client = ScriptedClient(*responses)
    with pytest.raises(AgentError, match="3 iterations"):
        loop(client, state, max_iterations=3)
    assert len(client.calls) == 3
    assert client.calls[0]["tool_choice"] == {"type": "auto"}
    assert client.calls[2]["tool_choice"] == {"type": "none"}


def test_token_cap_stops_before_the_next_call(tmp_path):
    state = RunState(model="claude-haiku-5-5", max_tokens=100, log_path=tmp_path / "run.jsonl")
    state.input_tokens = 100
    client = ScriptedClient()
    with pytest.raises(BudgetExceeded):
        loop(client, state)
    assert client.calls == []


def test_fabricated_number_gets_one_correction(state):
    client = ScriptedClient(text_response(assessment_json("It paid $2.1 billion for a rival.")),
                            text_response(assessment_json("It has made related deals.")))
    parsed, iterations, flagged = loop(client, state)
    assert flagged == [] and iterations == 2
    assert "$2.1 billion" in client.calls[1]["messages"][2]["content"]
    assert any(e["event"] == "check_failed" for e in log_events(state))


def test_number_that_stays_unsupported_is_flagged_not_dropped(state):
    bad = assessment_json("It paid $2.1 billion for a rival.")
    client = ScriptedClient(text_response(bad), text_response(bad))
    parsed, _, flagged = loop(client, state)
    assert flagged == ["$2.1 billion"]
    assert parsed.fit_score == 3


def test_number_from_tool_result_passes(state):
    client = ScriptedClient(tool_response("get_financials", {"ticker": "AAA"}),
                            text_response(assessment_json("Cash of $5.0B and market cap of $40B.")))
    _, _, flagged = loop(client, state)
    assert flagged == []


def test_invalid_output_gets_correction_then_fails(state):
    client = ScriptedClient(text_response('{"fit_score": 9}'), text_response("not json"))
    with pytest.raises(AgentError, match="invalid output"):
        loop(client, state)


def test_refusal_is_an_agent_error(state):
    refusal = text_response("")
    refusal.stop_reason = "refusal"
    with pytest.raises(AgentError, match="refusal"):
        loop(ScriptedClient(refusal), state)


def test_rate_limit_becomes_failed_row_and_run_continues(state):
    client = ScriptedClient(api_error(anthropic.RateLimitError, 429))
    result = assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), FIXTURE_TOOLS)
    assert result.status == "failed"
    assert result.financials["market_cap"] == 40e9


def test_auth_error_stops_the_run(state):
    client = ScriptedClient(api_error(anthropic.AuthenticationError, 401))
    with pytest.raises(anthropic.AuthenticationError):
        assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), FIXTURE_TOOLS)


def test_table_financials_come_from_python_not_the_model(state):
    client = ScriptedClient(tool_response("fetch_filing_excerpt", FETCH_10Q), text_response(assessment_json()))
    result = assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), FIXTURE_TOOLS)
    assert result.financials == FIXTURE_TOOLS["get_financials"]("AAA")
    assert result.ability_to_pay.cash_coverage_low == 10.0


def test_every_tool_call_and_token_count_is_logged(state):
    client = ScriptedClient(tool_response("get_financials", {"ticker": "AAA"}), text_response(assessment_json()))
    loop(client, state)
    events = log_events(state)
    assert [e["event"] for e in events] == ["api_call", "tool_call", "api_call"]
    assert events[1]["tool"] == "get_financials" and "market_cap" in events[1]["result"]
    assert events[0]["tokens"]["output"] == 150


def test_haiku_long_prompt_tier_costs_five_times_more():
    short = request_cost("claude-haiku-5-5", {"input": 100_000, "write": 0, "read": 0, "output": 0})
    long = request_cost("claude-haiku-5-5", {"input": 100_001, "write": 0, "read": 0, "output": 0})
    assert short == pytest.approx(0.01)
    assert long == pytest.approx(0.05, rel=1e-3)


def test_unknown_model_cost_is_not_available():
    assert request_cost("some-new-model", {"input": 1, "write": 0, "read": 0, "output": 0}) is None


def json_assessment(true):
    return BuyerAssessment.model_validate_json(assessment_json(true=true))


def test_ranking_uses_fit_then_relative_size_with_failures_last():
    def buyer(ticker, fit, pct):
        true = {5: FACTORS[1:4], 4: ("target_line_activity",)}.get(fit, ())
        assessment = json_assessment(true) if fit else None
        return BuyerResult(ticker=ticker, assessment=assessment, ability_to_pay={"basis": "pct_market_cap", "pct_market_cap_high": pct})
    ranked = rank_buyers([buyer("C", None, 1.0), buyer("A", 4, 5.0), buyer("B", 4, 2.0), buyer("D", 5, 9.0)])
    assert [b.ticker for b in ranked] == ["D", "B", "A", "C"]


def test_dry_run_end_to_end_makes_a_watermarked_memo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    run = run_buyer_analysis("crypto custody", deal_low=500e6, deal_high=1.5e9, dry_run=True)
    assert [b.ticker for b in run.buyers] == ["BBB", "AAA", "CCC"]
    memo = render_memo(run)
    assert memo.startswith("> **DRY RUN.")
    assert "## Buyer Universe" in memo and "Fixture Custody Bank (BBB)" in memo
    assert "$100B*" in memo and "n.m." in memo


def test_shortlist_cannot_add_tickers_outside_the_tool_result(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    client = ScriptedClient(text_response(json.dumps({"tickers": ["FAKE", "AAA"], "reasoning": "Chosen."})),
                            tool_response("fetch_filing_excerpt", FETCH_10Q), text_response(assessment_json()))
    run = run_buyer_analysis("target", client=client, tools=FIXTURE_TOOLS)
    assert [b.ticker for b in run.buyers] == ["AAA"]


def test_memo_without_deal_size_says_not_available(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    memo = render_memo(run_buyer_analysis("crypto custody", dry_run=True))
    assert "**Deal size:** not available" in memo


def test_failed_buyer_and_unverified_numbers_show_in_memo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    run = run_buyer_analysis("crypto custody", deal_low=500e6, deal_high=1.5e9, dry_run=True)
    run.buyers[0].unverified_numbers = ["$2.1 billion"]
    run.buyers[1].assessment = None
    run.buyers[1].status, run.buyers[1].error = "failed", "API down"
    memo = render_memo(run)
    assert "Check failed" in memo and "$2.1 billion" in memo
    assert "Assessment failed: API down" in memo


def test_model_cannot_research_a_different_ticker(state):
    # Regression: a live run called BK from memory instead of BNY and got no data.
    seen = []
    tools = {**FIXTURE_TOOLS, "fetch_filing_excerpt": lambda **args: seen.append(args) or FIXTURE_TOOLS["fetch_filing_excerpt"](**args)}
    client = ScriptedClient(
        tool_response("fetch_filing_excerpt", {**FETCH_10Q, "ticker": "OLD"}),
        text_response(assessment_json()),
    )
    result = assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), tools)
    assert seen[0]["ticker"] == "AAA"
    assert result.status == "ok"


def test_no_filing_evidence_means_no_fit_score(state):
    client = ScriptedClient(
        tool_response("get_financials", {"ticker": "AAA"}),
        text_response(assessment_json(true=())),
        text_response(assessment_json(true=())),
    )
    result = assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), FIXTURE_TOOLS)
    assert result.status == "failed" and result.assessment is None
    assert "No filing text" in result.error


@pytest.mark.parametrize("text", ["the deal is 1.56x market cap", "0.19 to 0.57 of market cap"])
def test_market_cap_ratio_without_percent_gets_corrected(state, text):
    # Regression: both forms appeared in live memos, and 1.56% read as 1.56x is badly wrong.
    client = ScriptedClient(tool_response("get_financials", {"ticker": "AAA"}),
                            text_response(assessment_json(f"At 1.25%, {text}.")),
                            text_response(assessment_json("At 1.25% to 3.75% of market cap, it is small.")))
    _, iterations, flagged = loop(client, state)
    assert flagged == [] and iterations == 3


def test_deal_context_summary_states_units(state):
    client = ScriptedClient(tool_response("get_financials", {"ticker": "AAA"}), text_response(assessment_json()))
    loop(client, state)
    summary = json.loads(client.calls[1]["messages"][2]["content"][0]["content"])["deal_context"]["summary"]
    assert summary == ("A $500M to $1.5B deal is 1.25% to 3.75% of market cap; "
                       "reported cash covers 10.0x of the low end and 3.33x of the high end.")


@pytest.mark.parametrize("text", ["I did not review the liquidity section.", "The deal_context gives 1.25%."])
def test_internal_language_gets_corrected(state, text):
    client = ScriptedClient(tool_response("get_financials", {"ticker": "AAA"}),
                            text_response(assessment_json(text)),
                            text_response(assessment_json("The filing describes custody activity.")))
    _, iterations, flagged = loop(client, state)
    assert flagged == [] and iterations == 3


@pytest.mark.parametrize("true,score", [
    (("digital_asset_activity", "target_line_activity", "stated_priority", "related_deal", "clear_obstacle"), 1),
    (("target_line_activity", "stated_priority", "related_deal"), 5),
    (("target_line_activity", "stated_priority"), 4),
    (("target_line_activity",), 4),
    (("digital_asset_activity", "stated_priority", "related_deal"), 3),
    (("digital_asset_activity",), 3),
    ((), 2),
])
def test_fit_score_is_calculated_from_factors(true, score):
    assert json_assessment(true).fit_score == score


def run_buyer(state, *answers, first_tool=None):
    client = ScriptedClient(first_tool or tool_response("fetch_filing_excerpt", FETCH_10Q),
                            *[text_response(answer) for answer in answers])
    return assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), FIXTURE_TOOLS), client


def test_verified_quote_passes_and_sources_are_built_by_code(state):
    result, _ = run_buyer(state, assessment_json())
    assert result.status == "ok" and result.unverified_numbers == []
    assert result.sources[0] == {"citation": CITATION, "url": "fixture", "exhibit_url": ""}
    assert result.sources[1]["citation"] == "Fixture data, not real"
    assert result.latest_filing == "10-Q filed 2026-10-01"


def test_invented_quote_gets_a_correction(state):
    invented = [{"supports": "digital_asset_activity", "citation": CITATION, "quote": "we plan to buy a crypto custodian soon"}]
    result, client = run_buyer(state, assessment_json(evidence=invented), assessment_json())
    assert result.unverified_numbers == []
    assert "not word for word" in client.calls[2]["messages"][4]["content"]


def test_invented_quote_is_flagged_if_it_stays(state):
    invented = [{"supports": "digital_asset_activity", "citation": CITATION, "quote": "we plan to buy a crypto custodian soon"}]
    bad = assessment_json(evidence=invented)
    result, _ = run_buyer(state, bad, bad)
    assert any("not word for word" in problem for problem in result.unverified_numbers)
    assert any("no verified quote" in problem for problem in result.unverified_numbers)
    assert result.assessment.evidence == []
    assert result.assessment.fit_score == 2  # the unsupported factor can't raise the score
    assert [source["citation"] for source in result.sources] == ["Fixture data, not real"]


def test_quote_citing_a_filing_never_fetched_is_rejected(state):
    fake = [{"supports": "digital_asset_activity", "citation": "AAA 8-K filed 2026-11-01", "quote": QUOTE}]
    bad = assessment_json(evidence=fake)
    result, _ = run_buyer(state, bad, bad)
    assert any("not retrieved" in problem for problem in result.unverified_numbers)


def test_true_factor_needs_its_own_quote(state):
    one_quote = [{"supports": "digital_asset_activity", "citation": CITATION, "quote": QUOTE}]
    bad = assessment_json(true=("digital_asset_activity", "related_deal"), evidence=one_quote)
    result, _ = run_buyer(state, bad, bad)
    assert result.unverified_numbers == ["no verified quote for true factor related_deal"]
    assert result.assessment.related_deal is False


def test_quote_match_ignores_curly_quotes_and_line_breaks(state):
    tools = {**FIXTURE_TOOLS, "fetch_filing_excerpt": lambda **args: {
        **FIXTURE_TOOLS["fetch_filing_excerpt"](**args), "excerpt": "We\u2019re expanding\nour digital asset services"}}
    quoted = [{"supports": "digital_asset_activity", "citation": CITATION, "quote": "We're expanding our digital asset"}]
    client = ScriptedClient(tool_response("fetch_filing_excerpt", FETCH_10Q), text_response(assessment_json(evidence=quoted)))
    result = assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), tools)
    assert result.unverified_numbers == []


def test_skipping_the_10q_gets_a_correction(state):
    client = ScriptedClient(
        tool_response("fetch_filing_excerpt", {**FETCH_10Q, "form": "10-K"}),
        text_response(assessment_json(evidence=[])),
        tool_response("fetch_filing_excerpt", FETCH_10Q),
        text_response(assessment_json()),
    )
    result = assess_buyer(client, state, "AAA", "target", (500e6, 1.5e9), FIXTURE_TOOLS)
    assert "10-Q was not checked" in client.calls[2]["messages"][4]["content"]
    assert result.unverified_numbers == []
    assert result.latest_filing == "10-Q filed 2026-10-01"


def test_text_cannot_state_a_score_that_code_might_contradict(state):
    result, client = run_buyer(state, assessment_json("The score is 4 rather than 5."), assessment_json())
    assert result.unverified_numbers == []
    assert "score" in client.calls[2]["messages"][4]["content"]


def test_memo_shows_factors_quotes_links_and_filing_date(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    run = run_buyer_analysis("crypto custody", deal_low=500e6, deal_high=1.5e9, dry_run=True)
    run.buyers[0].sources = [{"citation": "BBB 10-Q filed 2026-10-01", "url": "https://www.sec.gov/x.htm"},
                             {"citation": "BBB 10-K", "url": "https://www.sec.gov/y.htm", "exhibit_url": "https://www.sec.gov/ex13.htm"}]
    memo = render_memo(run)
    assert "| Latest filing |" in memo and "10-Q filed 2026-10-01" in memo
    assert "[BBB 10-Q filed 2026-10-01](https://www.sec.gov/x.htm)" in memo
    assert "[BBB 10-K](https://www.sec.gov/y.htm) and its [annual report exhibit](https://www.sec.gov/ex13.htm)" in memo
    assert "Activity in target's line: yes" in memo and "Clear obstacle: no" in memo
    assert 'is expanding its digital asset services' in memo


def test_stability_table_reports_range_and_changed_factors():
    from agent.stability import stability_table

    def run(*true):
        return BuyerResult(ticker="AAA", assessment=json_assessment(true))
    results = {
        "AAA": [run("digital_asset_activity"), run("digital_asset_activity")],
        "BBB": [run("digital_asset_activity"), run("target_line_activity")],
        "CCC": [BuyerResult(ticker="CCC", status="failed")],
    }
    table, stable, measured = stability_table(results)
    assert (stable, measured) == (1, 2)
    assert "| AAA | 3, 3 | 3-3 | none |" in table
    assert "| BBB | 3, 4 | 3-4 | digital_asset_activity, target_line_activity |" in table
    assert "| CCC | none completed | not available | none |" in table


def test_dry_run_reports_no_tokens_and_no_cost(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_module, "RUNS_DIR", tmp_path)
    run = run_buyer_analysis("crypto custody", deal_low=500e6, deal_high=1.5e9, dry_run=True)
    assert run.input_tokens + run.cache_write_tokens + run.cache_read_tokens + run.output_tokens == 0
    assert run.cost_usd == 0


@pytest.mark.parametrize("low,high,market_cap,shown", [
    (10e6, 40e6, 30e9, "0.03%-0.13%"),
    (500e6, 1.5e9, 99.4e9, "0.50%-1.51%"),
    (500e6, 1.5e9, 36.5e9, "1.4%-4.1%"),
    (1e6, 2e6, 900e9, "<0.01%-<0.01%"),
])
def test_market_cap_percent_stays_readable_for_small_deals(low, high, market_cap, shown):
    pay = ability_to_pay({"market_cap": market_cap, "balance_sheet_type": "bank_broker", "cash": 1e9}, low, high)
    assert pay_summary(BuyerResult(ticker="AAA", ability_to_pay=pay)).startswith(shown)


def test_summary_text_never_tells_the_model_a_deal_is_zero_percent():
    pay = ability_to_pay({"market_cap": 900e9, "balance_sheet_type": "bank_broker", "cash": 1e9}, 1e6, 2e6)
    assert pay_summary_text(pay) == "A $1M to $2M deal is under 0.01% to under 0.01% of market cap."
