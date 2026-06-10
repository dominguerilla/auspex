# 0001 — Source Router: Pluggable, Classified Research Sources

| | |
|---|---|
| **Status** | Proposed |
| **Created** | 2026-06-10 |
| **Owner** | Carlos |
| **Related** | `tools/web_search.py`, `tools/web_scraper.py`, `agents/searcher.py`, `agents/critic.py`, `graph/state.py`, `evals/` |

> A design sketch, not a commitment. The goal is that a future reader can decide
> whether this is worth building and start without re-deriving the discussion.

---

## Problem

Today every search goes through a single seam — `web_search(query) -> [{title, url, snippet}]`
in `tools/web_search.py`, backed only by DuckDuckGo. Two weaknesses surfaced while
running the humanities eval set (`evals/cases/humanities.jsonl`):

1. **One generic provider.** DDG returns SEO-grade web results and rate-limits
   (HTTP 429). For a question that is partly empirical ("how do cognitive and
   neurological science explain memory palaces?"), it never reaches the
   scholarly literature that would actually answer it.
2. **The scraper gets blocked.** The strong academic hits (ScienceDirect,
   ResearchGate, PsycNet, SSRN) returned `403`/`429` to `web_scraper.scrape_url`,
   so the report fell back to blog-grade sources and drifted into filler. The
   LLM judge correctly scored it ~0.4 — a *true* fail caused by source quality,
   not by the agent's reasoning.

We want a way to (a) tap **multiple, heterogeneous sources**, (b) each with its
own config/secrets and a notion of **when it's relevant**, and (c) let an agent
**decide which sources to use** — either up front or dynamically as gaps appear.

## Goals

- A provider plugin contract: secrets/config, availability, and self-described relevance.
- A router that selects providers per *query* (not per top-level question).
- Sources that return content directly should bypass the scraper.
- Graceful degradation: a missing key or a rate-limited provider never kills a run.
- Observable, evaluable routing decisions.

## Non-goals (for the first cut)

- A learned/feedback-trained classifier.
- A full LLM-judged router over the entire provider universe.
- Parallel/async fan-out (nice later; not required to prove the idea).

---

## Sketch

### Provider contract (the "plugin")

Each source is a small module exposing a **manifest** plus a search call:

```
class Provider:
    name: str
    def is_available(self) -> bool        # key/config present? never raises, never logs the key
    def relevance(self, query) -> float   # "when to use me" — topic coverage signal
    returns_content: bool                  # True => feed text straight to the reader, skip scrape_url
    cost_class: "free" | "metered" | "paid"
    def search(self, query) -> list[Result]
```

`Result` should be a **superset** of today's `{title, url, snippet}` with optional
provenance fields — see "Schema" below.

### Where the decision lives

The graph already has the two hooks:

- **Orchestrator** — natural home for *up-front* classification (coarse: is this
  academic? current-events? primary-text? esoteric/humanities?).
- **Critic loop** — natural signal for *dynamic escalation*. Today the critic
  only says pass/fail; if it also said *why* it failed (insufficient coverage vs
  insufficient authority vs stale), the router would know *what kind* of source
  to add on the next iteration instead of blindly re-searching.

Recommended shape: **tiered escalation**.

| Tier | Sources | When |
|---|---|---|
| 1 (broad/free) | Wikipedia, DDG | Always — cheap baseline |
| 2 (scholarly) | OpenAlex, Semantic Scholar, PubMed/Europe PMC, arXiv | Academic/empirical claims, or when tier 1 is judged thin on authority |
| 3 (metered/paid) | Tavily, Serper, Exa | Only when 1–2 leave a gap the critic flags |

Routing attaches to each generated search query, because one question can span
tiers (the memory-palace case is humanities **and** neuroscience at once).

### Classification mechanism

Start rule-based and cheap; escalate the *mechanism* only if it mis-routes:

| Mechanism | Pros | Cons |
|---|---|---|
| Keyword/regex on the query | Deterministic, debuggable, free | Brittle |
| LLM tags query → domains, match to manifests | Flexible | Latency, cost, nondeterminism |
| Embedding similarity (query ↔ provider description) | Semantic, no per-call LLM | Opaque, needs embeddings |
| Learned from eval feedback | Improves over time | Needs logging + closed eval loop |

Hybrid is the sweet spot: **hard-filter** by `is_available()` and budget first,
then rank the survivors (rules now, LLM/embedding later).

### Schema (extend, don't replace)

Flattening scholarly metadata to `{title, url, snippet}` discards the exact
**provenance** signal that would have rescued the memory-palace run. Add optional
fields so the writer/critic can prefer authoritative sources:

```
{ title, url, snippet,
  content?,           # full text if the provider returns it
  source_type?,       # web | encyclopedia | preprint | peer_reviewed | primary_text
  authority_score?,   # provider- or citation-derived
  published_date?,
  provider? }
```

### Cross-cutting concerns

- **Budget & circuit-breaking.** Per-run query budget, per-provider quotas, and a
  breaker: when a provider throws a 403/429 storm, bench it for the rest of the
  run. (`web_search` already degrades to `[]` on error — formalize that into
  health state.)
- **Dedup & fusion.** The same paper arrives from multiple providers; canonicalize
  by URL/DOI/title-similarity, then merge with reciprocal-rank fusion or
  authority weighting instead of naive concatenation.
- **State (`graph/state.py`).** Add `available_sources`, `selected_sources`,
  `tapped_sources` (history, to avoid re-tapping), `routing_rationale`. The
  tapped-source history wants **append/merge** semantics (a custom reducer like
  `add_messages`), not last-write-wins.
- **Loop safety.** Cap total sources; reuse `max_iterations`; detect diminishing
  returns (new source adds no new info); provide a graceful "report with caveats"
  exit when sources are exhausted (which the adversarial eval cases already reward).
- **Secrets.** Provider availability is a function of config presence; an
  unconfigured provider advertises itself unavailable and is excluded. Never log
  keys. (Mirror the existing `LLM_PROVIDER` env pattern, per-provider; consider a
  `SEARCH_PROVIDER` / per-provider env vars.)

### Eval implications (closes the loop with `evals/`)

A router is a new decision-maker, so measure it:

- Log which sources were tapped per case + the rationale.
- Add a scorer for **provenance appropriateness** ("did a scientific claim get a
  scholarly source?") — encodes the memory-palace lesson directly.
- An LLM router reduces reproducibility (same input, different route); log and/or
  cache decisions so eval runs stay comparable.

---

## Recommended incremental path

Don't build the cathedral. ~80% of the value is in:

1. **Provider registry** with declarative manifests (`is_available`, coarse topic
   tags, `returns_content`).
2. **Rule-based router** with a coarse classifier (academic / current-events /
   primary-text / general).
3. **Two or three tiers** with critic-driven escalation.

Prove it with two providers behind the existing `web_search` seam —
**Wikipedia** (clean extracts, no scraping, good for the esoteric/humanities
cases) and **OpenAlex** (no API key, no cost, returns abstracts — fixes the
scholarly gap and the 403 problem at once). Re-run the memory-palace case and
confirm the judge score rises. Add the LLM-judged router and the learned
classifier only once the rule-based one demonstrably mis-routes.

## Open questions

- Per-query routing vs per-sub-claim routing — how granular before it's not worth it?
- Does the critic emit a structured gap reason, or does the router re-infer gaps
  from the draft?
- Where does fusion live — in the searcher, or a new `merge`/`rank` node?
- Is async fan-out worth the error-handling/rate-accounting complexity at this scale?

## Prior art

RAG "router retrievers" and query routing; LangChain router chains; MCP server
selection; ensemble retrievers / reciprocal-rank fusion; the general
tool-selection-at-scale problem.
