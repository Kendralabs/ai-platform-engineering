# Implementation Plan: OpenBao-Direct Credential Store (Azure MCP Agents First)

**Status**: Phases 1-3 done (2026-10-28) — see [Correction](#correction-2026-10-28-mongo-envelope-credentialstore-was-already-shipped)
below. Phase 4 (Azure `azure_runner.py` cutover): `azure_power_ops`'s code + compose wiring done
(2026-10-28), gated off by default; service-account provisioning and the other three agents not started.
**Date**: 2026-10-27 (addendum), revised 2026-10-28
**Relationship to spec.md / plan.md / tasks.md**: Same functional requirements (FR-001 through FR-049), same
user stories, same acceptance criteria. This addendum **overrides the backend choice only**: it replaces
Option A (MongoDB envelope encryption first, OpenBao later) with **Option C run as the day-one backend**
instead of the hybrid-future path plan.md describes. MongoDB still holds non-secret metadata, ReBAC
references, and audit records — only the secret *material* moves to OpenBao instead of an encrypted Mongo
collection.

## Correction (2026-10-28): Mongo-envelope CredentialStore was already shipped

This plan originally assumed `ui/src/lib/credentials/` and the `/api/credentials/*` routes needed to be
built from scratch (Phases 2-3 below describe that from-scratch build). While starting Phase 1, we found
the Mongo-envelope `CredentialStore` — UI, API routes, audit, ReBAC wiring, the works — was **already
fully implemented and merged** (commit `8d665d4bc`, PR #2263), contrary to `tasks.md`'s stale unchecked
boxes.

Decision (user-confirmed): **swap the backend behind the existing interface** instead of rebuilding it.
Concretely, this meant:
- Keep all shipped UI/API/audit/ReBAC code (`secret-service.ts`, `retrieval-service.ts`, the
  `/api/credentials/*` routes, masking, OpenFGA wiring) completely unchanged.
- Add `ui/src/lib/credentials/openbao-store.ts` as a second implementation of the duck-typed
  `PayloadStore` interface already used internally by `secret-service.ts` (alongside the existing
  `mongo-envelope-store.ts`).
- Add `ui/src/lib/credentials/payload-store-factory.ts`, which both `secret-service-factory.ts` and
  `retrieval-service-factory.ts` now call to construct whichever `PayloadStore` is configured, instead of
  each factory building a `MongoEnvelopeCredentialStore` + key wrapper inline.
- Extend `ui/src/lib/feature-flags/credentials.ts`'s `CredentialStoreBackend` type from
  `"mongodb-envelope"` (only value) to `"openbao" | "mongodb-envelope"`, and flip the default to
  `"openbao"` — this is the single source of truth `payload-store-factory.ts` reads from.
- Add an `openbao` Compose service (dev-mode, `ghcr.io/openbao/openbao:2.1`, in-memory storage, fixed dev
  root token) to both `docker-compose.dev.yaml` and `docker-compose.yaml`, gated behind a `credentials`
  profile — not part of the OSS default install profile set. Wired `OPENBAO_ADDR`/`OPENBAO_TOKEN`/
  `OPENBAO_KV_MOUNT`/`OPENBAO_CREDENTIALS_PATH_PREFIX` into `caipe-ui`/`caipe-ui-prod`'s environment
  blocks in both compose files, plus `ui/env.example`.
- `key-wrapper.ts`/KMS-CMK code was **not** deleted — it's still used by the `mongodb-envelope` backend,
  kept as an opt-out (`CREDENTIAL_STORE_BACKEND=mongodb-envelope`) for environments that haven't
  provisioned OpenBao.

No `CredentialStore` interface, `collections.ts`, `masking.ts`, `audit.ts`, or `/api/credentials/*` route
was written from scratch — Phases 2 and 3 below are superseded by this swap and are kept only for
historical context. **Phase 4 (Azure MCP agent cutover) is unaffected by this correction and is still the
next real work.**

**Why this deviates from plan.md's recommendation**: plan.md picked Option A for first-release speed,
explicitly leaving OpenBao as a later swap. The project's own architectural directive (KIAM/OpenBao for
all cloud credentials, never `.env`) calls for OpenBao as the real backend now, not a placeholder behind
an interface that defaults to Mongo. Building the interface against Mongo first and swapping it later is
two migrations instead of one; this plan does the one that's actually wanted.

## Scope of this slice

Only **User Story 1** (manage secrets) and **User Story 2** (service credential API) from spec.md.
OAuth impersonation (US3/US4), governance UI (US5), deployment docs (US6), migration tooling (US7), and
PR #1282 porting (US8) are deferred — out of scope for this plan, picked up later against the same
`CredentialStore` interface.

**Concrete goal**: the four Azure MCP agents (`azure_{power,cost,cluster,core_services}_ops`) resolve
`ARM_CLIENT_ID/SECRET/TENANT_ID/SUBSCRIPTION_ID` from OpenBao through a `secret_ref`, with zero raw
credential material in `docker-compose.yaml`, `.env`, or Mongo.

## Architecture

```
┌─────────────┐   secret_ref     ┌──────────────┐   JWT-authed    ┌─────────────┐
│ MCP server /│ ───────────────► │ CAIPE BFF     │ ───────────────►│  OpenBao    │
│ Dynamic     │   (config only)  │ /credentials/ │   KV v2 path    │  KV v2      │
│ Agent       │                  │ retrieve      │   per secret    │  engine     │
└─────────────┘                  └──────┬───────┘                 └─────────────┘
                                         │ metadata, ReBAC check,
                                         │ audit event (non-secret)
                                         ▼
                                  ┌──────────────┐
                                  │  MongoDB      │  (secret_ref doc: owner, policy,
                                  │  (metadata)   │   OpenBao path pointer, status —
                                  └──────────────┘   never the secret value itself)
```

- **OpenBao** stores the actual secret material (KV v2, versioned, one path per secret — e.g.
  `secret/data/caipe/azure/power-ops/sp-credentials`).
- **MongoDB** stores only the `secret_ref` metadata document: id, owner, team bindings, OpenBao path,
  status, created/rotated timestamps — exactly the non-secret shape FR-002 requires.
- **OpenFGA** remains the source of truth for `secret_ref#use`/`#manage`/`#share` — unchanged from
  plan.md.
- **Keycloak** remains the JWT identity anchor — unchanged from plan.md.
- CAIPE's own OpenBao **auth method**: Kubernetes auth (in-cluster) or AppRole (Compose/VM) — the BFF
  and Dynamic Agents authenticate to OpenBao with a scoped role that can only read/write under
  `secret/data/caipe/*`, never root token in process env.

## Phase 1 — OpenBao plumbing (blocking everything else) — DONE (dev/Compose scope)

1. **Provision OpenBao** reachable from both the CAIPE UI/BFF and Dynamic Agents:
   - Local/Compose: add an `openbao` service to `docker-compose.dev.yaml` (dev-mode, in-memory or file
     storage, auto-unseal for local only) gated behind a `credentials` profile — not part of the OSS
     default profile set per the `docker-compose-first-install` skill.
   - VPS/prod (`/opt/caipe`): point at a real OpenBao instance (could run as its own container, or — per
     [[infra_kendrainfra_repo_overview]] — eventually live in the `kiam` chart's stack once KIAM's own
     OpenBao usage is clarified; treat these as separate OpenBao mounts for now rather than assuming
     shared infra).
   - Helm/GitOps: `charts/ai-platform-engineering` values for `OPENBAO_ADDR`, auth mount path, role name —
     no token or secret literal in values files.
2. **Enable KV v2** at `secret/` (or a dedicated `caipe/` mount) and a CAIPE-scoped policy restricting
   access to `caipe/*` paths only.
3. **Auth method**: AppRole for Compose/VM deployments (role-id in values/env, secret-id injected via
   the orchestrator's own secret mechanism — Compose `secrets:`, not plain `environment:`); Kubernetes
   auth for Helm deployments (ServiceAccount token, no stored credential at all).
4. **Client wrapper** `ui/src/lib/credentials/openbao-client.ts`: thin wrapper over OpenBao's HTTP API
   (read/write/delete under `secret/data/...`, versioned read, lease renewal if using dynamic secrets
   later). This is the one piece that would change if a future backend swap ever happened — everything
   above it only ever calls `CredentialStore`.

## Phase 2 — CredentialStore interface + OpenBao-backed implementation — SUPERSEDED

Not done as described below — see the [Correction](#correction-2026-10-28-mongo-envelope-credentialstore-was-already-shipped)
above. `openbao-store.ts` exists and does what's described here, but the interface it implements
(`PayloadStore` in `secret-service.ts`) and the file layout already existed; this section is kept for
historical context only.

Same file layout as plan.md's Project Structure, with `ui/src/lib/credentials/`:
- `types.ts` — unchanged from plan.md (`SecretReference`, `CredentialRetrievalRequest`, etc.)
- `openbao-store.ts` — implements the same `CredentialStore` interface plan.md defined for
  `mongo-envelope-store.ts`, but backed by the OpenBao client instead of Mongo envelope encryption.
  No KMS/CMK key-wrapper needed here — OpenBao does its own encryption-at-rest and key rotation.
- `collections.ts` — still needed, but now only for the metadata collection (`secret_refs`), not an
  encrypted-payload collection.
- `masking.ts`, `audit.ts`, `internal-caller.ts` — identical to plan.md; these operate on
  metadata/requests, not on the storage backend, so they're backend-agnostic by construction.
- Drop `key-wrapper.ts` (T013) and the Mongo envelope encrypt/decrypt tests (T015) — not needed when
  OpenBao is the backend.

Tests: replace "envelope store encrypt/decrypt/KMS unwrap" tests (T015) with OpenBao-store tests —
write/read/rotate a KV v2 secret, auth failure, OpenBao sealed/unavailable (must fail closed per FR-022).

## Phase 3 — Secrets manager (US1, scoped to what Azure needs) — ALREADY SATISFIED

The shipped Mongo-envelope-era secrets CRUD UI/API (PR #2263) already covers this; it now runs against
OpenBao transparently via the Phase 2 swap. Kept for historical context only.

Minimum UI/API slice — skip team-sharing UI polish initially, keep personal + one "service" secret type:
- `POST/GET /api/credentials/secrets` — create/list (masked)
- `POST /api/credentials/secrets/[secret_id]/rotate`
- A secret created here writes to OpenBao via the store, and a `secret_ref` metadata doc to Mongo.

## Phase 4 — Service credential API + Azure runner wiring (US2, the Azure payoff)

**Architecture note (2026-10-28)**: the Azure MCP agents (`mcp-azure-power-ops`, `mcp-azure-cost-ops`,
`mcp-azure-cluster-ops`, `mcp-azure-core-services-ops`) run as **standalone Docker Compose containers**,
not as dynamically-registered MCP servers in the `dynamic_agents`/Mongo `credential_sources` resolution
mechanism (`resolve_mcp_credential_refs` in `mcp_client.py` — that machinery already works, but only
applies to Mongo-registered MCP servers). So each Azure agent needs its own service-to-service auth to
call `/api/credentials/retrieve` directly, rather than reusing `dynamic_agents`' existing
`CredentialExchangeClient` (which also lives in a separate Python package from the standalone `mcp/azure_*`
agents). Chosen approach (user-confirmed): **Keycloak client-credentials**, reusing the already-shipped
service-accounts feature (`ui/src/lib/service-accounts.ts`, `rbac/keycloak-admin.ts
createServiceAccountClient`) rather than building new provisioning infra — a confidential Keycloak client
per agent (or shared), `serviceAccountsEnabled: true`, graphed in OpenFGA as `service_account:<sub>`, whose
client-credentials JWT is already recognized end-to-end by `getAuthFromBearerOrSession`
(`identity.isServiceAccount`) — the same contract `dynamic_agents`' `CredentialExchangeClient` and
`/api/credentials/retrieve`'s existing tests already exercise (`x-caipe-credential-caller`,
`x-caipe-credential-audience`, `{secret_ref, intended_use}` body).

1. `POST /api/credentials/retrieve` — **DONE** (already shipped, unchanged).
2. `ai_platform_engineering/mcp/azure_power_ops/tools/credential_client.py` — **DONE**. A small,
   self-contained `ServiceAccountCredentialClient`: does the OAuth2 client-credentials grant against
   `KEYCLOAK_TOKEN_URL`, caches/refreshes the JWT, then calls `/api/credentials/retrieve`. Deliberately not
   a shared import of `dynamic_agents`' `credential_exchange.py` — separate package/deployment unit.
3. **Azure runner change** — `ai_platform_engineering/mcp/azure_power_ops/tools/azure_runner.py` —
   **DONE for `azure_power_ops`**: `_ensure_login()` now calls `_resolve_client_secret()`, which reads
   `ARM_CLIENT_SECRET` from `os.environ` when `CAIPE_CREDENTIALS_ENABLED` is unset/false (default,
   unchanged behavior, FR-044), or resolves it via `credential_client.py` using `ARM_CLIENT_SECRET_REF`
   (default `azure-power-ops/arm-client-secret`) when enabled. `ARM_CLIENT_ID/TENANT_ID/SUBSCRIPTION_ID`
   are still plain env vars (not secret material). Not yet repeated for `azure_cost_ops`,
   `azure_cluster_ops`, `azure_core_services_ops`.
4. `docker-compose.yaml` / `docker-compose.dev.yaml` — **DONE for `mcp-azure-power-ops`**: added
   `CAIPE_CREDENTIALS_ENABLED` (default `false`), `CAIPE_CREDENTIAL_API_URL`, `KEYCLOAK_TOKEN_URL`,
   `CAIPE_SERVICE_ACCOUNT_CLIENT_ID`, `CAIPE_SERVICE_ACCOUNT_CLIENT_SECRET`, `ARM_CLIENT_SECRET_REF`
   alongside the existing `ARM_*` vars (not yet removed — that's step 4 below, once this path is verified
   end-to-end against a live Keycloak+OpenBao). Not yet repeated for the other three agents.
5. **Not started**: one-time provisioning of the `mcp-azure-power-ops` service account itself
   (`POST /api/admin/service-accounts`, then granting it the scope/OpenFGA tuple to retrieve
   `azure-power-ops/arm-client-secret` via `service-account-scopes.ts`) and writing the real Azure SP
   client secret into OpenBao at that `secret_ref` — both must be done by a human directly against
   Keycloak/OpenBao (never by an agent typing real credentials), then `CAIPE_SERVICE_ACCOUNT_CLIENT_ID`/
   `_SECRET` set in `.env` (the service-account's own Keycloak client secret — also not something to type
   into `.env` in plaintext long-term; same standing OpenBao-not-.env constraint applies here too, revisit
   once the provisioning flow is actually run).
6. **Not started**: once step 5 is done and verified, shrink the Azure agents' env blocks to drop the raw
   `ARM_CLIENT_SECRET` var entirely (keep `ARM_CLIENT_ID/TENANT_ID/SUBSCRIPTION_ID`, which aren't secret
   material) and flip `CAIPE_CREDENTIALS_ENABLED` default to `true`.

## What this does NOT change from plan.md

- ReBAC model, audit requirements, browser-guardrail requirements (FR-004 through FR-012) — identical.
- Feature-toggle-gating behavior (FR-042/043/044) — identical; `CREDENTIALS_ENABLED` still defaults off.
- Everything in US3-US8 (OAuth impersonation, connector admin UI, migration tooling, PR #1282 porting) —
  deferred, unaffected by the backend swap, resumed later exactly as plan.md/tasks.md describe.

## Suggested task order

1. ~~OpenBao reachable locally (Compose profile) + auth method decided.~~ **DONE** — dev-mode `openbao`
   service in `docker-compose.dev.yaml`/`docker-compose.yaml` behind the `credentials` profile; dev
   auth is the fixed `BAO_DEV_ROOT_TOKEN_ID` (AppRole/Kubernetes auth for real deployments still TODO,
   see Phase 1 step 3 above — not needed for local/dev).
2. ~~`CredentialStore` interface + `openbao-store.ts` + its tests.~~ **DONE** (as a `PayloadStore`
   implementation swapped in behind the existing interface — see Correction above). Unit tests for
   `openbao-store.ts` (write/read/rotate, sealed/unavailable fail-closed) are still **not written**.
3. ~~Minimal secrets CRUD (create/rotate).~~ **DONE** — already shipped, now running against OpenBao.
4. ~~`/api/credentials/retrieve` + browser-denial guard + its tests.~~ **DONE** — already shipped,
   unchanged, now running against OpenBao.
5. ~~Azure runner cutover, one agent first.~~ **DONE for `azure_power_ops`**: `credential_client.py` +
   `azure_runner.py` changes + compose env wiring, gated behind `CAIPE_CREDENTIALS_ENABLED` (default
   `false`, so the OSS default path is unaffected). **NEXT**: provision the real service account
   (Keycloak client + OpenFGA scope) and write the real Azure SP secret into OpenBao — both manual,
   human-only steps — then verify end-to-end before repeating the runner change for `azure_cost_ops`,
   `azure_cluster_ops`, `azure_core_services_ops`.
6. Compose/Helm env cleanup (drop `ARM_CLIENT_SECRET` literal, flip `CAIPE_CREDENTIALS_ENABLED` default)
   once all four agents are converted and verified. Not started.
7. Everything else in tasks.md (US3+) resumed later, unchanged. Not started.
