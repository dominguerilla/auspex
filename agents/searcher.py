"""
CONCEPT: Searcher Agent — Tool Use
=====================================
Pattern: Agent calls a tool, normalises results, writes to state

The searcher reads search_queries from state, calls the DuckDuckGo tool for
each query, deduplicates results by URL, and writes them back as SearchResult
TypedDicts.

What is given:
  - The import of the search tool
  - The loop skeleton (iterating over state["search_queries"])

What you must implement:
  - Calling the tool: results = web_search(query)  ← returns a list of dicts
  - Mapping raw dicts to SearchResult TypedDicts (title, url, snippet keys)
  - Deduplication: skip URLs already seen in this run
  - Return {"search_results": [...]}

Tool call hint:
  web_search is imported from tools.web_search. After your TODO in that file,
  it returns List[dict] where each dict has keys: title, url, snippet.
  You construct SearchResult(title=..., url=..., snippet=...) for each one.

Dedup hint:
  Keep a set of seen URLs. Before appending a result, check if its URL is in
  the set. If not, add to set AND append to results list.

State fields read:   search_queries
State fields written: search_results
"""

from graph.state import ResearchState, SearchResult
from tools.web_search import web_search


def run_searcher(state: ResearchState) -> dict:
    """
    Execute each search query and collect deduplicated results.

    Parameters
    ----------
    state : ResearchState
        Reads: search_queries

    Returns
    -------
    dict
        Keys: search_results (List[SearchResult])
    """
    all_results: list[SearchResult] = []
    seen_urls: set[str] = set()

    print(f"[searcher] running {len(state['search_queries'])} queries")
    for query in state["search_queries"]:
        results = web_search(query)
        print(f"[searcher] query={query!r} → {len(results)} results")
        for result in results:
            if result["url"] in seen_urls:
                continue
            seen_urls.add(result["url"])
            all_results.append(
                    SearchResult(
                        title=result["title"],
                        url=result["url"],
                        snippet=result["snippet"]
                        )
                    )

        

    return {"search_results": all_results}
