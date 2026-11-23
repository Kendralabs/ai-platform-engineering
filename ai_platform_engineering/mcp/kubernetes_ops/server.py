# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Kubernetes Ops MCP Server

Direct kubectl-style control over customer AKS clusters, for actions
outside what the ArgoCD agent's own Application/resource sync API covers:
restarting a Deployment rollout, scaling, tailing pod logs, deleting a
stuck pod, and describing events/pod status. Composed the same way
azure_cluster_ops and azure_power_ops compose their registry/runner split:
discovery-based registry (tools/registry.py) resolves a customer name or
"all" to AKS cluster(s), and tools/k8s_runner.py materializes a per-call
kubeconfig (via `az aks get-credentials` after a lazy service-principal
login) and hands it to the official kubernetes Python client - never a raw
kubectl/shell passthrough. See tools/deployments.py for the confirm=True
guard on every write tool, and README.md for what's deliberately out of
scope.
"""

import logging
import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware
from mcp_agent_auth.middleware import MCPAuthMiddleware

from tools import deployments, pods


def main():
    load_dotenv()

    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("sse_starlette.sse").setLevel(logging.INFO)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.INFO)

    MCP_MODE = os.getenv("MCP_MODE", "STDIO")
    MCP_HOST = os.getenv("MCP_HOST", "localhost")
    MCP_PORT = int(os.getenv("MCP_PORT", "8000"))

    logging.info("Starting MCP server in {} mode on {}:{}".format(MCP_MODE, MCP_HOST, MCP_PORT))

    SERVER_NAME = os.getenv("SERVER_NAME", "KubernetesOps")
    logging.info("*" * 40)
    logging.info("MCP Server name: {}".format(SERVER_NAME))
    logging.info("*" * 40)

    mcp = FastMCP(f"{SERVER_NAME} MCP Server")

    # Tier 1: read-only pod visibility (list, status, logs, events).
    mcp.tool()(pods.k8s_list_pods)
    mcp.tool()(pods.k8s_get_pod_status)
    mcp.tool()(pods.k8s_get_pod_logs)
    mcp.tool()(pods.k8s_describe_events)

    # Tier 2: read-only deployment visibility.
    mcp.tool()(deployments.k8s_get_deployment_status)

    # Tier 3: write actions - each gated by confirm=True, see tools/deployments.py.
    mcp.tool()(deployments.k8s_restart_deployment)
    mcp.tool()(deployments.k8s_scale_deployment)
    mcp.tool()(deployments.k8s_delete_pod)

    if MCP_MODE.lower() == "http":
        mcp.run(transport=MCP_MODE.lower(), host=MCP_HOST, port=MCP_PORT, middleware=[Middleware(MCPAuthMiddleware)])
    else:
        mcp.run(transport=MCP_MODE.lower())


if __name__ == "__main__":
    main()
