"""
PolyXRD MCP Server
=================
Makes PolyXRD's XRD analysis capabilities available to AI models
via the Model Context Protocol (MCP).

Usage:
    python -m polyxrd.mcp_server          # stdio transport (default)
    python -m polyxrd.mcp_server --http   # HTTP/SSE transport
"""

from polyxrd.mcp_server.server import mcp

__all__ = ["mcp"]
