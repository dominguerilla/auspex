# research-agent evals

End-to-end evaluation suite for the research agent, built on
[`assay`](https://github.com/dominguerilla/assay).

The eval suite is intentionally co-located with the agent: when the graph
schema or prompts change, the adapter and rubrics change in the same commit.

## Install

The eval suite has its own dependency on `assay` and the Anthropic SDK
(used by the LLM judge). Install on top of the agent's runtime deps:

```bash
pip install -r requirements.txt
pip install -r evals/requirements.txt
```

You also need:

- A working `.env` with `LLM_PROVIDER=ollama|huggingface` (same as `main.py`).
- `ANTHROPIC_API_KEY` in the environment **if** you want to run the LLM judge.
  Skip the judge with `--no-judge`.

## Run

```bash
python -m evals.run                  # full suite (12 cases, 4 scorers)
python -m evals.run --no-judge       # programmatic scorers only
python -m evals.run --concurrency 1  # serialize (kinder to DDG + Ollama)
```

Results land in `evals/runs/<run_id>/` as JSON plus a self-contained HTML
report.

## Layout

| File | Purpose |
| --- | --- |
| `cases/cases.jsonl` | 12 hand-authored cases: factoids, explanatory, comparative, freshness, adversarial. Each carries `expected.rubric` (judge sees it) plus structured `must_mention` / `min_sources` (programmatic scorers read them). |
| `cases/single_factoid.jsonl` | Single factoid case for quick iteration. |
| `cases/__init__.py` | Package marker for the cases module. |
| `adapter.py` | Wraps `graph.invoke(state)` into the `Callable[[dict], dict]` shape `assay` expects. Returns the report text plus `sources`, `critique`, and iteration count for downstream scorers. |
| `scorers.py` | `MustMention`, `MustNotMention`, `MinSources` — read keywords/thresholds out of `case.expected`. |
| `run.py` | CLI entry point that wires the four scorers and runs the suite. |

## What the suite is testing

| Category | Cases | What it exercises |
| --- | --- | --- |
| Factoid | 2 | Cheap sanity. `max_iterations=1`. |
| Explanatory | 3 | Mechanism completeness, causal chains. |
| Comparative | 3 | Tradeoff analysis across two artifacts. |
| Freshness | 2 | Live-search dependency; will rot if the question stops being current. |
| Adversarial | 2 | Refusal to fabricate (nonexistent paper; unknowable forecast). |

## Caveats

- **Live network + LLM**: every case hits DuckDuckGo, scrapes pages, and runs
  the local LLM. A full pass is slow (minutes) and non-deterministic. Keep
  concurrency low.
- **Freshness rot**: `ra_freshness_02` is written against "the last ~12
  months" rather than a fixed version, but rubrics here will need periodic
  refresh.
- **Adversarial cases** rely entirely on the judge — there's nothing for
  programmatic scorers to check.
