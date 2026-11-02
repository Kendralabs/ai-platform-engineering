# VPS LLM Backend Gotchas (`infra.kendralabs.com` / `/opt/caipe`)

Two non-obvious failure modes hit the self-hosted llama.cpp/Gemma LLM backend on this VPS.
Both surface the same way in the UI: a chat turn just times out (`status=cancelled
duration=~60s`, "Error: network error"), with no upstream error to point at the real cause.

## 1. `.env` vs `/etc/gemma4/env` API key drift

- `gemma4.service` (the systemd unit running `llama-server`) reads its API key from
  `/etc/gemma4/env`.
- `dynamic-agents` reads its key for talking to that backend from `/opt/caipe/.env`
  (`OPENAI_API_KEY` / `LLAMA_API_KEY`).
- These two files are **not the same file and nothing keeps them in sync.** If either one is
  rotated/regenerated independently, the key in `.env` stops matching what `llama-server`
  actually accepts, and every request from `dynamic-agents` to the LLM backend fails.
- **Check**: compare the key in `/opt/caipe/.env` against `/etc/gemma4/env` directly.
- **Fix**: update `.env` to match, then `docker compose up -d --no-deps dynamic-agents` on this
  VPS/Podman setup — use `--no-deps`, a plain `up -d dynamic-agents` has been observed to trigger
  an unsafe cascading recreate of unrelated core services here.

## 2. `GEMMA_GUARD` firewall chain blocking the Podman bridge subnet

- Port 6666 (the llama-server endpoint containers talk to, `host.containers.internal:6666`) is
  guarded by an iptables chain named `GEMMA_GUARD`.
- That chain is set up by `/opt/models/gemma4-e2b/firewall.sh`, which is `gemma4.service`'s
  `ExecStartPre` — so it reapplies on every service restart, and a narrow allowlist here silently
  persists across restarts instead of self-healing.
- It only allowed `lo` and `172.16.0.0/12`. The Podman bridge network containers actually run on
  (`10.89.2.0/24` for the `dynamic-agents` network, `10.89.0.0/16` more broadly across this VPS's
  Podman setup) was **not** in that range, so every container→host LLM request was dropped with
  no error — the only symptom is the ~60s timeout in point 1 above, which looks identical to the
  API-key-mismatch failure mode. Check both when this error shows up.
- **Check**: `iptables -L GEMMA_GUARD -n` (or equivalent) and compare against the actual subnet(s)
  containers are on (`docker network inspect <network> | grep Subnet`).
- **Fix**: add the missing subnet (`10.89.0.0/16` covers all Podman bridges on this VPS) to
  `/opt/models/gemma4-e2b/firewall.sh` so it persists across restarts, then
  `systemctl restart gemma4.service`.

## 3. Azure Power Ops Agent LLM provider config lives in MongoDB, not git

- Per-agent LLM provider/model selection for dynamic agents is **not** in
  `docker-compose.yaml`/`docker-compose.dev.yaml` or any git-tracked config — it's stored in
  MongoDB, collection `caipe.dynamic_agents`, one document per agent (`_id` like
  `agent-azure-power-ops-agent`), under the `model` field (`model.id`, `model.provider`).
- Grepping the repo for the provider string or agent name will find nothing; don't assume the
  config doesn't exist just because the repo search comes up empty — check Mongo directly:
  ```
  docker exec caipe-mongodb mongosh -u admin -p <MONGO_INITDB_ROOT_PASSWORD> \
    --authenticationDatabase admin --quiet --eval '
  db.getSiblingDB("caipe").dynamic_agents.find({_id:"agent-azure-power-ops-agent"}, {model:1}).toArray()
  '
  ```
- A bad value here raises `ValueError: Unsupported provider: <value>` from
  `cnoe_agent_utils.llm_factory.LLMFactory.__init__` in the `dynamic-agents` logs. Supported
  provider strings: `groq`, `google-gemini`, `aws-bedrock`, `openai`, `azure-openai`,
  `anthropic-claude`, `gcp-vertexai`.
- For the self-hosted llama.cpp/Gemma endpoint specifically, the correct provider is `openai`
  (pointed at `host.containers.internal:6666/v1`) — confirmed against the working Azure Cluster
  Ops Agent (`agent-azure-cluster-ops-agent`), which uses `model.id: "gemma-4-e2b"` with
  `model.provider: "openai"`.
- **Fix**: `updateOne` the offending agent's `model.provider` field via `mongosh`, then
  `docker compose up -d --no-deps dynamic-agents` to pick it up.
