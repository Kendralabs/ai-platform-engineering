# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Discovers customer Azure environments from the infra repo's envs/azure/
directory - same discovery mechanism as azure_power_ops/tools/registry.py,
azure_cost_ops/tools/registry.py, and azure_cluster_ops/tools/registry.py.
The unit here is one customer's "core services" bundle: VNet, Key Vault,
and Postgres Flexible Server - the resources envs/azure/customer-template
provisions alongside AKS that are neither stoppable (azure_power_ops) nor
billed by compute capacity (azure_cluster_ops), so they're visibility-only
here.

A customer directory without both terraform.tfvars and backend.hcl (not
actually applied - see envs/azure/customer-template/README.md) is never
included, and a name that doesn't resolve is refused, not attempted.
customer-template itself is always skipped - it has neither file by design.

Naming convention (see envs/azure/customer-template/main.tf and
modules/azure/network, modules/azure/storage):
  resource group:     kendra-<customer>-rg
  virtual network:     kendra-<customer>-vnet
  key vault:           kendra-<customer>-kv
  postgres server:     kendra-<customer>-pg
  workload identity:   kendra-<customer>-workload-identity

Set AZURE_CORE_SERVICES_OPS_INFRA_REPO_PATH to the local infra repo
checkout this server should read from.
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional, TypedDict

ALL_SCOPE = "all"


class CoreServicesSpec(TypedDict):
    resource_group: str
    vnet_name: str
    key_vault_name: str
    postgres_server_name: str
    workload_identity_name: str


def _envs_root() -> Optional[Path]:
    infra_repo_path = os.getenv("AZURE_CORE_SERVICES_OPS_INFRA_REPO_PATH", "")
    if not infra_repo_path:
        return None
    root = Path(infra_repo_path) / "envs" / "azure"
    return root if root.is_dir() else None


def _parse_customer(tfvars_path: Path) -> Optional[str]:
    match = re.search(r'customer\s*=\s*"([^"]+)"', tfvars_path.read_text())
    return match.group(1) if match else None


def discover_core_services() -> Dict[str, CoreServicesSpec]:
    """
    Returns {customer: CoreServicesSpec} for every customer env that has
    both a terraform.tfvars (names the customer) and a backend.hcl
    (actually applied). Empty if AZURE_CORE_SERVICES_OPS_INFRA_REPO_PATH
    isn't set, the path doesn't exist, or no environment has been applied
    yet - callers must treat an empty registry as "nothing to report on",
    not an error.
    """
    services: Dict[str, CoreServicesSpec] = {}
    root = _envs_root()
    if root is None:
        return services

    for env_dir in sorted(root.iterdir()):
        if not env_dir.is_dir() or env_dir.name == "customer-template":
            continue
        tfvars = env_dir / "terraform.tfvars"
        backend = env_dir / "backend.hcl"
        if not (tfvars.exists() and backend.exists()):
            continue
        customer = _parse_customer(tfvars)
        if not customer:
            continue
        services[customer] = {
            "resource_group": f"kendra-{customer}-rg",
            "vnet_name": f"kendra-{customer}-vnet",
            "key_vault_name": f"kendra-{customer}-kv",
            "postgres_server_name": f"kendra-{customer}-pg",
            "workload_identity_name": f"kendra-{customer}-workload-identity",
        }
    return services


def resolve_scope(scope: str):
    """
    Resolve a customer name or the "all" scope to a list of (customer,
    CoreServicesSpec) pairs. Returns an empty list for anything not
    resolvable - callers must treat that as "refused", not "no-op success".
    """
    services = discover_core_services()
    if scope == ALL_SCOPE:
        return list(services.items())
    if scope in services:
        return [(scope, services[scope])]
    return []
