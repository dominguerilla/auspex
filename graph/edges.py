"""
CONCEPT: Conditional Edges / Routing Functions
================================================
This is the architectural centerpiece of the graph.

A routing function receives the FULL state and returns a STRING that LangGraph
maps to the next node name. This is what makes the graph non-linear — instead
of a fixed pipeline, the graph can branch based on data in state.

Why a pure function?
  should_revise_or_write has no side effects and no LLM calls. It only reads
  state fields. This makes it trivially unit-testable:

    assert should_revise_or_write({"critique": {"passed": True}, "iteration": 0, "max_iterations": 3}) == "writer"
    assert should_revise_or_write({"critique": {"passed": False}, "iteration": 0, "max_iterations": 3}) == "searcher"
    assert should_revise_or_write({"critique": {"passed": False}, "iteration": 3, "max_iterations": 3}) == "writer"

State fields to read:
  state["critique"]["passed"]   — bool set by critic agent
  state["iteration"]            — int incremented by critic agent
  state["max_iterations"]       — int set at invocation, never mutated
"""

from graph.state import ResearchState


def should_revise_or_write(state: ResearchState) -> str:
    """
    Routing function for the conditional edge after the critic node.

    Returns
    -------
    "searcher"  — critique failed AND we haven't hit the iteration cap
    "writer"    — critique passed OR we've exhausted allowed iterations
    """
    # TODO: Read state["critique"]["passed"] and compare state["iteration"] to state["max_iterations"].
    # Return "writer" if research is good enough or we're out of retries.
    # Return "searcher" to loop back and gather more sources.
    #
    # Hint: the critic increments state["iteration"] before this function runs,
    # so iteration=1 means one critique cycle has already completed.
    #
    # YOUR CODE HERE
    raise NotImplementedError("Implement should_revise_or_write in graph/edges.py")
