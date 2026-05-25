from unittest.mock import patch


def test_normalizes_link_to_url():
    items = [{'title': 'T', 'link': 'https://example.com', 'snippet': 'S'}]
    with patch("tools.web_search._wrapper") as mock_wrapper:
        mock_wrapper.results.return_value = items
        from tools.web_search import web_search
        results = web_search("test query")
    assert results[0]["url"] == "https://example.com"


def test_returns_all_items():
    items = [
        {'title': 'T1', 'link': 'https://a.com', 'snippet': 'S1'},
        {'title': 'T2', 'link': 'https://b.com', 'snippet': 'S2'},
    ]
    with patch("tools.web_search._wrapper") as mock_wrapper:
        mock_wrapper.results.return_value = items
        from tools.web_search import web_search
        results = web_search("test")
    assert len(results) == 2


def test_returns_empty_on_tool_exception():
    with patch("tools.web_search._wrapper") as mock_wrapper:
        mock_wrapper.results.side_effect = Exception("network error")
        from tools.web_search import web_search
        results = web_search("test")
    assert results == []


def test_calls_wrapper_with_query():
    with patch("tools.web_search._wrapper") as mock_wrapper:
        mock_wrapper.results.return_value = []
        from tools.web_search import web_search
        web_search("my query")
    mock_wrapper.results.assert_called_once_with("my query", max_results=5)


def test_every_result_has_required_keys():
    items = [
        {'title': 'T1', 'link': 'https://a.com', 'snippet': 'S1'},
        {'title': 'T2', 'link': 'https://b.com', 'snippet': 'S2'},
    ]
    with patch("tools.web_search._wrapper") as mock_wrapper:
        mock_wrapper.results.return_value = items
        from tools.web_search import web_search
        results = web_search("test")
    for r in results:
        assert "title" in r
        assert "url" in r
        assert "snippet" in r
