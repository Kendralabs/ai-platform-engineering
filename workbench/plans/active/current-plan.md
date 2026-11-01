# Current Plan / Status

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

## Outstanding / Not Yet Decided

- Three orphaned "Created" duplicate containers from an earlier cascading-recreate incident are
  still present on the VPS — not yet cleaned up, not yet escalated.
- No documentation/runbook update yet for the `.env` vs `/etc/gemma4/env` key-drift discovered this
  session, or for the `GEMMA_GUARD` firewall subnet gotcha — worth a note so this isn't rediscovered
  blind next time.
- The temporary write-enabled `kendra_push_ed25519` / `caipe-vps-push-deploy-key` GitHub deploy key
  on the VPS has not been deleted or rotated.
- The "Degraded" status badge visible in the chat UI's top nav has not been investigated.
