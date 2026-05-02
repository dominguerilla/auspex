"""Run the research-agent eval suite.

Usage:
    python -m evals.run                  # full suite, default scorers
    python -m evals.run --no-judge       # skip the LLMJudge (no Anthropic key needed)
    python -m evals.run --concurrency 1  # serialize (kinder to DuckDuckGo + Ollama)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from assay import Eval
from assay.scorers import LLMJudge

from evals.adapter import run as agent
from evals.scorers import MinSources, MustMention, MustNotMention

JUDGE_RUBRIC = (
    "Grade the agent's research report against the criteria in `expected.rubric`. "
    "Reward correctness, coverage of the requested mechanisms or facts, and faithful "
    "use of the cited sources. Penalize fabricated facts, missing required content, "
    "and confident answers to unanswerable questions. Score 1.0 = fully meets the "
    "rubric; 0.0 = fully fails it."
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path,
                        default=Path(__file__).parent / "cases.jsonl")
    parser.add_argument("--out", type=Path, default=Path("evals/runs"))
    parser.add_argument("--name", default="research-agent-eval")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="Cases run in parallel. Keep low — DDG and Ollama "
                             "don't love being hammered.")
    parser.add_argument("--no-judge", action="store_true",
                        help="Skip the LLMJudge scorer (no Anthropic API key needed).")
    args = parser.parse_args()

    scorers = [MustMention(), MustNotMention(), MinSources()]
    if not args.no_judge:
        scorers.append(LLMJudge(rubric=JUDGE_RUBRIC))

    eval_ = Eval(
        agent=agent,
        dataset=args.dataset,
        scorers=scorers,
        name=args.name,
        concurrency=args.concurrency,
    )
    result = eval_.run()
    result.summary_print()
    result.save(args.out)
    report = result.report_html(args.out / result.run_id / "report.html")
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
