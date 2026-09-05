# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""Tools for /api/repos operations (repository status)."""

import logging
from typing import Dict, Any, List
from api.client import make_api_request

logger = logging.getLogger("mcp_tools")


async def list_repos() -> List[Dict[str, Any]] | Dict[str, Any]:
    """
    List all repositories enabled in Woodpecker CI, visible to the configured token.

    Returns:
        A list of repo objects (id, full_name, active, etc.), or a dict with
        an "error" key if the request fails.
    """
    success, response = await make_api_request("/api/user/repos")
    if not success:
        error = response.get("error") if isinstance(response, dict) else "Request failed"
        logger.error(f"Request failed: {error}")
        return {"error": error or "Request failed"}
    return response


async def get_repo(repo_id: int) -> Dict[str, Any]:
    """
    Get details for a single repository by its Woodpecker repo ID.

    Args:
        repo_id: Woodpecker's internal numeric repo ID (see list_repos for IDs).

    Returns:
        The repo object, or a dict with an "error" key if the request fails.
    """
    success, response = await make_api_request(f"/api/repos/{repo_id}")
    if not success:
        error = response.get("error") if isinstance(response, dict) else "Request failed"
        logger.error(f"Request failed: {error}")
        return {"error": error or "Request failed"}
    return response
