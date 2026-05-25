"""
Refiner Agent — Query Refinement from Critic Feedback
=======================================================
Runs between the critic and searcher on loop-back iterations.
Reads the critic's missing_topics and feedback, then generates
targeted replacement search queries to fill the identified gaps.

State fields read:   critique (missing_topics, feedback), research_question
State fields written: search_queries
"""

from pathlib import Path

from langchain_core.messages import HumanMessage

from graph.state import ResearchState
from llm.ollama_client import get_llm

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "refiner.txt"


def run_refiner(state: ResearchState) -> dict:
    """
    Generate new search queries targeting gaps identified by the critic.

    Parameters
    ----------
    state : ResearchState
        Reads: critique (missing_topics, feedback), research_question

    Returns
    -------
    dict
        Keys: search_queries (List[str])
    """
    llm = get_llm(temperature=0.2)
    prompt_template = _PROMPT_PATH.read_text()

    critique = state["critique"]
    missing_topics = critique["missing_topics"]
    feedback = critique["feedback"]

    # Format missing topics as a bulleted list, or fall back to the feedback alone
    if missing_topics:
        missing_str = "\n".join(f"- {topic}" for topic in missing_topics)
    else:
        missing_str = "(see feedback above)"

    prompt = prompt_template.format(
        research_question=state["research_question"],
        feedback=feedback,
        missing_topics=missing_str,
    )

    response = llm.invoke([HumanMessage(content=prompt)])
    raw_text = response.content

    queries = [
        line.strip()
        for line in raw_text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    return {"search_queries": queries}
