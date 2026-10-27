"""Run the Auspex eval suite.

Usage:
    python -m evals.run                                    # full suite, default scorers
    python -m evals.run --skip-judge                       # skip the LLMJudge (no API key needed)
    python -m evals.run --concurrency 1                    # serialize (kinder to DuckDuckGo + Ollama)
    python -m evals.run --skip-judge-check                 # skip connectivity pre-flight
    python -m evals.run --from-outputs evals/outputs/x.jsonl  # score pre-generated outputs

Corpus A/B experiment (evals/auspex_corpus_v1):
    python -m evals.run --corpus-suite --retrieval on      # live run, one arm
    python -m evals.run --corpus-suite --from-outputs evals/outputs/x.jsonl --judge-provider anthropic
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from assay import Eval
from assay.models import AgentOutput, Case
from assay.scorers import LLMJudge

from console_utf8 import configure_utf8_console
from evals.adapter import run as agent
from evals.auspex_corpus_v1.scorers import (
    CorrectnessJudge,
    FaithfulnessJudge,
    GroundingCited,
    GroundingRetrieved,
    RepoLeakage,
)
from evals.generate import failed_rows
from evals.scorers import MinSources, MustMention, MustNotMention

configure_utf8_console()

JUDGE_RUBRIC = (
    "Grade the agent's research report against the criteria in `expected.rubric`. "
    "Reward correctness, coverage of the requested mechanisms or facts, and faithful "
    "use of the cited sources. Penalize fabricated facts, missing required content, "
    "and confident answers to unanswerable questions. Score 1.0 = fully meets the "
    "rubric; 0.0 = fully fails it."
)
"""Rubric for the LLM judge to evaluate research reports. Used when --skip-judge is not set."""

CORPUS_DATASET = Path(__file__).parent / "auspex_corpus_v1" / "cases.jsonl"


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


def _strip_outputs_to_tmpfile(outputs_path: Path) -> Path:
    """Write a temp JSONL with the ``output`` key removed so assay can load it as a dataset."""
    entries = [
        json.loads(line)
        for line in outputs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for entry in entries:
        tmp.write(json.dumps({k: v for k, v in entry.items() if k != "output"}) + "\n")
    tmp.close()
    return Path(tmp.name)


def _with_retrieval_tmpfile(dataset_path: Path, retrieval: str) -> Path:
    """Write a temp copy of ``dataset_path`` with ``input.retrieval`` set on every case.

    The A/B condition is swept at run time, never stored in the case file
    (see evals/auspex_corpus_v1/README.md).
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    )
    for line in dataset_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            case = json.loads(line)
            case["input"]["retrieval"] = retrieval
            tmp.write(json.dumps(case) + "\n")
    tmp.close()
    return Path(tmp.name)


