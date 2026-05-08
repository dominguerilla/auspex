"""Run the research-agent eval suite.

Usage:
    python -m evals.run                  # full suite, default scorers
    python -m evals.run --skip-judge     # skip the LLMJudge (no API key needed)
    python -m evals.run --concurrency 1  # serialize (kinder to DuckDuckGo + Ollama)
    python -m evals.run --skip-judge-check  # skip connectivity pre-flight
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from assay import Eval
from assay.models import AgentOutput, Case
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
"""Rubric for the LLM judge to evaluate research reports. Used when --skip-judge is not set."""


def _judge_diagnostics(judge: LLMJudge) -> str:
    """Return diagnostic info about the LLM judge: provider, model, and endpoint URL."""
    provider = judge._provider_name
    model = judge.model
    if provider == "ollama":
        url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    elif provider == "anthropic":
        url = "https://api.anthropic.com"
    elif provider == "openai":
        url = "https://api.openai.com/v1"
    else:
        url = "(custom provider)"
    return f"provider={provider}  model={model}  url={url}"


def _check_agent_connectivity() -> None:
    """Smoke-test the agent's LLM before running any cases."""
    from langchain_core.messages import HumanMessage

    from llm.ollama_client import get_llm

    llm = get_llm()
    llm.invoke([HumanMessage(content="hi")])


async def _check_judge_connectivity(judge: LLMJudge) -> None:
    """Verify the LLM judge can connect and score. Raises RuntimeError if it fails."""
    dummy_case = Case(id="_connectivity_check", input={},
                      expected={"rubric": "Respond with score 1.0."})
    dummy_output = AgentOutput(text="OK")
    score = await judge.score(dummy_case, dummy_output)
    if score.explanation and "failed" in score.explanation.lower():
        raise RuntimeError(score.explanation)


def main() -> None:
    """Run the evaluation suite against research-agent.

    Sets up scorers (rule-based checks and optional LLM judge), verifies connectivity
    to both the agent LLM and judge LLM, then runs the eval suite against test cases.
    Results are saved to a directory and an HTML report is generated.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path,
                        default=Path(__file__).parent / "cases.jsonl",
                        help="Path to JSONL file containing test cases (default: evals/cases.jsonl)")
    parser.add_argument("--output-dir", type=Path, default=Path("evals/runs"),
                        help="Directory to save eval results and HTML report (default: evals/runs)")
    parser.add_argument("--name", default="research-agent-eval",
                        help="Name for this eval run, used in output directory and report (default: research-agent-eval)")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="Number of parallel cases. Keep low to avoid overwhelming DuckDuckGo and local Ollama (default: 2)")
    parser.add_argument("--skip-judge", action="store_true",
                        help="Skip the LLMJudge scorer (use when Anthropic/OpenAI API not available)")
    parser.add_argument("--judge-provider", type=str, default="ollama",
                        help="LLM provider for judge: ollama, openai, or anthropic. Only used if judge is enabled (default: ollama)")
    parser.add_argument("--judge-model", type=str, default=None,
                        help="Model for the LLM judge. Defaults to OLLAMA_MODEL env var (ollama) or assay package default (others)")
    parser.add_argument("--skip-judge-check", action="store_true",
                        help="Skip the LLM judge connectivity pre-flight check")
    args = parser.parse_args()

    scorers = [MustMention(), MustNotMention(), MinSources()]
    judge = None
    if not args.skip_judge:
        judge_model = args.judge_model
        if judge_model is None and args.judge_provider == "ollama":
            judge_model = os.environ.get("OLLAMA_MODEL")
        judge_kwargs = {"rubric": JUDGE_RUBRIC, "provider": args.judge_provider}
        if judge_model:
            judge_kwargs["model"] = judge_model
        judge = LLMJudge(**judge_kwargs)
        scorers.append(judge)

    print("Checking agent LLM connectivity...", flush=True)
    try:
        _check_agent_connectivity()
    except Exception as exc:
        print(f"ERROR: Agent LLM connectivity check failed: {exc}", file=sys.stderr)
        print("Check OLLAMA_BASE_URL and OLLAMA_MODEL in your .env (no /v1 suffix for ChatOllama).",
              file=sys.stderr)
        sys.exit(1)
    print("Agent LLM OK.", flush=True)

    if judge and not args.skip_judge_check:
        diag = _judge_diagnostics(judge)
        print(f"Checking LLM judge connectivity ({diag})...", flush=True)
        try:
            asyncio.run(_check_judge_connectivity(judge))
        except Exception as exc:
            print(f"ERROR: LLM judge connectivity check failed: {exc}", file=sys.stderr)
            print(f"  {diag}", file=sys.stderr)
            print("Re-run with --skip-judge to skip scoring, or --skip-judge-check to ignore this.",
                  file=sys.stderr)
            sys.exit(1)
        print("LLM judge OK.", flush=True)

    eval_ = Eval(
        agent=agent,
        dataset=args.dataset,
        scorers=scorers,
        name=args.name,
        concurrency=args.concurrency,
    )
    result = eval_.run()
    result.summary_print()
    result.save(args.output_dir)
    report = result.report_html(args.output_dir / result.run_id / "report.html")
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
