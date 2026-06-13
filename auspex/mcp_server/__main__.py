"""Entrypoint: python -m auspex.mcp_server"""
from auspex.mcp_server.server import mcp

if __name__ == "__main__":
    mcp.run(transport="stdio")
