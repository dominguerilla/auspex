"""
CONCEPT: Writer Agent — Prompt Assembly + Final Output
=======================================================
Pattern: Aggregate state → build rich prompt → LLM writes report

The writer is the terminal node. It has access to everything accumulated in
state: the original question, all scraped sources with summaries, and the
critic's final feedback. Its job is to assemble a coherent research report.

What you must implement (entire function body):
  - Load prompts/writer.txt
  - Build a sources block from state["sources"] (url + summary for each)
  - Format the prompt with research_question, sources_text, and critique feedback
  - Call the LLM (use temperature=0.5 for more natural prose)
  - Return {"final_report": report_text}

Prompt assembly hint:
  sources_text = "\n\n".join(
      f"### {s['url']}\n{s['summary']}" for s in state["sources"]
  )
  critique_feedback = state["critique"]["feedback"] if state["critique"] else "N/A"

State fields read:   research_question, sources, critique
State fields written: final_report
"""

from pathlib import Path

from langchain_core.messages import HumanMessage

from graph.state import ResearchState, RetrievedChunk
from llm.contract import CITATION_FORMAT_HINT
from llm.ollama_client import get_llm

_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "writer.txt"


def corpus_citation_id(chunk: RetrievedChunk) -> str:
    """The identifier the writer cites a corpus chunk by: ``path:Lstart-Lend``.

    This is the corpus analogue of a web source's URL — it points citations at
    file+line, which is what makes the faithfulness scorer checkable.
    """
    start, end = chunk.get("start_line"), chunk.get("end_line")
    lines = f":L{start}-L{end}" if start is not None else ""
    return f"{chunk['file_path']}{lines}"


def render_sources(state: ResearchState) -> str:
    """Combine web sources and corpus chunks into one citable source block.

    Each entry's ``### <identifier>`` heading is the exact string the writer must
    cite it by. Corpus chunks are only present when retrieval is "on"; when the
    list is empty this renders exactly the web-only block it always did.
    """
    blocks = [f"### {s['url']}\n{s['summary']}" for s in state["sources"]]
    blocks += [
        f"### {corpus_citation_id(c)}\n{c['content']}"
        for c in state.get("corpus_results", [])
    ]
    return "\n\n".join(blocks)


def run_writer(state: ResearchState) -> dict:
    """
    Write the final research report from accumulated sources.

    Parameters
    ----------
    state : ResearchState
        Reads: research_question, sources, critique

    Returns
    -------
    dict
        Keys: final_report (str)
    """
    llm = get_llm(temperature=0.5)
    prompt_template = _PROMPT_PATH.read_text()

    sources_text = render_sources(state)
    critique_feedback = state["critique"]["feedback"] if state["critique"] else "N/A"
    prompt = prompt_template.format(
        research_question=state["research_question"],
        sources_text=sources_text,
        critique_feedback=critique_feedback,
        citation_format=CITATION_FORMAT_HINT,
    )
    report_text = llm.invoke([HumanMessage(content=prompt)]).content
    return {"final_report": report_text}
