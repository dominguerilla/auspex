"""Tests for the corpus_retriever node and its consumption by writer/critic.

Fully mocked: the embedder and the psycopg2 connection are patched, so these
run with no Ollama and no Postgres (same discipline as the rest of the suite).
"""

from unittest.mock import MagicMock, patch

from graph.state import ResearchState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _state(**overrides) -> ResearchState:
    base = {
        "research_question": "How does auth work?",
        "max_iterations": 2,
        "retrieval": "off",
        "iteration": 0,
        "search_queries": [],
        "search_results": [],
        "corpus_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }
    base.update(overrides)
    return base  # type: ignore[return-value]


def _row(id_, path, start, end, distance):
    """A RealDictCursor-style row as the retrieval SQL would return."""
    return {
        "id": id_,
        "file_path": path,
        "start_line": start,
        "end_line": end,
        "commit_sha": "9b8b08f",
        "content": f"content of {path}",
        "distance": distance,
    }


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return self.rows


class _FakeConn:
    def __init__(self, rows):
        self.cur = _FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cur

    def close(self):
        self.closed = True


# ---------------------------------------------------------------------------
# Gating: inert unless retrieval == "on"
# ---------------------------------------------------------------------------

def test_inert_when_retrieval_off():
    from agents import corpus_retriever
    with patch.object(corpus_retriever, "_retrieve") as mock_retrieve:
        result = corpus_retriever.run_corpus_retriever(_state(retrieval="off"))
    assert result == {"corpus_results": []}
    mock_retrieve.assert_not_called()  # no embedding, no DB when off


def test_inert_when_retrieval_key_absent():
    from agents import corpus_retriever
    state = _state()
    del state["retrieval"]  # simulate a pre-flag / web-only entrypoint state
    with patch.object(corpus_retriever, "_retrieve") as mock_retrieve:
        result = corpus_retriever.run_corpus_retriever(state)
    assert result == {"corpus_results": []}
    mock_retrieve.assert_not_called()


def test_active_passes_through_retrieved_chunks():
    from agents import corpus_retriever
    sample = [
        {"chunk_id": 1, "file_path": "a.py", "start_line": 1, "end_line": 9,
         "commit_sha": "9b8b08f", "content": "x", "similarity": 0.9, "source": "corpus"},
    ]
    with patch.object(corpus_retriever, "_retrieve", return_value=sample) as mock_retrieve:
        result = corpus_retriever.run_corpus_retriever(_state(retrieval="on"))
    mock_retrieve.assert_called_once_with("How does auth work?")
    assert result == {"corpus_results": sample}


# ---------------------------------------------------------------------------
# _retrieve: row -> RetrievedChunk mapping, similarity, top-k
# ---------------------------------------------------------------------------

def test_retrieve_maps_rows_and_computes_similarity():
    from agents import corpus_retriever
    rows = [
        _row(10, "graph/state.py", 72, 118, 0.1),
        _row(11, "app.py", 5, 40, 0.25),
    ]
    embedder = MagicMock()
    embedder.embed_query.return_value = [0.0] * 768
    with patch("llm.embeddings.get_embedder", return_value=embedder), \
         patch.object(corpus_retriever, "_get_conn", return_value=_FakeConn(rows)) as conn_factory:
        chunks = corpus_retriever._retrieve("query text")

    # similarity = 1 - cosine distance
    assert chunks[0]["similarity"] == 1.0 - 0.1
    assert chunks[1]["similarity"] == 1.0 - 0.25
    # provenance carried through, tagged as corpus
    assert chunks[0]["chunk_id"] == 10
    assert chunks[0]["file_path"] == "graph/state.py"
    assert chunks[0]["start_line"] == 72 and chunks[0]["end_line"] == 118
    assert all(c["source"] == "corpus" for c in chunks)
    # TOP_K bound is passed as the LIMIT parameter, connection is closed
    conn = conn_factory.return_value
    assert conn.cur.executed[1][-1] == corpus_retriever.TOP_K
    assert conn.closed is True


# ---------------------------------------------------------------------------
# Writer consumption
# ---------------------------------------------------------------------------

def test_corpus_citation_id_format():
    from agents.writer import corpus_citation_id
    chunk = {"file_path": "graph/state.py", "start_line": 72, "end_line": 118}
    assert corpus_citation_id(chunk) == "graph/state.py:L72-L118"


def test_corpus_citation_id_without_lines():
    from agents.writer import corpus_citation_id
    chunk = {"file_path": "README.md", "start_line": None, "end_line": None}
    assert corpus_citation_id(chunk) == "README.md"


def test_render_sources_web_only_unchanged():
    from agents.writer import render_sources
    state = _state(sources=[{"url": "https://x.com/a", "summary": "S", "raw_length": 10}])
    rendered = render_sources(state)
    assert rendered == "### https://x.com/a\nS"


def test_render_sources_includes_corpus():
    from agents.writer import render_sources
    state = _state(
        sources=[{"url": "https://x.com/a", "summary": "S", "raw_length": 10}],
        corpus_results=[{
            "chunk_id": 1, "file_path": "graph/state.py", "start_line": 72,
            "end_line": 118, "commit_sha": "9b8b08f", "content": "STATE BODY",
            "similarity": 0.9, "source": "corpus",
        }],
    )
    rendered = render_sources(state)
    assert "### https://x.com/a" in rendered
    assert "### graph/state.py:L72-L118" in rendered
    assert "STATE BODY" in rendered


def test_writer_prompt_contains_corpus_identifier():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="report")
    state = _state(
        retrieval="on",
        critique={"passed": True, "feedback": "ok", "missing_topics": []},
        corpus_results=[{
            "chunk_id": 1, "file_path": "llm/embeddings.py", "start_line": 5,
            "end_line": 30, "commit_sha": "9b8b08f", "content": "EMBED BODY",
            "similarity": 0.8, "source": "corpus",
        }],
    )
    with patch("agents.writer.get_llm", return_value=llm):
        from agents.writer import run_writer
        run_writer(state)
    prompt = str(llm.invoke.call_args)
    assert "llm/embeddings.py:L5-L30" in prompt
    assert "EMBED BODY" in prompt


# ---------------------------------------------------------------------------
# Critic consumption
# ---------------------------------------------------------------------------

def test_critic_prompt_includes_corpus_evidence():
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="PASSED\nGood.")
    state = _state(
        retrieval="on",
        corpus_results=[{
            "chunk_id": 1, "file_path": "graph/edges.py", "start_line": 1,
            "end_line": 20, "commit_sha": "9b8b08f", "content": "EDGES BODY",
            "similarity": 0.7, "source": "corpus",
        }],
    )
    with patch("agents.critic.get_llm", return_value=llm):
        from agents.critic import run_critic
        run_critic(state)
    prompt = str(llm.invoke.call_args)
    assert "graph/edges.py:L1-L20" in prompt
    assert "EDGES BODY" in prompt
