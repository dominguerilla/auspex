"""
CONCEPT: LangGraph State
=========================
This file is given complete. Trace every field to the agent that writes it.

In LangGraph, STATE is the single source of truth that flows through the graph.
Every node receives the current state as input and returns a dict of updates.
LangGraph merges those updates into the state before calling the next node.

TypedDict vs dataclass:
  LangGraph requires TypedDict (not dataclass, not Pydantic model) for the
  top-level state. TypedDict is just a type-hint container — no runtime overhead.

Reducers:
  The `messages` field uses Annotated[List[BaseMessage], add_messages].
  `add_messages` is a REDUCER — instead of replacing the list on each update,
  LangGraph appends new messages. This is why agents can write
    return {"messages": [AIMessage(content="...")]}
  and the list grows rather than being overwritten.

  All other fields use the DEFAULT reducer, which is plain assignment (last write wins).
  That's intentional: search_results from the searcher should replace, not accumulate.

Fields to trace:
  research_question → set once at invocation (main.py), read by orchestrator + writer
  search_queries    → orchestrator writes, searcher reads
  iteration         → critic increments each loop, edges.py reads to enforce max_iterations
  max_iterations    → set at invocation, never mutated
  search_results    → searcher writes (list of SearchResult dicts)
  sources           → reader writes (list of ScrapedSource dicts)
  critique          → critic writes (CritiqueResult dict), edges.py reads .passed
  final_report      → writer writes, main.py reads for file output
  messages          → every agent MAY append for debug tracing (optional but useful)
"""

from __future__ import annotations

from typing import Annotated, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# ---------------------------------------------------------------------------
# Sub-types (used as TypedDicts so they survive JSON serialisation in state)
# ---------------------------------------------------------------------------

class SearchResult(TypedDict):
    """One result from DuckDuckGo (or any search backend)."""
    title: str
    url: str
    snippet: str


class ScrapedSource(TypedDict):
    """One web page after scraping + LLM summarisation."""
    url: str
    summary: str          # produced by reader agent's LLM call
    raw_length: int       # character count before summarisation (useful for debugging)


class CritiqueResult(TypedDict):
    """Critic's structured evaluation of the research so far."""
    passed: bool          # True → proceed to writer; False → loop back to searcher
    feedback: str         # Free-text explanation; searcher uses this for next queries
    missing_topics: List[str]  # Specific gaps; orchestrator can use these on re-run


# ---------------------------------------------------------------------------
# Top-level state
# ---------------------------------------------------------------------------

class ResearchState(TypedDict):
    # --- Input (set once at invocation) ---
    research_question: str
    max_iterations: int

    # --- Orchestrator writes ---
    search_queries: List[str]

    # --- Loop counter (critic increments) ---
    iteration: int

    # --- Searcher writes ---
    search_results: List[SearchResult]

    # --- Reader writes ---
    sources: List[ScrapedSource]

    # --- Critic writes ---
    critique: Optional[CritiqueResult]

    # --- Writer writes ---
    final_report: Optional[str]

    # --- Debug trace (append-only via add_messages reducer) ---
    messages: Annotated[List[BaseMessage], add_messages]
