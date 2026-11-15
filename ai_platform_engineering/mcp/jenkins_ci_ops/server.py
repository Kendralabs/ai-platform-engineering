# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Jenkins CI Ops MCP Server. See README.md for the full tool surface and the
design principle behind it (no raw az/kubectl/terraform passthrough tools).
"""

import os

from fastmcp import FastMCP
from mcp_agent_auth.middleware import MCPAuthMiddleware
from starlette.middleware import Middleware

from tools import acr_ops, jenkins_client, keyvault_ops, terraform_ops

MCP_MODE = os.getenv("MCP_MODE", "STDIO")
MCP_HOST = os.getenv("MCP_HOST", "localhost")
MCP_PORT = int(os.getenv("MCP_PORT", "8000"))
SERVER_NAME = os.getenv("SERVER_NAME", "JenkinsCIOps")

mcp = FastMCP(f"{SERVER_NAME} MCP Server")

# Tier 1 - read-only
mcp.tool()(jenkins_client.get_build_status)
mcp.tool()(jenkins_client.get_queue)
mcp.tool()(acr_ops.acr_list_repositories)
mcp.tool()(acr_ops.acr_show_digest)
mcp.tool()(keyvault_ops.keyvault_list_secret_names)
mcp.tool()(terraform_ops.terraform_show_state)

# Tier 2 - plan/diff
mcp.tool()(terraform_ops.terraform_plan)

# Tier 3 - write/apply (deliberately unimplemented stubs, see README.md)
mcp.tool()(terraform_ops.terraform_apply)
mcp.tool()(keyvault_ops.keyvault_set_secret)


def main() -> None:
    if MCP_MODE.lower() == "http":
        mcp.run(transport=MCP_MODE.lower(), host=MCP_HOST, port=MCP_PORT, middleware=[Middleware(MCPAuthMiddleware)])
    else:
        mcp.run(transport=MCP_MODE.lower())


if __name__ == "__main__":
    main()
