# Azure Core Services Ops MCP Server

Read-only visibility for the Azure resources
[`infra`](https://github.com/Kendralabs/infra)'s `envs/azure/<customer>`
Terraform/OpenTofu provisions alongside AKS that neither `azure_power_ops`
nor `azure_cluster_ops` cover: the VNet/subnets, Key Vault, Postgres
Flexible Server, and the workload-identity federated credential.

Fourth of the Azure agent set, built on the same registry/runner split as
`azure_power_ops`, `azure_cost_ops`, and `azure_cluster_ops`: a
discovery-based registry (`tools/registry.py`) resolves a customer name or
`"all"` to the core-services resource names in scope, and
`tools/azure_runner.py` runs a fixed `az` command set after a lazy
service-principal login.

## Registry is discovered, not hand-maintained

`tools/registry.py` reads `AZURE_CORE_SERVICES_OPS_INFRA_REPO_PATH`'s
`envs/azure/` directory at call time and includes a customer only if its
directory has both `terraform.tfvars` (names the customer) and
`backend.hcl` (actually `tofu apply`'d). `customer-template` itself is
always skipped. If no customer environment has been applied yet, the
registry is simply empty - the expected state today, not an error.

Component names follow `envs/azure/customer-template/main.tf`'s own
convention: VNet `kendra-<customer>-vnet`, Key Vault `kendra-<customer>-kv`,
Postgres server `kendra-<customer>-pg`, workload identity
`kendra-<customer>-workload-identity`, all in resource group
`kendra-<customer>-rg`.

## Scope

- `core_get_network(scope)` - VNet address space and subnet topology
  (name, address prefix, provisioning state) for a customer or `"all"`
  customers.
- `core_get_key_vault(scope)` - Key Vault SKU, soft-delete/purge-protection
  flags, and access-policy grants (object ID + secret/key permissions
  **only** - secret values are never read or returned).
- `core_get_postgres(scope)` - Postgres Flexible Server state, version,
  SKU, storage size, and high-availability mode/state. Never credentials.
- `core_get_workload_identity(scope)` - the workload identity's client ID,
  principal ID, and its federated-credential bindings (issuer, subject,
  audiences).

A scope that doesn't resolve to a registered customer is refused outright -
the registry, not the request, is the safety boundary.

## Deliberately no write tools

Unlike `azure_power_ops` (power on/off) and `azure_cluster_ops` (node-pool
scaling), this server has no write actions at all:

- **VNet/subnets, Key Vault, and workload identity** aren't meant to be
  resized, power-cycled, or reconfigured through a chat agent - changing
  any of them is a Terraform-level change (`envs/azure/<customer>`), not a
  runtime operation.
- **Postgres Flexible Server config** (SKU, storage, HA mode) is likewise
  a Terraform concern; only its power state is agent-controlled, and that
  belongs to `azure_power_ops`.
- **Key Vault secret values are never exposed** - `core_get_key_vault`
  reports access-policy *grants* (who can read what), never secret
  contents, regardless of caller.

If a write action becomes genuinely needed here, add a dedicated,
explicitly guarded tool rather than widening one of these read tools.

## Authentication

Reuses the same Azure service-principal credentials `azure_power_ops`,
`azure_cost_ops`, and `azure_cluster_ops` already use:

| Variable | Description |
|---|---|
| `ARM_CLIENT_ID` | Service principal client ID |
| `ARM_CLIENT_SECRET` | Service principal secret |
| `ARM_TENANT_ID` | Azure AD tenant ID |
| `ARM_SUBSCRIPTION_ID` | Target subscription |

Scope this service principal to **Reader** on the target resource groups -
no write permissions are needed for this server's tools. If it shares a
service principal with the write-capable Azure agents, that principal's
broader grants are driven by those agents' needs, not this one's.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `AZURE_CORE_SERVICES_OPS_INFRA_REPO_PATH` | Local path to the infra repo checkout to read `envs/azure/` from | (required to discover any environment) |
| `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` / `ARM_TENANT_ID` / `ARM_SUBSCRIPTION_ID` | Service principal credentials | (required for any action) |
| `AZURE_CORE_SERVICES_OPS_AZ_TIMEOUT` | Per-`az`-command timeout (seconds) | `120` |
| `MCP_MODE` | `STDIO` or `http` | `STDIO` |
| `MCP_HOST` | Bind host in `http` mode | `localhost` |
| `MCP_PORT` | Bind port in `http` mode | `8000` |
| `SERVER_NAME` | Display name for the MCP server | `AzureCoreServicesOps` |

## RBAC note

Run with its own `MCP_PDP_SCOPE` (see `mcp_agent_auth.middleware`),
distinct from the other three Azure agents. Since every tool here is
read-only and explicitly excludes secret values, this server's blast
radius is informational disclosure of infrastructure topology, not
resource control - a different (and narrower) authorization concern than
`azure_power_ops`, `azure_cost_ops`, or `azure_cluster_ops`.

## Not yet built

- `azure-scale-ops`, `azure-backup-ops`, `azure-policy-ops`,
  `azure-security-ops` - the rest of the Azure agent set, built in order
  after `azure-power-ops`, `azure-cost-ops`, `azure-cluster-ops`, and this
  server.
- No live customer environment has actually been `tofu apply`'d yet, so
  this server has not been run end-to-end against real Azure resources -
  only against an empty registry.
