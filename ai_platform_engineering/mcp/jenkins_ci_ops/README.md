# Jenkins CI Ops MCP Server

Control/manage/monitor/configure surface for the Jenkins-on-AKS CI/CD
pipeline described in [`kendra-ci`](https://github.com/Kendralabs/kendra-ci)'s
`docs/CICD-SPEC.md`, plus the Terraform-provisioned ACR registry and the
Azure Key Vault secrets it depends on. Built on the same registry/runner
split as `azure_cluster_ops`, `azure_power_ops`, and `azure_cost_ops`: a
discovery-based registry (`tools/registry.py`) resolves a customer name
(e.g. `"kendralabs"`) or `"all"` to the infra in scope, and
`tools/azure_runner.py` runs a fixed `az` command set after a lazy
service-principal login.

## Why this server exists

Agents should never get raw `az`/`kubectl`/`terraform` shell passthrough -
every capability below is its own typed MCP tool with a fixed parameter
shape, so KACP's policy layer can grant or deny per-tool instead of trying
to parse/allow arbitrary CLI strings. See
`kendra-ci/docs/CICD-SPEC.md` and the Key Vault / ACR provisioning work in
`infra/docs/runbooks/azure-platform/` for the infra this server fronts.

## Tool surface

### Tier 1 - read-only (always on, no approval)

- `jenkins_get_build_status(scope, job_name)` - last build result, duration,
  commit SHA for one Jenkins job.
- `jenkins_get_queue(scope)` - current build queue.
- `acr_list_repositories(scope)` - repositories in the customer's ACR.
- `acr_show_digest(scope, repository, tag)` - resolves a tag to its
  immutable digest (`az acr repository show`), matching the
  build-once-deploy-anywhere convention (`ArtifactManager.groovy`).
- `keyvault_list_secret_names(scope)` - secret **names** only, never values.
- `terraform_show_state(scope, module_path)` - reads current state for a
  module (`terraform show`, read-only, no plan execution).

### Tier 2 - plan/diff (safe to run freely, no live mutation)

- `terraform_plan(scope, module_path)` - runs `terraform plan`, returns the
  diff. Never applies. Requires live Azure credentials; returns a clear
  error if the sandbox/environment has none (this is the same gap the
  human subagents hit during the initial AKS/ACR provisioning work).

### Tier 3 - write/apply (KACP policy-gated, audit-logged, human approval
required, same `confirm=True` discipline as `azure_cluster_ops`)

- `terraform_apply(scope, module_path, plan_id, confirm)` - **not yet
  implemented**. Deliberately stubbed: an apply must be scoped to a plan
  hash that was actually reviewed, not a fresh plan computed at apply time
  (prevents apply-drift from what a human approved). Wire this up only
  once KACP's plan-hash attachment flow exists.
- `acr_delete_repository`, `terraform_import`,
  `azurerm_role_assignment_create` - **not implemented**. Each would be its
  own narrowly-scoped tool (never a generic `az`/`terraform` passthrough).
- `keyvault_set_secret` - **deliberately not implemented as a direct `az
  keyvault secret set` call.** `kendra-kendralabs-kv` must never be written
  to except via the in-cluster-pod pattern established in
  `infra/docs/runbooks/azure-platform/04b-kiam-identity-admin-vault-provisioning.md`
  (no public network access to the vault, ever). This tool exists only as a
  stub that returns that runbook's steps - it never touches the vault
  itself.

## Registry is discovered, not hand-maintained

Same mechanism as `azure_cluster_ops/tools/registry.py`: reads
`JENKINS_CI_OPS_INFRA_REPO_PATH`'s `envs/azure/` directory at call time,
includes an env only if it has both `terraform.tfvars` and `backend.hcl`.
Kendra Labs' own platform is just another entry here (`"kendralabs"`), not
a special case - the registry doesn't distinguish "our infra" from
"customer infra".

## Authentication

Same Azure service-principal variables as `azure_cluster_ops`
(`ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` / `ARM_TENANT_ID` /
`ARM_SUBSCRIPTION_ID`, resolved via the CAIPE credential-exchange API when
`CAIPE_CREDENTIALS_ENABLED=true` - see `tools/credential_client.py`), plus:

| Variable | Description |
|---|---|
| `JENKINS_URL` | Base URL of the Jenkins controller |
| `JENKINS_API_TOKEN_REF` | Credential-exchange secret ref for the Jenkins API token (or `JENKINS_API_TOKEN` env var directly when `CAIPE_CREDENTIALS_ENABLED=false`) |
| `JENKINS_USER` | Jenkins user the API token belongs to |

Scope the service principal to **AcrPull/AcrPush on the specific registry**
and **Reader on the AKS resource** - never subscription-wide Contributor,
and never any Key Vault role beyond what the in-cluster pod identity
already has (this server's own credentials must not be able to write
secrets either).

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `JENKINS_CI_OPS_INFRA_REPO_PATH` | Local path to the `infra` repo checkout to read `envs/azure/` from | (required to discover any environment) |
| `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` / `ARM_TENANT_ID` / `ARM_SUBSCRIPTION_ID` | Service principal credentials | (required for any `az` action) |
| `JENKINS_URL` / `JENKINS_USER` / `JENKINS_API_TOKEN_REF` | Jenkins API access | (required for Jenkins tools) |
| `JENKINS_CI_OPS_AZ_TIMEOUT` | Per-`az`-command timeout (seconds) | `120` |
| `JENKINS_CI_OPS_TERRAFORM_TIMEOUT` | Per-`terraform`-command timeout (seconds) | `300` |
| `MCP_MODE` | `STDIO` or `http` | `STDIO` |
| `MCP_HOST` | Bind host in `http` mode | `localhost` |
| `MCP_PORT` | Bind port in `http` mode | `8000` |
| `SERVER_NAME` | Display name for the MCP server | `JenkinsCIOps` |

## RBAC note

Run with its own `MCP_PDP_SCOPE` (see `mcp_agent_auth.middleware`), distinct
from the Azure cluster/power/cost agents - this server's eventual write
tools (`terraform_apply`, etc.) carry a different blast radius than node
pool scaling or a power toggle, and should be approvable independently.

## Known gaps / not yet built

- Tier 3 tools are intentionally unimplemented stubs - see above. Do not
  wire them up without a KACP-side plan-hash/approval mechanism to attach
  to `terraform_apply`.
- `terraform_plan`/`terraform_show_state` shell out to a locally-checked-out
  `infra` repo path; they do not clone or fetch it themselves.
- No live customer/Kendra Labs environment has had this server run against
  it end-to-end yet - built directly from the patterns in
  `azure_cluster_ops`/`azure_power_ops`/`azure_cost_ops` and the
  `kendra-ci`/`infra` conventions established in the Jenkins-on-AKS and ACR
  provisioning work, not yet exercised live.
