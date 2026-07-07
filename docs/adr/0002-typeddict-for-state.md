# 0002 — Use TypedDict (not Pydantic) for LangGraph state

| | |
|---|---|
| **Status** | Accepted *(inferred — confirm)* |
| **Date** | 2026-05-28 (inferred from initial commit) |
| **Evidence** | `graph/state.py:36-96`, `LEARNING.md:117-119` |

## Context

LangGraph needs to JSON-serialise and deserialise the pipeline state for checkpointing, streaming (`astream`), and inter-node communication. The choice was between:

- **TypedDict** — zero-overhead at runtime, pure type hints, native JSON round-trips.
- **Pydantic `BaseModel`** — runtime validation, richer type coercion, but adds serialisation complexity (`.model_dump()` / `.model_validate()`) and validation overhead on every state merge.
- **dataclass** — not supported by LangGraph as a top-level state type.

## Decision

Use `TypedDict` for `ResearchState` and all sub-types (`SearchResult`, `ScrapedSource`, `CritiqueResult`). TypedDict is LangGraph's required / recommended type for state — it maps directly to a plain dict, which LangGraph can merge and serialise without extra ceremony.

## Consequences

- No runtime validation: a buggy agent that writes the wrong type into state will not be caught until a downstream consumer fails.
- State sub-types (`SearchResult`, etc.) are also TypedDicts and survive JSON serialisation intact.
- IDE autocomplete works via the type hints; mypy / pyright can catch type errors statically.
- Pydantic is still used at the HTTP boundary (`app.py:163-165` — `ResearchRequest`) where input validation is appropriate.
