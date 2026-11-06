# Current Plan / Status

## Status Snapshot (2026-11-06)

**Blocked, waiting on Azure support.** `~/Software/infra` (separate repo) `envs/azure/dev`
`tofu apply` migration from `uksouth` → `westeurope` is paused mid-flight: `westeurope` is
rejecting VNet/Key Vault/user-assigned identity/Log Analytics Workspace creation for this
subscription with `RequestDisallowedByAzure: region is currently not accepting new customers`,
even though RG/budget/DNS zone/role-assignment succeeded in the same region. Support ticket
drafted (not yet confirmed submitted) with subscription ID and both failed regions' errors. See
Session 6 below for full detail. Do not run further `tofu apply` in that repo until region
eligibility is confirmed.

## Status Snapshot (2026-11-01)

Production VPS (`infra.kendralabs.com` / `srv1892964.hstgr.cloud`, `/opt/caipe`) Azure Cluster Ops
Agent chat is **working end-to-end**. Fixed two unrelated, stacked production issues that both had
to be resolved before any chat turn with that agent could succeed.

## Current Work

Azure MCP connectivity + LLM backend outage on the production VPS — resolved.

### Root cause #1: AgentGateway JWT issuer mismatch (fixed, committed, pushed)
- `deploy/agentgateway/config.yaml`'s bootstrap issuer was hardcoded to
  `http://localhost:7080/realms/caipe`. `agentgateway-config-bridge` perpetuates this value on every
  reconcile (it reads AgentGateway's own live admin API as its "baseline" instead of regenerating
  from env vars), so the wrong issuer never self-healed.
- Fix: issuer corrected to `https://auth.kendralabs.com/realms/caipe`; cleared the stale generated
  config from the `agentgateway_config` shared volume; restarted `agentgateway-config-bridge` then
  `agentgateway` (it only reads config at startup, no hot-reload).
- Committed: `55c5d8794` (`fix(agentgateway): correct JWT issuer to production Keycloak host`),
  pushed to `Kendralabs/ai-platform-engineering` main.

### Root cause #2: LLM backend unreachable from dynamic-agents (fixed, VPS-local config only)
Two stacked issues under this one symptom (`status=cancelled duration=~60s`, "Error: network error"
in the UI, no upstream errors visible):

1. **API key mismatch** — `/opt/caipe/.env`'s `OPENAI_API_KEY`/`LLAMA_API_KEY` didn't match the key
   `gemma4.service`/`llama-server` actually uses (`/etc/gemma4/env`). Fixed by updating `.env`'s keys
   to match and recreating `dynamic-agents` (`docker compose up -d --no-deps dynamic-agents` — use
   `--no-deps` on this VPS/Podman setup to avoid a known unsafe cascading-recreate of unrelated core
   services).
2. **Firewall silently dropping container traffic** — the `GEMMA_GUARD` iptables chain guarding port
   6666 only allowed `lo` and `172.16.0.0/12`. The Podman bridge network `dynamic-agents` runs on
   (`10.89.2.0/24`) wasn't in that range, so every container→host LLM request was dropped with no
   error, surfacing only as a ~60s timeout. Fixed by adding `10.89.0.0/16` to
   `/opt/models/gemma4-e2b/firewall.sh` (persisted, since that script is `gemma4.service`'s
   `ExecStartPre`) and restarting `gemma4.service`.
- These are VPS-local config changes (`.env`, `/etc/gemma4/env` area, `/opt/models/gemma4-e2b/firewall.sh`),
  not tracked in this git repo — not committed, no PR.

