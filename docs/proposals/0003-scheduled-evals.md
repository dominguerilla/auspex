# 0003 — Scheduled Evaluation of Past Reports via MCP

| | |
|---|---|
| **Status** | Proposed |
| **Created** | 2026-06-15 |
| **Owner** | Carlos |
| **Related** | `evals/generate.py`, `evals/run.py`, `evals/adapter.py`, `evals/scorers.py`, `auspex/mcp_server/server.py`, `graph/state.py` |

> A design sketch, not a commitment. The goal is that a future reader can decide
> whether this is worth building and start without re-deriving the discussion.

---

## Problem

Reports produced by the hosted MCP server (e.g. the daily Hermes report) are
delivered and then forgotten. We want to **evaluate stored reports on a schedule**
— a cron'd agent calls an MCP tool that scores a past run and records the result —
to get:

- **Quality monitoring / regression detection** over time (did report quality drift
  as the model, prompts, or sources changed?).
- **A labeled dataset from real usage**, not just hand-authored eval cases.
- **Re-scoring on demand** when scorers, rubrics, or the judge model change —
  without re-running the (expensive, nondeterministic) research pipeline.

This builds on the durable-persistence and async-job decisions in
[0002](0002-hosting-auspex.md); it does **not** disturb them (see there:
*Future feature*).

## Goals

- Score a **stored** report without re-researching it.
- Drive it through MCP (`start_evaluation` → poll → result), externally scheduled,
  consistent with 0002 (Auspex has no scheduler of its own).
- Reuse the existing `evals/` scorers and the generate/score split — don't rebuild.

## Non-goals (first cut)

- Authoring new rubrics interactively, or a rubric-management UI.
- Continuous/streaming eval; this is batch, triggered.
- Comparative A/B eval across model versions (a later analysis layer).

---

## Key insight: the generate↔score split already exists

The eval suite already decouples *running the agent* from *scoring its output* —
which is exactly what "score a past report without re-research" needs:

- **`evals/generate.py`** runs the agent over a dataset and writes an **outputs
  JSONL**, one line per case: `{id, input, expected, metadata, output}`.
- **`evals/run.py --from-outputs <file>`** scores those saved outputs by *replaying*
  them (`_make_replay_agent` matches on the `input` key) — the graph is never
  invoked.
- **`evals/adapter.py`'s `run()`** already returns everything a scorer needs:
  ```python
  {"text": report,
   "data": {"text": report, "sources": [...], "critique": {...},
            "iterations_used": int, "agent_model": "provider/model"}}
  ```
- **`evals/scorers.py`** (`MustMention`, `MustNotMention`, `MinSources`) plus the
  `LLMJudge` read their criteria from `case.expected`.

So a stored MCP run, serialized into the **outputs-JSONL shape**, is directly
score-able by the existing `--from-outputs` path. The user's intuition — "persist
run data in an `eval.generate()`-similar format" — is precisely right: that format
already exists and already has a scorer.

## Sketch

### What's missing (the actual work)

1. **Persist each MCP run in the outputs shape.** `start_research` already produces
   the same fields the adapter returns; capture them durably. Per 0002, the one
   field to ensure is `agent_model` (`describe_llm()` provider/model) — without it a
   stored run can't be fairly attributed. `sources`, `critique`, and the report are
   already in scope for persistence.
2. **Source the `expected` criteria** — see below; this is the real design question.
3. **MCP eval tools** — additive, async, same pattern as research.
4. **Eval result storage** — `eval_runs` / `eval_scores` tables.
5. **Scoring execution** — reuse `assay.Eval` with a replay agent, or call the
   scorers directly on the stored record.

### The central question: where does `expected` come from?

A hand-authored eval *case* carries `expected` (rubric, `must_mention`,
`min_sources`). A **live research report has no `expected`** — nobody authored
criteria for an ad-hoc daily topic. Scheduled eval must source criteria somehow:

