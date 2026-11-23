# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Confirms observability_restart_component's two guard invariants:
  1. confirm=False always short-circuits with an error, before any
     Azure/Kubernetes call is attempted.
  2. A component outside the fixed allow-list is refused outright, before
     any Azure/Kubernetes call is attempted (and before the confirm check).
No real Azure CLI or Kubernetes client call is made in this file.
"""

from unittest.mock import AsyncMock, patch

import pytest

from tools import restart


@pytest.mark.asyncio
async def test_restart_rejects_unknown_component_even_with_confirm():
    with patch.object(restart, "_ensure_kubeconfig", new=AsyncMock()) as mock_ensure:
        result = await restart.observability_restart_component("zookeeper", confirm=True)

    assert "error" in result
    assert "zookeeper" in result["error"]
    mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_restart_rejects_completely_unknown_component():
    with patch.object(restart, "_ensure_kubeconfig", new=AsyncMock()) as mock_ensure:
        result = await restart.observability_restart_component("not-a-real-component", confirm=True)

    assert "error" in result
    mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_restart_short_circuits_without_confirm():
    with patch.object(restart, "_ensure_kubeconfig", new=AsyncMock()) as mock_ensure:
        result = await restart.observability_restart_component("otel-collector", confirm=False)

    assert "error" in result
    assert "confirm" in result["error"].lower()
    mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_restart_short_circuits_with_default_confirm():
    """confirm defaults to False - calling without it at all must also short-circuit."""
    with patch.object(restart, "_ensure_kubeconfig", new=AsyncMock()) as mock_ensure:
        result = await restart.observability_restart_component("query-service")

    assert "error" in result
    mock_ensure.assert_not_called()


@pytest.mark.asyncio
async def test_restart_proceeds_for_allowed_component_with_confirm():
    """Sanity check the happy path reaches the patch call for an allow-listed
    component with confirm=True - mocking out Azure login and the actual
    Kubernetes patch (no real cluster call)."""
    with patch.object(restart, "_ensure_kubeconfig", new=AsyncMock(return_value="/tmp/fake-kubeconfig")):
        with patch("tools.restart.asyncio.to_thread", new=AsyncMock(return_value={
            "deployment": "frontend",
            "namespace": "observability",
            "restarted_at": "2026-01-01T00:00:00+00:00",
            "observed_generation": 2,
        })) as mock_to_thread:
            result = await restart.observability_restart_component("frontend", confirm=True)

    assert "error" not in result
    assert result["component"] == "frontend"
    assert result["deployment"] == "frontend"
    mock_to_thread.assert_called_once()
