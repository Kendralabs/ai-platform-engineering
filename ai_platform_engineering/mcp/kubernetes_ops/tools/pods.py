# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Read-only pod visibility tools for customer AKS clusters: listing pods,
getting one pod's status, tailing its logs, and describing recent events.

None of these write anything - they exist to cover the kubectl-style
visibility that the ArgoCD agent's own Application/resource sync API
doesn't give (ArgoCD reports an Application's sync/health state, not a raw
`kubectl get pods` / `kubectl logs` / `kubectl describe` view of a single
pod). See tools/deployments.py for the write (confirm-gated) tools.
"""

import logging
from typing import Any, Dict, Optional

from .k8s_runner import KubernetesOpsConfigError, call_k8s, get_clients
from .registry import resolve_scope

logger = logging.getLogger(__name__)


def _summarize_pod(pod: Any) -> Dict[str, Any]:
    container_statuses = pod.status.container_statuses or []
    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "phase": pod.status.phase,
        "pod_ip": pod.status.pod_ip,
        "node_name": pod.spec.node_name,
        "restart_count": sum(cs.restart_count for cs in container_statuses),
        "ready": all(cs.ready for cs in container_statuses) if container_statuses else False,
        "container_statuses": [
            {
                "name": cs.name,
                "ready": cs.ready,
                "restart_count": cs.restart_count,
                "state": _summarize_container_state(cs.state),
            }
            for cs in container_statuses
        ],
    }


def _summarize_container_state(state: Any) -> Dict[str, Any]:
    if state.running is not None:
        return {"status": "running", "started_at": str(state.running.started_at)}
    if state.waiting is not None:
        return {"status": "waiting", "reason": state.waiting.reason, "message": state.waiting.message}
    if state.terminated is not None:
        return {
            "status": "terminated",
            "reason": state.terminated.reason,
            "exit_code": state.terminated.exit_code,
            "message": state.terminated.message,
        }
    return {"status": "unknown"}


async def k8s_list_pods(scope: str, namespace: str) -> dict:
    """
    List pods in one namespace of a customer's AKS cluster, or every
    registered customer when scope="all".

    Args:
        scope: A customer name (e.g. "acme"), as registered under
            envs/azure/<customer>/, or "all" for every registered customer.
        namespace: The Kubernetes namespace to list pods in.
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

        outcome = await call_k8s(clients.core_v1.list_namespaced_pod, namespace)
        if not outcome["success"]:
            clusters[customer] = {"error": outcome["error"]}
            continue

        clusters[customer] = {"pods": [_summarize_pod(p) for p in outcome["result"].items]}

    return {"scope": scope, "namespace": namespace, "clusters": clusters}


async def k8s_get_pod_status(scope: str, namespace: str, pod_name: str) -> dict:
    """
    Get one pod's status (phase, readiness, restart counts, per-container
    state) in a customer's AKS cluster.

    Args:
        scope: A customer name or "all". A single pod name only makes sense
            against one cluster at a time, but "all" is still accepted so
            callers can discover which cluster(s) actually have that pod.
        namespace: The Kubernetes namespace the pod lives in.
        pod_name: The pod's name.
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

        outcome = await call_k8s(clients.core_v1.read_namespaced_pod, pod_name, namespace)
        if not outcome["success"]:
            clusters[customer] = {"error": outcome["error"]}
            continue

        clusters[customer] = _summarize_pod(outcome["result"])

    return {"scope": scope, "namespace": namespace, "pod_name": pod_name, "clusters": clusters}


async def k8s_get_pod_logs(
    scope: str,
    namespace: str,
    pod_name: str,
    container: Optional[str] = None,
    tail_lines: int = 200,
) -> dict:
    """
    Tail a pod's logs in a customer's AKS cluster.

    Args:
        scope: A customer name or "all".
        namespace: The Kubernetes namespace the pod lives in.
        pod_name: The pod's name.
        container: Container name, required only when the pod has more than
            one container. None uses the pod's only/default container.
        tail_lines: Number of lines to return from the end of the log.
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

        kwargs: Dict[str, Any] = {"tail_lines": tail_lines}
        if container:
            kwargs["container"] = container
        outcome = await call_k8s(clients.core_v1.read_namespaced_pod_log, pod_name, namespace, **kwargs)
        if not outcome["success"]:
            clusters[customer] = {"error": outcome["error"]}
            continue

        clusters[customer] = {"logs": outcome["result"]}

    return {
        "scope": scope,
        "namespace": namespace,
        "pod_name": pod_name,
        "container": container,
        "tail_lines": tail_lines,
        "clusters": clusters,
    }


async def k8s_describe_events(scope: str, namespace: str, limit: int = 50) -> dict:
    """
    List recent Kubernetes events in one namespace of a customer's AKS
    cluster - the `kubectl describe` / `kubectl get events` equivalent for
    diagnosing why a pod is pending, crashing, or failing to schedule.

    Args:
        scope: A customer name or "all".
        namespace: The Kubernetes namespace to list events in.
        limit: Maximum number of events to return, most recent first.
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

        outcome = await call_k8s(clients.core_v1.list_namespaced_event, namespace)
        if not outcome["success"]:
            clusters[customer] = {"error": outcome["error"]}
            continue

        events = sorted(
            outcome["result"].items,
            key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp,
            reverse=True,
        )[:limit]
        clusters[customer] = {
            "events": [
                {
                    "type": e.type,
                    "reason": e.reason,
                    "message": e.message,
                    "involved_object": f"{e.involved_object.kind}/{e.involved_object.name}",
                    "count": e.count,
                    "last_timestamp": str(e.last_timestamp or e.event_time),
                }
                for e in events
            ]
        }

    return {"scope": scope, "namespace": namespace, "limit": limit, "clusters": clusters}