| Option | How | Trade-off |
|---|---|---|
| **A. Generic quality rubric** | An `LLMJudge` with a fixed "faithfulness / coverage / no-fabrication" rubric that needs no per-case fields; `MinSources` with a global threshold | No authoring; but only generic quality, not task-specific correctness |
| **B. Criteria attached at research time** | `start_research(query, …, eval_rubric=…, min_sources=…)` stores `expected` with the job | Targeted, reproducible; requires the caller to supply criteria up front |
| **C. Derive rubric from the question** | An LLM turns the question into a rubric at eval time, then judges against it | Powerful, fully automatic; the rubric itself is nondeterministic (log/cache it) |

Recommended: **A as the default** (works for any past report with zero authoring),
with **B available** when the caller wants targeted criteria. C is a later
enhancement once A's generic signal proves too coarse. Note `must_mention` /
`must_not_mention` are inherently per-case (A can't supply them), so the no-criteria
path leans on the judge + `MinSources`.

### MCP tool surface (additive — no contract break)

```python
start_evaluation(job_id: str, rubric: str | None = None) -> dict
    # {"eval_id": str, "status": "queued"}; rubric overrides the default (Option B)
get_evaluation_status(eval_id: str) -> dict
    # {"eval_id", "status": "queued|running|done|error", "error": str | None}
get_evaluation_report(eval_id: str) -> dict
    # {"eval_id", "job_id", "status", "scores": [{scorer, value, passed, explanation}]}
```

Same async-job machinery as research (enqueue, poll, retrieve). Reuses the stateless
/ external-scheduler / one-image decisions from 0002 unchanged.

### Storage (raw SQL + Alembic, per 0002)

```sql
CREATE TABLE eval_runs (
    id          TEXT         PRIMARY KEY,           -- eval_id
    job_id      TEXT         NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status      TEXT         NOT NULL,              -- queued|running|done|error
    rubric      TEXT,                               -- the criteria used (audit/repro)
    agent_model TEXT,                               -- model that produced the report
    judge_model TEXT,                               -- model that scored it
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    error       TEXT
);
CREATE TABLE eval_scores (
    id          BIGSERIAL    PRIMARY KEY,
    eval_id     TEXT         NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    scorer      TEXT         NOT NULL,              -- must_mention | min_sources | llm_judge | ...
    value       REAL         NOT NULL,
    passed      BOOLEAN,
    explanation TEXT
);
```

This is the schema growth flagged in 0002: `jobs` + `sources` + `eval_runs` +
`eval_scores` reach ~4 related tables — still fine as raw SQL, but the point at
which adopting SQLAlchemy + autogenerate would start to earn its cost.

### Dependency boundary (matters for packaging)

`assay` and the Anthropic SDK are **eval-only deps** (`evals/requirements.txt`), not
in the main `requirements.txt`. Triggering scoring in-process pulls them into
whatever runtime does it. Cleanest: scoring runs in the **worker** (which already
carries the heavy deps), not the stateless server — and `evals/requirements.txt`
gets installed there. This nudges the "one image, two entrypoints" worker toward
also being the eval runner, or a dedicated eval worker if isolation is wanted later.

---

## Recommended incremental path

1. **Persist runs in the outputs shape** (ensure `agent_model` is captured — a 0002
   item anyway).
2. **A one-shot, non-MCP `score_job(job_id)`** that loads a stored run, builds the
   outputs record, and scores it with `MinSources` + a generic `LLMJudge` (Option A).
   Prove the path end-to-end with no new MCP surface.
3. **Wrap it as the MCP eval tools** + the `eval_runs`/`eval_scores` tables.
4. **Let the external scheduler call it** daily after the report job completes.

Only later: Option B/C rubric sourcing, quality dashboards, cross-model comparison.

## Open questions

- Default rubric (A) vs caller-supplied (B) vs derived (C) — start with A, but is
  generic quality signal useful enough on its own?
- Is the canonical stored run an **evals outputs-JSONL row**, a DB row serialized to
  it on demand, or both? (Affects whether `--from-outputs` is reused verbatim.)
- Does scoring run in the research worker or a separate eval worker (dep isolation,
  cost)?
- Judge determinism: pin the judge model + cache derived rubrics so re-scores are
  comparable over time.

## Prior art

`evals/generate.py` + `evals/run.py --from-outputs` (the existing offline-scoring
split); `assay`'s `Eval` / `Scorer` / `LLMJudge`; LLM-as-judge evaluation; CI-style
regression testing applied to generative output; dataset-from-production-traffic
labeling.
