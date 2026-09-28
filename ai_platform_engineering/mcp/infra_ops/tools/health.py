# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Read-only infrastructure health and container visibility tools.
"""

import re
from typing import Any, Dict

from tools.ssh_runner import run_remote_command

CONTAINER_NAME_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


async def infra_health() -> Dict[str, Any]:
    """
    Get overall host health for the configured infra-ops target: load average,
    memory usage, disk usage, and uptime.

    Returns:
        Dict with uptime/load, memory, and disk usage output from the host.
    """
    uptime = await run_remote_command(["uptime"])
    memory = await run_remote_command(["free", "-h"])
    disk = await run_remote_command(["df", "-h", "/"])

    return {
        "uptime": uptime,
        "memory": memory,
        "disk": disk,
    }


async def infra_list_containers(tenant_prefix: str = "") -> Dict[str, Any]:
    """
    List containers visible to the configured infra-ops SSH user, including
    status and restart-related fields useful for spotting crash loops.

    Args:
        tenant_prefix: Optional container-name prefix filter (e.g. "mcp-").
            Only the SSH user's own rootless containers are visible - this
            tool cannot see other tenants' containers on a shared host.

    Returns:
        Dict with the raw `podman ps -a` table, optionally pre-filtered.
    """
    if tenant_prefix and not CONTAINER_NAME_REGEX.match(tenant_prefix):
        return {"error": f"Invalid tenant_prefix: {tenant_prefix}"}

    result = await run_remote_command(
        ["podman", "ps", "-a", "--format",
         "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.CreatedAt}}"]
    )

    if tenant_prefix and result.get("success"):
        lines = result["stdout"].splitlines()
        result["stdout"] = "\n".join(
            line for line in lines if line.startswith(tenant_prefix)
        )

    return result


async def infra_container_logs(name: str, lines: int = 100) -> Dict[str, Any]:
    """
    Read the tail of a container's logs (read-only).

    Args:
        name: Exact container name. Must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$.
        lines: Number of trailing log lines to fetch. Defaults to 100, max 1000.

    Returns:
        Dict with the container's recent log output.
    """
    if not CONTAINER_NAME_REGEX.match(name):
        return {"error": f"Invalid container name: {name}"}

    lines = min(max(1, lines), 1000)

    return await run_remote_command(["podman", "logs", "--tail", str(lines), name])
