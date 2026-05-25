"""Generate and save agent outputs for offline scoring.

Run the research-agent against a dataset and write each output to a JSONL file.
The saved outputs can later be scored with ``evals.run --from-outputs``.

Usage:
    python -m evals.generate --dataset evals/cases/cases.jsonl
    python -m evals.generate --dataset evals/cases/single_factoid.jsonl --output evals/outputs/quick.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from evals.adapter import run as agent


def _check_agent_connectivity() -> None:
    from langchain_core.messages import HumanMessage
    from llm.ollama_client import get_llm

    llm = get_llm()
    llm.invoke([HumanMessage(content="hi")])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the research-agent and save outputs for later scoring."
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
        "--skip-connectivity-check",
        action="store_true",
        help="Skip the agent LLM connectivity pre-flight check",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"ERROR: dataset not found: {args.dataset}", file=sys.stderr)
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path: Path = args.output or (
        Path(__file__).parent / "outputs" / f"{timestamp}_{args.dataset.stem}.jsonl"
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
    print(f"Loaded {len(cases)} cases from {args.dataset}", flush=True)

    with output_path.open("w", encoding="utf-8") as f:
        for i, case in enumerate(cases, 1):
            case_id = case.get("id", f"case_{i}")
            print(f"[{i}/{len(cases)}] Running {case_id}...", flush=True)
            try:
                output = agent(case["input"])
            except Exception as exc:
                print(f"  ERROR: {exc}", file=sys.stderr)
                output = {"text": "", "data": {"text": "", "sources": [], "critique": None,
                                               "iterations_used": 0, "error": str(exc)}}
            entry = {
                "id": case_id,
                "input": case["input"],
                "expected": case.get("expected"),
                "metadata": case.get("metadata"),
                "output": output,
            }
            f.write(json.dumps(entry) + "\n")
            f.flush()

    print(f"\nSaved {len(cases)} outputs to {output_path}")
    print(f"Score them with:  python -m evals.run --from-outputs \"{output_path}\"")


if __name__ == "__main__":
    main()
