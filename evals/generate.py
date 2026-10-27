"""Generate and save agent outputs for offline scoring.

Run Auspex against a dataset and write each output to a JSONL file.
The saved outputs can later be scored with ``evals.run --from-outputs``.

A case that produces no report is retried (--attempts), then recorded with an
``output.data.error`` and counted in a stderr summary; the process exits non-zero
if any case ended that way, and ``evals.run --from-outputs`` refuses to score the
file. That keeps an infra blip from being graded as a wrong answer. --resume picks
a killed sweep back up without discarding the rows that already succeeded.

Usage:
    python -m evals.generate --dataset evals/cases/cases.jsonl
    python -m evals.generate --dataset evals/cases/single_factoid.jsonl --output evals/outputs/quick.jsonl
    python -m evals.generate --dataset evals/auspex_corpus_v1/cases.jsonl --retrieval on
    python -m evals.generate --dataset evals/auspex_corpus_v1/cases.jsonl --output evals/outputs/x.jsonl --resume
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from console_utf8 import configure_utf8_console
from evals.adapter import run as agent

# Same reason as main.py / app.py / evals.run: the searcher logs a U+2192
# arrow and reports carry em-dashes, which kill a cp1252 stdout on Windows.
configure_utf8_console()


def _check_agent_connectivity() -> None:
    from langchain_core.messages import HumanMessage

    from llm.ollama_client import get_llm

    llm = get_llm()
    llm.invoke([HumanMessage(content="hi")])


def _blank_output(reason: str) -> dict:
    return {"text": "", "data": {"text": "", "sources": [], "critique": None,
                                 "iterations_used": 0, "error": reason}}


def _run_case(case_input: dict, attempts: int, backoff: float) -> tuple[dict, str | None]:
    """Run one case, retrying a failure up to ``attempts`` times in total.

    Returns ``(output, failure_reason)``, where ``failure_reason`` is None once a
    run produced a report. Two things count as a failure worth retrying: the graph
    raising, and the graph finishing with an empty report (``adapter.run`` defaults
    ``final_report`` to ""). Both are usually transient here — a dropped Ollama
    connection, a model that returned only reasoning tokens — so for an unattended
    sweep a retry is worth more than a lost case.
    """
    output: dict | None = None
    reason = "no attempt made"

    for attempt in range(1, attempts + 1):
        try:
            output = agent(case_input)
        except Exception as exc:
            output, reason = None, f"{type(exc).__name__}: {exc}"
        else:
            if str(output.get("text") or "").strip():
                return output, None
            reason = "empty report (graph completed without raising)"

        if attempt < attempts:
            delay = backoff * attempt  # linear, not exponential: a local blip is short
            print(f"  attempt {attempt}/{attempts} failed ({reason}); "
                  f"retrying in {delay:.0f}s", file=sys.stderr, flush=True)
            time.sleep(delay)

    # Exhausted. Keep the last output when there was one — an empty report still
    # carries its sources and iteration count, which helps explain the failure.
    if output is None:
        return _blank_output(reason), reason
    output.setdefault("data", {})["error"] = reason
    return output, reason


def failed_rows(outputs_path: Path) -> list[tuple[str, str]]:
    """Case ids in an outputs file whose run produced no report, with the reason.

    This module writes the ``output.data.error`` marker, so it defines what a
    failed row is; ``evals.run`` imports this rather than re-deriving it, the way
    ``llm/contract.py`` keeps a writer and its reader on one definition.
    """
    failed: list[tuple[str, str]] = []
    for line in outputs_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        error = entry.get("output", {}).get("data", {}).get("error")
        if error:
            failed.append((entry.get("id", "(no id)"), str(error)))
    return failed


def _completed_entries(output_path: Path) -> dict[str, dict]:
    """Rows in an existing outputs file that succeeded, keyed by case id.

    Used by --resume: a failed row is not "done", so it gets re-run.
    """
    if not output_path.exists():
        return {}
    done: dict[str, dict] = {}
    for line in output_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # A run killed mid-write can leave a partial last line; drop it.
            continue
        if entry.get("output", {}).get("data", {}).get("error") is None:
            done[entry.get("id")] = entry
    return done


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Auspex and save outputs for later scoring."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path(__file__).parent / "cases" / "cases.jsonl",
        help="Path to JSONL file containing test cases (default: evals/cases/cases.jsonl)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path to write the outputs JSONL file. "
            "Defaults to evals/outputs/<dataset-stem>.jsonl"
        ),
    )
    parser.add_argument(
        "--retrieval",
        choices=["on", "off"],
        default=None,
        help=(
            "A/B condition: set input.retrieval on every case. The value is saved "
            "with each output, so --from-outputs scoring keeps the arms apart. "
            "Default: leave cases as-is (the adapter treats unset as off)."
        ),
    )
    parser.add_argument(
        "--skip-connectivity-check",
        action="store_true",
        help="Skip the agent LLM connectivity pre-flight check",
    )
    parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        metavar="N",
        help=(
            "Tries per case before recording it as failed. A retry re-rolls a case "
            "that raised or produced no report, which is what an unattended sweep "
            "wants; pass 1 to disable and record the first failure (default: 3)."
        ),
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="Base delay between attempts, scaled linearly by attempt number (default: 10)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Reuse the successful rows already in the output file and re-run only "
            "the missing or failed cases. Use to continue a sweep that was killed "
            "partway without discarding the completed work."
        ),
    )
    args = parser.parse_args()

    if args.attempts < 1:
        print("ERROR: --attempts must be at least 1", file=sys.stderr)
        sys.exit(1)

    if not args.dataset.exists():
        print(f"ERROR: dataset not found: {args.dataset}", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    condition = f"_retrieval-{args.retrieval}" if args.retrieval else ""
    output_path: Path = args.output or (
        Path(__file__).parent / "outputs" / f"{timestamp}_{args.dataset.stem}{condition}.jsonl"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not args.skip_connectivity_check:
        print("Checking agent LLM connectivity...", flush=True)
        try:
            _check_agent_connectivity()
        except Exception as exc:
            print(f"ERROR: Agent LLM connectivity check failed: {exc}", file=sys.stderr)
            print(
                "Check OLLAMA_BASE_URL and OLLAMA_MODEL in your .env "
                "(no /v1 suffix for ChatOllama).",
                file=sys.stderr,
            )
            sys.exit(1)
        print("Agent LLM OK.", flush=True)

    cases = [
        json.loads(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.retrieval:
        for case in cases:
            case["input"]["retrieval"] = args.retrieval
    print(f"Loaded {len(cases)} cases from {args.dataset}", flush=True)

    # A failed case still gets a row, so the file stays aligned with the dataset.
    # But an empty report scores as a confidently wrong answer rather than as a
    # dropped run, so an infra blip would land in the means as a real result.
    # Collect the failures and say so loudly at the end.
    failures: list[tuple[str, str]] = []

    done = _completed_entries(output_path) if args.resume else {}
    if args.resume:
        print(f"Resuming: {len(done)} case(s) already succeeded, re-running the rest",
              flush=True)

    with output_path.open("w", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            case_id = case.get("id", f"case_{i}")
            if case_id in done:
                print(f"[{i}/{len(cases)}] {case_id} already done, reusing", flush=True)
                f.write(json.dumps(done[case_id]) + "\n")
                f.flush()
                continue

            print(f"[{i}/{len(cases)}] Running {case_id}...", flush=True)
            output, reason = _run_case(case["input"], args.attempts, args.retry_backoff)
            if reason is not None:
                print(f"  ERROR: {reason}", file=sys.stderr)
                failures.append((case_id, reason))
            entry = {
                "id": case_id,
                "input": case["input"],
                "expected": case.get("expected"),
                "metadata": case.get("metadata"),
                "output": output,
            }
            f.write(json.dumps(entry) + "\n")
            f.flush()

    ok = len(cases) - len(failures)
    # flush before the stderr block below, so a piped log keeps them in order.
    print(f"\nSaved {len(cases)} outputs to {output_path} ({ok} ok, {len(failures)} failed)",
          flush=True)

    if failures:
        print(f"\nWARNING: {len(failures)}/{len(cases)} cases produced no report:",
              file=sys.stderr)
        for case_id, reason in failures:
            print(f"  - {case_id}: {reason}", file=sys.stderr)
        print(
            "\nScoring this file as-is grades these as incorrect answers rather than "
            "dropped runs, which biases the arm. evals.run --from-outputs refuses it "
            "for that reason. Retry just these cases with:\n"
            f"  python -m evals.generate --dataset {args.dataset}"
            f"{f' --retrieval {args.retrieval}' if args.retrieval else ''}"
            f" --output {output_path} --resume",
            file=sys.stderr,
        )
        # Non-zero exit so a sweep loop over conditions/seeds can stop on a bad
        # arm instead of moving on with a file that only looks complete.
        sys.exit(1)

    print(f"Score them with:  python -m evals.run --from-outputs \"{output_path}\"")


if __name__ == "__main__":
    main()
