# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

#!/usr/bin/env python3
"""
Observability Ops MCP Server

Gives read access to the platform's observability stack (SigNoz
query-service + the dedicated "signoz" ClickHouse database), plus a
guarded ability to restart unhealthy observability Deployments in
Kubernetes. See README.md for the full tool surface and known gaps.
"""

import logging
import os

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from mcp_agent_auth.middleware import MCPAuthMiddleware

from tools import observability, restart


def main():
    # Load environment variables
    load_dotenv()

    # Configure logging
    logging.basicConfig(level=logging.INFO)

    # Get MCP configuration from environment variables
    MCP_MODE = os.getenv("MCP_MODE", "stdio").lower()

    # Get host and port for server
    MCP_HOST = os.getenv("MCP_HOST", "localhost")
    MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

    logging.info(f"Starting MCP server in {MCP_MODE} mode on {MCP_HOST}:{MCP_PORT}")

    # Get agent name from environment variables
    SERVER_NAME = os.getenv("SERVER_NAME") or os.getenv("AGENT_NAME") or "OBSERVABILITY_OPS"
    logging.info(f"MCP Server name: {SERVER_NAME}")

    # Create server instance
    mcp = FastMCP(f"{SERVER_NAME} MCP Server")

    # ------------------------------------------------------------------
    # Tier 1 - read-only tools (always on, no approval). SigNoz
    # query-service + signoz ClickHouse database, read-only queries only.
    # ------------------------------------------------------------------
    mcp.tool()(observability.observability_get_service_health)
    mcp.tool()(observability.observability_query_traces)
    mcp.tool()(observability.observability_query_logs)
    mcp.tool()(observability.observability_query_metrics)

    # ------------------------------------------------------------------
    # Tier 2 - write tool (confirm=True gated, KACP policy-gated,
    # audit-logged). Restarts one allow-listed observability Deployment.
    # ------------------------------------------------------------------
    mcp.tool()(restart.observability_restart_component)

    # Run the MCP server
    if MCP_MODE.lower() == "http":
        mcp.run(transport=MCP_MODE.lower(), host=MCP_HOST, port=MCP_PORT, middleware=[Middleware(MCPAuthMiddleware)])
    else:
        mcp.run(transport=MCP_MODE.lower())


if __name__ == "__main__":
    main()
