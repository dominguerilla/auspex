#!/usr/bin/env bash
#
# Entrypoint for the Auspex MCP server on AWS App Runner (see docs/adr/0004).
#
# Used as the App Runner *start command* against the shared project image
# (the Dockerfile's default CMD still runs the FastAPI web app for HF Spaces —
# this is the "one image, two entrypoints" split):
#
#     bash deploy/entrypoint-mcp.sh
#
# It applies any pending DB migrations, then serves the streamable-HTTP MCP
# server on $PORT (App Runner default 8080). Single instance, so running the
# migration at startup is safe (no concurrent-migration race).
set -euo pipefail

echo "[entrypoint] alembic upgrade head ..."
alembic upgrade head

PORT="${PORT:-8080}"
echo "[entrypoint] starting MCP server (streamable HTTP) on 0.0.0.0:${PORT} ..."
exec python -m auspex.mcp_server --http --host 0.0.0.0 --port "${PORT}"
