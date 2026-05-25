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

from langchain_core.messages import AIMessage, HumanMessage

from graph.state import CritiqueResult, ResearchState
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

    lines = raw_text.splitlines()
    passed, verdict_idx = find_verdict(lines)
    feedback_lines, missing_idx = find_feedback_and_missing(verdict_idx, lines)
    missing_topics = get_missing_topics(missing_idx, lines)
    feedback = "\n".join(feedback_lines).strip()
    critique = CritiqueResult(passed=passed, feedback=feedback, missing_topics=missing_topics)

    new_iteration = state["iteration"] + 1

    return {"critique" : critique, "iteration" : new_iteration, "messages" : [AIMessage(content=raw_text)]}


def find_verdict(lines: list[str]) -> tuple[bool, int | None]:
    passed = False
    verdict_line = None
    for i, line in enumerate(lines):
        upper = line.strip().upper()
        if upper == "PASSED":
            passed = True
            verdict_line = i
            break
        elif upper == "FAILED":
            passed = False
            verdict_line = i
            break
    return (passed, verdict_line)


def find_feedback_and_missing(start_idx: int | None, lines: list[str]) -> tuple[list[str], int | None]:
    feedback_lines = []
    missing_idx = None
    if start_idx is not None:
        for i, line in enumerate(lines[start_idx + 1:]):
            if line.strip().upper().startswith("MISSING:"):
                missing_idx = start_idx + 1 + i
                break
            else:
                feedback_lines.append(line)

    return (feedback_lines, missing_idx)


def get_missing_topics(idx: int | None, lines: list[str]) -> list[str]:
    missing_topics = []
    if idx is not None:
        missing_line = lines[idx]
        colon_idx = missing_line.index(":")
        missing_topics = [topic.strip() for topic in missing_line[colon_idx + 1:].split(",") if topic.strip()]

    return missing_topics
