from unittest.mock import MagicMock, patch


def make_search_result(url="https://example.com"):
    return {"title": "Title", "url": url, "snippet": "Snippet"}


def make_mock_llm(summary="Summary text"):
    llm = MagicMock()
    response = MagicMock()
    response.content = summary
    llm.invoke.return_value = response
    return llm


def test_returns_sources_key(base_state):
    base_state["search_results"] = [make_search_result()]
    base_state["research_question"] = "test question"
    llm = make_mock_llm()
    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", return_value="scraped content"):
        from agents.reader import run_reader
        result = run_reader(base_state)
    assert "sources" in result


def test_source_url_matches_input(base_state):
    url = "https://specific.com/page"
    base_state["search_results"] = [make_search_result(url)]
    base_state["research_question"] = "test"
    llm = make_mock_llm()
    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", return_value="content"):
        from agents.reader import run_reader
        result = run_reader(base_state)
    assert result["sources"][0]["url"] == url


def test_raw_length_equals_len_of_scraped_text(base_state):
    base_state["search_results"] = [make_search_result()]
    base_state["research_question"] = "test"
    scraped = "x" * 100
    llm = make_mock_llm()
    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", return_value=scraped):
        from agents.reader import run_reader
        result = run_reader(base_state)
    assert result["sources"][0]["raw_length"] == 100


def test_raw_length_reflects_full_text_not_truncated(base_state):
    base_state["search_results"] = [make_search_result()]
    base_state["research_question"] = "test"
    scraped = "x" * 8000
    llm = make_mock_llm()
    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", return_value=scraped):
        from agents.reader import run_reader
        result = run_reader(base_state)
    assert result["sources"][0]["raw_length"] == 8000


def test_summary_equals_llm_content(base_state):
    base_state["search_results"] = [make_search_result()]
    base_state["research_question"] = "test"
    expected_summary = "This is the LLM summary"
    llm = make_mock_llm(expected_summary)
    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", return_value="content"):
        from agents.reader import run_reader
        result = run_reader(base_state)
    assert result["sources"][0]["summary"] == expected_summary


def test_scrape_failure_skips_source(base_state):
    base_state["search_results"] = [
        make_search_result("https://fail.com"),
        make_search_result("https://ok.com"),
    ]
    base_state["research_question"] = "test"
    llm = make_mock_llm()

    def scrape_side_effect(url):
        if "fail" in url:
            raise Exception("network error")
        return "good content"

    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", side_effect=scrape_side_effect):
        from agents.reader import run_reader
        result = run_reader(base_state)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["url"] == "https://ok.com"


def test_n_successful_results_gives_n_sources(base_state):
    base_state["search_results"] = [
        make_search_result("https://a.com"),
        make_search_result("https://b.com"),
        make_search_result("https://c.com"),
    ]
    base_state["research_question"] = "test"
    llm = make_mock_llm()
    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", return_value="content"):
        from agents.reader import run_reader
        result = run_reader(base_state)
    assert len(result["sources"]) == 3


def test_scrape_url_called_with_correct_url(base_state):
    url = "https://target.com/article"
    base_state["search_results"] = [make_search_result(url)]
    base_state["research_question"] = "test"
    llm = make_mock_llm()
    with patch("agents.reader.get_llm", return_value=llm), \
         patch("agents.reader.scrape_url", return_value="content") as mock_scrape:
        from agents.reader import run_reader
        run_reader(base_state)
    mock_scrape.assert_called_once_with(url)
