# Copyright 2026 CNOE
# SPDX-License-Identifier: Apache-2.0

"""
Service-account credential client for the Azure MCP agents.

These agents run as standalone Docker Compose containers, outside the
dynamic-agents `credential_sources` resolution mechanism (which only applies
to dynamically-registered MCP servers in the Mongo `mcp_servers` collection).
So this module does its own, minimal service-to-service auth: an OAuth2
client-credentials grant against the CAIPE Keycloak realm, using a confidential
client provisioned through the existing service-accounts feature
(ui/src/lib/rbac/keycloak-admin.ts `createServiceAccountClient`), then calls
the CAIPE BFF's `/api/credentials/retrieve` with the resulting JWT - the same
wire contract `dynamic_agents`' `CredentialExchangeClient` already uses
(`x-caipe-credential-caller`, `x-caipe-credential-audience`, `{secret_ref,
intended_use}` body).

Not reusing `dynamic_agents.services.credential_exchange.CredentialExchangeClient`
directly: it lives in a separate Python package/deployment unit from this one.
"""

import os
import time
from typing import Optional

import httpx

CREDENTIAL_CALLER = "mcp_agent"
# Must be one of retrieval-service.ts's ALLOWED_INTENDED_USES
# ("mcp_server", "provider_exchange", "internal_service") - "mcp_agent"
# is rejected by the server as invalid_retrieval_request.
DEFAULT_INTENDED_USE = "mcp_server"
DEFAULT_AUDIENCE = "caipe-credential-service"
TOKEN_REFRESH_MARGIN_SECONDS = 30


class CredentialClientError(RuntimeError):
    """Raised when the client-credentials grant or the retrieve call fails."""


class ServiceAccountCredentialClient:
    """Mints and caches a Keycloak client-credentials JWT, then retrieves secrets."""

    def __init__(
        self,
        *,
        keycloak_token_url: str,
        client_id: str,
        client_secret: str,
        credential_api_url: str,
        audience: str = DEFAULT_AUDIENCE,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._keycloak_token_url = keycloak_token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._credential_api_url = credential_api_url.rstrip("/")
        self._audience = audience
        self._http = http_client or httpx.AsyncClient(timeout=30.0)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    async def _fetch_token(self) -> str:
        try:
            response = await self._http.post(
                self._keycloak_token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise CredentialClientError(f"Keycloak client-credentials grant failed: {e}") from e

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise CredentialClientError("Keycloak token response had no access_token")
        expires_in = int(payload.get("expires_in", 60))
        self._token_expires_at = time.monotonic() + expires_in
        self._token = token
        return token

    async def _get_token(self) -> str:
        if self._token and time.monotonic() < self._token_expires_at - TOKEN_REFRESH_MARGIN_SECONDS:
            return self._token
        return await self._fetch_token()

    async def retrieve_secret(self, secret_ref: str, *, intended_use: str = DEFAULT_INTENDED_USE) -> str:
        """Retrieve one secret's credential material by its `secret_ref`."""
        token = await self._get_token()
        try:
            response = await self._http.post(
                f"{self._credential_api_url}/retrieve",
                json={"secret_ref": secret_ref, "intended_use": intended_use},
                headers={
                    "Authorization": f"Bearer {token}",
                    "x-caipe-credential-caller": CREDENTIAL_CALLER,
                    "x-caipe-credential-audience": self._audience,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise CredentialClientError(f"Credential retrieve failed for {secret_ref!r}: {e}") from e

        data = response.json()
        credential = (data.get("data") or data).get("credential")
        if not credential:
            raise CredentialClientError(f"Credential retrieve response for {secret_ref!r} had no credential")
        return credential


def credentials_enabled() -> bool:
    return os.getenv("CAIPE_CREDENTIALS_ENABLED", "false").strip().lower() == "true"


def create_client_from_env() -> ServiceAccountCredentialClient:
    """Builds a client from env vars, raising if any required one is missing."""
    required = (
        "KEYCLOAK_TOKEN_URL",
        "CAIPE_SERVICE_ACCOUNT_CLIENT_ID",
        "CAIPE_SERVICE_ACCOUNT_CLIENT_SECRET",
        "CAIPE_CREDENTIAL_API_URL",
    )
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise CredentialClientError(
            f"CAIPE_CREDENTIALS_ENABLED is true but missing env vars: {', '.join(missing)}"
        )
    return ServiceAccountCredentialClient(
        keycloak_token_url=os.environ["KEYCLOAK_TOKEN_URL"],
        client_id=os.environ["CAIPE_SERVICE_ACCOUNT_CLIENT_ID"],
        client_secret=os.environ["CAIPE_SERVICE_ACCOUNT_CLIENT_SECRET"],
        credential_api_url=os.environ["CAIPE_CREDENTIAL_API_URL"],
        audience=os.getenv("CAIPE_CREDENTIAL_AUDIENCE", DEFAULT_AUDIENCE),
    )
