from unittest.mock import patch


def make_result(title, url, snippet):
    return {"title": title, "url": url, "snippet": snippet}


def test_returns_search_results_key(base_state):
    base_state["search_queries"] = ["test query"]
    with patch("agents.searcher.web_search", return_value=[make_result("T", "https://a.com", "S")]):
        from agents.searcher import run_searcher
        result = run_searcher(base_state)
    assert "search_results" in result


def test_results_from_all_queries_combined(base_state):
    base_state["search_queries"] = ["query one", "query two"]
    side_effects = [
        [make_result("T1", "https://a.com", "S1")],
        [make_result("T2", "https://b.com", "S2")],
    ]
    with patch("agents.searcher.web_search", side_effect=side_effects):
        from agents.searcher import run_searcher
        result = run_searcher(base_state)
    assert len(result["search_results"]) == 2


def test_duplicate_urls_deduplicated(base_state):
    base_state["search_queries"] = ["query one", "query two"]
    side_effects = [
        [make_result("T1", "https://a.com", "S1")],
        [make_result("T2", "https://a.com", "S2")],  # same URL
    ]
    with patch("agents.searcher.web_search", side_effect=side_effects):
        from agents.searcher import run_searcher
        result = run_searcher(base_state)
    assert len(result["search_results"]) == 1


def test_each_result_has_required_keys(base_state):
    base_state["search_queries"] = ["query"]
    with patch("agents.searcher.web_search", return_value=[make_result("T", "https://a.com", "S")]):
        from agents.searcher import run_searcher
        result = run_searcher(base_state)
    for r in result["search_results"]:
        assert "title" in r
        assert "url" in r
        assert "snippet" in r


def test_web_search_called_n_times(base_state):
    base_state["search_queries"] = ["q1", "q2", "q3"]
    with patch("agents.searcher.web_search", return_value=[]) as mock_ws:
        from agents.searcher import run_searcher
        run_searcher(base_state)
    assert mock_ws.call_count == 3


def test_empty_queries_returns_empty_results(base_state):
    base_state["search_queries"] = []
    with patch("agents.searcher.web_search", return_value=[]) as mock_ws:
        from agents.searcher import run_searcher
        result = run_searcher(base_state)
    assert result["search_results"] == []
    mock_ws.assert_not_called()


def test_empty_search_results_not_added(base_state):
    base_state["search_queries"] = ["query"]
    with patch("agents.searcher.web_search", return_value=[]):
        from agents.searcher import run_searcher
        result = run_searcher(base_state)
    assert result["search_results"] == []
