# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Shared `az` CLI execution helper for Azure-backed components. Mirrors
power_ops/tools/ssh_runner.py's shape (fixed argv, never an arbitrary
string) but talks to the `az` CLI instead of SSH.

Auth reads the same service-principal values kendrainfra's own Jenkinsfile
already sets for Terraform (ARM_CLIENT_ID / ARM_CLIENT_SECRET / ARM_TENANT_ID /
ARM_SUBSCRIPTION_ID). When CAIPE_CREDENTIALS_ENABLED=true, ARM_CLIENT_SECRET is
instead resolved at login time from the CAIPE credential-exchange API (OpenBao
-backed) via a Keycloak service-account client-credentials grant - see
credential_client.py - rather than read from the environment, so the real
secret never needs to sit in a Compose `environment:` block or `.env` file.
Unlike the Terraform AzureRM provider, the `az` CLI itself doesn't pick these
up automatically, so this module runs `az login --service-principal` once per
process the first time a command is needed, then reuses that session.
"""

import asyncio
import logging
import os
from typing import Any, Dict, List

from .credential_client import CredentialClientError, create_client_from_env, credentials_enabled

logger = logging.getLogger(__name__)

AZ_TIMEOUT = int(os.getenv("AZURE_POWER_OPS_AZ_TIMEOUT", "120"))
REQUIRED_ENV = ("ARM_CLIENT_ID", "ARM_TENANT_ID", "ARM_SUBSCRIPTION_ID")
ARM_CLIENT_SECRET_REF = os.getenv("ARM_CLIENT_SECRET_REF", "azure-power-ops/arm-client-secret")

_logged_in = False
_login_lock = asyncio.Lock()


class AzureConfigError(RuntimeError):
    """Raised when required Azure service-principal config is missing, or az login fails."""


def _require_config() -> None:
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        raise AzureConfigError(
            f"Azure service principal is not configured, missing env vars: {', '.join(missing)}"
        )
    if not credentials_enabled() and not os.getenv("ARM_CLIENT_SECRET"):
        raise AzureConfigError(
            "Azure service principal is not configured, missing env var: ARM_CLIENT_SECRET"
        )


async def _resolve_client_secret() -> str:
    if not credentials_enabled():
        return os.environ["ARM_CLIENT_SECRET"]
    try:
        client = create_client_from_env()
        return await client.retrieve_secret(ARM_CLIENT_SECRET_REF)
    except CredentialClientError as e:
        raise AzureConfigError(f"Failed to resolve ARM_CLIENT_SECRET via credential exchange: {e}") from e


async def _run(argv: List[str]) -> Dict[str, Any]:
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


async def _ensure_login() -> None:
    global _logged_in
    if _logged_in:
        return
    _require_config()
    async with _login_lock:
        if _logged_in:
            return
        client_secret = await _resolve_client_secret()
        login_result = await _run([
            "az", "login", "--service-principal",
            "-u", os.environ["ARM_CLIENT_ID"],
            "-p", client_secret,
            "--tenant", os.environ["ARM_TENANT_ID"],
            "--output", "none",
        ])
        if not login_result["success"]:
            raise AzureConfigError(f"az login --service-principal failed: {login_result.get('stderr', '')}")

        set_sub_result = await _run([
            "az", "account", "set", "--subscription", os.environ["ARM_SUBSCRIPTION_ID"],
        ])
        if not set_sub_result["success"]:
            raise AzureConfigError(f"az account set failed: {set_sub_result.get('stderr', '')}")

        _logged_in = True


async def run_az_command(argv: List[str]) -> Dict[str, Any]:
    """
    Run a single fixed `az` command (after ensuring login) and return its
    result.

    Args:
        argv: The az subcommand as an argument list, e.g.
            ["aks", "stop", "-g", rg, "-n", name]. Never built from
            unsanitized user input - callers only pass fixed, allowlisted
            command shapes built from registry entries.
    """
    await _ensure_login()
    try:
        return await _run(["az", "--output", "json"] + argv)
    except AzureConfigError:
        raise
    except Exception as e:
        logger.error(f"azure-power-ops az command failed: {e}")
        return {"command": " ".join(argv), "error": str(e), "success": False}
