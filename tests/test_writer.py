from unittest.mock import MagicMock, patch


def make_mock_llm(content="Generated report"):
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.invoke.return_value = response
    return llm


def test_returns_final_report_key(base_state):
    base_state["research_question"] = "test"
    base_state["sources"] = []
    base_state["critique"] = {"passed": True, "feedback": "Good", "missing_topics": []}
    llm = make_mock_llm()
    with patch("agents.writer.get_llm", return_value=llm):
        from agents.writer import run_writer
        result = run_writer(base_state)
    assert "final_report" in result


def test_final_report_equals_llm_content(base_state):
    base_state["research_question"] = "test"
    base_state["sources"] = []
    base_state["critique"] = {"passed": True, "feedback": "Good", "missing_topics": []}
    expected = "This is the final research report."
    llm = make_mock_llm(expected)
    with patch("agents.writer.get_llm", return_value=llm):
        from agents.writer import run_writer
        result = run_writer(base_state)
    assert result["final_report"] == expected


def test_get_llm_called_with_temperature_0_5(base_state):
    base_state["research_question"] = "test"
    base_state["sources"] = []
    base_state["critique"] = {"passed": True, "feedback": "Good", "missing_topics": []}
    llm = make_mock_llm()
    with patch("agents.writer.get_llm", return_value=llm) as mock_get_llm:
        from agents.writer import run_writer
        run_writer(base_state)
    mock_get_llm.assert_called_once_with(temperature=0.5)


def test_llm_invoke_called_exactly_once(base_state):
    base_state["research_question"] = "test"
    base_state["sources"] = []
    base_state["critique"] = {"passed": True, "feedback": "Good", "missing_topics": []}
    llm = make_mock_llm()
    with patch("agents.writer.get_llm", return_value=llm):
        from agents.writer import run_writer
        run_writer(base_state)
    llm.invoke.assert_called_once()


def test_none_critique_does_not_raise(base_state):
    base_state["research_question"] = "test"
    base_state["sources"] = []
    base_state["critique"] = None
    llm = make_mock_llm()
    with patch("agents.writer.get_llm", return_value=llm):
        from agents.writer import run_writer
        result = run_writer(base_state)
    assert "final_report" in result


def test_source_urls_appear_in_prompt(base_state):
    base_state["research_question"] = "test"
    base_state["sources"] = [
        {"url": "https://unique-source.com/article", "summary": "Summary A", "raw_length": 100},
    ]
    base_state["critique"] = {"passed": True, "feedback": "Good", "missing_topics": []}
    llm = make_mock_llm()
    with patch("agents.writer.get_llm", return_value=llm):
        from agents.writer import run_writer
        run_writer(base_state)
    call_args = llm.invoke.call_args
    prompt_text = str(call_args)
    assert "https://unique-source.com/article" in prompt_text
