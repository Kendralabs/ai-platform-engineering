# Observability Ops MCP Server

Read access to the platform's observability stack - SigNoz query-service
plus the dedicated `signoz` ClickHouse database - and a single guarded
tool to restart an unhealthy observability component in Kubernetes.

Built against the stack described in
`charts/observability/values.yaml` (infra repo): SigNoz query-service on
port 8080, ClickHouse at `clickhouse.observability:9000` / database
`signoz` / user `signoz`, with `otel-collector`, `query-service`,
`frontend`, `zookeeper` as the Deployments/StatefulSet in the
`observability` namespace.

## Why this server exists

Same principle as `jenkins_ci_ops/README.md`: agents should never get raw
shell/SQL passthrough. Every capability below is its own typed MCP tool
with a fixed parameter shape - `tools/clickhouse_client.py` exposes only
parameterized query *templates*, never a raw-SQL entry point, and
`tools/restart.py` only ever restarts one of three allow-listed
Deployments, never an arbitrary `kubectl` command.

## Tool surface

### Tier 1 - read-only (always on, no approval)

- `observability_get_service_health()` - SigNoz query-service health +
  the services it currently sees telemetry from.
- `observability_query_traces(service_name, lookback_minutes=60, limit=20)`
  - recent traces for a service.
- `observability_query_logs(service_name, lookback_minutes=60, limit=50, query_filter=None)`
  - recent logs for a service, with an optional body "contains" filter.
- `observability_query_metrics(metric_name, lookback_minutes=60)` - a
  summary (count/min/max/avg) of a metric's sample values, read from the
  `signoz` ClickHouse database via a single fixed query template.

### Tier 2 - write (confirm-gated, KACP policy-gated, audit-logged)

| Tool | Guard |
|---|---|
| `observability_restart_component(component, confirm=False)` | `component` must be one of `"otel-collector"`, `"query-service"`, `"frontend"` (fixed allow-list - anything else is refused outright, before any Azure/Kubernetes call). `confirm` must be `True`. |

`observability_restart_component` patches the target Deployment's
pod-template annotation in the `observability` namespace - the same
mechanism `kubectl rollout restart` uses - via its own self-contained
Kubernetes Apps V1 API call. It does not cross-call `azure_cluster_ops` or
any other MCP server at runtime: each MCP server in this repo ships as an
independently-deployable unit (see how `azure_power_ops`/`azure_cost_ops`/
`azure_cluster_ops`/`jenkins_ci_ops` each duplicate their own
runner/registry rather than sharing one).

`zookeeper` is deliberately **not** in the allow-list - it's a
StatefulSet, not a Deployment, and this tool only patches Deployments.

## Authentication

### SigNoz / ClickHouse

| Variable | Description | Default |
|---|---|---|
| `SIGNOZ_QUERY_SERVICE_URL` | Base URL of SigNoz query-service | (required for Tier 1 trace/log/health tools) |
| `OBSERVABILITY_OPS_HTTP_TIMEOUT` | Per-request timeout to query-service (seconds) | `30` |
| `CLICKHOUSE_HOST` | ClickHouse host | `clickhouse.observability` |
| `CLICKHOUSE_PORT` | ClickHouse port | `9000` |
| `CLICKHOUSE_DATABASE` | ClickHouse database | `signoz` |
| `CLICKHOUSE_USER` | ClickHouse user | `signoz` |
| `CLICKHOUSE_PASSWORD_REF` | Credential-exchange secret ref for the ClickHouse password (used when `CAIPE_CREDENTIALS_ENABLED=true`) | `observability-ops/clickhouse-password` |
| `CLICKHOUSE_PASSWORD` | ClickHouse password directly (used when `CAIPE_CREDENTIALS_ENABLED=false`) | (required for `observability_query_metrics` when credential-exchange is disabled) |

### Kubernetes restart tool

Same Azure service-principal pattern as `azure_cluster_ops`/
`jenkins_ci_ops` (`ARM_CLIENT_ID`/`ARM_CLIENT_SECRET`/`ARM_TENANT_ID`/
`ARM_SUBSCRIPTION_ID`, resolved via the CAIPE credential-exchange API when
`CAIPE_CREDENTIALS_ENABLED=true` - see `tools/credential_client.py`),
plus a fixed single-cluster target (this agent only ever targets the
platform's own observability stack, never a per-customer one, so there is
no customer registry here):

| Variable | Description |
|---|---|
| `OBSERVABILITY_OPS_AKS_RESOURCE_GROUP` | Resource group of the AKS cluster running the `observability` namespace |
| `OBSERVABILITY_OPS_AKS_CLUSTER_NAME` | Name of that AKS cluster |
| `OBSERVABILITY_OPS_AZ_TIMEOUT` | Per-`az`-command timeout (seconds), default `120` |

### Common

| Variable | Description | Default |
|---|---|---|
| `CAIPE_CREDENTIALS_ENABLED` | Resolve `ARM_CLIENT_SECRET`/`CLICKHOUSE_PASSWORD` via CAIPE's credential-exchange API instead of plain env vars | `false` |
| `MCP_MODE` | `STDIO` or `http` | `STDIO` |
| `MCP_HOST` | Bind host in `http` mode | `localhost` |
| `MCP_PORT` | Bind port in `http` mode | `8000` |
| `SERVER_NAME` | Display name for the MCP server | `OBSERVABILITY_OPS` |

Scope the service principal to **Reader on the AKS resource** only - this
server's only Kubernetes action is a Deployment annotation patch in one
fixed namespace, never cluster-admin.

## RBAC note

Run with its own `MCP_PDP_SCOPE` (see `mcp_agent_auth.middleware`),
distinct from the Azure agents and from `jenkins_ci_ops` - restarting an
observability component has a different (and platform-wide) blast radius
than node-pool scaling or a customer power toggle.

## Known gaps

- **SigNoz query-service's exact API shape is unverified.** The endpoint
  paths and payload shapes in `tools/signoz_client.py`
  (`/api/v1/health`, `/api/v1/services`, `/api/v3/query_range`) are
  written against SigNoz's *documented* v3/v4 query-range API shape as
  best-effort. This has never been exercised against a live SigNoz
  instance. Verify against a real deployment before trusting this in
  production.
- **Never run end-to-end against the real deployment.** This server has
  not been pointed at the actual SigNoz/ClickHouse stack described in
  `charts/observability/values.yaml` - built directly from that chart's
  values and the patterns in `splunk`/`azure_power_ops`/
  `azure_cluster_ops`/`jenkins_ci_ops`, not yet exercised live.
- `CLICKHOUSE_PORT` defaults to `9000` (ClickHouse's native TCP port, to
  match `values.yaml`'s own default), but `clickhouse-connect`'s client
  talks ClickHouse's HTTP interface - operators pointing this at a real
  cluster will likely need to set `CLICKHOUSE_PORT` to that instance's
  HTTP port (commonly `8123`) instead. Verify against the live
  `charts/clickhouse` Service before relying on the default.
- `observability_restart_component` only patches Deployments. `zookeeper`
  runs as a StatefulSet in this chart and is intentionally left out of
  the allow-list - restarting it has different failure-mode implications
  that haven't been designed for here.
