# Runbook: Provision `mcp-azure-power-ops` Service Account + OpenBao Secret

**Human-only.** Every step here enters real secret material (the Azure SP
client secret, a minted Keycloak client secret) into a live system. Never run
these steps through an agent — see `openbao-direct-implementation-plan.md`
Phase 4 step 5 and the project's KIAM/OpenBao-not-`.env` rule.

`POST /api/credentials/secrets` accepts an optional `id` field — pass the
human-readable id you want (e.g. `azure-power-ops/arm-client-secret`,
matching `credential_client.py`'s default `ARM_CLIENT_SECRET_REF`) and it's
used verbatim instead of a generated UUID, as long as it matches
`SECRET_ID_PATTERN` and isn't already taken (409 `CREDENTIAL_ID_CONFLICT` if
so). Omit `id` to get a generated UUID as before. Step 2 below uses this, so
you can skip straight to the human-readable ref in step 5 instead of reading
back a UUID.

## 1. Create the Keycloak service-account client

```
POST /api/admin/service-accounts
Authorization: <your admin session cookie / bearer>
Content-Type: application/json

{
  "name": "mcp-azure-power-ops",
  "owning_team_id": "<team you administer>",
  "scopes": []
}
```

- You must be a member of `owning_team_id` (OpenFGA `member` check).
- The response's `data.credential` is shown **once** — copy
  `client_id` and `client_secret` immediately; they're never re-fetchable.
- Also note `data.id` (the service-account's Mongo id) and the Keycloak
  `sa_sub` — the OpenFGA subject is `service_account:<sa_sub>`.

This step alone also writes the `mcp_gateway:list` baseline tuple needed for
every SA tool call to pass the coarse ext_authz gate — nothing more to do
there.

## 2. Write the real Azure SP secret into OpenBao

Via the existing Secrets UI/API as any user who can create a secret (does
**not** need to be the service account — the SA will be granted `use` on it
in step 4):

```
POST /api/credentials/secrets
{
  "id": "azure-power-ops/arm-client-secret",
  "name": "azure-power-ops-arm-client-secret",
  "type": "service",
  "plaintext": "<the real Azure SP client secret — from Azure, never typed by an agent>",
  "ownerType": "user"   // or "team" if you'd rather a team own it
}
```

This writes the secret material into OpenBao (via `openbao-store.ts`,
transparently — nothing OpenBao-specific to configure here beyond the
`openbao` Compose service already being up) and a `secret_refs` metadata doc
into Mongo. The returned `id` is exactly what you passed —
`azure-power-ops/arm-client-secret` — that's your `secret_ref` value for
everything below (and already matches `credential_client.py`'s default, so
step 5 can leave `ARM_CLIENT_SECRET_REF` unset).

## 3. Grant the service account `use` on that secret

There's no "secret" scope type in `service-account-scopes.ts` yet (only
`agent`/`tool`), so grant it with a direct OpenFGA tuple write via the admin
tuples endpoint:

```
POST /api/admin/openfga/tuples
{
  "writes": [
    {
      "user": "service_account:<sa_sub from step 1>",
      "relation": "can_use",
      "object": "secret_ref:azure-power-ops/arm-client-secret"
    }
  ],
  "deletes": []
}
```

Verify with
`GET /api/admin/openfga/tuples?object=secret_ref:azure-power-ops/arm-client-secret`
— you should see the tuple you just wrote.

## 4. Find your Keycloak token URL

```
KEYCLOAK_TOKEN_URL=https://<your-keycloak-host>/realms/caipe/protocol/openid-connect/token
```

(Same realm the rest of CAIPE's Keycloak admin-client config already points
at — `KEYCLOAK_URL`/`KEYCLOAK_REALM` in your `.env`.)

## 5. Set env vars for `mcp-azure-power-ops`

In your deployment's secret store (Compose `secrets:`, not plain
`environment:` for the two secret values — or your orchestrator's
equivalent):

```
CAIPE_CREDENTIALS_ENABLED=true
CAIPE_CREDENTIAL_API_URL=<BFF base URL>/api/credentials
KEYCLOAK_TOKEN_URL=<from step 4>
CAIPE_SERVICE_ACCOUNT_CLIENT_ID=<client_id from step 1>
CAIPE_SERVICE_ACCOUNT_CLIENT_SECRET=<client_secret from step 1>
ARM_CLIENT_SECRET_REF=azure-power-ops/arm-client-secret   # matches the default; can be left unset
```

Leave `ARM_CLIENT_ID` / `ARM_TENANT_ID` / `ARM_SUBSCRIPTION_ID` as plain env
vars (not secret material, unchanged). You can now drop `ARM_CLIENT_SECRET`
from this agent's env block — it's no longer read when
`CAIPE_CREDENTIALS_ENABLED=true`.

## 6. Verify end-to-end

Restart `mcp-azure-power-ops` and exercise any tool call that needs
`az login` (triggers `_ensure_login()` → `_resolve_client_secret()` →
`credential_client.py`). Check:

- The container logs show a successful login, not an `AzureConfigError`.
- `GET /api/credentials/audit` (or the Audit UI) shows a
  `credential.retrieve` event for this `secret_ref`, actor
  `service_account:<sa_sub>`.
- Revoke the tuple from step 3 and confirm retrieval now fails closed
  (403, not a silent fallback) — this is the FR-022 fail-closed behavior
  the plan calls out.

Once this is verified, repeat steps 1-6 for `azure_cost_ops`,
`azure_cluster_ops`, `azure_core_services_ops` (each needs its own
`credential_client.py`/`azure_runner.py` wiring first, per
`openbao-direct-implementation-plan.md` Phase 4 step 6).
