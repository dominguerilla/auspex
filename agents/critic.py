"""
CONCEPT: Critic Agent — Structured Output Parsing
===================================================
Pattern: LLM call → parse structured fields from text response

The critic evaluates whether the collected sources adequately cover the
research question. It outputs a structured CritiqueResult and increments
the iteration counter.

What is given:
  - The LLM call and raw response extraction
  - The iteration increment (IMPORTANT: always return this)

What you must implement:
  - Parsing the LLM's response into a CritiqueResult TypedDict
  - The prompt instructs the model to output PASSED/FAILED on one line,
    then feedback, then optionally a MISSING: line

Parsing strategy:
  Look for "PASSED" or "FAILED" in the text (case-insensitive).
  Everything after that line is feedback.
  Look for a "MISSING:" line and split on commas for missing_topics.
  Default passed=False if parsing is ambiguous (conservative).

State fields read:   sources, research_question, iteration
State fields written: critique (CritiqueResult), iteration (incremented)
"""

from pathlib import Path

from langchain_core.messages import HumanMessage, AIMessage

from graph.state import ResearchState, CritiqueResult
from llm.ollama_client import get_llm

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "critic.txt"


def run_critic(state: ResearchState) -> dict:
    """
    Evaluate research coverage and produce a structured critique.

    Parameters
    ----------
    state : ResearchState
        Reads: sources, research_question, iteration

    Returns
    -------
    dict
        Keys: critique (CritiqueResult), iteration (int), messages
    """
    llm = get_llm(temperature=0.1)
    prompt_template = _PROMPT_PATH.read_text()

    # Build a summary of sources for the prompt
    sources_text = "\n\n".join(
        f"Source: {s['url']}\n{s['summary']}" for s in state["sources"]
    )

    prompt = prompt_template.format(
        research_question=state["research_question"],
        sources_text=sources_text,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    raw_text = response.content

    # TODO: Parse raw_text into a CritiqueResult TypedDict.
    # The prompt asks the model to output:
    #   Line 1: "PASSED" or "FAILED"
    #   Line 2+: Feedback text
    #   Optional: "MISSING: topic1, topic2, ..."
    #
    # Parse each part and construct:
    #   CritiqueResult(passed=..., feedback=..., missing_topics=[...])
    #
    # YOUR CODE HERE
    raise NotImplementedError("Implement CritiqueResult parsing in agents/critic.py")

    # IMPORTANT: Always return iteration incremented by 1.
    # The conditional edge reads this to enforce max_iterations.
    new_iteration = state["iteration"] + 1

    # TODO: Return {"critique": critique, "iteration": new_iteration, "messages": [AIMessage(content=raw_text)]}
