# Architecture Decision Records

Records of decisions already made — the "why" behind architectural choices. Each entry describes the context, the decision, and the consequences, so future contributors don't re-derive the same discussion.

**Forward-looking proposals** (not yet decided) go in [docs/proposals/](../proposals/) instead.

Items marked `(inferred)` were reconstructed from code and git history; confirm or correct them.

## Convention

- Filename: `NNNN-short-slug.md` (zero-padded, monotonically increasing).
- Status: `Accepted` · `Superseded`.
- `(inferred)` in the status means a human has not yet confirmed the entry.

## Index

| # | Decision | Status |
|---|---|---|
| [0001](0001-fastapi-over-streamlit.md) | Replace Streamlit with FastAPI + custom frontend | Accepted *(inferred)* |
| [0002](0002-typeddict-for-state.md) | Use TypedDict (not Pydantic) for LangGraph state | Accepted *(inferred)* |
| [0003](0003-sqlite-job-persistence.md) | Use SQLite for completed-job persistence in the web server | Accepted *(inferred)* · scoped by 0004 |
| [0004](0004-host-mcp-server-on-aws-postgres.md) | Host the MCP server on AWS with Postgres-backed state | Accepted |
