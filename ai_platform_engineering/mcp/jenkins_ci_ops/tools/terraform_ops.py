# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Terraform tools for one environment's module in the `infra` repo
(resolved via registry.py's `module_path`).

`terraform_show_state` (Tier 1) and `terraform_plan` (Tier 2) both shell
out to a fixed, allowlisted `terraform` argv in the module's directory -
never an arbitrary command string. Neither ever applies.

`terraform_apply` (Tier 3) is a deliberate non-implementation: see
README.md - an apply must be scoped to a plan hash a human actually
reviewed, which KACP does not yet have a mechanism to attach.
"""

import asyncio
import os
from typing import Any, Dict, List

from .registry import resolve_scope

TERRAFORM_TIMEOUT = int(os.getenv("JENKINS_CI_OPS_TERRAFORM_TIMEOUT", "300"))


async def _run_terraform(argv: List[str], cwd: str) -> Dict[str, Any]:
    cmd_str = " ".join(argv)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=TERRAFORM_TIMEOUT)
        return {
            "command": cmd_str,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
            "success": proc.returncode == 0,
        }
    except asyncio.TimeoutError:
        return {"command": cmd_str, "error": "terraform command timed out", "success": False}
    except FileNotFoundError as e:
        return {"command": cmd_str, "error": str(e), "success": False}


def _resolve_module_path(scope: str) -> Dict[str, Any]:
    matches = resolve_scope(scope)
    if len(matches) != 1:
        return {"error": f"expected exactly one resolved environment for scope {scope!r}, got {len(matches)}"}
    env_name, env_spec = matches[0]
    return {"env_name": env_name, "module_path": env_spec["module_path"]}


async def terraform_show_state(scope: str) -> Dict[str, Any]:
    """Reads current Terraform state for one environment's module (read-only)."""
    resolved = _resolve_module_path(scope)
    if "error" in resolved:
        return {**resolved, "success": False}
    result = await _run_terraform(["terraform", "show", "-json"], cwd=resolved["module_path"])
    return {**result, "environment": resolved["env_name"]}


async def terraform_plan(scope: str) -> Dict[str, Any]:
    """
    Runs `terraform plan` for one environment's module and returns the diff.
    Never applies. Requires live Azure credentials in the environment this
    server runs in (ARM_* vars) - returns the plan command's own error if
    those aren't configured.
    """
    resolved = _resolve_module_path(scope)
    if "error" in resolved:
        return {**resolved, "success": False}
    result = await _run_terraform(
        ["terraform", "plan", "-input=false", "-no-color"],
        cwd=resolved["module_path"],
    )
    return {**result, "environment": resolved["env_name"]}


async def terraform_apply(scope: str, plan_id: str, confirm: bool = False) -> Dict[str, Any]:
    """
    Not implemented. An apply must be scoped to a specific, human-reviewed
    plan's hash so it can't silently diverge from what was approved - KACP
    does not yet have a mechanism to attach that, so this tool refuses
    rather than running a fresh plan+apply at call time.
    """
    return {
        "success": False,
        "implemented": False,
        "reason": (
            "terraform_apply is intentionally not implemented pending a KACP "
            "mechanism to attach an approved plan's hash to the apply call."
        ),
        "scope": scope,
        "plan_id": plan_id,
    }
