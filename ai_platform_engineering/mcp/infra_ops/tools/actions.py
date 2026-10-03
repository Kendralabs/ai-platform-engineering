# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Container lifecycle action tools.

Deliberately narrow scope: only stop/start/restart, only on the infra-ops
SSH user's own rootless containers (this tool can't reach other tenants'
containers on a shared host), and only via a fixed allowlisted podman
invocation - never a container name or action taken from raw shell input.

Access control: this server should run with MCP_PDP_ENABLED=true and a
dedicated MCP_PDP_SCOPE (see mcp_agent_auth.middleware) so it can be granted
to a narrower set of users/agents than the read-only infra_health/
infra_list_containers/infra_container_logs tools in tools/health.py. If a
deployment needs the read-only and action tools gated independently by
CAIPE's OpenFGA/agent-use RBAC (rather than this MCP-server-wide PDP scope),
split this module into its own MCP server instead of adding it here.

Explicitly excluded from this tool, always: rm/prune, volume operations,
and any target outside the infra-ops SSH user's own containers.
"""

from typing import Any, Dict

from tools.health import CONTAINER_NAME_REGEX
from tools.ssh_runner import run_remote_command

ALLOWED_ACTIONS = frozenset({"stop", "start", "restart"})


async def infra_container_action(name: str, action: str) -> Dict[str, Any]:
    """
    Stop, start, or restart a container.

    Args:
        name: Exact container name. Must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$.
        action: One of "stop", "start", "restart". No other actions are
            supported - destructive operations (rm, prune, volume changes)
            are never exposed by this tool.

    Returns:
        Dict with the result of the podman action, or an error if the
        name or action failed validation.
    """
    if action not in ALLOWED_ACTIONS:
        return {
            "error": f"Invalid action: {action!r}. Must be one of {sorted(ALLOWED_ACTIONS)}."
        }

    if not CONTAINER_NAME_REGEX.match(name):
        return {"error": f"Invalid container name: {name}"}

    return await run_remote_command(["podman", action, name])