def _make_replay_agent(outputs_path: Path):
    """Return an agent callable that replays saved outputs instead of running the graph."""
    outputs: dict[str, dict] = {}
    for line in outputs_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            key = json.dumps(entry["input"], sort_keys=True)
            outputs[key] = entry["output"]

    def replay(input_: dict) -> dict:
        key = json.dumps(input_, sort_keys=True)
        if key not in outputs:
            raise KeyError(f"No saved output for input: {input_}")
        return outputs[key]

    return replay


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
    """Run the evaluation suite against Auspex.

    Sets up scorers (rule-based checks and optional LLM judge), verifies connectivity
    to both the agent LLM and judge LLM, then runs the eval suite against test cases.
    Results are saved to a directory and an HTML report is generated.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path,
                        default=Path(__file__).parent / "cases" / "cases.jsonl",
                        help="Path to JSONL file containing test cases (default: evals/cases.jsonl)")
    parser.add_argument("--output-dir", type=Path, default=Path("evals/runs"),
                        help="Directory to save eval results and HTML report (default: evals/runs)")
    parser.add_argument("--name", default="auspex-eval",
                        help="Name for this eval run, used in output directory and report (default: auspex-eval)")
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
    parser.add_argument("--from-outputs", type=Path, default=None,
                        metavar="OUTPUTS_JSONL",
                        help="Score pre-generated outputs instead of running the agent "
                             "(produced by evals.generate)")
    parser.add_argument("--allow-failed", action="store_true",
                        help="Score an outputs file even though some cases produced no "
                             "report. Off by default: those rows grade as wrong answers "
                             "rather than dropped runs, which biases the arm.")
    parser.add_argument("--retrieval", choices=["on", "off"], default=None,
                        help="A/B condition for a live run: set input.retrieval on every case. "
                             "Not valid with --from-outputs (saved outputs already carry it).")
    parser.add_argument("--corpus-suite", action="store_true",
                        help="Corpus A/B experiment: default the dataset to "
                             "evals/auspex_corpus_v1/cases.jsonl and score with the split "
                             "correctness/faithfulness judges, grounding scorers, and the "
                             "repo-leakage covariate instead of the generic judge.")
    args = parser.parse_args()

    if args.retrieval and args.from_outputs is not None:
        print("ERROR: --retrieval applies to live runs only; the condition is already "
              "saved in the outputs (use evals.generate --retrieval).", file=sys.stderr)
        sys.exit(1)
    if args.corpus_suite and args.from_outputs is None \
            and args.dataset == Path(__file__).parent / "cases" / "cases.jsonl":
        args.dataset = CORPUS_DATASET
    dataset_stem = Path(args.dataset).stem
    if args.retrieval:
        dataset_stem = f"{dataset_stem}_retrieval-{args.retrieval}"

    if args.from_outputs is not None:
        if not args.from_outputs.exists():
            print(f"ERROR: outputs file not found: {args.from_outputs}", file=sys.stderr)
            sys.exit(1)
        # Rows evals.generate marked as producing no report. Replaying them would
        # have the judge grade an infra failure as a wrong answer, turning it into
        # an apparent hallucination and biasing whichever arm it landed in.
        failed = failed_rows(args.from_outputs)
        if failed and not args.allow_failed:
            print(f"ERROR: {len(failed)} case(s) in {args.from_outputs} produced no "
                  "report:", file=sys.stderr)
            for case_id, reason in failed:
                print(f"  - {case_id}: {reason}", file=sys.stderr)
            print(
                "\nScoring them would grade infra failures as wrong answers and bias "
                "this arm. Retry just those cases:\n"
                f"  python -m evals.generate --dataset <cases.jsonl> "
                f"--output {args.from_outputs} --resume\n"
                "Or pass --allow-failed to score anyway and exclude them in the readout.",
                file=sys.stderr,
            )
            sys.exit(1)
        if failed:
            print(f"WARNING: scoring {len(failed)} failed case(s) because "
                  "--allow-failed was passed; exclude them in the readout: "
                  + ", ".join(case_id for case_id, _ in failed), file=sys.stderr, flush=True)
        agent_fn = _make_replay_agent(args.from_outputs)
        if args.dataset == Path(__file__).parent / "cases" / "cases.jsonl":
            _tmp_dataset = _strip_outputs_to_tmpfile(args.from_outputs)
            args.dataset = _tmp_dataset
        else:
            _tmp_dataset = None
        print(f"Replaying outputs from {args.from_outputs}", flush=True)
    else:
        _tmp_dataset = None
        if args.retrieval:
            _tmp_dataset = _with_retrieval_tmpfile(args.dataset, args.retrieval)
            args.dataset = _tmp_dataset
        agent_fn = agent
        print("Checking agent LLM connectivity...", flush=True)
        try:
            _check_agent_connectivity()
        except Exception as exc:
            print(f"ERROR: Agent LLM connectivity check failed: {exc}", file=sys.stderr)
            print("Check OLLAMA_BASE_URL and OLLAMA_MODEL in your .env (no /v1 suffix for ChatOllama).",
                  file=sys.stderr)
            sys.exit(1)
        print("Agent LLM OK.", flush=True)

    scorers = [MustMention(), MustNotMention(), MinSources()]
    if args.corpus_suite:
        scorers += [GroundingRetrieved(), GroundingCited(), RepoLeakage()]
    judge = None
    judge_model: str | None = None
    if not args.skip_judge:
        judge_model = args.judge_model
        if judge_model is None and args.judge_provider == "ollama":
            judge_model = os.environ.get("OLLAMA_MODEL")
        judge_kwargs = {"provider": args.judge_provider}
        if judge_model:
            judge_kwargs["model"] = judge_model
        if args.corpus_suite:
            judges = [CorrectnessJudge(**judge_kwargs), FaithfulnessJudge(**judge_kwargs)]
        else:
            judges = [LLMJudge(rubric=JUDGE_RUBRIC, **judge_kwargs)]
        # Both corpus judges share provider + model, so one connectivity check covers them.
        judge = judges[0]
        scorers += judges

    # Give the replay function a descriptive identity so the report shows what was scored.
    if args.from_outputs is not None:
        judge_label = judge_model or "no-judge"
        agent_fn.__qualname__ = (
            f"replay[outputs={args.from_outputs.stem}, judge={judge_label}]"
        )
        agent_fn.__module__ = "evals"

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
        agent=agent_fn,
        dataset=args.dataset,
        scorers=scorers,
        name=args.name,
        concurrency=args.concurrency,
    )
    try:
        result = eval_.run()
    finally:
        if _tmp_dataset is not None:
            _tmp_dataset.unlink(missing_ok=True)

    # Replace the ULID run_id with a human-readable folder name.
    date_str = result.started_at.strftime("%Y%m%d_%H%M%S")
    if args.from_outputs is not None:
        # Strip any leading YYYYMMDD_HHMMSS_ timestamp already in the outputs filename.
        dataset_part = re.sub(r"^\d{8}_\d{6}_", "", args.from_outputs.stem) or args.from_outputs.stem
    else:
        dataset_part = dataset_stem
    judge_part = (
        "judge-" + re.sub(r"[:/\\]", "-", judge_model) if judge_model else "no-judge"
    )
    result.run_id = f"{date_str}_{dataset_part}_{judge_part}"

    result.summary_print()
    result.save(args.output_dir)
    report = result.report_html(args.output_dir / result.run_id / "report.html")
    print(f"\nReport: {report}")


if __name__ == "__main__":
    main()
