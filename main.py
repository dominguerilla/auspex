"""
CONCEPT: CLI Entry Point + Graph Invocation
============================================
Pattern: Parse args → build initial state → invoke graph → write output

main.py is the only file that knows about the outside world: CLI arguments,
the filesystem, and the final output path. The graph itself is pure — it
takes state in and returns state out.

What is given:
  - argparse setup (research question, max_iterations, output directory)
  - Output path construction

What you must implement:
  - Import and call build_graph() to get the compiled graph
  - Construct the initial ResearchState dict
  - Call graph.invoke(initial_state) → returns final state dict
  - Extract state["final_report"] and write it to the output path
  - Print a success message with the output file path

Initial state hint:
  The state must satisfy ResearchState's TypedDict schema. You need to
  provide values for all non-Optional fields. Optional fields (critique,
  final_report) can be set to None. List fields (search_queries,
  search_results, sources) start as empty lists. messages starts as [].

  initial_state = {
      "research_question": args.question,
      "max_iterations": args.max_iterations,
      "iteration": 0,
      "search_queries": [],
      "search_results": [],
      "sources": [],
      "critique": None,
      "final_report": None,
      "messages": [],
  }

invoke() hint:
  final_state = graph.invoke(initial_state)
  report = final_state["final_report"]
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

from graph.graph_builder import build_graph

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

def parse_args():
    parser = argparse.ArgumentParser(
        description="Multi-agent research assistant powered by LangGraph + Ollama"
    )
    parser.add_argument(
        "question",
        type=str,
        help='The research question to investigate (e.g. "What are the tradeoffs of Rust vs Go?")',
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=2,
        help="Maximum critique-and-revise cycles before writing (default: 2)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Directory to write the report into (default: output/)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Build output path with timestamp to avoid collisions
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = args.question[:40].replace(" ", "_").replace("?", "").lower()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"{timestamp}_{slug}.md"

    logger.info("Research question: %s", args.question)
    logger.info("Max iterations:    %d", args.max_iterations)
    logger.info("Output path:       %s", output_path)

    graph = build_graph()
    initial_state = {
        "research_question": args.question,
        "max_iterations": args.max_iterations,
        "iteration": 0,
        "search_queries": [],
        "search_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }
    logger.info("Running research graph...")
    final_state = graph.invoke(initial_state)
    report = final_state["final_report"]
    output_path.write_text(report, encoding="utf-8")
    logger.info("\nReport written to: %s", output_path)


if __name__ == "__main__":
    main()
