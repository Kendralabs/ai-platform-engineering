# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Tier 2 - the one write tool this server has: a guarded rollout-restart of
an unhealthy observability Deployment in the `observability` namespace.

Gated behind `confirm: bool = False`, exactly like
azure_power_ops/tools/power.py's power_on/power_off. `component` is
restricted to a fixed allow-list (ALLOWED_COMPONENTS below) matching the
Deployments this chart actually creates (see
`charts/observability/values.yaml` in the infra repo: otel-collector,
query-service, frontend are Deployments; zookeeper is a StatefulSet and is
deliberately left out of this allow-list - see README.md "Known gaps").
Anything outside the allow-list is refused outright, before any Azure or
Kubernetes call is made.

This module ships its own self-contained `az login --service-principal` +
`az aks get-credentials` + `kubernetes.config.load_kube_config()` runner
rather than cross-calling azure_cluster_ops/azure_power_ops at runtime -
this repo's convention (confirmed by how azure_power_ops/azure_cost_ops/
azure_cluster_ops/jenkins_ci_ops each duplicate their own runner/registry
rather than importing a shared one) is that each MCP server ships as an
independently-deployable unit. This agent only ever targets the platform's
own fixed observability AKS cluster (OBSERVABILITY_OPS_AKS_RESOURCE_GROUP /
OBSERVABILITY_OPS_AKS_CLUSTER_NAME) - there is no per-customer registry
here, unlike the Azure agents.
"""

import asyncio
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from .credential_client import CredentialClientError, create_client_from_env, credentials_enabled

logger = logging.getLogger(__name__)

AZ_TIMEOUT = int(os.getenv("OBSERVABILITY_OPS_AZ_TIMEOUT", "120"))
REQUIRED_ARM_ENV = ("ARM_CLIENT_ID", "ARM_TENANT_ID", "ARM_SUBSCRIPTION_ID")
ARM_CLIENT_SECRET_REF = os.getenv("ARM_CLIENT_SECRET_REF", "observability-ops/arm-client-secret")
OBSERVABILITY_NAMESPACE = "observability"

# Fixed allow-list: component name -> Deployment name in the `observability`
# namespace. Anything not a key here is refused in observability_restart_component
# before any Azure/Kubernetes call happens.
ALLOWED_COMPONENTS: Dict[str, str] = {
    "otel-collector": "otel-collector",
    "query-service": "query-service",
    "frontend": "frontend",
}

_kubeconfig_path: str | None = None
_login_lock = asyncio.Lock()


class ObservabilityOpsConfigError(RuntimeError):
    """Raised when required Azure/AKS config is missing, or az/kubeconfig setup fails."""


def _require_arm_config() -> None:
    missing = [name for name in REQUIRED_ARM_ENV if not os.getenv(name)]
    if missing:
        raise ObservabilityOpsConfigError(
            f"Azure service principal is not configured, missing env vars: {', '.join(missing)}"
        )
    if not credentials_enabled() and not os.getenv("ARM_CLIENT_SECRET"):
        raise ObservabilityOpsConfigError(
            "Azure service principal is not configured, missing env var: ARM_CLIENT_SECRET"
        )

    aks_missing = [
        name
        for name in ("OBSERVABILITY_OPS_AKS_RESOURCE_GROUP", "OBSERVABILITY_OPS_AKS_CLUSTER_NAME")
        if not os.getenv(name)
    ]
    if aks_missing:
        raise ObservabilityOpsConfigError(
            f"Target AKS cluster is not configured, missing env vars: {', '.join(aks_missing)}"
        )


async def _resolve_client_secret() -> str:
    if not credentials_enabled():
        return os.environ["ARM_CLIENT_SECRET"]
    try:
        client = create_client_from_env()
        return await client.retrieve_secret(ARM_CLIENT_SECRET_REF)
    except CredentialClientError as e:
        raise ObservabilityOpsConfigError(
            f"Failed to resolve ARM_CLIENT_SECRET via credential exchange: {e}"
        ) from e


async def _run_az(argv: list[str]) -> Dict[str, Any]:
    cmd_str = " ".join(argv)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AZ_TIMEOUT)
        return {
            "command": cmd_str,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
            "success": proc.returncode == 0,
        }
    except asyncio.TimeoutError:
        return {"command": cmd_str, "error": "az command timed out", "success": False}


async def _ensure_kubeconfig() -> str:
    """
    Logs into Azure as the configured service principal, then fetches
    kubeconfig for the fixed observability AKS cluster into a dedicated
    temp file (never the operator's own ~/.kube/config). Returns that
    kubeconfig path. Cached for the life of the process.
    """
    global _kubeconfig_path
    if _kubeconfig_path:
        return _kubeconfig_path

    _require_arm_config()
    async with _login_lock:
        if _kubeconfig_path:
            return _kubeconfig_path

        client_secret = await _resolve_client_secret()
        login_result = await _run_az([
            "az", "login", "--service-principal",
            "-u", os.environ["ARM_CLIENT_ID"],
            "-p", client_secret,
            "--tenant", os.environ["ARM_TENANT_ID"],
            "--output", "none",
        ])
        if not login_result["success"]:
            raise ObservabilityOpsConfigError(
                f"az login --service-principal failed: {login_result.get('stderr', '')}"
            )

        set_sub_result = await _run_az([
            "az", "account", "set", "--subscription", os.environ["ARM_SUBSCRIPTION_ID"],
        ])
        if not set_sub_result["success"]:
            raise ObservabilityOpsConfigError(f"az account set failed: {set_sub_result.get('stderr', '')}")

        kubeconfig_fd, kubeconfig_path = tempfile.mkstemp(prefix="observability-ops-kubeconfig-")
        os.close(kubeconfig_fd)

        get_creds_result = await _run_az([
            "az", "aks", "get-credentials",
            "-g", os.environ["OBSERVABILITY_OPS_AKS_RESOURCE_GROUP"],
            "-n", os.environ["OBSERVABILITY_OPS_AKS_CLUSTER_NAME"],
            "-f", kubeconfig_path,
            "--overwrite-existing",
        ])
        if not get_creds_result["success"]:
            raise ObservabilityOpsConfigError(
                f"az aks get-credentials failed: {get_creds_result.get('stderr', '')}"
            )

        _kubeconfig_path = kubeconfig_path
        return _kubeconfig_path


def _patch_deployment_restart(kubeconfig_path: str, deployment_name: str) -> Dict[str, Any]:
    """Synchronous Kubernetes Apps V1 API call - run via asyncio.to_thread."""
    k8s_config.load_kube_config(config_file=kubeconfig_path)
    apps_v1 = k8s_client.AppsV1Api()

    restarted_at = datetime.now(timezone.utc).isoformat()
    body = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": restarted_at,
                    }
                }
            }
        }
    }

    patched = apps_v1.patch_namespaced_deployment(
        name=deployment_name,
        namespace=OBSERVABILITY_NAMESPACE,
        body=body,
    )
    return {
        "deployment": deployment_name,
        "namespace": OBSERVABILITY_NAMESPACE,
        "restarted_at": restarted_at,
        "observed_generation": patched.status.observed_generation if patched.status else None,
    }


async def observability_restart_component(component: str, confirm: bool = False) -> Dict[str, Any]:
    """
    Trigger a rollout restart of one observability Deployment by patching
    its pod-template annotation, the same mechanism `kubectl rollout
    restart` uses. ALWAYS requires confirm=True - this is this server's
    only write tool.

    Args:
        component: One of "otel-collector", "query-service", "frontend"
            (see ALLOWED_COMPONENTS). Any other value is refused outright,
            before any Azure/Kubernetes call is made. "zookeeper" is
            deliberately not supported - it's a StatefulSet, not a
            Deployment, and restarting it has different failure-mode
            implications (see README.md "Known gaps").
        confirm: Must be True to actually restart the component.
    """
    if component not in ALLOWED_COMPONENTS:
        return {
            "error": (
                f"Unknown or disallowed component: {component!r}. "
                f"Allowed: {sorted(ALLOWED_COMPONENTS)}"
            )
        }
    if not confirm:
        return {"error": "observability_restart_component always requires confirm=True"}

    try:
        kubeconfig_path = await _ensure_kubeconfig()
    except ObservabilityOpsConfigError as e:
        return {"error": str(e)}

    deployment_name = ALLOWED_COMPONENTS[component]
    try:
        result = await asyncio.to_thread(_patch_deployment_restart, kubeconfig_path, deployment_name)
    except Exception as e:  # kubernetes client raises its own ApiException hierarchy
        logger.error(f"observability_restart_component failed for {component!r}: {e}")
        return {"error": f"Kubernetes patch failed for {deployment_name!r}: {e}"}

    return {"component": component, "confirm": confirm, **result}
