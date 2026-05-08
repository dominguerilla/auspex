from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage


def make_mock_llm(content):
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.invoke.return_value = response
    return llm


def test_returns_search_queries_key(base_state):
    base_state["research_question"] = "What is quantum computing?"
    llm = make_mock_llm("1. quantum basics\n2. quantum applications")
    with patch("agents.orchestrator.get_llm", return_value=llm):
        from agents.orchestrator import run_orchestrator
        result = run_orchestrator(base_state)
    assert "search_queries" in result
    assert isinstance(result["search_queries"], list)


def test_strips_numbered_prefixes(base_state):
    base_state["research_question"] = "test question"
    llm = make_mock_llm("1. first query\n2. second query\n3. third query")
    with patch("agents.orchestrator.get_llm", return_value=llm):
        from agents.orchestrator import run_orchestrator
        result = run_orchestrator(base_state)
    assert "first query" in result["search_queries"]
    assert "second query" in result["search_queries"]
    assert "third query" in result["search_queries"]
    for q in result["search_queries"]:
        assert not q.startswith("1.")
        assert not q.startswith("2.")


def test_strips_bullet_prefixes(base_state):
    base_state["research_question"] = "test question"
    llm = make_mock_llm("- first query\n* second query")
    with patch("agents.orchestrator.get_llm", return_value=llm):
        from agents.orchestrator import run_orchestrator
        result = run_orchestrator(base_state)
    for q in result["search_queries"]:
        assert not q.startswith("- ")
        assert not q.startswith("* ")


def test_filters_blank_lines(base_state):
    base_state["research_question"] = "test question"
    llm = make_mock_llm("query one\n\n\nquery two\n")
    with patch("agents.orchestrator.get_llm", return_value=llm):
        from agents.orchestrator import run_orchestrator
        result = run_orchestrator(base_state)
    assert "" not in result["search_queries"]


def test_messages_contains_ai_message_with_raw_content(base_state):
    base_state["research_question"] = "test question"
    raw = "1. some query"
    llm = make_mock_llm(raw)
    with patch("agents.orchestrator.get_llm", return_value=llm):
        from agents.orchestrator import run_orchestrator
        result = run_orchestrator(base_state)
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == raw


def test_get_llm_called_with_temperature_0_2(base_state):
    base_state["research_question"] = "test"
    llm = make_mock_llm("query one")
    with patch("agents.orchestrator.get_llm", return_value=llm) as mock_get_llm:
        from agents.orchestrator import run_orchestrator
        run_orchestrator(base_state)
    mock_get_llm.assert_called_once_with(temperature=0.2)


def test_raises_when_response_content_is_none(base_state):
    base_state["research_question"] = "test"
    llm = make_mock_llm(None)
    with patch("agents.orchestrator.get_llm", return_value=llm):
        from agents.orchestrator import run_orchestrator
        with pytest.raises(Exception):
            run_orchestrator(base_state)
