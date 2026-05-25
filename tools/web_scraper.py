"""
CONCEPT: Web Scraping — requests + BeautifulSoup + markdownify
================================================================
Pattern: Fetch → parse → clean → convert to markdown

HTML pages are noisy: navbars, ads, scripts, cookie banners. The scraper's
job is to extract the meaningful text content and return it as clean markdown
that the LLM can read efficiently.

What is given:
  - The requests.get() call with a timeout
  - The BeautifulSoup parse

What you must implement:
  - Tag removal: strip <script>, <style>, <nav>, <footer>, <header> tags
    (these are noise for the LLM; removing them reduces token count)
  - Content selection: find the main content area (try <article>, <main>, <body>)
  - markdownify conversion: md(str(element)) converts HTML to markdown text
  - Error handling: raise on HTTP errors (response.raise_for_status())

Tag removal hint:
  for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
      tag.decompose()   # removes the tag and its children from the tree

Content selection hint:
  main = soup.find("article") or soup.find("main") or soup.find("body")
  If all are None, fall back to str(soup).

markdownify hint:
  from markdownify import markdownify as md
  text = md(str(main), heading_style="ATX")
"""

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ResearchBot/1.0; +https://github.com/example/researcher)"
    )
}


def scrape_url(url: str) -> str:
    """
    Fetch a URL and return its main content as markdown text.

    Parameters
    ----------
    url : str
        The page to scrape.

    Returns
    -------
    str
        Markdown representation of the page's main content.

    Raises
    ------
    requests.HTTPError
        On 4xx/5xx responses (caller should catch this).
    requests.RequestException
        On network errors.
    """
    response = requests.get(url, headers=_HEADERS, timeout=10)
    response.raise_for_status()  # raises HTTPError on 4xx/5xx

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    main_content = soup.find("article") or soup.find("main") or soup.find("body")
    main_content = str(soup) if main_content is None else main_content

    return md(str(main_content), heading_style="ATX")

