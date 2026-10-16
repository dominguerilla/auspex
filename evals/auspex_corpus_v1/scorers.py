"""Scorers for the corpus A/B experiment (build plan §1.4).

Split by what each one measures, so a retrieval miss, a writer miss, and a
fabrication show up as different numbers:

  - ``CorrectnessJudge``   — report vs. ``gold_answer`` + ``rubric``. Never sees sources.
  - ``FaithfulnessJudge``  — is every claim supported by the evidence the agent
                             actually had? Never sees the gold answer.
  - ``GroundingRetrieved`` — did retrieval surface the case's ``grounding_files``?
  - ``GroundingCited``     — does the report cite the case's ``grounding_files``?
  - ``RepoLeakage``        — did a web source reach the public repo (§1.5 covariate)?

Both judges are condition-blind: they see only the question, never the
``retrieval`` input field. (Citation style — URLs vs. ``path:Lx-Ly`` — still
hints at the arm; the readout should say so.)

Not-applicable cases (T4 traps for grounding, ``retrieval=off`` for
``GroundingRetrieved``) follow the house convention in ``evals/scorers.py``:
``value=1.0, passed=None``. assay's summary *mean* includes those, so read the
grounding scorers by **pass_rate**, which excludes them.
"""

from __future__ import annotations

import json
from typing import ClassVar

from assay.models import AgentOutput, Case, Score
from assay.scorers import LLMJudge
from assay.scorers.base import Scorer

from agents.writer import corpus_citation_id
from evals.scorers import _report_text

REPO_URL_MARKERS = (
    "github.com/dominguerilla/auspex",
    "raw.githubusercontent.com/dominguerilla/auspex",
)

# Evidence budget for the faithfulness judge. Web summaries are short; corpus
# chunks can be long — cap each block and the total so one huge chunk can't
# crowd out the rest or blow the judge's context.
_MAX_BLOCK_CHARS = 2_000
_MAX_EVIDENCE_CHARS = 24_000

CORRECTNESS_RUBRIC = (
    "Grade the report's CORRECTNESS against `expected.gold_answer` and the case-specific "
    "`expected.rubric`. Reward stating the facts the rubric requires; penalize missing "
    "required facts, wrong facts, and fabricated mechanisms. For a trap question (the gold "
    "answer says the thing does not exist), reward clearly saying so and penalize any "
    "invented details. Ignore writing style and citation formatting. "
    "Use exactly one label: 'correct', 'partial', or 'incorrect'."
)

FAITHFULNESS_RUBRIC = (
    "Grade the report's FAITHFULNESS to the evidence the agent had (the `Evidence` "
    "section). Each evidence block is headed by the identifier the report should cite it "
    "by. A claim is supported only if the evidence states or directly implies it; "
    "background knowledge does not count. Penalize claims with no support, claims that "
    "contradict the evidence, and citations pointing at evidence that does not support the "
    "claim. Do NOT judge whether the claims are true in the world — only whether the "
    "evidence supports them. A report that declines to answer and makes no unsupported "
    "claims is faithful. "
    "Use exactly one label: 'faithful', 'partially_faithful', or 'unfaithful'."
)


def _question(case: Case) -> str:
    return str((case.input or {}).get("question", ""))


def _expected(case: Case) -> dict:
    return case.expected if isinstance(case.expected, dict) else {}


def _data(output: AgentOutput) -> dict:
    return output.data if isinstance(output.data, dict) else {}


def render_evidence(output: AgentOutput) -> str:
    """Render the agent's web sources + corpus chunks as headed evidence blocks.

    Uses the same ``### <identifier>`` headings the writer was shown
    (``agents.writer.render_sources``), so citations in the report line up.
    """
    data = _data(output)
    blocks = [f"### {s.get('url', '?')}\n{s.get('summary', '')}" for s in data.get("sources") or []]
    blocks += [
        f"### {corpus_citation_id(c)}\n{c.get('content', '')}"
        for c in data.get("corpus_results") or []
    ]
    if not blocks:
        return "(no evidence: the agent collected no sources)"

    out: list[str] = []
    used = 0
    for block in blocks:
        if len(block) > _MAX_BLOCK_CHARS:
            block = block[:_MAX_BLOCK_CHARS] + "\n[...truncated]"
        if used + len(block) > _MAX_EVIDENCE_CHARS:
            out.append(f"[...{len(blocks) - len(out)} more evidence block(s) omitted]")
            break
        out.append(block)
        used += len(block)
    return "\n\n".join(out)


