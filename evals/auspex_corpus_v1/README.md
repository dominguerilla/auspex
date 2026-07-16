# Auspex corpus eval suite (`auspex_corpus_v1`)

The 25-case, hand-authored evaluation suite for the flat-retrieval A/B experiment
(build plan Phase 1 §1.3). It is the **measurement instrument**: frozen against
corpus commit `9b8b08f` and reused unchanged in Phase 2, so the graph-vs-flat
comparison runs on exactly these cases.

**Author these by hand.** The whole point of the experiment is an *uncorrelated*
instrument — questions a human maintainer actually asks, not questions shaped by
what an LLM finds easy to ask/answer/judge. See `TOPIC_INVENTORY.md` for raw
candidate material (subsystems + where answers live) to draw from without having
the questions pre-written for you.

## Tiers

| Tier | Count | Tests | ID prefix |
|---|---|---|---|
| T1 factual lookup | 8 | single-file fact | `t1_lookup_*` |
| T2 multi-file synthesis | 8 | cross-file assembly | `t2_synth_*` |
| T3 design rationale | 7 | *why*, not what (gold usually lives in an ADR) | `t3_rationale_*` |
| T4 trap | 2 | correct declination — refusing to fabricate | `t4_trap_*` |

T4 traps ask about things the corpus **does not contain**; the correct answer
states the premise is false / not present. They matter most in the **web-only**
condition, where the model has nothing to check against — they're the
hallucination canaries.

## The A/B condition is NOT stored in the case

A case defines one **question**; the retrieval condition (`off` = web-only
baseline, `on` = corpus) is swept at **run time**, not baked in — otherwise
you'd store every question twice and risk them drifting apart. The run harness
(§1.5) supplies `retrieval` per condition; `evals/adapter.py` already reads it.
So: 25 cases × 2 conditions × 3 seeds = 150 runs, all from this one file.

Keep everything else identical across conditions (`max_iterations`, model,
temperature) — that discipline is what makes the delta attributable to retrieval.

## Case schema

```jsonc
{
  "id": "t1_lookup_01",
  "input": {
    "question": "",           // the question, verbatim as asked
    "max_iterations": 2        // controlled variable — keep constant across the suite
  },
  "expected": {
    "gold_answer": "",         // the correct answer (or, for T4, the correct declination)
    "grounding_files": [],     // repo paths a correct answer must be grounded in.
                               //   Required for T1-T3; empty for T4 (nothing to ground).
                               //   Every path is checked to exist at corpus_commit.
    "must_mention": [],        // optional: literal strings a programmatic scorer requires
    "must_not_mention": [],    // optional: strings whose presence signals fabrication
    "min_sources": 1,          // programmatic floor on cited sources
    "rubric": ""               // instructions for the LLM judge (correctness + faithfulness)
  },
  "metadata": {
    "tier": "T1",
    "corpus_commit": "9b8b08fd4c7ac74e4b0c1d02f664faa32dd6b031",
    "notes": ""                // optional: why this case belongs in its tier, gotchas
  }
}
```

`gold_answer`, `grounding_files`, and `tier` are the corpus-suite extensions;
`must_mention` / `must_not_mention` / `min_sources` / `rubric` are read by the
existing scorers (`evals/scorers.py`) and the LLM judge, so this suite runs on
the same harness as `evals/cases/`.

### Authoring guidance

- **`grounding_files`** — the files a correct answer *must* rest on. For T1 that's
  usually one path; for T2 it's the set the answer has to assemble across. These
  are load-bearing in Phase 2 (graph nodes point at these files), so be exact.
  `validate.py` checks each path exists at `9b8b08f` — a rename won't slip through.
- **`rubric`** — write it so a judge who hasn't seen the code can grade: state the
  facts that must appear and what to penalize. For T4, the rubric should reward
  explicitly saying the thing doesn't exist and penalize any invented mechanism.
- **`must_mention`** — reserve for unambiguous literals (a symbol name, a number,
  a file path). Don't force natural-language phrasings through it; that's the
  judge's job.
- **T4 traps** — leave `grounding_files` empty; lean on `rubric`. `must_not_mention`
  is awkward here (a correct answer *does* say the trap's noun, e.g. "there is no
  Redis layer"), so use it only for fabricated specifics if at all.

### Illustrative row (NOT one of the 25 — shows a filled case)

```json
{"id": "example_illustrative", "input": {"question": "Which Python versions does CI run the test suite on?", "max_iterations": 2}, "expected": {"gold_answer": "CI runs pytest on Python 3.10 and 3.12 (see the test workflow matrix).", "grounding_files": [".github/workflows/test.yml"], "must_mention": ["3.10", "3.12"], "must_not_mention": [], "min_sources": 1, "rubric": "Must state both 3.10 and 3.12. Penalize other versions or a single-version answer."}, "metadata": {"tier": "T1", "corpus_commit": "9b8b08fd4c7ac74e4b0c1d02f664faa32dd6b031", "notes": "Illustrative only — replace with your own."}}
```

## Validate as you author

```sh
python -m evals.auspex_corpus_v1.validate                  # progress + structural checks
python -m evals.auspex_corpus_v1.validate --require-complete   # gate: fail on any TODO
```

It checks the tier counts (8/8/7/2), required fields, and that every
`grounding_files` path exists at the pinned commit. It does **not** run the
pipeline — that's the scorer/run work in §1.4–§1.5.

## Known confound: public-repo leakage in the baseline

The corpus is this repo, and it is **public** on GitHub
(`github.com/dominguerilla/auspex`). So the web-only baseline (`retrieval=off`)
has a potential backdoor to the corpus: if its DuckDuckGo search surfaces the
repo, its scraper can read answers straight from the public README/code — many
T1/T2 facts are stated there (providers, MCP tool names, node names, SQLite,
Python versions). A few are corpus-only (bearer/`AUSPEX_MCP_TOKEN`, the Anthropic
provider, deep code internals like `ThreadPoolExecutor(max_workers=3)`).

Whether it actually leaks is empirical — "Auspex" is an overloaded search term
and the queries never name the owner, so ranking is likely weak — but it must be
**measured, not assumed**.

**Do NOT mitigate by blocklisting GitHub from the baseline's search.** That
changes the search between conditions, violates the single-codepath rule (§1.0),
and biases the experiment toward retrieval. The baseline stays honest, backdoor
and all.

**§1.5 readout requirement — measure the leakage as a covariate:**

- For each **baseline** (`retrieval=off`) run, scan `data["sources"]` URLs for the
  repo domains (`github.com/dominguerilla/auspex`,
  `raw.githubusercontent.com/dominguerilla/auspex`). Record a per-run
  `reached_repo` boolean.
- In `results/phase1_readout.md`, report the **leakage rate per tier** alongside
  the on/off faithfulness/correctness deltas.
- Interpret accordingly:
  - **leakage ≈ 0** → clean on-vs-off, as originally framed;
  - **leakage high** → the comparison is honestly "structured pgvector retrieval
    vs. a web baseline that can reach the public repo" — a harder, more realistic
    baseline. Corpus winning it is a stronger result; a tie is still a real finding.

## Status

- [x] Scaffolding, schema, validator (§1.3 structure)
- [ ] 25 questions authored (yours to write)
- [ ] Faithfulness + correctness scorers wired against `gold_answer` /
      `grounding_files` (§1.4)
- [ ] κ calibration on ~15 answers (§1.4)
- [ ] 150-run protocol + `results/phase1_readout.md` (§1.5)
- [ ] Baseline repo-leakage covariate in the readout (see "Known confound" above) (§1.5)
