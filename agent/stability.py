"""Runs the same buyers several times and reports how much each fit score moves."""

import argparse
import datetime
import os
import pathlib

import anthropic

from agent.agent import DEFAULT_MODEL, assess_buyer, new_run_state
from agent.schemas import BuyerResult
from agent.tools import LIVE_TOOLS
from data import BUYER_UNIVERSE


def stability_table(results: dict[str, list[BuyerResult]]) -> tuple[str, int, int]:
    """Markdown table plus the number of buyers whose score stayed the same and the number measured."""
    lines = ["| Buyer | Scores by run | Range | Factors that changed |", "|---|---|---|---|"]
    stable = measured = 0
    for ticker, runs in results.items():
        done = [r for r in runs if r.assessment]
        scores = [r.assessment.fit_score for r in done]
        answers = [r.assessment.true_factors() for r in done]
        changed = sorted(set().union(*answers) - set.intersection(*answers)) if answers else []
        if scores:
            measured += 1
            stable += min(scores) == max(scores)
        shown = ", ".join(str(s) for s in scores) or "none completed"
        spread = f"{min(scores)}-{max(scores)}" if scores else "not available"
        lines.append(f"| {ticker} | {shown} | {spread} | {', '.join(changed) or 'none'} |")
    return "\n".join(lines), stable, measured


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target")
    parser.add_argument("--deal-low", type=float, required=True, help="In $M")
    parser.add_argument("--deal-high", type=float, required=True, help="In $M")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--tickers", nargs="*", default=list(BUYER_UNIVERSE)[:10])
    parser.add_argument("--output", default="docs/score_stability.md")
    args = parser.parse_args()

    model = os.environ.get("MODEL_NAME") or DEFAULT_MODEL
    client = anthropic.Anthropic(max_retries=5)
    run_id = "stability-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    state = new_run_state(model, run_id)
    deal = (args.deal_low * 1e6, args.deal_high * 1e6)
    results = {t: [assess_buyer(client, state, t, args.target, deal, LIVE_TOOLS) for _ in range(args.runs)]
               for t in args.tickers}

    table, stable, measured = stability_table(results)
    cost = "not available" if state.cost_usd is None else f"${state.cost_usd:.2f}"
    flagged = sum(bool(r.unverified_numbers) for runs in results.values() for r in runs)
    total = sum(len(runs) for runs in results.values())
    pathlib.Path(args.output).write_text(
        f"# Fit Score Stability\n\nThe same {len(args.tickers)} buyers assessed {args.runs} times each, "
        f"on {datetime.date.today()}.\n\n**Target:** {args.target}  \n**Model:** {model}  \n"
        f"**Buyers with the same score in every run:** {stable} of {measured}  \n"
        f"**Assessments with a failed check after correction:** {flagged} of {total}  \n"
        f"**Cost of this test:** {cost}\n\n{table}\n"
    )
    print(f"Saved {args.output}. Stable: {stable}/{measured}. Flagged: {flagged}/{total}. Cost: {cost}. Log: {state.log_path}")


if __name__ == "__main__":
    main()
