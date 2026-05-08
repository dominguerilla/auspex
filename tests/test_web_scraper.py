from unittest.mock import MagicMock, patch

import pytest
import requests


def make_mock_response(html, status_code=200):
    mock_resp = MagicMock()
    mock_resp.text = html
    mock_resp.status_code = status_code
    if status_code >= 400:
        mock_resp.raise_for_status.side_effect = requests.HTTPError(
            response=mock_resp
        )
    else:
        mock_resp.raise_for_status.return_value = None
    return mock_resp


def test_returns_content_from_article():
    html = "<html><body><article><p>Main content here</p></article></body></html>"
    with patch("tools.web_scraper.requests.get") as mock_get:
        mock_get.return_value = make_mock_response(html)
        from tools.web_scraper import scrape_url
        result = scrape_url("https://example.com")
    assert "Main content here" in result
    assert len(result) > 0


def test_nav_header_footer_excluded():
    html = (
        "<html><body>"
        "<nav>Navigation text</nav>"
        "<header>Header text</header>"
        "<footer>Footer text</footer>"
        "<article><p>Real content</p></article>"
        "</body></html>"
    )
    with patch("tools.web_scraper.requests.get") as mock_get:
        mock_get.return_value = make_mock_response(html)
        from tools.web_scraper import scrape_url
        result = scrape_url("https://example.com")
    assert "Navigation text" not in result
    assert "Header text" not in result
    assert "Footer text" not in result


def test_falls_back_to_main():
    html = "<html><body><main><p>Main section content</p></main></body></html>"
    with patch("tools.web_scraper.requests.get") as mock_get:
        mock_get.return_value = make_mock_response(html)
        from tools.web_scraper import scrape_url
        result = scrape_url("https://example.com")
    assert "Main section content" in result


def test_raises_http_error_on_4xx():
    with patch("tools.web_scraper.requests.get") as mock_get:
        mock_get.return_value = make_mock_response("<html></html>", status_code=404)
        from tools.web_scraper import scrape_url
        with pytest.raises(requests.HTTPError):
            scrape_url("https://example.com/notfound")


def test_get_called_with_correct_url_and_timeout():
    html = "<html><body><article><p>content</p></article></body></html>"
    with patch("tools.web_scraper.requests.get") as mock_get:
        mock_get.return_value = make_mock_response(html)
        from tools.web_scraper import scrape_url
        scrape_url("https://example.com/page")
    call_args = mock_get.call_args
    assert call_args[0][0] == "https://example.com/page"
    assert call_args[1]["timeout"] == 10


def test_script_and_style_stripped():
    html = (
        "<html><body>"
        "<script>alert('xss')</script>"
        "<style>.foo { color: red; }</style>"
        "<article><p>Clean content</p></article>"
        "</body></html>"
    )
    with patch("tools.web_scraper.requests.get") as mock_get:
        mock_get.return_value = make_mock_response(html)
        from tools.web_scraper import scrape_url
        result = scrape_url("https://example.com")
    assert "alert" not in result
    assert "color: red" not in result
    assert "Clean content" in result
