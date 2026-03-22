"""
CONCEPT: StateGraph Construction
==================================
Pattern: Builder pattern
  LangGraph uses a builder: you create a StateGraph, register nodes and edges,
  then call .compile() to get a runnable Pregel graph object.

  Nodes  = Python functions with signature (state: ResearchState) -> dict
  Edges  = directed connections between nodes
  Conditional edges = edges whose target depends on a routing function

What is given here:
  - All five nodes are registered (add_node calls).
  - The entry point is set.
  - The final edge (writer → END) is set.

What you must implement:
  - The linear edges: orchestrator → searcher → reader → critic
  - The conditional edge from critic using should_revise_or_write from edges.py

Hint — conditional edge syntax:
  graph.add_conditional_edges(
      "source_node",
      routing_function,          # receives state, returns a string
      {"returned_string": "target_node", ...}
  )
  The routing function must return one of the keys in the mapping dict.
"""

from langgraph.graph import StateGraph, START, END

from graph.state import ResearchState
from graph.edges import should_revise_or_write
from agents.orchestrator import run_orchestrator
from agents.searcher import run_searcher
from agents.reader import run_reader
from agents.critic import run_critic
from agents.writer import run_writer


def build_graph():
    """Construct, wire, and compile the research graph."""
    graph = StateGraph(ResearchState)

    # --- Register nodes ---
    # Each string name becomes addressable as a node in add_edge / add_conditional_edges.
    graph.add_node("orchestrator", run_orchestrator)
    graph.add_node("searcher", run_searcher)
    graph.add_node("reader", run_reader)
    graph.add_node("critic", run_critic)
    graph.add_node("writer", run_writer)

    # --- Entry point ---
    graph.add_edge(START, "orchestrator")

    # --- TODO: Wire the linear chain ---
    # Connect orchestrator → searcher → reader → critic in sequence.
    # Syntax: graph.add_edge("source", "target")
    #
    # YOUR CODE HERE

    # --- TODO: Wire the conditional edge from critic ---
    # After the critic runs, call should_revise_or_write(state) to decide next node.
    # should_revise_or_write returns either "searcher" or "writer" (strings).
    # Use graph.add_conditional_edges with a mapping dict.
    #
    # YOUR CODE HERE

    # --- Terminal edge (given) ---
    graph.add_edge("writer", END)

    return graph.compile()
