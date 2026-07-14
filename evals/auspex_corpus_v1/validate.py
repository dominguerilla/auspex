"""Validate the hand-authored corpus eval suite (build plan §1.3).

Structural guardrails for cases.jsonl — it does NOT run the pipeline or judge
answers, it just checks the suite is well-formed and grounded before you spend
150 runs on it:

  - exactly 25 cases, tier distribution 8 / 8 / 7 / 2 (T1 / T2 / T3 / T4)
  - required fields present and (with --require-complete) non-empty
  - every expected.grounding_files path actually exists at the pinned commit
    (a typo'd or since-renamed path would silently break grounding scoring)
  - T4 traps carry a rubric (they're judged on refusing to fabricate)

Usage (from repo root):
    python -m evals.auspex_corpus_v1.validate                 # progress + structural check
    python -m evals.auspex_corpus_v1.validate --require-complete   # also fail on any TODO

Exit code is non-zero if a structural error is found (or, with the flag, if any
case is still incomplete), so this can gate CI later.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_CASES = Path(__file__).parent / "cases.jsonl"
_EXPECTED_TIERS = {"T1": 8, "T2": 8, "T3": 7, "T4": 2}


def _load_cases() -> list[dict]:
    return [
        json.loads(line)
        for line in _CASES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _tracked_paths(commit: str) -> set[str]:
    """All file paths tracked at ``commit`` (to check grounding_files exist)."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit],
        capture_output=True, text=True, check=True,
    ).stdout
    return {p for p in out.splitlines() if p.strip()}


def validate(require_complete: bool) -> tuple[list[str], list[str]]:
    """Return (errors, todos). errors = structural problems; todos = unfilled cases."""
    errors: list[str] = []
    todos: list[str] = []
    cases = _load_cases()

    # --- suite-level: count + tier distribution ---
    if len(cases) != 25:
        errors.append(f"expected 25 cases, found {len(cases)}")
    tier_counts: dict[str, int] = {}
    for c in cases:
        tier = c.get("metadata", {}).get("tier", "?")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    for tier, want in _EXPECTED_TIERS.items():
        got = tier_counts.get(tier, 0)
        if got != want:
            errors.append(f"tier {tier}: expected {want} cases, found {got}")

    # --- grounding paths must exist at each case's pinned commit ---
    tracked_by_commit: dict[str, set[str]] = {}

    for c in cases:
        cid = c.get("id", "<no-id>")
        exp = c.get("expected", {})
        meta = c.get("metadata", {})
        tier = meta.get("tier", "?")
        question = c.get("input", {}).get("question", "").strip()
        gold = exp.get("gold_answer", "").strip()
        rubric = exp.get("rubric", "").strip()
        grounding = exp.get("grounding_files", []) or []

        # Completeness (a case with no question is still a TODO, not an error).
        if not question or not gold or not rubric:
            todos.append(cid)
        # T1-T3 must ground in real files; T4 traps legitimately have none
        # (the correct answer is "the corpus contains no such thing").
        if tier != "T4" and question and not grounding:
            errors.append(f"{cid}: no grounding_files (required for {tier})")
        if tier == "T4" and not rubric and question:
            errors.append(f"{cid}: T4 trap needs a rubric (judged on declining to fabricate)")

        commit = meta.get("corpus_commit", "")
        if grounding and commit:
            if commit not in tracked_by_commit:
                try:
                    tracked_by_commit[commit] = _tracked_paths(commit)
                except subprocess.CalledProcessError:
                    errors.append(f"{cid}: corpus_commit {commit!r} not found in git")
                    tracked_by_commit[commit] = set()
            tracked = tracked_by_commit[commit]
            for path in grounding:
                if path not in tracked:
                    errors.append(f"{cid}: grounding path not at {commit[:7]}: {path}")

    if require_complete and todos:
        errors.append(f"{len(todos)} case(s) still incomplete: {', '.join(todos)}")
    return errors, todos


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-complete", action="store_true",
                        help="Treat any unfilled (TODO) case as an error.")
    args = parser.parse_args()

    errors, todos = validate(args.require_complete)
    filled = 25 - len(todos)
    print(f"corpus eval suite: {filled}/25 cases filled")
    if todos:
        print(f"  TODO ({len(todos)}): {', '.join(todos)}")
    if errors:
        print(f"\n{len(errors)} structural error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("structure OK" + ("" if not todos else " (still authoring)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
