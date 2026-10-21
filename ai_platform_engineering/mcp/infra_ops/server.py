# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Infra Ops MCP Server

Read-only infrastructure health and container-visibility tools for the
CAIPE-managed VPS tenant, over an allowlisted SSH command set. See
tools/ssh_runner.py for the connection model and tools/health.py for scope.
"""

import logging
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from mcp_agent_auth.middleware import MCPAuthMiddleware

from tools import actions
from tools import health


def main():
    load_dotenv()

    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("sse_starlette.sse").setLevel(logging.INFO)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.INFO)

    MCP_MODE = os.getenv("MCP_MODE", "STDIO")
    MCP_HOST = os.getenv("MCP_HOST", "localhost")
    MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

    logging.info("Starting MCP server in {} mode on {}:{}".format(MCP_MODE, MCP_HOST, MCP_PORT))

    SERVER_NAME = os.getenv("SERVER_NAME", "InfraOps")
    logging.info("*" * 40)
    logging.info("MCP Server name: {}".format(SERVER_NAME))
    logging.info("*" * 40)

    mcp = FastMCP(f"{SERVER_NAME} MCP Server")

    # Read-only host health and container visibility (Phase 1)
    mcp.tool()(health.infra_health)
    mcp.tool()(health.infra_list_containers)
    mcp.tool()(health.infra_container_logs)

    # Container lifecycle actions (Phase 2) - see tools/actions.py for the
    # scope restrictions and the RBAC caveat before enabling in production.
    mcp.tool()(actions.infra_container_action)

    if MCP_MODE.lower() == "http":
        mcp.run(transport=MCP_MODE.lower(), host=MCP_HOST, port=MCP_PORT, middleware=[Middleware(MCPAuthMiddleware)])
    else:
        mcp.run(transport=MCP_MODE.lower())


if __name__ == "__main__":
    main()
