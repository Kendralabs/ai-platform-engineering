# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

#!/usr/bin/env python3
"""
Woodpecker CI MCP Server

Provides a Model Context Protocol (MCP) interface to Woodpecker CI, allowing
large language models and AI assistants to check CI/deploy status and
restart pipelines.
"""

import logging
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from mcp_agent_auth.middleware import MCPAuthMiddleware

from tools import repos
from tools import pipelines


def main():
    load_dotenv()

    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("sse_starlette.sse").setLevel(logging.INFO)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.INFO)

    MCP_MODE = os.getenv("MCP_MODE", "STDIO")
    MCP_HOST = os.getenv("MCP_HOST", "localhost")
    MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

    logging.info("Starting MCP server in {} mode on {}:{}".format(MCP_MODE, MCP_HOST, MCP_PORT))

    SERVER_NAME = os.getenv("SERVER_NAME", "Woodpecker")
    logging.info('*' * 40)
    logging.info("MCP Server name: {}".format(SERVER_NAME))
    logging.info('*' * 40)

    mcp = FastMCP(f"{SERVER_NAME} MCP Server")

    # Repositories
    mcp.tool()(repos.list_repos)
    mcp.tool()(repos.get_repo)

    # Pipelines (CI/deploy status)
    mcp.tool()(pipelines.list_pipelines)
    mcp.tool()(pipelines.get_pipeline)
    mcp.tool()(pipelines.get_latest_pipeline)
    mcp.tool()(pipelines.restart_pipeline)

    if MCP_MODE.lower() == "http":
        mcp.run(transport=MCP_MODE.lower(), host=MCP_HOST, port=MCP_PORT, middleware=[Middleware(MCPAuthMiddleware)])
    else:
        mcp.run(transport=MCP_MODE.lower())


if __name__ == "__main__":
    main()
