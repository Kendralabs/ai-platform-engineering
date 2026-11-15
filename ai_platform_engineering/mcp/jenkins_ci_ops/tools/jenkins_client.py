# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Minimal Jenkins REST client for the Tier 1 read-only tools
(`jenkins_get_build_status`, `jenkins_get_queue`). Talks to the Jenkins
controller's JSON API directly (`<JENKINS_URL>/job/<name>/lastBuild/api/json`,
`<JENKINS_URL>/queue/api/json`) using basic auth with a Jenkins API token -
never a generic HTTP/shell passthrough.

See registry.py for how a `scope` resolves to an environment (and,
eventually, which Jenkins controller serves it); for now there is a single
JENKINS_URL per deployment of this server.
"""

import os
from typing import Any, Dict, Optional

import httpx

from .credential_client import CredentialClientError, create_client_from_env, credentials_enabled

JENKINS_TIMEOUT = int(os.getenv("JENKINS_CI_OPS_JENKINS_TIMEOUT", "30"))


class JenkinsConfigError(RuntimeError):
    """Raised when required Jenkins config is missing or a request fails."""


async def _resolve_api_token() -> str:
    if not credentials_enabled():
        token = os.getenv("JENKINS_API_TOKEN")
        if not token:
            raise JenkinsConfigError("JENKINS_API_TOKEN is not set and CAIPE_CREDENTIALS_ENABLED is false")
        return token
    secret_ref = os.getenv("JENKINS_API_TOKEN_REF")
    if not secret_ref:
        raise JenkinsConfigError("JENKINS_API_TOKEN_REF is not set")
    try:
        client = create_client_from_env()
        return await client.retrieve_secret(secret_ref)
    except CredentialClientError as e:
        raise JenkinsConfigError(f"Failed to resolve Jenkins API token via credential exchange: {e}") from e


def _require_base_url() -> str:
    base_url = os.getenv("JENKINS_URL")
    if not base_url:
        raise JenkinsConfigError("JENKINS_URL is not set")
    return base_url.rstrip("/")


async def _get_json(path: str) -> Dict[str, Any]:
    base_url = _require_base_url()
    user = os.getenv("JENKINS_USER")
    if not user:
        raise JenkinsConfigError("JENKINS_USER is not set")
    token = await _resolve_api_token()

    async with httpx.AsyncClient(timeout=JENKINS_TIMEOUT) as client:
        try:
            response = await client.get(f"{base_url}{path}", auth=(user, token))
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise JenkinsConfigError(f"Jenkins request to {path!r} failed: {e}") from e
        return response.json()


async def get_build_status(job_name: str, build_number: Optional[str] = None) -> Dict[str, Any]:
    """Fetches last-build (or a specific build's) status for one Jenkins job."""
    build_segment = build_number or "lastBuild"
    data = await _get_json(f"/job/{job_name}/{build_segment}/api/json")
    return {
        "job_name": job_name,
        "build_number": data.get("number"),
        "result": data.get("result"),
        "duration_ms": data.get("duration"),
        "building": data.get("building"),
        "commit_sha": next(
            (
                action.get("lastBuiltRevision", {}).get("SHA1")
                for action in data.get("actions", [])
                if "lastBuiltRevision" in action
            ),
            None,
        ),
        "url": data.get("url"),
    }


async def get_queue() -> Dict[str, Any]:
    """Fetches the current Jenkins build queue."""
    data = await _get_json("/queue/api/json")
    items = data.get("items", [])
    return {
        "queue_length": len(items),
        "items": [
            {
                "task": item.get("task", {}).get("name"),
                "why": item.get("why"),
                "stuck": item.get("stuck"),
                "in_queue_since": item.get("inQueueSince"),
            }
            for item in items
        ],
    }
