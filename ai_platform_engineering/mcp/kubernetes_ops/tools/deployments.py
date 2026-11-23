# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Deployment status (read-only) and write tools for customer AKS clusters:
restarting a rollout, scaling replica count, and deleting a stuck pod.

Every write tool here follows the same confirm=True discipline documented
in azure_power_ops/tools/power.py: confirm defaults to False and, when
False, the tool short-circuits with a clear "set confirm=True to proceed"
error instead of acting - never a dry-run that silently does nothing with
no explanation. There is no "all" scope for the write tools in this module
(unlike azure_cluster_ops/power_ops's customer-group scope) - restarting,
scaling, or deleting always names one specific cluster, namespace, and
object; broadcasting a write across every registered customer in one call
is never the intended action here.
"""

import logging
from typing import Any, Dict

from .k8s_runner import KubernetesOpsConfigError, call_k8s, get_clients, optional_grace_period, patch_body_restart
from .registry import resolve_scope

logger = logging.getLogger(__name__)


def _resolve_one(scope: str) -> Dict[str, Any]:
    """
    Resolve scope to exactly one (customer, ClusterSpec) pair, or an
    {"error": ...} dict if it doesn't resolve to exactly one cluster. Used
    by every write tool in this module - "all" is refused here, unlike the
    read-only tools, since a single deployment/pod write across every
    customer's cluster in one call is never the intended action.
    """
    pairs = resolve_scope(scope)
    if not pairs:
        return {"error": f"Unknown customer or scope: {scope!r}. No registered Azure environment matches."}
    if len(pairs) > 1:
        return {"error": f"scope {scope!r} resolves to {len(pairs)} clusters; write tools require exactly one."}
    customer, spec = pairs[0]
    return {"customer": customer, "spec": spec}


def _summarize_deployment(deployment: Any) -> Dict[str, Any]:
    status = deployment.status
    return {
        "name": deployment.metadata.name,
        "namespace": deployment.metadata.namespace,
        "replicas_desired": deployment.spec.replicas,
        "replicas_ready": status.ready_replicas or 0,
        "replicas_available": status.available_replicas or 0,
        "replicas_updated": status.updated_replicas or 0,
        "replicas_unavailable": status.unavailable_replicas or 0,
        "conditions": [
            {"type": c.type, "status": c.status, "reason": c.reason, "message": c.message}
            for c in (status.conditions or [])
        ],
    }


async def k8s_get_deployment_status(scope: str, namespace: str, deployment_name: str) -> dict:
    """
    Get one Deployment's rollout status (desired/ready/available/updated
    replica counts, conditions) in a customer's AKS cluster. Read-only.

    Args:
        scope: A customer name or "all".
        namespace: The Kubernetes namespace the Deployment lives in.
        deployment_name: The Deployment's name.
    """
    pairs = resolve_scope(scope)
    if not pairs:
        return {"error": f"Unknown customer or scope: {scope!r}. No registered Azure environment matches."}

    clusters: Dict[str, Any] = {}
    for customer, spec in pairs:
        try:
            clients = await get_clients(spec["resource_group"], spec["cluster_name"])
        except KubernetesOpsConfigError as e:
            clusters[customer] = {"error": str(e)}
            continue

        outcome = await call_k8s(clients.apps_v1.read_namespaced_deployment, deployment_name, namespace)
        if not outcome["success"]:
            clusters[customer] = {"error": outcome["error"]}
            continue

        clusters[customer] = _summarize_deployment(outcome["result"])

    return {"scope": scope, "namespace": namespace, "deployment_name": deployment_name, "clusters": clusters}


async def k8s_restart_deployment(
    scope: str,
    namespace: str,
    deployment_name: str,
    confirm: bool = False,
) -> dict:
    """
    Restart a Deployment's rollout - the `kubectl rollout restart`
    equivalent, done by patching the pod template's
    `kubectl.kubernetes.io/restartedAt` annotation so the Deployment
    controller rolls out a fresh ReplicaSet without changing any other
    field.

    Args:
        scope: A single customer name (never "all" - see module docstring).
        namespace: The Kubernetes namespace the Deployment lives in.
        deployment_name: The Deployment's name.
        confirm: Must be True to proceed. Defaults to False, in which case
            this returns an error asking the caller to set confirm=True
            rather than taking any action.
    """
    if not confirm:
        return {"error": "This restarts a running Deployment's rollout. Set confirm=True to proceed."}

    resolved = _resolve_one(scope)
    if "error" in resolved:
        return resolved
    spec = resolved["spec"]

    try:
        clients = await get_clients(spec["resource_group"], spec["cluster_name"])
    except KubernetesOpsConfigError as e:
        return {"error": str(e)}

    outcome = await call_k8s(
        clients.apps_v1.patch_namespaced_deployment,
        deployment_name,
        namespace,
        patch_body_restart(),
    )
    if not outcome["success"]:
        return {"error": outcome["error"]}

    return {
        "scope": scope,
        "customer": resolved["customer"],
        "namespace": namespace,
        "deployment_name": deployment_name,
        "action": "restart",
        "result": _summarize_deployment(outcome["result"]),
    }


async def k8s_scale_deployment(
    scope: str,
    namespace: str,
    deployment_name: str,
    replicas: int,
    confirm: bool = False,
) -> dict:
    """
    Set a Deployment's replica count - the `kubectl scale` equivalent.

    Args:
        scope: A single customer name (never "all" - see module docstring).
        namespace: The Kubernetes namespace the Deployment lives in.
        deployment_name: The Deployment's name.
        replicas: The desired replica count (must be >= 0).
        confirm: Must be True to proceed. Defaults to False, in which case
            this returns an error asking the caller to set confirm=True
            rather than taking any action.
    """
    if not confirm:
        return {"error": "This changes a running Deployment's replica count. Set confirm=True to proceed."}
    if replicas < 0:
        return {"error": f"replicas must be >= 0, got {replicas}"}

    resolved = _resolve_one(scope)
    if "error" in resolved:
        return resolved
    spec = resolved["spec"]

    try:
        clients = await get_clients(spec["resource_group"], spec["cluster_name"])
    except KubernetesOpsConfigError as e:
        return {"error": str(e)}

    outcome = await call_k8s(
        clients.apps_v1.patch_namespaced_deployment_scale,
        deployment_name,
        namespace,
        {"spec": {"replicas": replicas}},
    )
    if not outcome["success"]:
        return {"error": outcome["error"]}

    return {
        "scope": scope,
        "customer": resolved["customer"],
        "namespace": namespace,
        "deployment_name": deployment_name,
        "action": "scale",
        "replicas_requested": replicas,
        "result": {
            "name": outcome["result"].metadata.name,
            "replicas": outcome["result"].spec.replicas,
        },
    }


async def k8s_delete_pod(
    scope: str,
    namespace: str,
    pod_name: str,
    confirm: bool = False,
) -> dict:
    """
    Delete one pod - the `kubectl delete pod` equivalent, typically used to
    unstick a pod that a controller (Deployment/ReplicaSet) will
    immediately recreate.

    Args:
        scope: A single customer name (never "all" - see module docstring).
        namespace: The Kubernetes namespace the pod lives in.
        pod_name: The pod's name.
        confirm: Must be True to proceed. Defaults to False, in which case
            this returns an error asking the caller to set confirm=True
            rather than taking any action.
    """
    if not confirm:
        return {"error": "This deletes a running pod. Set confirm=True to proceed."}

    resolved = _resolve_one(scope)
    if "error" in resolved:
        return resolved
    spec = resolved["spec"]

    try:
        clients = await get_clients(spec["resource_group"], spec["cluster_name"])
    except KubernetesOpsConfigError as e:
        return {"error": str(e)}

    outcome = await call_k8s(
        clients.core_v1.delete_namespaced_pod,
        pod_name,
        namespace,
        **optional_grace_period(None),
    )
    if not outcome["success"]:
        return {"error": outcome["error"]}

    return {
        "scope": scope,
        "customer": resolved["customer"],
        "namespace": namespace,
        "pod_name": pod_name,
        "action": "delete",
        "status": "deleted",
    }
