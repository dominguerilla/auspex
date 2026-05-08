from unittest.mock import patch


def test_normalizes_link_to_url():
    raw = "[{'title': 'T', 'link': 'https://example.com', 'snippet': 'S'}]"
    with patch("tools.web_search._tool") as mock_tool:
        mock_tool.run.return_value = raw
        from tools.web_search import web_search
        results = web_search("test query")
    assert results[0]["url"] == "https://example.com"


def test_returns_all_items():
    raw = (
        "[{'title': 'T1', 'link': 'https://a.com', 'snippet': 'S1'},"
        " {'title': 'T2', 'link': 'https://b.com', 'snippet': 'S2'}]"
    )
    with patch("tools.web_search._tool") as mock_tool:
        mock_tool.run.return_value = raw
        from tools.web_search import web_search
        results = web_search("test")
    assert len(results) == 2


def test_returns_empty_on_malformed_string():
    with patch("tools.web_search._tool") as mock_tool:
        mock_tool.run.return_value = "not valid python"
        from tools.web_search import web_search
        results = web_search("test")
    assert results == []


def test_returns_empty_on_tool_exception():
    with patch("tools.web_search._tool") as mock_tool:
        mock_tool.run.side_effect = Exception("network error")
        from tools.web_search import web_search
        results = web_search("test")
    assert results == []


def test_calls_tool_once_with_query():
    raw = "[{'title': 'T', 'link': 'https://example.com', 'snippet': 'S'}]"
    with patch("tools.web_search._tool") as mock_tool:
        mock_tool.run.return_value = raw
        from tools.web_search import web_search
        web_search("my query")
    mock_tool.run.assert_called_once_with("my query")


def test_every_result_has_required_keys():
    raw = (
        "[{'title': 'T1', 'link': 'https://a.com', 'snippet': 'S1'},"
        " {'title': 'T2', 'link': 'https://b.com', 'snippet': 'S2'}]"
    )
    with patch("tools.web_search._tool") as mock_tool:
        mock_tool.run.return_value = raw
        from tools.web_search import web_search
        results = web_search("test")
    for r in results:
        assert "title" in r
        assert "url" in r
        assert "snippet" in r
