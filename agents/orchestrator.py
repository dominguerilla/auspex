"""
CONCEPT: Orchestrator Agent — Query Generation
================================================
Pattern: LLM call → structured output via text parsing

The orchestrator's job: take the research_question and produce a list of search
queries that a searcher can execute. More/better queries → better sources.

What is given:
  - Loading the prompt template from prompts/orchestrator.txt
  - The LLM call (llm.invoke returns an AIMessage; .content is the string)

What you must implement:
  - Parsing the LLM's text response into a Python List[str]
  - The LLM will output numbered lines or bullet points — split and clean them
  - Updating state: return {"search_queries": [...], "messages": [...]}

Parsing hint:
  The prompt instructs the model to output one query per line, optionally
  prefixed with "1.", "2.", "-", or "*". A robust parser strips those prefixes.
  Try: [line.lstrip("0123456789.-* ").strip() for line in text.splitlines() if line.strip()]

State fields written:
  search_queries : List[str]
  messages       : append AIMessage for debug trace (optional but helpful)
"""

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from graph.state import ResearchState
from llm.ollama_client import get_llm

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "orchestrator.txt"


def run_orchestrator(state: ResearchState) -> dict:
    """
    Generate search queries from the research question.

    Parameters
    ----------
    state : ResearchState
        Reads: research_question

    Returns
    -------
    dict
        Keys: search_queries, messages
    """
    llm = get_llm(temperature=0.2)
    prompt_template = _PROMPT_PATH.read_text()

    # Fill the prompt template (uses Python .format() — see prompts/orchestrator.txt)
    prompt = prompt_template.format(research_question=state["research_question"])

    # LLM call — returns AIMessage; .content is the raw text string
    response = llm.invoke([HumanMessage(content=prompt)])
    raw_text = response.content

    # According to docs online about AIMessage, raw_text is str | list[str | dict] | None
    if not raw_text:
        # I'm not sure in what scenarios an AIMessage's content would be null.
        # Raising an exception for now. Might be a better way to handle this.
        raise Exception("Response content is null!")
    stripped_list = [ line.lstrip("1234567890.-* ").strip() for line in raw_text.splitlines() if line.strip()]

    return {
        "search_queries" : stripped_list,
        "messages" : [AIMessage(content=raw_text)]
    }
