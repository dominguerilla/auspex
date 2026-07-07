# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** for the canonical project entrypoint: orientation, doc map, build/test/run commands, and rules of the road.

## Claude Code–specific notes

- Shell: PowerShell on Windows (`$env:VAR`, backtick line continuation). Use `Bash` tool for POSIX scripts.
- Most tests are fully mocked — `pytest` needs no Ollama server or internet. **Exception:** the MCP server tests (`tests/test_mcp_server.py`) need a Postgres database (`DATABASE_URL`, default the local `docker-compose` Postgres); they skip if it is absent. CI provides a Postgres service. Note: psycopg cannot connect in-process alongside the langgraph stack on native Windows (libpq DLL conflict) — run those tests via CI or WSL2/Linux, not native Windows.
- Lint before committing: `ruff check .` (CI enforces ruff + pytest on every push to `master`/`develop`/`feature/**`).
- Contract files that require extra care when editing: `graph/state.py`, `llm/contract.py`, `graph/edges.py` — see AGENTS.md "Rules of the road".
