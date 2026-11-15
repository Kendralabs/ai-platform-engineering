# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Key Vault tools.

`keyvault_list_secret_names` is Tier 1: it lists secret **names** only,
never values, via `az keyvault secret list` (which never returns secret
values itself).

`keyvault_set_secret` is a **deliberate non-implementation**. Azure Key
Vault `kendra-kendralabs-kv` must never be given public network access or
written to from outside the cluster - see
infra/docs/runbooks/azure-platform/04b-kiam-identity-admin-vault-provisioning.md.
This tool exists only so an agent asking "how do I set a secret here" gets
that runbook back, never a live write path.
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


async def keyvault_list_secret_names(scope: str) -> Dict[str, Any]:
    """Lists secret names (never values) in the Key Vault for the given scope."""
    matches = resolve_scope(scope)
    if not matches:
        return {"error": f"scope {scope!r} did not resolve to any registered environment", "success": False}

    results = {}
    for env_name, env_spec in matches:
        vault_name = env_spec.get("vault_name")
        if not vault_name:
            results[env_name] = {"error": "no Key Vault resolved for this environment", "success": False}
            continue
        result = await azure_runner.run_az_command(
            ["keyvault", "secret", "list", "--vault-name", vault_name, "--query", "[].name"]
        )
        result["secret_names"] = _parse_json(result.get("stdout", "")) if result.get("success") else None
        results[env_name] = result
    return {"results": results}


async def keyvault_set_secret(scope: str, secret_name: str, confirm: bool = False) -> Dict[str, Any]:
    """
    Not implemented. Returns the in-cluster-pod provisioning runbook instead
    of writing anything - this server's own credentials must never be able
    to write Key Vault secrets.
    """
    return {
        "success": False,
        "implemented": False,
        "reason": (
            "keyvault_set_secret is intentionally not implemented. "
            f"kendra-kendralabs-kv (and every per-environment vault) must never be "
            "given public network access or written to directly - secrets are set "
            "only via an in-cluster pod using workload identity."
        ),
        "runbook": "infra/docs/runbooks/azure-platform/04b-kiam-identity-admin-vault-provisioning.md",
        "scope": scope,
        "secret_name": secret_name,
    }