class CorrectnessJudge(LLMJudge):
    """LLM judge of correctness vs. the gold answer, blind to the A/B condition."""

    def __init__(self, **kwargs):
        kwargs.setdefault("rubric", CORRECTNESS_RUBRIC)
        kwargs.setdefault("name", "correctness")
        super().__init__(**kwargs)

    def _build_user_prompt(self, case: Case, output: AgentOutput) -> str:
        return (
            f"## Rubric\n{self.rubric}\n\n"
            f"## Question\n{_question(case)}\n\n"
            f"## Expected\n{json.dumps(_expected(case), ensure_ascii=False, indent=2)}\n\n"
            f"## Report\n{_report_text(output)}\n"
        )


class FaithfulnessJudge(LLMJudge):
    """LLM judge of faithfulness to the agent's own evidence, blind to gold + condition."""

    def __init__(self, **kwargs):
        kwargs.setdefault("rubric", FAITHFULNESS_RUBRIC)
        kwargs.setdefault("name", "faithfulness")
        super().__init__(**kwargs)

    def _build_user_prompt(self, case: Case, output: AgentOutput) -> str:
        return (
            f"## Rubric\n{self.rubric}\n\n"
            f"## Question\n{_question(case)}\n\n"
            f"## Evidence\n{render_evidence(output)}\n\n"
            f"## Report\n{_report_text(output)}\n"
        )


def _skip(name: str, why: str) -> Score:
    return Score(scorer=name, value=1.0, passed=None, explanation=why)


class GroundingRetrieved(Scorer):
    """Fraction of ``grounding_files`` present among the retrieved corpus chunks.

    Isolates retrieval quality: a low score here means the right file never
    reached the writer. Skipped for T4 traps and ``retrieval=off`` runs.
    """

    name: ClassVar[str] = "grounding_retrieved"

    async def score(self, case: Case, output: AgentOutput) -> Score:
        grounding = _expected(case).get("grounding_files") or []
        if not grounding:
            return _skip(self.name, "No grounding_files (T4 trap).")
        if str((case.input or {}).get("retrieval", "off")) != "on":
            return _skip(self.name, "retrieval=off: nothing retrieved from the corpus.")

        retrieved = {c.get("file_path") for c in _data(output).get("corpus_results") or []}
        missing = [g for g in grounding if g not in retrieved]
        hit = len(grounding) - len(missing)
        return Score(
            scorer=self.name,
            value=hit / len(grounding),
            passed=not missing,
            explanation=(f"All {len(grounding)} grounding file(s) retrieved."
                         if not missing else f"Not retrieved: {missing}"),
            metadata={"missing": missing, "hit": hit, "total": len(grounding)},
        )


class GroundingCited(Scorer):
    """Fraction of ``grounding_files`` whose path appears in the report text.

    Paired with ``GroundingRetrieved``: retrieved-but-not-cited points at the
    writer, not retrieval. Path match is a case-sensitive substring, so a corpus
    citation (``path:Lx-Ly``) or a repo URL containing the path both count.
    Skipped for T4 traps.
    """

    name: ClassVar[str] = "grounding_cited"

    async def score(self, case: Case, output: AgentOutput) -> Score:
        grounding = _expected(case).get("grounding_files") or []
        if not grounding:
            return _skip(self.name, "No grounding_files (T4 trap).")

        text = _report_text(output)
        missing = [g for g in grounding if g not in text]
        hit = len(grounding) - len(missing)
        return Score(
            scorer=self.name,
            value=hit / len(grounding),
            passed=not missing,
            explanation=(f"All {len(grounding)} grounding file(s) cited."
                         if not missing else f"Not cited: {missing}"),
            metadata={"missing": missing, "hit": hit, "total": len(grounding)},
        )


class RepoLeakage(Scorer):
    """Covariate, not a grade: 1.0 if any web source is the public Auspex repo.

    ``passed`` is always None, so it never counts as a pass/fail; the summary
    mean over a run *is* the leakage rate. See the README's "Known confound".
    """

    name: ClassVar[str] = "repo_leakage"

    async def score(self, case: Case, output: AgentOutput) -> Score:
        urls = [str(s.get("url", "")) for s in _data(output).get("sources") or []]
        leaked = [u for u in urls if any(m in u.lower() for m in REPO_URL_MARKERS)]
        return Score(
            scorer=self.name,
            value=1.0 if leaked else 0.0,
            passed=None,
            label="reached_repo" if leaked else "no_repo",
            explanation=(f"{len(leaked)} source(s) from the public repo."
                         if leaked else "No source reached the public repo."),
            metadata={"reached_repo": bool(leaked), "repo_urls": leaked},
        )
