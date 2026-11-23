# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
kubectl-style execution helper for customer AKS clusters - same lazy
service-principal login contract as azure_cluster_ops/tools/azure_runner.py
(and azure_power_ops/azure_cost_ops's copies), but one step further: instead
of running `az` subcommands directly, it materializes a per-call kubeconfig
via `az aks get-credentials` and hands it to the official `kubernetes`
Python client, so the actual pod/deployment calls below go through typed
API objects rather than a kubectl/shell passthrough.

Lifecycle per call:
  1. `az login --service-principal` (once per process - see _ensure_login,
     identical pattern to azure_runner.py).
  2. `az aks get-credentials -g <rg> -n <cluster> -f <temp file>` writes a
     fresh kubeconfig to a NamedTemporaryFile.
  3. `kubernetes.config.load_kube_config(config_file=<temp file>)` builds an
     API client from it.
  4. The temp kubeconfig file is deleted in a `finally` block - it holds
     short-lived AKS exec credentials and must never outlive the call.

Every helper below wraps exactly one Kubernetes API call, bounds it with
KUBERNETES_OPS_TIMEOUT, and returns a clean `{"error": "..."}` dict on
failure instead of letting a kubernetes.client.ApiException (or anything
else) bubble up to the MCP tool layer - same error-handling shape as
azure_runner.py's run_az_command / the argocd agent's sync_application.
"""

import asyncio
import datetime
import logging
import os
import tempfile
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

from .credential_client import CredentialClientError, create_client_from_env, credentials_enabled

logger = logging.getLogger(__name__)

AZ_LOGIN_TIMEOUT = int(os.getenv("KUBERNETES_OPS_AZ_LOGIN_TIMEOUT", "120"))
K8S_TIMEOUT = int(os.getenv("KUBERNETES_OPS_TIMEOUT", "60"))
REQUIRED_ENV = ("ARM_CLIENT_ID", "ARM_TENANT_ID", "ARM_SUBSCRIPTION_ID")
ARM_CLIENT_SECRET_REF = os.getenv("ARM_CLIENT_SECRET_REF", "kubernetes-ops/arm-client-secret")

_logged_in = False
_login_lock = asyncio.Lock()


class KubernetesOpsConfigError(RuntimeError):
    """Raised when required Azure service-principal config is missing, or az login/get-credentials fails."""


def _require_config() -> None:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        raise KubernetesOpsConfigError(
            f"Azure service principal is not configured, missing env vars: {', '.join(missing)}"
        )
    if not credentials_enabled() and not os.getenv("ARM_CLIENT_SECRET"):
        raise KubernetesOpsConfigError(
            "Azure service principal is not configured, missing env var: ARM_CLIENT_SECRET"
        )


async def _resolve_client_secret() -> str:
    if not credentials_enabled():
        return os.environ["ARM_CLIENT_SECRET"]
    try:
        client = create_client_from_env()
        return await client.retrieve_secret(ARM_CLIENT_SECRET_REF)
    except CredentialClientError as e:
        raise KubernetesOpsConfigError(f"Failed to resolve ARM_CLIENT_SECRET via credential exchange: {e}") from e


async def _run_az(argv: List[str]) -> Dict[str, Any]:
    cmd_str = " ".join(argv)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=AZ_LOGIN_TIMEOUT)
        return {
            "command": cmd_str,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
            "success": proc.returncode == 0,
        }
    except asyncio.TimeoutError:
        return {"command": cmd_str, "error": "az command timed out", "success": False}


async def _ensure_login() -> None:
    global _logged_in
    if _logged_in:
        return
    _require_config()
    async with _login_lock:
        if _logged_in:
            return
        client_secret = await _resolve_client_secret()
        login_result = await _run_az([
            "az", "login", "--service-principal",
            "-u", os.environ["ARM_CLIENT_ID"],
            "-p", client_secret,
            "--tenant", os.environ["ARM_TENANT_ID"],
            "--output", "none",
        ])
        if not login_result["success"]:
            raise KubernetesOpsConfigError(f"az login --service-principal failed: {login_result.get('stderr', '')}")

        set_sub_result = await _run_az([
            "az", "account", "set", "--subscription", os.environ["ARM_SUBSCRIPTION_ID"],
        ])
        if not set_sub_result["success"]:
            raise KubernetesOpsConfigError(f"az account set failed: {set_sub_result.get('stderr', '')}")

        _logged_in = True


@contextmanager
def _temp_kubeconfig_path() -> Iterator[str]:
    """Yields a path to a not-yet-created temp file, deleting it afterward if it exists."""
    fd, path = tempfile.mkstemp(prefix="kubernetes-ops-kubeconfig-", suffix=".yaml")
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def _get_credentials(resource_group: str, cluster_name: str, kubeconfig_path: str) -> Dict[str, Any]:
    return await _run_az([
        "az", "aks", "get-credentials",
        "--resource-group", resource_group,
        "--name", cluster_name,
        "--file", kubeconfig_path,
        "--overwrite-existing",
        "--output", "none",
    ])


class ClusterClients:
    """A matched pair of CoreV1Api/AppsV1Api clients for one cluster's kubeconfig."""

    def __init__(self, core_v1: k8s_client.CoreV1Api, apps_v1: k8s_client.AppsV1Api) -> None:
        self.core_v1 = core_v1
        self.apps_v1 = apps_v1


async def get_clients(resource_group: str, cluster_name: str) -> ClusterClients:
    """
    Materializes a per-call kubeconfig for one AKS cluster (after ensuring
    service-principal login) and returns configured CoreV1Api/AppsV1Api
    clients built from it. The temp kubeconfig file is always deleted
    before this returns - the clients returned keep their own copy of the
    credentials in memory, not a reference to the file on disk.

    Raises KubernetesOpsConfigError if login or get-credentials fails -
    callers (tools/pods.py, tools/deployments.py) catch this and return a
    clean {"error": ...} dict rather than letting it propagate.
    """
    await _ensure_login()
    with _temp_kubeconfig_path() as kubeconfig_path:
        result = await _get_credentials(resource_group, cluster_name, kubeconfig_path)
        if not result.get("success"):
            raise KubernetesOpsConfigError(
                f"az aks get-credentials failed for {cluster_name!r}: {result.get('stderr') or result.get('error')}"
            )
        api_client = k8s_config.new_client_from_config(config_file=kubeconfig_path)
        return ClusterClients(
            core_v1=k8s_client.CoreV1Api(api_client),
            apps_v1=k8s_client.AppsV1Api(api_client),
        )


async def call_k8s(fn, *args, **kwargs) -> Dict[str, Any]:
    """
    Runs one blocking kubernetes-client call (e.g. core_v1.list_namespaced_pod)
    in a thread, bounded by KUBERNETES_OPS_TIMEOUT, and normalizes any
    failure into a {"error": ...} dict instead of raising - same shape as
    azure_runner.run_az_command's error handling.

    Args:
        fn: A bound kubernetes-client method (never a raw kubectl/shell
            command - this project never builds argv from unsanitized input
            for Kubernetes actions).
        *args, **kwargs: Forwarded to fn as-is.
    """
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(fn, *args, **kwargs),
            timeout=K8S_TIMEOUT,
        )
        return {"success": True, "result": result}
    except asyncio.TimeoutError:
        return {"success": False, "error": f"Kubernetes API call timed out after {K8S_TIMEOUT}s"}
    except k8s_client.exceptions.ApiException as e:
        return {"success": False, "error": f"Kubernetes API error ({e.status}): {e.reason}"}
    except KubernetesOpsConfigError:
        raise
    except Exception as e:
        logger.error(f"kubernetes-ops API call failed: {e}")
        return {"success": False, "error": str(e)}


def patch_body_restart() -> Dict[str, Any]:
    """
    Builds the standard `kubectl rollout restart` equivalent patch body: a
    pod-template annotation set to the current UTC timestamp, which forces
    a new ReplicaSet without changing any other field.
    """
    return {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": datetime.datetime.now(datetime.timezone.utc).isoformat()
                    }
                }
            }
        }
    }


def optional_grace_period(grace_period_seconds: Optional[int]) -> Dict[str, Any]:
    """Builds kwargs for delete_namespaced_pod when a non-default grace period is given."""
    return {} if grace_period_seconds is None else {"grace_period_seconds": grace_period_seconds}