### Verified
End-to-end chat test in the UI: Azure Cluster Ops Agent now calls its real Azure MCP tool and
returns a genuine application-level response (e.g. "scope 'all' is not registered... please provide
a specific customer name") — not an infra/network error.

## Work Log

- 2026-11-01: Diagnosed and fixed AgentGateway JWT issuer mismatch (root cause #1); confirmed via
  `dynamic-agents` logs showing successful MCP connection (3 tools loaded).
- 2026-11-01: Diagnosed and fixed LLM API key mismatch in `/opt/caipe/.env` (root cause #2a).
- 2026-11-01: Diagnosed and fixed `GEMMA_GUARD` iptables chain blocking the Podman bridge subnet
  from reaching `llama-server` on port 6666 (root cause #2b) — the actual remaining blocker after
  the API key fix.
- 2026-11-01: Verified full end-to-end chat flow working in the UI.
- 2026-11-01: Committed root cause #1 fix (`55c5d8794`) with DCO sign-off from Alpesh Doshi, pushed
  to `Kendralabs/ai-platform-engineering` main via the `kendra_push_ed25519` deploy key on the VPS.

## Session 2: Disk Space / "Degraded" Badge / Syslog Spam (2026-11-01)

### Root cause: disk at 88% used, triggering Audit Service "Degraded" storage warning
Traced the gap down to two things, both resolved:

1. **Orphaned rootless Podman stack** (`~/.local/share/containers/storage`, separate from the live
   rootful store the real `docker compose` stack runs under) — a duplicate, half-finished `caipe`
   compose project plus Woodpecker CI / Langfuse / Milvus RAG experiments, mostly stuck
   `Created`/`Exited`/`Removing` for 6-8 weeks. One container (a duplicate `keycloak-postgres`) was
   actually `Up 9 days (healthy)`, health-checking every ~6-10s the whole time. Stopped/removed all
   containers, pruned the 15 orphaned volumes (~24G) and all unused images (~24G). Rootless store
   went from 28.7G → 1.4M.
2. **Syslog volume** (`/var/log/syslog.1` was 5.9G/21M lines) — top contributors were `systemd[1]`
   (1.2M lines/week) and `monitor-cloud-backend` (1M lines/week), not primarily Podman health-check
   spam as first assumed. Root-caused:
   - `systemd[1]`: `slack-bot` container crash-looping — **331,340 restarts** since creation 7 days
     ago, every cycle logging start/stop lines. Cause: missing/invalid
     `SLACK_INTEGRATION_BOT_TOKEN`/`SLACK_BOT_TOKEN` → Slack API `not_authed` → unhandled
     `BoltError` → immediate exit → restart policy relaunches instantly. Stopped the container
     (`docker compose stop slack-bot`) until a valid token is configured — slack-bot isn't part of
     the documented default profile path anyway.
   - `monitor-cloud-backend`: unrelated third-party VPS monitoring agent at `/opt/monitor-cloud`
     (not part of caipe), opening a fresh SSH session via `asyncssh` roughly every 1.5 minutes —
     likely the hosting provider's own management agent. Not something to change from this repo.
   - A separate historical crash-loop of the Azure MCP agent containers (`mcp-azure-power-ops` and
     3 siblings, visible in `/var/log/syslog.1` from ~2026-10-28–11-01) had already self-resolved —
     current containers are different IDs, `Up 7 hours (healthy)`.

### Result
`df -h /`: 88% → **73%** used (169G → 140G, 54G free). Audit Service disk warning should clear.

### Outstanding
- `/var/log/syslog.1` (5.9G) itself not yet compressed/removed — needs `sudo gzip` or deletion,
  which requires write sudo I don't have; handed to the user to run.
- `/etc/logrotate.d/rsyslog` still has no `maxsize` cap and `delaycompress` — proposed edit (add
  `maxsize 200M`, drop `delaycompress`) given to the user to apply; not yet confirmed done.
- Confirm the "Degraded" badge actually clears in the UI now that disk usage is down.
- ~~The Azure Power Ops Agent's LLM provider misconfiguration~~ **Fixed.** Root cause: the agent's
  config lives in MongoDB, not git — `caipe.dynamic_agents` doc `_id: "agent-azure-power-ops-agent"`
  had `model.provider: "google-genai-self-hosted-llamacpp "` (invalid provider string, also had a
  trailing space), not one of `cnoe_agent_utils.llm_factory.LLMFactory`'s supported providers.
  The working Azure Cluster Ops Agent (`agent-azure-cluster-ops-agent`) uses the same model id
  (`gemma-4-e2b`) with `provider: "openai"` against the self-hosted llama.cpp/Gemma endpoint —
  updated Power Ops to match via `mongosh updateOne`, recreated `dynamic-agents`
  (`docker compose up -d --no-deps dynamic-agents`), confirmed no `Unsupported provider` errors on
  startup. VPS-local DB change only, not tracked in git, no PR.
- ~~Three orphaned "Created" duplicate containers~~ **Checked, not an issue.** The three
  hash-prefixed containers (`f344364b9d78_mcp-netutils`, `8efd4a91c573_mcp-jira`,
  `8d1cb5240e45_mcp-webex`) are each the single running instance of that service — unusual naming
  (cosmetic, likely from a past Podman Compose conflict-resolution rename), not a duplicate
  running alongside a normal-named twin. No cleanup needed.
- ~~No documentation/runbook update~~ **Done.** Written up at
  `workbench/runbooks/vps-llm-backend-gotchas.md`: `.env` vs `/etc/gemma4/env` key drift,
  `GEMMA_GUARD` firewall subnet gotcha, and the MongoDB-not-git location of per-agent LLM
  provider config (with the Azure Power Ops Agent fix as a worked example).
- ~~The temporary write-enabled deploy key~~ **Resolved.** GitHub side: `gh api
  repos/Kendralabs/ai-platform-engineering/keys` returns no registered deploy keys — already
  clear. VPS side: deleted the closest-matching local key pair, `~/.ssh/kendra_ci_deploy_ed25519`
  (+ `.pub`), with explicit confirmation.

## Session 3: Neo4j Aura → VPS Migration (2026-11-02)

### Summary
Migrated the `kendra-kiam` Neo4j Aura instance (project "Kendra Labs", ID `8ce64c3e`) off Aura
and onto a new dedicated `kcg-prod-neo4j` container on the production VPS, to stop Aura billing.
KCG app's `.env` was updated and the `kcg` service restarted (by someone with root/`kcg-deploy`
write access); end-to-end UI verification at `https://nexus.kendralabs.com` confirms it's fully
working against the new backend.

### What was done
- Created a temporary Aura user `migrator` (role `architect`) via the Aura Query console, since
  there is no real "recover credentials" flow — Aura's docs call this "create a new user" instead.
- Exported all data from Aura over Bolt (`neo4j+s://8ce64c3e.databases.neo4j.io`) using
  `elementId()` as a correlation key, and imported into `kcg-prod-neo4j` (already running on the
  VPS, Bolt on `127.0.0.1:7689`) via APOC's `apoc.create.node`/`apoc.create.relationship`, over an
  SSH tunnel. Verified counts and label distributions match exactly: 16,771 nodes, 308
  relationships.
- Paused the `kendra-kiam` Aura instance (RUNNING $0.36/hr → PAUSED $0.072/hr).
- Deleted the plaintext `/tmp/kcg-prod-neo4j-creds.txt` on the VPS.
- `/opt/kcg/.env` updated (`NEO4J_URI=bolt://kcg-prod-neo4j:7687`, `NEO4J_USER=neo4j`,
  `NEO4J_PASSWORD=<see kcg-prod-neo4j container env>`) and the `kcg` compose service
  force-recreated (`docker compose -p kcg -f docker-compose.yml -f docker-compose.prod.yml up -d
  --force-recreate kcg`). Logs confirmed clean startup against `bolt://kcg-prod-neo4j:7687`.
- Found and fixed a follow-on issue: `kcg-backend`'s container IP changed on recreate
  (`10.89.0.8` → `10.89.0.13` on the `kcg_default` network), but `kcg-dashboard`'s nginx had the
  old IP cached, causing `/api/auth/login` and other `/api/*` calls to fail with 502 ("Host is
  unreachable"). Fixed with `docker restart kcg-dashboard` to force nginx to re-resolve.
- Verified end-to-end in the browser at `https://nexus.kendralabs.com`: login works, dashboard
  shows "KCG connected" with real metrics (1000 nodes, 191 edges, eval metrics populated), and the
  Graph explorer renders real migrated data (Decision: 992, Agent: 7 nodes).

### Outstanding
- The Aura `migrator` user (role `architect`) was **not** dropped — decided to leave it dormant
  while the instance is paused (no one can authenticate to a paused instance) rather than pay for
  a resume/drop/re-pause cycle. Drop it next time the instance is resumed for any reason, or before
  final decommission.
- Aura instance is paused, not deleted — final disposition (stay paused vs. delete) still pending
  user's planned move to another host (e.g. Azure).
- Worth a follow-up note/runbook entry: any future `kcg` service recreate needs a `kcg-dashboard`
  nginx restart too, since its upstream IP isn't re-resolved automatically.

## Session 4: Azure Cluster Ops Agent → NVIDIA NIM LLM Backend (2026-11-03)

### Summary
Switched the Azure Cluster Ops Agent's LLM backend on the production VPS from the slow
self-hosted Gemma/llama.cpp setup to NVIDIA NIM (`https://integrate.api.nvidia.com/v1`,
model `nvidia/nemotron-3-ultra-550b-a55b`), via the OpenAI-compatible `openai` provider path —
no code changes needed, pure config.

### What was done
- Registered the new model in the Kendra Infra admin UI's LLM Models tab
  (`nvidia/nemotron-3-ultra-550b-a55b` / "Nemotron 3 Ultra (NVIDIA NIM)" / provider `openai`).
- Attempted to store the NVIDIA API key via the UI's "Connect provider" flow — failed with
  "Credential features are disabled." Root cause: `CAIPE_CREDENTIALS_ENABLED` is unset on this
  VPS and there is no OpenBao service deployed at all (not a bug — that subsystem was never
  turned on here).
- Per explicit user decision, bypassed the credential store as a temporary exception and put the
  key directly in `/opt/caipe/.env` as `OPENAI_API_KEY` (`OPENAI_ENDPOINT` was already pointed at
  NVIDIA NIM from earlier in this session).
- Updated `caipe.dynamic_agents` doc `_id: "agent-azure-cluster-ops-agent"` via `mongosh`:
  `model.id` → `nvidia/nemotron-3-ultra-550b-a55b`, `model.provider` stays `openai`.
- Hit a 401 (`Invalid JWT serialization`) on first retest — root-caused to a stale/unrelated key
  (`sk-kcg...`) left in `OPENAI_API_KEY`, not the NVIDIA key. User corrected the value; confirmed
  by shape only (`nvapi-...`, 70 chars) without ever printing the secret.
- Recreated `dynamic-agents` (`docker compose up -d --no-deps dynamic-agents`); verified clean
  startup.

### Verified
End-to-end chat test in the UI: Azure Cluster Ops Agent's `self_identity` tool confirms
`model_id: nvidia/nemotron-3-ultra-550b-a55b`, `model_provider: openai`, and the agent replies
correctly identifying itself as running on NVIDIA Nemotron 3 Ultra. No 401, no network error.

### Outstanding
- This is a VPS-local config change only (`.env`, MongoDB) — not tracked in git, no PR.
- The NVIDIA API key living in `/opt/caipe/.env` is an explicit, scoped exception to the
  OpenBao/KIAM-secrets rule, made only because the credential-store subsystem isn't deployed on
  this host — revisit if/when that subsystem is brought up here.
- Not yet extended to the other Azure agents (Power Ops, Core Services, Cost Ops) — not
  requested by the user.

### Update: extended to all Azure agents (2026-11-03, same day)
User asked to switch all agents to the NVIDIA model. Updated `caipe.dynamic_agents` for
`agent-azure-power-ops-agent`, `agent-azure-cost-ops-agent`, and
`agent-azure-core-services-ops-agent` (Cost Ops and Core Services also had the known invalid
`"google-genai-self-hosted-llamacpp "` provider string — fixed as part of this change) to
`model.id: nvidia/nemotron-3-ultra-550b-a55b`, `model.provider: openai`, matching Cluster Ops.
Recreated `dynamic-agents`; clean startup, no `Unsupported provider` errors. All 4 real Azure
agents (`hello-world` has no model configured and was left alone) now confirmed via `mongosh`
pointing at the NVIDIA model. Live UI chat re-verification for Power Ops/Cost Ops/Core Services
not yet done (Chrome extension disconnected mid-session) — config + clean container startup are
the current evidence.

## Session 5: Azure Service Principal for MCP Agents (2026-11-03)

### Summary
Discovered the `mcp-azure-*` containers (power-ops, cost-ops, cluster-ops, core-services-ops)
were running on the VPS with no real Azure subscription credentials — only
`AZURE_OPENAI_*` vars (an LLM endpoint, unrelated) existed in `/opt/caipe/.env`. Created a real
Azure AD service principal so these agents can actually operate against Azure resources, not
just respond with app-level placeholder messages.

### What was done
- Confirmed local `az` CLI already authenticated as the user against subscription
  "Kendra Platform" (`c53f4750-141e-4653-b484-0ca2774bca63`).
- Per explicit user choice (Contributor role, whole-subscription scope), created
  `az ad sp create-for-rbac --name caipe-azure-mcp-agents --role Contributor --scopes
  /subscriptions/c53f4750-141e-4653-b484-0ca2774bca63` — output redirected straight to a local
  scratchpad file, never printed to the transcript.
- Wrote `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` to a
  local snippet file, `scp`'d it to the VPS `/tmp`, then (separate approved step)
  `cat >> /opt/caipe/.env` and removed the temp file — same scoped
  no-OpenBao-deployed exception as the NVIDIA key, with the secret value never appearing in chat.
  Deleted the local scratchpad SP/snippet files afterward.
- Recreated all 4 `mcp-azure-*` containers (`docker compose up -d --no-deps ...`); confirmed
  clean FastMCP startup logs for all four, no auth errors.

### Outstanding
- VPS-local `.env` change + a live Azure AD/subscription resource (service principal +
  Contributor role assignment) — not tracked in git, no PR.
- Not yet verified end-to-end that the agents can actually list/manage real Azure resources with
  the new SP (only confirmed clean container startup so far) — next step is a live chat test per
  agent once the Chrome extension reconnects.
- Contributor at subscription scope is broad — revisit narrowing to specific resource groups
  once real usage patterns are known, per the user's own call at setup time.
- The SP secret has no expiry override applied (uses Azure AD's default, currently 1 year) —
  note for future rotation.

## Session 6: Azure `dev` Region Migration (uksouth → westeurope), blocked (2026-11-06)

### Context
Separate repo: `~/Software/infra` (OpenTofu), `envs/azure/dev`. Per explicit user instruction,
executed a real `tofu apply` for this environment (previously held off pending approval).

### What was done
- Fixed `AvailabilityZoneNotSupported`: `availability_zones` variable wasn't passed through from
  `envs/azure/dev`/`customer-template` down to `modules/azure/compute` — added the variable +
  wiring to both envs.
- Hit a deeper blocker: `uksouth` has **zero VM compute SKUs available at all** for this
  subscription (`az vm list-skus --location uksouth --resource-type virtualMachines` returns
  nothing usable) — not a zone or size issue, a full compute-quota absence. PaaS resources
  (Postgres, Key Vault, VNet) deployed fine there; AKS never could.
- Escalated to user via AskUserQuestion (destroy/recreate of already-provisioned uksouth
  resources was the cost of switching) — user chose **westeurope**.
- Changed `azure_region` to `westeurope` in `dev/terraform.tfvars`, reverted the
  `availability_zones = []` override (westeurope fully supports AZs).
- Ran the destroy+recreate apply. Hit a second blocker mid-migration: Resource Group deletion
  failed because `azurerm_private_dns_zone.postgres` (global resource, no `location` attribute)
  wasn't included in the destroy plan — root-caused and fixed with
  `-replace=module.storage.azurerm_private_dns_zone.postgres` alongside the RG replacement.
- Re-ran the apply: RG, budget, DNS zone, and the infra-admins role assignment were created
  successfully in `westeurope`. Then hit the **current blocker**: VNet, NSG, Key Vault,
  user-assigned identity, and Log Analytics Workspace were all rejected with
  `RequestDisallowedByAzure: The selected region is currently not accepting new customers` —
  a subscription-eligibility restriction, not a capacity/SKU issue, and not queryable via `az` CLI.
- Escalated again rather than guessing a third region (two consecutive region failures already
  incurred real destroy/recreate cost) — user chose to pause and open an Azure support ticket.
  Drafted the ticket text (subscription ID, both failed regions, affected resource types, error
  strings) for the user to submit via the Portal.

### Current live Azure state (envs/azure/dev, `kendra-dev-rg` in `westeurope`)
- Exists: Resource Group, Consumption Budget, Private DNS Zone
  (`privatelink.postgres.database.azure.com`), Contributor role assignment (infra admins).
- Does NOT yet exist: VNet, NSG, Key Vault, user-assigned identity, Log Analytics Workspace,
  AKS cluster, dashboard, Postgres server, federated identity credential, workload key vault
  access policy — these are what the next `tofu apply` needs to create once a working region is
  confirmed.

### Outstanding
- Waiting on user to submit the drafted support ticket and report back which region(s) this
  subscription is eligible for.
- Once confirmed: update `azure_region` in `dev/terraform.tfvars` again if westeurope isn't
  viable, `tofu plan`/`apply` (same `-exclude` flags for the 3 diagnostic-setting resources, plus
  `-replace` on the DNS zone again only if migrating regions a second time), then run the second
  plain `tofu apply` (no excludes) to converge diagnostics per
  `docs/runbooks/azure-platform/07-observability.md`.
- Consider whether `customer-template`'s own default region has the same subscription-eligibility
  gap — not yet checked, only relevant if/when a new customer env is provisioned from it.
