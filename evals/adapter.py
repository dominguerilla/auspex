"""Adapter wrapping the research-agent LangGraph for the assay harness.

assay calls agents as ``Callable[[dict], str | dict]``. The graph expects a
fully populated ``ResearchState`` TypedDict; this module builds that initial
state and returns the rendered report.
"""

from __future__ import annotations

from typing import Any

from graph.graph_builder import build_graph

_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _initial_state(question: str, max_iterations: int) -> dict[str, Any]:
    return {
        "research_question": question,
        "max_iterations": max_iterations,
        "iteration": 0,
        "search_queries": [],
        "search_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }


def run(input: dict) -> dict:
    """Run the research graph for one assay case.

    Returns a dict so downstream scorers can inspect ``sources`` and
    ``critique`` in addition to the report text.
    """
    question = input["question"]
    max_iterations = int(input.get("max_iterations", 2))

    final_state = _get_graph().invoke(_initial_state(question, max_iterations))

    report = final_state.get("final_report") or ""
    return {
        "text": report,
        "data": {
            "text": report,
            "sources": final_state.get("sources") or [],
            "critique": final_state.get("critique"),
            "iterations_used": final_state.get("iteration", 0),
        },
    }
