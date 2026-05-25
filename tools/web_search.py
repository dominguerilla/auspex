"""
CONCEPT: Tool Wrapping — Normalising Third-Party APIs
======================================================
Pattern: Thin wrapper that normalises output to a known schema

DuckDuckGo's Python library returns results in its own dict format.
Rather than letting every agent know about that format, this module
exposes a single function with a stable return type: List[dict] with
keys {title, url, snippet}.

What is given:
  - The DuckDuckGoSearchResults tool instantiation
  - The raw_results = tool.run(query) call

What you must implement:
  - Normalise each raw result dict into {title, url, snippet}
  - DuckDuckGo returns dicts with keys: "title", "href" (not "url"), "body" (not "snippet")
  - Return an empty list if the tool raises (network error, rate limit, etc.)

Normalisation hint:
  raw = tool.run(query)  # returns a string repr of a list of dicts; eval carefully
  Actually DuckDuckGoSearchResults.run() returns a STRING like:
    "[{'snippet': '...', 'title': '...', 'link': '...'}, ...]"
  Use ast.literal_eval() to parse it safely. Keys vary by version — inspect
  what you actually get by printing one result during development.

Safe parsing hint:
  import ast
  try:
      items = ast.literal_eval(raw)
  except Exception:
      return []
"""

from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

_wrapper = DuckDuckGoSearchAPIWrapper()


def web_search(query: str) -> list[dict]:
    """
    Search DuckDuckGo and return normalised results.

    Parameters
    ----------
    query : str
        The search query string.

    Returns
    -------
    List[dict]
        Each dict has keys: title (str), url (str), snippet (str).
        Returns empty list on error.
    """
    try:
        items = _wrapper.results(query, max_results=5)
        return [
            {
                'title': item.get('title', ''),
                'url': item.get('link', item.get('url', '')),
                'snippet': item.get('snippet', item.get('body', '')),
            }
            for item in items
        ]
    except Exception as e:
        print(f"[web_search] query={query!r} failed: {e}")
        return []
