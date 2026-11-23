# Kubernetes Ops MCP Server

Direct kubectl-style control over a customer's AKS cluster
(`kendra-<customer>-aks`), provisioned by
[`infra`](https://github.com/Kendralabs/infra)'s `envs/azure/<customer>`
Terraform/OpenTofu. Covers the workload-level actions that the ArgoCD
agent's own Application/resource sync API ([`argocd`](../argocd))
doesn't: restarting a Deployment rollout, scaling, tailing pod logs,
deleting a stuck pod, and describing events/pod status.

Built on the same registry/runner split as `azure_cluster_ops` and
`azure_power_ops`, one step further: `tools/registry.py` resolves a
customer name or `"all"` to AKS cluster(s), and `tools/k8s_runner.py`
materializes a per-call kubeconfig (`az aks get-credentials`, after a lazy
service-principal login) and hands it to the official `kubernetes` Python
client - never a raw `kubectl`/shell passthrough.

## Why this is separate from `argocd`

The `argocd` MCP server reports and acts on an **Application's** sync and
health state (`api_v1_applications_name_sync`, resource tree, events) -
GitOps-level operations. It has no tool for "restart this one Deployment
right now", "scale this Deployment to N replicas outside of Git", "tail
this pod's logs", or "delete this stuck pod" - all genuinely
cluster-level, imperative actions that fall outside GitOps reconciliation.
This server exists to cover exactly that gap, with its own tool surface
and its own RBAC scope (see below) rather than widening ArgoCD's.

## Registry is discovered, not hand-maintained

`tools/registry.py` reads `KUBERNETES_OPS_INFRA_REPO_PATH`'s `envs/azure/`
directory at call time and includes a customer only if its directory has
both `terraform.tfvars` (names the customer) and `backend.hcl` (actually
`tofu apply`'d). `customer-template` itself is always skipped. If no
customer environment has been applied yet, the registry is simply empty -
the expected state today, not an error.

Cluster name follows `envs/azure/customer-template/main.tf`'s own
convention (also documented in `azure_power_ops/README.md`): AKS cluster
`kendra-<customer>-aks` in resource group `kendra-<customer>-rg`.

## Tool surface

### Tier 1 - read-only pod visibility (always on, no approval)

- `k8s_list_pods(scope, namespace)` - list pods (phase, readiness, restart
  counts, per-container state) in a namespace, for a customer or `"all"`.
- `k8s_get_pod_status(scope, namespace, pod_name)` - one pod's detailed
  status.
- `k8s_get_pod_logs(scope, namespace, pod_name, container, tail_lines)` -
  tail a pod's logs (default 200 lines).
- `k8s_describe_events(scope, namespace, limit)` - recent namespace events,
  most recent first (default 50) - the `kubectl describe`/`kubectl get
  events` equivalent for diagnosing pending/crashing/unschedulable pods.

### Tier 2 - read-only deployment visibility

- `k8s_get_deployment_status(scope, namespace, deployment_name)` - desired
  / ready / available / updated replica counts and rollout conditions.

### Tier 3 - write (confirm=True required, same discipline as
`azure_power_ops/tools/power.py`)

- `k8s_restart_deployment(scope, namespace, deployment_name, confirm)` -
  the `kubectl rollout restart` equivalent: patches the pod template's
  `kubectl.kubernetes.io/restartedAt` annotation to force a fresh
  ReplicaSet.
- `k8s_scale_deployment(scope, namespace, deployment_name, replicas,
  confirm)` - the `kubectl scale` equivalent.
- `k8s_delete_pod(scope, namespace, pod_name, confirm)` - the `kubectl
  delete pod` equivalent, typically used to unstick a pod a controller will
  immediately recreate.

Every write tool defaults `confirm=False` and short-circuits with a clear
`"...Set confirm=True to proceed."` error instead of acting when it's
False. Unlike the read-only tools, the write tools never accept
`scope="all"` - they always resolve to exactly one customer's cluster, so a
single restart/scale/delete can never silently fan out across every
registered customer.

A scope that doesn't resolve to a registered customer is refused outright -
the registry, not the request, is the safety boundary.

## Deliberately out of scope

- **Anything ArgoCD already owns** - Application sync/rollback, GitOps
  drift detection. Use the `argocd` agent for that; this server only
  touches live workload objects directly.
- **Namespace/RBAC/CRD management** - creating namespaces, RoleBindings, or
  custom resources. Only pods and Deployments are in scope for this first
  pass.
- **Node-level actions** (drain, cordon, node pool scaling) - that's
  `azure_cluster_ops`'s job.
- **Raw kubectl/shell passthrough** - every action is its own typed tool
  with a fixed parameter shape, never an arbitrary command string.

## Authentication

Reuses the same Azure service-principal credentials `azure_cluster_ops` and
`azure_power_ops` already use, to run `az aks get-credentials`:

| Variable | Description |
|---|---|
| `ARM_CLIENT_ID` | Service principal client ID |
| `ARM_CLIENT_SECRET` | Service principal secret |
| `ARM_TENANT_ID` | Azure AD tenant ID |
| `ARM_SUBSCRIPTION_ID` | Target subscription |

Scope this service principal to **Reader** (for `az aks get-credentials`
and cluster discovery) plus the specific Kubernetes RBAC verbs the tools
above need on the target namespace(s) - `get`/`list`/`watch` on
`pods`/`events`, `get`/`watch` on `pods/log`, `get`/`patch` on
`deployments`/`deployments/scale`, and `delete` on `pods` - granted via a
namespaced RoleBinding to this service principal's cluster identity.
**Never cluster-admin.** The service principal's Azure RBAC role
(`Azure Kubernetes Service Cluster User Role`) only grants it a kubeconfig;
the Kubernetes RBAC RoleBinding above is what actually limits what it can
do once inside the cluster.

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `KUBERNETES_OPS_INFRA_REPO_PATH` | Local path to the infra repo checkout to read `envs/azure/` from | (required to discover any environment) |
| `ARM_CLIENT_ID` / `ARM_CLIENT_SECRET` / `ARM_TENANT_ID` / `ARM_SUBSCRIPTION_ID` | Service principal credentials | (required for any action) |
| `KUBERNETES_OPS_AZ_LOGIN_TIMEOUT` | Per-`az`-command timeout (seconds), for login and `get-credentials` | `120` |
| `KUBERNETES_OPS_TIMEOUT` | Per-Kubernetes-API-call timeout (seconds) | `60` |
| `MCP_MODE` | `STDIO` or `http` | `STDIO` |
| `MCP_HOST` | Bind host in `http` mode | `localhost` |
| `MCP_PORT` | Bind port in `http` mode | `8000` |
| `SERVER_NAME` | Display name for the MCP server | `KubernetesOps` |

## RBAC note

Run with its own `MCP_PDP_SCOPE` (see `mcp_agent_auth.middleware`),
distinct from `azure_cluster_ops`, `azure_power_ops`, and `argocd` - this
server's write actions (restart, scale, delete pod) act directly on live
workloads inside a cluster, a different blast radius than node pool
scaling, whole-environment power on/off, or an Application sync.

## Known gaps

- No live customer environment has actually been exercised end-to-end by
  this server yet - only against an empty registry and mocked Kubernetes
  API responses in `tests/`. The `az aks get-credentials` +
  `kubernetes`-client path has not been run against a real AKS cluster.
- `k8s_get_pod_logs` only tails the current container's log stream
  (`tail_lines`), not previous-container logs after a crash
  (`previous=true` in `kubectl logs -p`) - add a dedicated parameter if
  that's needed.
- No `kubectl exec` / port-forward equivalent - deliberately left out as a
  much larger blast radius than the read/restart/scale/delete surface
  here.
