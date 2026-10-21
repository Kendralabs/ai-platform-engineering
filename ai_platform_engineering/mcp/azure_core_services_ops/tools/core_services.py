# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Read-only visibility for the Azure resources envs/azure/customer-template
provisions alongside AKS that neither azure_power_ops nor azure_cluster_ops
cover: the VNet/subnets, Key Vault, Postgres Flexible Server, and the
workload-identity federated credential.

This server never writes. Nothing here is stoppable or billed by compute
capacity the way AKS/Postgres power state is (that's azure_power_ops), and
none of it is meant to be scaled (that's azure_cluster_ops) - it's config
and topology an operator wants to see, not control. In particular, Key
Vault access is reported as policy metadata (object ID + permission grants)
only - secret *values* are never read or returned.
"""

import json
import logging
from typing import Any, Dict

from .azure_runner import AzureConfigError, run_az_command
from .registry import resolve_scope

logger = logging.getLogger(__name__)


def _parse_json(raw_stdout: str):
    try:
        return json.loads(raw_stdout) if raw_stdout.strip() else None
    except json.JSONDecodeError:
        return None


async def _run_or_error(argv: list) -> tuple:
    """Returns (data, error) - data is None if the call failed or didn't parse."""
    try:
        result = await run_az_command(argv)
    except AzureConfigError as e:
        return None, str(e)
    if not result.get("success"):
        return None, result.get("stderr") or result.get("error") or "az command failed"
    data = _parse_json(result.get("stdout", ""))
    if data is None:
        return None, f"Could not parse output of: {' '.join(argv)}"
    return data, None


async def core_get_network(scope: str) -> dict:
    """
    Get VNet and subnet topology for a customer's Azure environment, or
    every registered customer when scope="all".

    Args:
        scope: A customer name (e.g. "acme"), as registered under
            envs/azure/<customer>/, or "all" for every registered customer.
    """
    pairs = resolve_scope(scope)
    if not pairs:
        return {"error": f"Unknown customer or scope: {scope!r}. No registered Azure environment matches."}

    networks: Dict[str, Any] = {}
    for customer, spec in pairs:
        vnet_data, err = await _run_or_error([
            "network", "vnet", "show", "-g", spec["resource_group"], "-n", spec["vnet_name"],
        ])
        if err:
            networks[customer] = {"error": err}
            continue

        subnets_data, err = await _run_or_error([
            "network", "vnet", "subnet", "list", "-g", spec["resource_group"], "--vnet-name", spec["vnet_name"],
        ])
        subnets = [
            {
                "name": s.get("name"),
                "address_prefix": s.get("addressPrefix"),
                "provisioning_state": s.get("provisioningState"),
            }
            for s in (subnets_data or [])
        ] if not err else {"error": err}

        networks[customer] = {
            "vnet_name": spec["vnet_name"],
            "resource_group": spec["resource_group"],
            "address_space": (vnet_data.get("addressSpace") or {}).get("addressPrefixes"),
            "provisioning_state": vnet_data.get("provisioningState"),
            "subnets": subnets,
        }

    return {"scope": scope, "networks": networks}


async def core_get_key_vault(scope: str) -> dict:
    """
    Get Key Vault metadata and access-policy grants (object ID + permissions
    only, never secret values) for a customer, or every registered customer
    when scope="all".

    Args:
        scope: A customer name or "all".
    """
    pairs = resolve_scope(scope)
    if not pairs:
        return {"error": f"Unknown customer or scope: {scope!r}. No registered Azure environment matches."}

    vaults: Dict[str, Any] = {}
    for customer, spec in pairs:
        data, err = await _run_or_error([
            "keyvault", "show", "-g", spec["resource_group"], "-n", spec["key_vault_name"],
        ])
        if err:
            vaults[customer] = {"error": err}
            continue

        props = data.get("properties", {})
        vaults[customer] = {
            "key_vault_name": spec["key_vault_name"],
            "resource_group": spec["resource_group"],
            "provisioning_state": props.get("provisioningState"),
            "sku": (props.get("sku") or {}).get("name"),
            "soft_delete_enabled": props.get("enableSoftDelete"),
            "purge_protection_enabled": props.get("enablePurgeProtection"),
            "access_policies": [
                {
                    "object_id": p.get("objectId"),
                    "secret_permissions": (p.get("permissions") or {}).get("secrets"),
                    "key_permissions": (p.get("permissions") or {}).get("keys"),
                }
                for p in (props.get("accessPolicies") or [])
            ],
        }

    return {"scope": scope, "key_vaults": vaults}


async def core_get_postgres(scope: str) -> dict:
    """
    Get Postgres Flexible Server configuration (version, SKU, storage, HA
    state - never credentials) for a customer, or every registered customer
    when scope="all".

    Args:
        scope: A customer name or "all".
    """
    pairs = resolve_scope(scope)
    if not pairs:
        return {"error": f"Unknown customer or scope: {scope!r}. No registered Azure environment matches."}

    servers: Dict[str, Any] = {}
    for customer, spec in pairs:
        data, err = await _run_or_error([
            "postgres", "flexible-server", "show",
            "-g", spec["resource_group"], "-n", spec["postgres_server_name"],
        ])
        if err:
            servers[customer] = {"error": err}
            continue

        servers[customer] = {
            "postgres_server_name": spec["postgres_server_name"],
            "resource_group": spec["resource_group"],
            "state": data.get("state"),
            "version": data.get("version"),
            "sku": (data.get("sku") or {}).get("name"),
            "storage_gb": (data.get("storage") or {}).get("storageSizeGb"),
            "ha_mode": (data.get("highAvailability") or {}).get("mode"),
            "ha_state": (data.get("highAvailability") or {}).get("state"),
        }

    return {"scope": scope, "postgres_servers": servers}


async def core_get_workload_identity(scope: str) -> dict:
    """
    Get the workload-identity (user-assigned managed identity) client ID
    and federated-credential binding for a customer, or every registered
    customer when scope="all".

    Args:
        scope: A customer name or "all".
    """
    pairs = resolve_scope(scope)
    if not pairs:
        return {"error": f"Unknown customer or scope: {scope!r}. No registered Azure environment matches."}

    identities: Dict[str, Any] = {}
    for customer, spec in pairs:
        data, err = await _run_or_error([
            "identity", "show", "-g", spec["resource_group"], "-n", spec["workload_identity_name"],
        ])
        if err:
            identities[customer] = {"error": err}
            continue

        fed_data, err = await _run_or_error([
            "identity", "federated-credential", "list",
            "-g", spec["resource_group"], "--identity-name", spec["workload_identity_name"],
        ])
        federated_credentials = [
            {
                "name": f.get("name"),
                "issuer": f.get("issuer"),
                "subject": f.get("subject"),
                "audiences": f.get("audiences"),
            }
            for f in (fed_data or [])
        ] if not err else {"error": err}

        identities[customer] = {
            "identity_name": spec["workload_identity_name"],
            "resource_group": spec["resource_group"],
            "client_id": data.get("clientId"),
            "principal_id": data.get("principalId"),
            "federated_credentials": federated_credentials,
        }

    return {"scope": scope, "workload_identities": identities}
