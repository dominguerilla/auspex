# CLAUDE.md

See **[AGENTS.md](AGENTS.md)** for the canonical project entrypoint: orientation, doc map, build/test/run commands, and rules of the road.

## Claude Code–specific notes

- Shell: PowerShell on Windows (`$env:VAR`, backtick line continuation). Use `Bash` tool for POSIX scripts.
- Tests are fully mocked — `pytest` requires no running Ollama server or internet access.
- Lint before committing: `ruff check .` (CI enforces this on every master push).
- Contract files that require extra care when editing: `graph/state.py`, `llm/contract.py`, `graph/edges.py` — see AGENTS.md "Rules of the road".
