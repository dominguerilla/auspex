---
last_verified: 2026-06-16
sources: [pyproject.toml, .github/workflows/test.yml, graph/state.py, agents/refiner.py, tests/conftest.py, prompts/]
owner: Carlos
status: draft
---

# Conventions

## Code style

- **Linter / formatter:** `ruff` — rules E, F, W, I; line-length 100 (source: `pyproject.toml:6-12`).
- E501 (line-too-long) is ignored — concept docstrings are intentionally verbose.
- Run before committing: `ruff check .`
- CI enforces ruff before running tests (`.github/workflows/test.yml:28-29`).

## Commit messages

Imperative present tense, descriptive. Examples from git log:
```
Add CI, linting, and portfolio polish
Use llm/contract to specify citation, pass/fail formatting
Fix ruff CI failures: sort imports, remove unused imports, trim whitespace
```

No ticket numbers, no "WIP". Merge commits use GitHub's default format.

## Agent function contract

Every agent is a plain function in `agents/`:

```python
def run_<name>(state: ResearchState) -> dict:
    """
    One-line summary.

    Parameters
    ----------
    state : ResearchState
        Reads: <field>, <field>

    Returns
    -------
    dict
        Keys: <field> (<type>)
    """
    ...
    return {"field": value}
```

Rules:
- Signature is exactly `(state: ResearchState) -> dict`.
- Return only the keys the agent writes — LangGraph merges the partial dict into state.
- Load the LLM via `get_llm(temperature=...)` from `llm/ollama_client.py`.
- Load the prompt from `prompts/<name>.txt` at call time (not module load time).

Source pattern: `agents/refiner.py:22-64`

## State field rules

- **Last-write-wins** fields (`search_queries`, `search_results`, `sources`, `critique`, `final_report`): an agent's return dict replaces the field entirely. Do not append — return the full new value.
- **Append-only** field (`messages`): use `return {"messages": [AIMessage(content="...")]}` — the `add_messages` reducer handles appending.
- Never mutate `research_question` or `max_iterations` after initial state construction.

Source: `graph/state.py`

## Prompt file conventions

- One `.txt` file per agent in `prompts/`.
- Placeholders use Python `.format()` syntax: `{research_question}`, `{feedback}`, etc.
- Placeholder names must exactly match the keys passed by the agent's `.format(...)` call — a mismatch raises `KeyError` at runtime.
- The constants in `llm/contract.py` must stay in sync with the literal strings in the prompt files they control. Change both together.

## Test conventions

- All tests live in `tests/`; test files are `test_<module>.py`.
- Use fixtures from `tests/conftest.py`:
  - `mock_llm` — a `MagicMock` that mimics `BaseChatModel`; `mock_llm.invoke.return_value.content` is `""` by default.
  - `base_state` — a zeroed `ResearchState` dict with empty lists and `None` optional fields.
- LLM calls and network calls (DuckDuckGo, `requests`) are always mocked via `unittest.mock.patch`. No test needs a running Ollama server or internet access.
- **Exception — the MCP server tests** (`tests/test_mcp_server.py`) need a **Postgres** database (`DATABASE_URL`, default the local `docker-compose` Postgres; the pipeline itself is still mocked). They `skip` if Postgres is unreachable or unmigrated. Run `alembic upgrade head` first. CI provides a Postgres service. These tests do **not** run on native Windows (psycopg/libpq conflicts with the langgraph stack in-process) — use CI or WSL2/Linux.
- Async tests (e.g. MCP server tests) use `pytest-asyncio` with `asyncio_mode = "auto"` (source: `pyproject.toml`) — no `@pytest.mark.asyncio` decorator needed.
- Integration testing (real LLM, real network) is done manually with `main.py`.

Source: `tests/conftest.py`, test files in `tests/`

## Branching

- `master` is the deploy branch — every push auto-deploys to HF Spaces.
- Feature work happens on branches (e.g., `feature/...`, `evals`); merge via PR.
- CI must be green (ruff + pytest on 3.10 + 3.12) before merging.
