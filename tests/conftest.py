from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    response = MagicMock()
    response.content = ""
    llm.invoke.return_value = response
    return llm


@pytest.fixture
def base_state():
    return {
        "research_question": "",
        "max_iterations": 3,
        "search_queries": [],
        "iteration": 0,
        "search_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }
