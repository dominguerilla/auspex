"""
Streamlit frontend for the research agent.

Run locally:
    streamlit run streamlit_app.py

Deploy on Hugging Face Spaces:
    1. Create a new Space with SDK = "Streamlit"
    2. Push this repo
    3. In the Space settings, add these secrets:
         LLM_PROVIDER = huggingface
         HF_TOKEN     = <your HF access token>
         HF_MODEL     = meta-llama/Llama-3.1-8B-Instruct   (or any instruct model)
"""

from datetime import datetime

import streamlit as st

from graph.graph_builder import build_graph


st.set_page_config(
    page_title="Multi-Agent Research Assistant",
    page_icon=":mag:",
    layout="wide",
)

st.title("Multi-Agent Research Assistant")
st.caption(
    "A LangGraph pipeline — orchestrator, searcher, reader, critic, refiner, writer — "
    "that turns a question into a cited markdown report."
)

with st.sidebar:
    st.header("Settings")
    max_iterations = st.slider(
        "Max critique-and-revise cycles",
        min_value=1,
        max_value=5,
        value=2,
        help="How many times the critic may send the searcher back for more sources.",
    )
    st.divider()
    st.markdown(
        "**How it works**\n\n"
        "1. *Orchestrator* breaks your question into search queries\n"
        "2. *Searcher* runs web searches\n"
        "3. *Reader* scrapes and summarizes pages\n"
        "4. *Critic* judges whether the evidence is enough\n"
        "5. *Refiner* rewrites queries to fill gaps identified by the critic (on loop-back)\n"
        "6. *Writer* produces a final cited report"
    )
    st.divider()
    st.markdown(
        "[View source on GitHub](https://github.com/dominguerilla/research-agent)"
    )

question = st.text_area(
    "Research question",
    placeholder="e.g. What are the tradeoffs of Rust vs Go for backend services?",
    height=100,
)

run = st.button("Run research", type="primary", disabled=not question.strip())

NODE_LABELS = {
    "orchestrator": "Planning search queries",
    "searcher": "Running web searches",
    "reader": "Reading and summarizing sources",
    "critic": "Critiquing evidence",
    "refiner": "Refining queries to fill gaps",
    "writer": "Writing the final report",
}


@st.cache_resource
def get_graph():
    """Build the compiled graph once per session."""
    return build_graph()


def run_research(question: str, max_iterations: int):
    """Stream graph execution and yield (node_name, state_snapshot) tuples."""
    graph = get_graph()
    initial_state = {
        "research_question": question,
        "max_iterations": max_iterations,
        "iteration": 0,
        "search_queries": [],
        "search_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }
    for update in graph.stream(initial_state, stream_mode="updates"):
        # update is {node_name: partial_state}
        for node_name, partial in update.items():
            yield node_name, partial


if run:
    status = st.status("Running research graph...", expanded=True)
    final_report = None

    try:
        with status:
            for node_name, partial in run_research(question.strip(), max_iterations):
                label = NODE_LABELS.get(node_name, node_name)
                st.write(f"**{label}**")
                if node_name == "writer" and partial.get("final_report"):
                    final_report = partial["final_report"]
        status.update(label="Research complete", state="complete", expanded=False)
    except Exception as e:
        status.update(label="Research failed", state="error")
        st.error(f"Graph execution failed: {e}")
        st.stop()

    if final_report:
        st.divider()
        st.subheader("Report")
        st.markdown(final_report)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = question.strip()[:40].replace(" ", "_").replace("?", "").lower()
        st.download_button(
            "Download report (.md)",
            data=final_report,
            file_name=f"{timestamp}_{slug}.md",
            mime="text/markdown",
        )
    else:
        st.warning("The graph finished but produced no final report.")
