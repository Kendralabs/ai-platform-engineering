# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""Tools for /api/repos/{repo_id}/pipelines operations (CI/deploy status)."""

import logging
from typing import Dict, Any, List, Optional
from api.client import make_api_request

logger = logging.getLogger("mcp_tools")


async def list_pipelines(repo_id: int, page: Optional[int] = None) -> List[Dict[str, Any]] | Dict[str, Any]:
    """
    List recent pipelines (CI/deploy runs) for a repository, newest first.

    Args:
        repo_id: Woodpecker's internal numeric repo ID (see list_repos for IDs).
        page: Optional page number for pagination (Woodpecker paginates results).

    Returns:
        A list of pipeline summary objects (number, status, branch, event,
        created/finished timestamps, author, commit message), or a dict with
        an "error" key if the request fails.
    """
    params = {}
    if page is not None:
        params["page"] = page
    success, response = await make_api_request(f"/api/repos/{repo_id}/pipelines", params=params)
    if not success:
        error = response.get("error") if isinstance(response, dict) else "Request failed"
        logger.error(f"Request failed: {error}")
        return {"error": error or "Request failed"}
    return response


async def get_pipeline(repo_id: int, pipeline_number: int) -> Dict[str, Any]:
    """
    Get full detail for a single pipeline run, including its per-step status.

    Args:
        repo_id: Woodpecker's internal numeric repo ID.
        pipeline_number: The pipeline's number within that repo (shown in the
            Woodpecker UI, and returned by list_pipelines/get_latest_pipeline).

    Returns:
        The pipeline object including its `workflows`/`steps` breakdown, or a
        dict with an "error" key if the request fails.
    """
    success, response = await make_api_request(f"/api/repos/{repo_id}/pipelines/{pipeline_number}")
    if not success:
        error = response.get("error") if isinstance(response, dict) else "Request failed"
        logger.error(f"Request failed: {error}")
        return {"error": error or "Request failed"}
    return response


async def get_latest_pipeline(repo_id: int, branch: Optional[str] = None) -> Dict[str, Any]:
    """
    Get the most recent pipeline run for a repository — the quickest way to
    answer "did the last CI run / deploy for this repo succeed?".

    Args:
        repo_id: Woodpecker's internal numeric repo ID.
        branch: Optional branch name to filter to (e.g. "main") — without it,
            the single most recent pipeline across all branches is returned.

    Returns:
        The most recent matching pipeline summary object, or a dict with an
        "error" key if none is found or the request fails.
    """
    success, response = await make_api_request(f"/api/repos/{repo_id}/pipelines")
    if not success:
        error = response.get("error") if isinstance(response, dict) else "Request failed"
        logger.error(f"Request failed: {error}")
        return {"error": error or "Request failed"}

    pipelines = response if isinstance(response, list) else []
    if branch:
        pipelines = [p for p in pipelines if p.get("branch") == branch]

    if not pipelines:
        return {"error": f"No pipelines found for repo {repo_id}" + (f" on branch {branch}" if branch else "")}

    # Woodpecker returns pipelines newest-first; guard against API changes anyway.
    latest = max(pipelines, key=lambda p: p.get("created", 0))
    return latest


async def restart_pipeline(repo_id: int, pipeline_number: int) -> Dict[str, Any]:
    """
    Restart (re-run) a pipeline — equivalent to clicking "Restart" in the
    Woodpecker UI. Use for re-triggering a failed CI run or a deploy.

    Args:
        repo_id: Woodpecker's internal numeric repo ID.
        pipeline_number: The pipeline number to restart.

    Returns:
        The newly created pipeline object, or a dict with an "error" key if
        the request fails.
    """
    success, response = await make_api_request(f"/api/repos/{repo_id}/pipelines/{pipeline_number}", method="POST")
    if not success:
        error = response.get("error") if isinstance(response, dict) else "Request failed"
        logger.error(f"Request failed: {error}")
        return {"error": error or "Request failed"}
    return response
