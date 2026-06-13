---
last_verified: 2026-06-12
sources: [auspex/mcp_server/server.py, auspex/mcp_server/__main__.py, requirements.txt]
owner: Carlos
status: draft
---

# MCP Server — Auspex Research Agent

Auspex ships an MCP server so Claude Desktop, Cursor, and other MCP clients
can run research jobs directly as tool calls over the
[Model Context Protocol](https://modelcontextprotocol.io/).

## Tools

### `start_research`

Starts a background research job and returns immediately with a `job_id`.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `query` | string | yes | — | Research question; must be non-empty |
| `max_iterations` | integer | no | 2 | Critique/refine cycles; clamped to 1–5 |

**Returns**
```json
{"job_id": "a1b2c3d4...", "status": "queued"}
```

### `get_research_status`

Poll the status of a running or completed job.

| Parameter | Type | Required |
|-----------|------|----------|
| `job_id` | string | yes |

**Returns**
```json
{
  "job_id": "a1b2c3d4...",
  "status": "queued | running | done | error",
  "current_node": "reader | null",
  "iteration": 1,
  "error": null
}
```

`current_node` reflects the most recently completed pipeline step
(`orchestrator → searcher → reader → critic → refiner → writer`).
`iteration` is the critique cycle count (increments each time the critic
evaluates the research).

Raises a tool error if `job_id` is unknown.

### `get_research_report`

Retrieve the final Markdown report for a completed job.

| Parameter | Type | Required |
|-----------|------|----------|
| `job_id` | string | yes |

**Returns**
```json
{
  "job_id": "a1b2c3d4...",
  "status": "done",
  "report": "# Research Report\n\n...",
  "sources": [
    {"url": "https://example.com", "summary": "...", "raw_length": 4200}
  ]
}
```

If `status` is not `"done"`, `report` is `null` — keep polling
`get_research_status` and retry once it transitions to `"done"`.

> **Note:** `sources` is only populated for jobs started in the current
> server session. It is not persisted to the database, so jobs retrieved
> from a previous session will return `sources: []`.

## Resource

```
research://{job_id}
```

Returns the raw Markdown report string for a completed job. Raises if the
job is unknown or not yet done.

## Running locally

```bash
# From the project root with the virtualenv active:
python -m auspex.mcp_server
```

The server reads JSON-RPC messages from stdin and writes to stdout (stdio
transport). LLM provider configuration uses the same environment variables
as the CLI — see [README.md](../README.md#setup) for details.

## Claude Desktop configuration

Add the following block to your Claude Desktop config file and restart
the app.

**macOS** — `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows** — `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "auspex": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "auspex.mcp_server"],
      "cwd": "/absolute/path/to/research-agent",
      "env": {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:3b"
      }
    }
  }
}
```

**Windows example** (adjust paths to your environment):

```json
{
  "mcpServers": {
    "auspex": {
      "command": "C:\\Projects\\AI\\research-agent\\.venv\\Scripts\\python.exe",
      "args": ["-m", "auspex.mcp_server"],
      "cwd": "C:\\Projects\\AI\\research-agent",
      "env": {
        "LLM_PROVIDER": "ollama",
        "OLLAMA_BASE_URL": "http://localhost:11434",
        "OLLAMA_MODEL": "qwen2.5:3b"
      }
    }
  }
}
```

**HuggingFace Inference API** — replace the `env` block with:

```json
"env": {
  "LLM_PROVIDER": "huggingface",
  "HF_TOKEN": "<your-hf-token>",
  "HF_MODEL": "meta-llama/Llama-3.1-8B-Instruct"
}
```

### Config notes

- `command` must be the **absolute path** to the Python interpreter inside
  your virtual environment (`.venv/bin/python` on Unix,
  `.venv\Scripts\python.exe` on Windows).
- `cwd` must be the **absolute path** to the project root so that `jobs.db`
  and the `graph/` package resolve correctly.
- The `env` block is merged with the server process's environment, so you
  can also rely on a `.env` file in the project root — but explicit values
  in `env` take precedence.

## Example conversation

```
User: Research the tradeoffs between Rust and Go for CLI tools.

Claude: [calls start_research]
→ {"job_id": "abc123", "status": "queued"}

Claude: [calls get_research_status — a few seconds later]
→ {"status": "running", "current_node": "reader", "iteration": 0}

Claude: [calls get_research_status — when done]
→ {"status": "done", "current_node": "writer"}

Claude: [calls get_research_report]
→ {"status": "done", "report": "# Rust vs Go for CLI Tools\n\n..."}

Claude: Here is a summary of the research findings: ...
```

## Troubleshooting

**Server doesn't appear in Claude Desktop**

- Confirm `command` is the correct absolute path to the venv Python.
- Run `python -m auspex.mcp_server` in your terminal to check for import
  errors (missing deps, Python version issues).
- Fully quit and relaunch Claude Desktop after editing the config.
- Check Claude Desktop logs: `~/Library/Logs/Claude/` (macOS) or
  `%APPDATA%\Claude\logs\` (Windows).

**`ModuleNotFoundError: No module named 'auspex'`**

- The `cwd` in the config must be the project root (the directory containing
  the `auspex/` folder and `requirements.txt`).

**`ModuleNotFoundError: No module named 'mcp'`**

```bash
pip install "mcp[cli]>=1.2.0"
```

**`ModuleNotFoundError: No module named 'graph'`**

- Same as above: `cwd` must point to the project root.

**Ollama connection refused**

- Confirm Ollama is running: `ollama serve`
- Check `OLLAMA_BASE_URL` in the env block (default: `http://localhost:11434`).

**Jobs persist across server restarts but sources don't**

This is expected. The final Markdown report is stored in `jobs.db` and
survives restarts. The scraped source details are held in-memory only and
are lost when the server process exits.

## Roadmap (v2+)

- **HTTP transport**: Mount the MCP server at `/mcp` on the existing FastAPI
  app so the HF Spaces deployment serves it too (bearer-token auth required).
- **Job cancellation**: Allow clients to cancel an in-flight job.
- **Progress notifications**: Emit MCP progress notifications from `_run_job`
  so clients receive live node updates without polling.
- **Rate limiting / multi-tenancy**: Per-client job quotas.
