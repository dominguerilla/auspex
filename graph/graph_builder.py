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

from langgraph.graph import END, START, StateGraph

from agents.critic import run_critic
from agents.orchestrator import run_orchestrator
from agents.reader import run_reader
from agents.refiner import run_refiner
from agents.searcher import run_searcher
from agents.writer import run_writer
from graph.edges import should_revise_or_write
from graph.state import ResearchState


def build_graph():
    """Construct, wire, and compile the research graph."""
    graph = StateGraph(ResearchState)

    # --- Register nodes ---
    # Each string name becomes addressable as a node in add_edge / add_conditional_edges.
    graph.add_node("orchestrator", run_orchestrator)
    graph.add_node("searcher", run_searcher)
    graph.add_node("reader", run_reader)
    graph.add_node("critic", run_critic)
    graph.add_node("refiner", run_refiner)
    graph.add_node("writer", run_writer)

    # --- Entry point ---
    graph.add_edge(START, "orchestrator")

    graph.add_edge("orchestrator","searcher")
    graph.add_edge("searcher","reader")
    graph.add_edge("reader","critic")

    graph.add_conditional_edges(
            "critic",
            should_revise_or_write,
            {"refiner": "refiner", "writer": "writer"}
            )

    graph.add_edge("refiner", "searcher")

    # --- Terminal edge (given) ---
    graph.add_edge("writer", END)

    return graph.compile()
