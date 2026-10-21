# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Azure Core Services Ops MCP Server

Read-only visibility for a customer's VNet/subnets, Key Vault (policy
metadata only, never secret values), Postgres Flexible Server config, and
workload-identity federated credential - the resources
envs/azure/customer-template provisions alongside AKS that neither
azure_power_ops (power on/off) nor azure_cluster_ops (node-pool scaling)
cover. Composed the same way as the other three Azure agents: a
discovery-based registry (tools/registry.py) resolves a customer name or
"all", and tools/azure_runner.py runs a fixed `az` command set after a lazy
service-principal login. No write tools - see README.md for why.
"""

import logging
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from mcp_agent_auth.middleware import MCPAuthMiddleware

from tools import core_services


def main():
    load_dotenv()

    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("sse_starlette.sse").setLevel(logging.INFO)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.INFO)

    MCP_MODE = os.getenv("MCP_MODE", "STDIO")
    MCP_HOST = os.getenv("MCP_HOST", "localhost")
    MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

    logging.info("Starting MCP server in {} mode on {}:{}".format(MCP_MODE, MCP_HOST, MCP_PORT))

    SERVER_NAME = os.getenv("SERVER_NAME", "AzureCoreServicesOps")
    logging.info("*" * 40)
    logging.info("MCP Server name: {}".format(SERVER_NAME))
    logging.info("*" * 40)

    mcp = FastMCP(f"{SERVER_NAME} MCP Server")

    # Read-only visibility - no write tools in this server.
    mcp.tool()(core_services.core_get_network)
    mcp.tool()(core_services.core_get_key_vault)
    mcp.tool()(core_services.core_get_postgres)
    mcp.tool()(core_services.core_get_workload_identity)

    if MCP_MODE.lower() == "http":
        mcp.run(transport=MCP_MODE.lower(), host=MCP_HOST, port=MCP_PORT, middleware=[Middleware(MCPAuthMiddleware)])
    else:
        mcp.run(transport=MCP_MODE.lower())


if __name__ == "__main__":
    main()
