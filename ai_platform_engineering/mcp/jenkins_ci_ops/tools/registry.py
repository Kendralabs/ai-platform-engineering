# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Discovers Azure environments from the infra repo's envs/azure/ directory -
same discovery mechanism as azure_cluster_ops/tools/registry.py,
azure_power_ops/tools/registry.py, and azure_cost_ops/tools/registry.py.
The unit here is one environment's CI surface: its AKS cluster (where
Jenkins runs), its ACR registry, and its Key Vault - since this server
fronts the Jenkins-on-AKS pipeline for that environment, not any single
resource type.

Deliberately not special-cased for Kendra Labs' own platform: "kendralabs"
is just another registered environment, discovered the same way a
customer environment would be. See envs/azure/kendralabs/ for the entry
this server resolves today.

A directory without both terraform.tfvars and backend.hcl (not actually
applied - see envs/azure/customer-template/README.md) is never included,
and a name that doesn't resolve is refused, not attempted.
customer-template itself is always skipped.

Naming convention (see envs/azure/customer-template/main.tf and
infra/modules/azure/registry/ added for the ACR provisioning work):
  resource group:  kendra-<env>-rg
  AKS cluster:     kendra-<env>-aks
  ACR login server: output of module.registry.login_server (not derivable
    from the env name alone - resolved per-env via terraform output, see
    tools/terraform_ops.py's `_read_registry_login_server`)

Set JENKINS_CI_OPS_INFRA_REPO_PATH to the local infra repo checkout this
server should read from.
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional, TypedDict

ALL_SCOPE = "all"


class EnvSpec(TypedDict):
    resource_group: str
    cluster_name: str
    module_path: str
    registry_name: Optional[str]
    vault_name: Optional[str]


def _envs_root() -> Optional[Path]:
    infra_repo_path = os.getenv("JENKINS_CI_OPS_INFRA_REPO_PATH", "")
    if not infra_repo_path:
        return None
    root = Path(infra_repo_path) / "envs" / "azure"
    return root if root.is_dir() else None


def _parse_customer(tfvars_path: Path) -> Optional[str]:
    match = re.search(r'customer\s*=\s*"([^"]+)"', tfvars_path.read_text())
    return match.group(1) if match else None


def discover_envs() -> Dict[str, EnvSpec]:
    """
    Returns {env_name: EnvSpec} for every env that has both a
    terraform.tfvars (names the env) and a backend.hcl (actually applied).
    Empty if JENKINS_CI_OPS_INFRA_REPO_PATH isn't set, the path doesn't
    exist, or no environment has been applied yet - callers must treat an
    empty registry as "nothing to report on", not an error.
    """
    envs: Dict[str, EnvSpec] = {}
    root = _envs_root()
    if root is None:
        return envs

    for env_dir in sorted(root.iterdir()):
        if not env_dir.is_dir() or env_dir.name == "customer-template":
            continue
        tfvars = env_dir / "terraform.tfvars"
        backend = env_dir / "backend.hcl"
        if not (tfvars.exists() and backend.exists()):
            continue
        name = _parse_customer(tfvars)
        if not name:
            continue
        envs[name] = {
            "resource_group": f"kendra-{name}-rg",
            "cluster_name": f"kendra-{name}-aks",
            "module_path": str(env_dir),
            # Not derivable from the env name alone - azure_runner/az CLI
            # tools below must resolve these from live Azure state (az acr
            # list / az keyvault list scoped to resource_group) and treat
            # None as "not yet resolved", not an error.
            "registry_name": None,
            "vault_name": None,
        }
    return envs


def resolve_scope(scope: str):
    """
    Resolve an environment name or the "all" scope to a list of
    (env_name, EnvSpec) pairs. Returns an empty list for anything not
    resolvable - callers must treat that as "refused", not "no-op success".
    """
    envs = discover_envs()
    if scope == ALL_SCOPE:
        return list(envs.items())
    if scope in envs:
        return [(scope, envs[scope])]
    return []
