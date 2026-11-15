# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Tier 1 read-only ACR tools. Each resolves a `scope` (customer/env name, or
"all") via registry.py, then runs a fixed, allowlisted `az acr` command per
matched environment through azure_runner.run_az_command - never a raw
`az` passthrough.

Tier 3 write tools (acr_delete_repository, etc.) are intentionally not
implemented here - see README.md.
"""

from typing import Any, Dict

from . import azure_runner
from .registry import resolve_scope


def _parse_json(raw: str):
    import json

    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def acr_list_repositories(scope: str) -> Dict[str, Any]:
    """Lists repositories in the ACR registry for the given scope ("all" or an env name)."""
    matches = resolve_scope(scope)
    if not matches:
        return {"error": f"scope {scope!r} did not resolve to any registered environment", "success": False}

    results = {}
    for env_name, env_spec in matches:
        registry_name = env_spec.get("registry_name")
        if not registry_name:
            results[env_name] = {"error": "no ACR registry resolved for this environment", "success": False}
            continue
        result = await azure_runner.run_az_command(
            ["acr", "repository", "list", "--name", registry_name]
        )
        result["repositories"] = _parse_json(result.get("stdout", "")) if result.get("success") else None
        results[env_name] = result
    return {"results": results}


async def acr_show_digest(scope: str, repository: str, tag: str) -> Dict[str, Any]:
    """
    Resolves a tag to its immutable digest for one environment's ACR
    registry - matches ArtifactManager.groovy's build-once-deploy-anywhere
    convention of promoting by digest, never by mutable tag.
    """
    matches = resolve_scope(scope)
    if len(matches) != 1:
        return {
            "error": f"acr_show_digest requires exactly one resolved environment, got {len(matches)} for scope {scope!r}",
            "success": False,
        }
    env_name, env_spec = matches[0]
    registry_name = env_spec.get("registry_name")
    if not registry_name:
        return {"error": f"no ACR registry resolved for environment {env_name!r}", "success": False}

    result = await azure_runner.run_az_command([
        "acr", "repository", "show",
        "--name", registry_name,
        "--image", f"{repository}:{tag}",
    ])
    parsed = _parse_json(result.get("stdout", "")) if result.get("success") else None
    return {
        **result,
        "digest": (parsed or {}).get("digest"),
        "environment": env_name,
    }
