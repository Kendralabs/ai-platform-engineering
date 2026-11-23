# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Unit tests for tools/deployments.py's confirm=False short-circuit
discipline. The Kubernetes API client is mocked out everywhere - these
tests never make a real `az` or Kubernetes API call.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import deployments  # noqa: E402


@pytest.mark.asyncio
async def test_restart_deployment_short_circuits_without_confirm(monkeypatch):
    # get_clients must never be reached when confirm=False - patch it to
    # raise if called, so the test fails loudly if the short-circuit breaks.
    get_clients_mock = AsyncMock(side_effect=AssertionError("get_clients should not be called when confirm=False"))
    monkeypatch.setattr(deployments, "get_clients", get_clients_mock)

    result = await deployments.k8s_restart_deployment("acme", "default", "my-deployment", confirm=False)

    assert "error" in result
    assert "confirm=True" in result["error"]
    get_clients_mock.assert_not_called()


@pytest.mark.asyncio
async def test_scale_deployment_short_circuits_without_confirm(monkeypatch):
    get_clients_mock = AsyncMock(side_effect=AssertionError("get_clients should not be called when confirm=False"))
    monkeypatch.setattr(deployments, "get_clients", get_clients_mock)

    result = await deployments.k8s_scale_deployment("acme", "default", "my-deployment", replicas=3, confirm=False)

    assert "error" in result
    assert "confirm=True" in result["error"]
    get_clients_mock.assert_not_called()


@pytest.mark.asyncio
async def test_delete_pod_short_circuits_without_confirm(monkeypatch):
    get_clients_mock = AsyncMock(side_effect=AssertionError("get_clients should not be called when confirm=False"))
    monkeypatch.setattr(deployments, "get_clients", get_clients_mock)

    result = await deployments.k8s_delete_pod("acme", "default", "my-pod-xyz", confirm=False)

    assert "error" in result
    assert "confirm=True" in result["error"]
    get_clients_mock.assert_not_called()


@pytest.mark.asyncio
async def test_scale_deployment_rejects_negative_replicas_even_with_confirm(monkeypatch):
    get_clients_mock = AsyncMock(side_effect=AssertionError("get_clients should not be called for invalid input"))
    monkeypatch.setattr(deployments, "get_clients", get_clients_mock)

    result = await deployments.k8s_scale_deployment("acme", "default", "my-deployment", replicas=-1, confirm=True)

    assert "error" in result
    get_clients_mock.assert_not_called()


@pytest.mark.asyncio
async def test_restart_deployment_refuses_unknown_scope(monkeypatch):
    monkeypatch.setattr(deployments, "resolve_scope", lambda scope: [])

    result = await deployments.k8s_restart_deployment("does-not-exist", "default", "my-deployment", confirm=True)

    assert "error" in result
    assert "does-not-exist" in result["error"]


@pytest.mark.asyncio
async def test_restart_deployment_refuses_scope_resolving_to_multiple_clusters(monkeypatch):
    # "all" (or any scope resolving to >1 cluster) is refused for a write
    # tool - see _resolve_one in tools/deployments.py.
    monkeypatch.setattr(
        deployments,
        "resolve_scope",
        lambda scope: [
            ("acme", {"resource_group": "kendra-acme-rg", "cluster_name": "kendra-acme-aks"}),
            ("globex", {"resource_group": "kendra-globex-rg", "cluster_name": "kendra-globex-aks"}),
        ],
    )

    result = await deployments.k8s_restart_deployment("all", "default", "my-deployment", confirm=True)

    assert "error" in result
    assert "2 clusters" in result["error"]
