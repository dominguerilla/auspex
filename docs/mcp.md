---
last_verified: 2026-06-17
sources: [auspex/mcp_server/server.py, auspex/mcp_server/__main__.py, alembic/, docker-compose.yml, requirements.txt]
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

> **Note:** `sources` is persisted durably (the `sources` table), so it is
> returned whether the job just completed or is read back in a later session.

## Resource

```
research://{job_id}
```

Returns the raw Markdown report string for a completed job. Raises if the
job is unknown or not yet done.

## Database

The server stores all job state — status, report, and sources — in **Postgres**
from the moment a job is created, so jobs are durable and status/report reads
work from any instance (see [docs/adr/0004](adr/0004-host-mcp-server-on-aws-postgres.md),
[0005](adr/0005-worker-split-cloud-tasks.md)).
Set `DATABASE_URL` (default: the local `docker-compose` database
`postgresql://auspex:auspex@localhost:5432/auspex`) and apply migrations before
serving:

```bash
docker compose up -d          # local Postgres
alembic upgrade head          # create / update the schema
```

> **Windows note:** on native Windows, psycopg/libpq conflicts with the langgraph
> native stack in-process, so the Postgres-backed server can't run there. Use WSL2
> (Linux) for local runs; the hosted deployment is Linux and unaffected.

## Running locally

There are two transport modes:

**stdio** (default) — for Claude Desktop and other local MCP clients that launch the server as a subprocess:
```bash
python -m auspex.mcp_server
```

**HTTP** — for remote MCP clients on the same network (e.g. a Hermes agent on a Raspberry Pi):
```bash
# Recommended: require a bearer token
AUSPEX_MCP_TOKEN=<a-long-random-secret> python -m auspex.mcp_server --http
# Windows PowerShell:
#   $env:AUSPEX_MCP_TOKEN = "<secret>"; python -m auspex.mcp_server --http
```

Serves at `http://<your-ip>:<port>/mcp` (default port 8765, override with `--port`).
Binds to all interfaces by default so LAN clients can reach it.

**Authentication.** If `AUSPEX_MCP_TOKEN` is set, every HTTP request must carry an
`Authorization: Bearer <token>` header; requests without it get `401 Unauthorized`.
If the variable is unset, the endpoint is **unauthenticated** and the server logs a
warning at startup — only appropriate on a fully trusted network. (stdio mode has no
network surface and ignores this variable.)

LLM provider configuration uses the same environment variables as the CLI in both
modes — see [README.md](../README.md#setup) for details.

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
        "DATABASE_URL": "postgresql://auspex:auspex@localhost:5432/auspex",
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
        "DATABASE_URL": "postgresql://auspex:auspex@localhost:5432/auspex",
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
- `cwd` must be the **absolute path** to the project root so the `graph/` and
  `auspex/` packages resolve correctly.
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

**Where job state lives**

All job state — status, the final report, and scraped sources — is persisted to
Postgres from job creation (see docs/adr/0004, 0005). Status and reports resolve
from the database regardless of which instance handles the request, and
`sources` is returned on every `get_research_report` call.

**A job stays `queued` and never runs (hosted)**

Usually the Cloud Tasks worker can't reach the service — verify `worker_base_url`
matches `terraform output -raw service_url` (see [infra/README.md](../infra/README.md)).

## Hermes agent (Raspberry Pi / LAN)

Start the server in HTTP mode on your desktop, with a bearer token:
```bash
AUSPEX_MCP_TOKEN=<a-long-random-secret> python -m auspex.mcp_server --http
# Listening on http://0.0.0.0:8765/mcp
```

Then add it to `~/.hermes/config.yaml` on the Pi:
```yaml
mcp_servers:
  auspex:
    url: "http://10.0.0.37:8765/mcp"
    headers:
      Authorization: "Bearer <a-long-random-secret>"
```

Replace `10.0.0.37` with your desktop's IP on the shared subnet (verify with
`ipconfig` on Windows) and use the same secret in both places. Port 8765 is the
default; override with `--port`. If you omit `AUSPEX_MCP_TOKEN` on the server,
drop the `headers` block on the Pi too — but then anyone on the network can
reach the endpoint.

The server process must stay running while the Pi agent is active. Consider
running it in a terminal with the virtualenv active, or wrapping it in a
Windows service (NSSM / Task Scheduler) for persistence.

## Roadmap

- **HTTPS**: TLS for the HTTP transport (e.g. via `mkcert` on the LAN) so the
  bearer token and traffic aren't sent in the clear.
- **Job cancellation**: Allow clients to cancel an in-flight job.
- **Progress notifications**: Emit MCP progress notifications from the job
  runner so clients receive live node updates without polling.
- **HF Spaces HTTP endpoint**: Mount at `/mcp` on the FastAPI app so the
  deployed Space serves MCP over the public URL.
