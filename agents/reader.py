"""
CONCEPT: Reader Agent — Tool Use + LLM Summarisation
======================================================
Pattern: For each source → scrape → summarise → collect

The reader loops over search_results, scrapes each URL, asks the LLM to
summarise the content in relation to the research question, and writes
ScrapedSource TypedDicts to state.

What is given:
  - The loop skeleton
  - The scrape call: raw_text = scrape_url(result["url"])

What you must implement:
  - The LLM summarisation call (use prompts/reader.txt as a template)
  - try/except error handling: if scrape fails, skip that source gracefully
  - Assembly of ScrapedSource(url=..., summary=..., raw_length=...)
  - Return {"sources": [...]}

Error handling hint:
  scrape_url raises on network errors. Wrap the whole per-source block in
  try/except Exception as e: then continue to the next source.
  You can print a warning but don't crash the graph.

Summarisation hint:
  Load prompts/reader.txt, format it with {research_question} and {content},
  then call llm.invoke([HumanMessage(content=prompt)]).content

State fields read:   search_results, research_question
State fields written: sources
"""

from pathlib import Path

from langchain_core.messages import HumanMessage

from graph.state import ResearchState, ScrapedSource
from llm.ollama_client import get_llm
from tools.web_scraper import scrape_url

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "reader.txt"


def run_reader(state: ResearchState) -> dict:
    """
    Scrape and summarise each search result.

    Parameters
    ----------
    state : ResearchState
        Reads: search_results, research_question

    Returns
    -------
    dict
        Keys: sources (List[ScrapedSource])
    """
    llm = get_llm(temperature=0.2)
    prompt_template = _PROMPT_PATH.read_text()
    sources: list[ScrapedSource] = []

    for result in state["search_results"]:
        try:
            raw_text = scrape_url(result["url"])
        except Exception as e:
            print(f"[reader] scrape failed for {result['url']}: {e} — falling back to snippet")
            raw_text = result.get("snippet", "")

        if not raw_text:
            continue

        try:
            prompt = prompt_template.format(research_question=state["research_question"], content=raw_text[:4000])
            summary = llm.invoke([HumanMessage(content=prompt)]).content
            sources.append(ScrapedSource(url=result["url"], summary=summary, raw_length=len(raw_text)))
        except Exception as e:
            print(f"[reader] LLM summarisation failed for {result['url']}: {e}")

    return {"sources" : sources}
