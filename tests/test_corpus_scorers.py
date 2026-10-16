"""Tests for the corpus A/B scorers (evals/auspex_corpus_v1/scorers.py).

Fully offline: the LLM judges get a fake provider that records the prompt.
Skipped when the eval harness (assay, from evals/requirements.txt) is absent.
"""

import asyncio
import json

import pytest

pytest.importorskip("assay")

from assay.models import AgentOutput, Case  # noqa: E402

from evals.auspex_corpus_v1.scorers import (  # noqa: E402
    CorrectnessJudge,
    FaithfulnessJudge,
    GroundingCited,
    GroundingRetrieved,
    RepoLeakage,
    render_evidence,
)
from evals.scorers import MinSources  # noqa: E402


class FakeProvider:
    def __init__(self, reply: dict):
        self.reply = json.dumps(reply)
        self.user_prompt = None

    def call(self, system, user, *, model, temperature):
        self.user_prompt = user
        return self.reply


def _case(retrieval="on", grounding=("docs/adr/0005-worker-split-cloud-tasks.md",)):
    return Case(
        id="t3_rationale_06",
        input={"question": "Why Cloud Tasks?", "max_iterations": 2, "retrieval": retrieval},
        expected={"gold_answer": "GOLD-SENTINEL scale to zero", "rubric": "mention scale-to-zero",
                  "grounding_files": list(grounding), "min_sources": 1},
    )


def _output(text="report", sources=(), chunks=()):
    return AgentOutput(text=text, data={"text": text, "sources": list(sources),
                                        "corpus_results": list(chunks)})


def _chunk(path="docs/adr/0005-worker-split-cloud-tasks.md", content="scale-to-zero kills tasks"):
    return {"chunk_id": 1, "file_path": path, "start_line": 10, "end_line": 20,
            "commit_sha": "9b8b08f", "content": content, "similarity": 0.9, "source": "corpus"}


def _score(scorer, case, output):
    return asyncio.run(scorer.score(case, output))


# --- judges: condition-blind prompts ---------------------------------------------

def test_correctness_judge_sees_gold_but_not_condition():
    provider = FakeProvider({"score": 1.0, "passed": True, "label": "correct", "explanation": "ok"})
    judge = CorrectnessJudge(provider=provider)
    score = _score(judge, _case(), _output())
    assert score.scorer == "correctness"
    assert score.label == "correct"
    assert "GOLD-SENTINEL" in provider.user_prompt
    assert "retrieval" not in provider.user_prompt


def test_faithfulness_judge_sees_evidence_but_not_gold_or_condition():
    provider = FakeProvider({"score": 0.5, "passed": True, "label": "partially_faithful",
                             "explanation": "x"})
    judge = FaithfulnessJudge(provider=provider)
    out = _output(sources=[{"url": "https://example.com/a", "summary": "web summary"}],
                  chunks=[_chunk()])
    score = _score(judge, _case(), out)
    assert score.scorer == "faithfulness"
    assert "https://example.com/a" in provider.user_prompt
    assert "docs/adr/0005-worker-split-cloud-tasks.md:L10-L20" in provider.user_prompt
    assert "GOLD-SENTINEL" not in provider.user_prompt
    assert "retrieval" not in provider.user_prompt


def test_render_evidence_truncates_long_blocks_and_handles_empty():
    assert "no evidence" in render_evidence(_output())
    rendered = render_evidence(_output(chunks=[_chunk(content="x" * 10_000)]))
    assert "[...truncated]" in rendered
    assert len(rendered) < 3_000


# --- grounding --------------------------------------------------------------------

def test_grounding_retrieved_hit_and_miss():
    case = _case(grounding=("docs/adr/0005-worker-split-cloud-tasks.md", "infra/cloudrun.tf"))
    score = _score(GroundingRetrieved(), case, _output(chunks=[_chunk()]))
    assert score.value == 0.5
    assert score.passed is False
    assert score.metadata["missing"] == ["infra/cloudrun.tf"]


def test_grounding_retrieved_skips_off_arm_and_traps():
    assert _score(GroundingRetrieved(), _case(retrieval="off"), _output()).passed is None
    assert _score(GroundingRetrieved(), _case(grounding=()), _output()).passed is None


def test_grounding_cited_matches_path_in_report():
    text = "Per [ADR](docs/adr/0005-worker-split-cloud-tasks.md:L10-L20), scale to zero..."
    score = _score(GroundingCited(), _case(), _output(text=text))
    assert score.passed is True
    assert _score(GroundingCited(), _case(), _output(text="no citation")).passed is False


# --- leakage covariate --------------------------------------------------------------

def test_repo_leakage_flags_public_repo_urls():
    leaked = _output(sources=[{"url": "https://github.com/dominguerilla/auspex/blob/master/app.py",
                               "summary": ""}])
    clean = _output(sources=[{"url": "https://cloud.google.com/tasks", "summary": ""}])
    s1 = _score(RepoLeakage(), _case(retrieval="off"), leaked)
    s2 = _score(RepoLeakage(), _case(retrieval="off"), clean)
    assert (s1.value, s1.passed, s1.metadata["reached_repo"]) == (1.0, None, True)
    assert (s2.value, s2.passed, s2.metadata["reached_repo"]) == (0.0, None, False)


# --- MinSources counts corpus chunks --------------------------------------------------

def test_min_sources_counts_corpus_chunks():
    score = _score(MinSources(), _case(), _output(chunks=[_chunk()]))
    assert score.passed is True
    assert score.metadata["n_sources"] == 1
