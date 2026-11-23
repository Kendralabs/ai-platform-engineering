# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for tools/registry.py discovery - no real filesystem outside tmp_path, no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import registry  # noqa: E402


def _write_customer_env(envs_root: Path, customer: str, applied: bool = True) -> Path:
    env_dir = envs_root / customer
    env_dir.mkdir(parents=True, exist_ok=True)
    (env_dir / "terraform.tfvars").write_text(f'customer = "{customer}"\n')
    if applied:
        (env_dir / "backend.hcl").write_text("bucket = \"example\"\n")
    return env_dir


def test_discover_clusters_empty_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("KUBERNETES_OPS_INFRA_REPO_PATH", raising=False)
    assert registry.discover_clusters() == {}


def test_discover_clusters_empty_when_path_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("KUBERNETES_OPS_INFRA_REPO_PATH", str(tmp_path / "does-not-exist"))
    assert registry.discover_clusters() == {}


def test_discover_clusters_resolves_naming_convention(monkeypatch, tmp_path):
    envs_root = tmp_path / "envs" / "azure"
    _write_customer_env(envs_root, "acme")
    monkeypatch.setenv("KUBERNETES_OPS_INFRA_REPO_PATH", str(tmp_path))

    clusters = registry.discover_clusters()

    assert clusters == {
        "acme": {"resource_group": "kendra-acme-rg", "cluster_name": "kendra-acme-aks"}
    }


def test_discover_clusters_skips_customer_template(monkeypatch, tmp_path):
    envs_root = tmp_path / "envs" / "azure"
    _write_customer_env(envs_root, "customer-template")
    monkeypatch.setenv("KUBERNETES_OPS_INFRA_REPO_PATH", str(tmp_path))

    assert registry.discover_clusters() == {}


def test_discover_clusters_skips_unapplied_env(monkeypatch, tmp_path):
    envs_root = tmp_path / "envs" / "azure"
    _write_customer_env(envs_root, "acme", applied=False)
    monkeypatch.setenv("KUBERNETES_OPS_INFRA_REPO_PATH", str(tmp_path))

    assert registry.discover_clusters() == {}


def test_resolve_scope_all_returns_every_cluster(monkeypatch, tmp_path):
    envs_root = tmp_path / "envs" / "azure"
    _write_customer_env(envs_root, "acme")
    _write_customer_env(envs_root, "globex")
    monkeypatch.setenv("KUBERNETES_OPS_INFRA_REPO_PATH", str(tmp_path))

    pairs = dict(registry.resolve_scope("all"))

    assert set(pairs.keys()) == {"acme", "globex"}


def test_resolve_scope_unknown_customer_returns_empty(monkeypatch, tmp_path):
    envs_root = tmp_path / "envs" / "azure"
    _write_customer_env(envs_root, "acme")
    monkeypatch.setenv("KUBERNETES_OPS_INFRA_REPO_PATH", str(tmp_path))

    assert registry.resolve_scope("does-not-exist") == []
