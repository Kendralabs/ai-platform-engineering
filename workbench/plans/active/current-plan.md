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
- The temporary write-enabled `kendra_push_ed25519` / `caipe-vps-push-deploy-key` GitHub deploy key
  on the VPS has not been deleted or rotated.
