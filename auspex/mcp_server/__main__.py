"""Entrypoint: python -m auspex.mcp_server

Modes
-----
stdio (default):
    python -m auspex.mcp_server
    Launched as a subprocess by Claude Desktop or similar local MCP clients.

HTTP (remote clients on the same network):
    python -m auspex.mcp_server --http [--host 0.0.0.0] [--port 8765]
    Serves the MCP server over streamable HTTP so remote agents (e.g. a
    Hermes agent on a Pi) can connect to http://<your-ip>:<port>/mcp.

    Set AUSPEX_MCP_TOKEN to require an Authorization: Bearer <token> header
    on every HTTP request. If unset, the endpoint is unauthenticated (only
    appropriate on a fully trusted network).
"""

import argparse
import logging
import os

from auspex.mcp_server.server import build_http_app, mcp

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Auspex MCP server")
    parser.add_argument(
        "--http",
        action="store_true",
        help="Run over HTTP instead of stdio (for remote MCP clients)",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host to bind when running in HTTP mode (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on when running in HTTP mode (default: 8765)",
    )
    args = parser.parse_args()

    if args.http:
        import uvicorn

        logging.basicConfig(level=logging.INFO)
        token = os.environ.get("AUSPEX_MCP_TOKEN")
        if not token:
            logger.warning(
                "AUSPEX_MCP_TOKEN is not set — the HTTP endpoint is UNAUTHENTICATED. "
                "Anyone who can reach this host:port can start jobs and read reports."
            )
        app = build_http_app(token)
        uvicorn.run(app, host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
