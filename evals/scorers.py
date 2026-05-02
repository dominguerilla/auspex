"""Custom scorers for the research-agent eval suite.

These read structured fields out of ``case.expected`` (``must_mention``,
``must_not_mention``, ``min_sources``) so the dataset itself drives the
checks, no per-case scorer wiring needed.

The agent's adapter returns a dict; assay packs that into
``AgentOutput.data``. ``output.text`` holds the rendered report (also stuffed
into ``data["text"]``); ``data["sources"]`` is the list of scraped sources.
"""

from __future__ import annotations

from typing import ClassVar

from assay.models import AgentOutput, Case, Score
from assay.scorers.base import Scorer


def _report_text(output: AgentOutput) -> str:
    if output.text:
        return output.text
    if isinstance(output.data, dict):
        return str(output.data.get("text") or "")
    return ""


class MustMention(Scorer):
    """Pass iff every keyword in ``case.expected['must_mention']`` is present.

    Case-insensitive substring match. Cases without ``must_mention`` are
    skipped (returns 1.0, passed=None).
    """

    name: ClassVar[str] = "must_mention"

    async def score(self, case: Case, output: AgentOutput) -> Score:
        expected = case.expected if isinstance(case.expected, dict) else {}
        needles = expected.get("must_mention") or []
        if not needles:
            return Score(scorer=self.name, value=1.0, passed=None,
                         explanation="No must_mention configured.")

        text = _report_text(output).lower()
        missing = [n for n in needles if n.lower() not in text]
        hit = len(needles) - len(missing)
        value = hit / len(needles)
        return Score(
            scorer=self.name,
            value=value,
            passed=not missing,
            explanation=(
                f"All {len(needles)} keywords present."
                if not missing
                else f"Missing: {missing}"
            ),
            metadata={"missing": missing, "hit": hit, "total": len(needles)},
        )


class MustNotMention(Scorer):
    """Fail if any anti-keyword in ``case.expected['must_not_mention']`` appears."""

    name: ClassVar[str] = "must_not_mention"

    async def score(self, case: Case, output: AgentOutput) -> Score:
        expected = case.expected if isinstance(case.expected, dict) else {}
        anti = expected.get("must_not_mention") or []
        if not anti:
            return Score(scorer=self.name, value=1.0, passed=None,
                         explanation="No must_not_mention configured.")

        text = _report_text(output).lower()
        hits = [a for a in anti if a.lower() in text]
        return Score(
            scorer=self.name,
            value=0.0 if hits else 1.0,
            passed=not hits,
            explanation=(
                "No anti-keywords present."
                if not hits
                else f"Found banned terms: {hits}"
            ),
            metadata={"hits": hits},
        )


class MinSources(Scorer):
    """Pass iff the agent collected at least ``case.expected['min_sources']`` sources."""

    name: ClassVar[str] = "min_sources"

    async def score(self, case: Case, output: AgentOutput) -> Score:
        expected = case.expected if isinstance(case.expected, dict) else {}
        threshold = expected.get("min_sources")
        if threshold is None:
            return Score(scorer=self.name, value=1.0, passed=None,
                         explanation="No min_sources configured.")

        sources = []
        if isinstance(output.data, dict):
            sources = output.data.get("sources") or []
        n = len(sources)
        passed = n >= threshold
        return Score(
            scorer=self.name,
            value=min(1.0, n / threshold) if threshold else 1.0,
            passed=passed,
            explanation=f"{n} sources (threshold {threshold}).",
            metadata={"n_sources": n, "threshold": threshold},
        )
