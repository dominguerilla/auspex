# 0001 — Replace Streamlit with FastAPI + custom frontend

| | |
|---|---|
| **Status** | Accepted *(inferred — confirm)* |
| **Date** | 2026-05-28 (inferred from git: "Use FASTAPI + stepper frontend, job queuing, shareable report URLs") |
| **Evidence** | git log ("Remove streamlit"), `app.py`, `frontend/`, `requirements.txt` |

## Context

The initial prototype used Streamlit for the web UI. Streamlit's execution model re-runs the entire script on each interaction, which made it difficult to:
- Stream live per-node progress as the LangGraph pipeline ran.
- Generate a shareable URL for a completed report.
- Run the pipeline as a background job (so the browser tab could be closed mid-run).

## Decision

Replace Streamlit with a FastAPI server (`app.py`) that drives a custom React-ish single-flow frontend (`frontend/`). The server streams per-node `node_complete` SSE events using `sse-starlette`, persists completed jobs in SQLite so their reports survive page refreshes and tab closes, and exposes a `/r/{job_id}` shareable URL.

## Consequences

- The web UI is now a bespoke JSX + CSS prototype (`frontend/flow-prototype.jsx`, `flow-prototype.css`) — higher maintenance than Streamlit but full control over the "Circle" animation and spirit-detail cards.
- Shareable URLs require SQLite to be present; on HF Spaces free tier the DB is ephemeral and wiped on each redeploy.
- `streamlit_app.py` was deleted; `streamlit` is no longer in `requirements.txt`.
- The CLI (`main.py`) is unaffected — it still calls `graph.invoke()` synchronously.
