from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage


def make_mock_llm(content):
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.invoke.return_value = response
    return llm


def run_critic_with(state, llm_content):
    llm = make_mock_llm(llm_content)
    with patch("agents.critic.get_llm", return_value=llm):
        from agents.critic import run_critic
        return run_critic(state)


def test_passed_sets_critique_passed_true(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "PASSED\nGood coverage.")
    assert result["critique"]["passed"] is True


def test_failed_sets_critique_passed_false(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "FAILED\nNeeds more sources.")
    assert result["critique"]["passed"] is False


def test_case_insensitive_passed(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "passed\nGood.")
    assert result["critique"]["passed"] is True


def test_case_insensitive_failed(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "Failed\nBad coverage.")
    assert result["critique"]["passed"] is False


def test_missing_topics_parsed(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "FAILED\nFeedback.\nMISSING: topic1, topic2, topic3")
    assert result["critique"]["missing_topics"] == ["topic1", "topic2", "topic3"]


def test_passed_response_has_empty_missing_topics(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "PASSED\nAll good.")
    assert result["critique"]["missing_topics"] == []


def test_iteration_incremented(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    base_state["iteration"] = 1
    result = run_critic_with(base_state, "PASSED\nGood.")
    assert result["iteration"] == 2


def test_messages_contains_ai_message_with_raw_text(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    raw = "PASSED\nAll good."
    result = run_critic_with(base_state, raw)
    assert "messages" in result
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == raw


def test_return_dict_has_required_keys(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "PASSED\nGood.")
    assert "critique" in result
    assert "iteration" in result
    assert "messages" in result


def test_ambiguous_response_defaults_to_failed(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    result = run_critic_with(base_state, "Unclear response with no verdict")
    assert result["critique"]["passed"] is False


def test_get_llm_called_with_temperature_0_1(base_state):
    base_state["sources"] = [{"url": "https://a.com", "summary": "summary", "raw_length": 100}]
    base_state["research_question"] = "test"
    llm = make_mock_llm("PASSED\nGood.")
    with patch("agents.critic.get_llm", return_value=llm) as mock_get_llm:
        from agents.critic import run_critic
        run_critic(base_state)
    mock_get_llm.assert_called_once_with(temperature=0.1)
