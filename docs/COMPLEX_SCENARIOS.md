# CloudHorus — Complex Scenarios Guide

This guide walks through the two scenarios that operators most commonly get wrong:

1. **Cross-tenant visualization** — resources in tenant A consumed by resources in tenant B.
2. **Pre-deployment visualization via Bicep templates** — diagram an architecture *before*
   anything is deployed to Azure.

Both modes rely on the same downstream rendering engine, so the resulting diagrams are
identical in style and detail to live-mode output.

---

## 1. Mode Selection at a Glance

| You want to… | Mode | Auth required? | Required CLI args |
|--------------|------|----------------|-------------------|
| Diagram resources that already exist in Azure | **Live** | Yes (`Reader` on each scope) | `--tenants`, `--subscriptions`, `--resourcegroups` |
| Diagram a future architecture from `.bicep` files | **Bicep** | **No** — fully offline | `--bicepFiles`, `--parametersFiles` |

Bicep mode is **completely offline** — it never authenticates and never calls Azure. It is
the recommended choice for design reviews, pre-merge PR checks, and air-gapped environments.

---

## 2. Live Mode — Cross-Tenant Scenarios

### 2.1 What "cross-tenant" means in CloudHorus
A cross-tenant architecture is one where:

- A resource in **tenant A** (e.g. a Private Endpoint, NIC, or peered VNet) references a
  resource in **tenant B** (e.g. an Event Hub namespace, a Key Vault, a hub VNet).
- Each tenant has its own Azure AD directory; **a single user/SP is rarely a member of
  both**, so two separate identity grants are required.

CloudHorus accepts **multiple tenants in a single invocation** and will iterate them,
authenticating once per tenant before discovering resources.

### 2.2 Permission requirements
For each tenant in the visualization, the CloudHorus identity needs:

- **`Reader` role** on every subscription you list under that tenant.
- A valid **token issued by that tenant's directory** (CloudHorus handles the per-tenant
  token acquisition automatically).

If your CI/CD runs as a service principal:

- The SP must be **a guest user or a separate SP registered in each tenant**.
- Each tenant's directory must have granted that SP `Reader` on the relevant scope.

### 2.3 Argument alignment rules
For live mode the three list arguments are aligned **positionally**:

```
--tenants         <T1>   <T2>   <T3>
--subscriptions   <S1a>  <S2a>  <S3a>
--resourcegroups  <R1a>  <R2a>  <R3a>
```

Each column describes one (tenant, subscription, resource group) tuple. Common pitfalls:

- ⚠️ **Wrong order** — putting tenant 2's subscription under tenant 1 will **not** raise
  an error. CloudHorus resolves each subscription's *home tenant* (via the ARM
  `subscriptions` API) and **silently skips** any subscription whose home tenant doesn't
  match the column it's listed under. The diagram is generated, but it will be missing
  the resources you expected. Watch the logs for lines like:
  `Subscription <name> is accessible from <tenantA> but its home tenant is <tenantB> — skipping (guest access)`.
- ❌ **Mismatched lengths** — if you have 3 tenants and only 2 subscriptions, CloudHorus
  cannot pair them. Repeat the subscription/RG you want to reuse.
- ✅ **Repeated values are OK** — the same subscription can appear twice if you want to
  visualize two RGs from it.
- ✅ **Guest-access subscriptions are filtered automatically** — a subscription you can
  *see* from tenant A as a guest but that *belongs to* tenant B will only be rendered
  under tenant B (in the column that lists tenant B). This prevents duplicate rendering.

### 2.4 Example — two tenants, one RG each

```bash
python3 src/main.py \
  --tenants \
    11111111-1111-1111-1111-111111111111 \
    22222222-2222-2222-2222-222222222222 \
  --subscriptions \
    aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa \
    bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb \
  --resourcegroups \
    rg-tenant1-app \
    rg-tenant2-data
```

If running in CI/CD, add `--authMethod environment` (the runner has already done
`azure/login` for both tenants via separate steps, or uses an SP that is a guest in both):

```bash
python3 src/main.py --authMethod environment \
  --tenants <T1> <T2> \
  --subscriptions <S1> <S2> \
  --resourcegroups <R1> <R2>
```

### 2.5 Cross-tenant device-code flow
When `--authMethod device-code` is used with multiple tenants, CloudHorus prompts
**once per tenant**. The browser must allow the operator to switch directories. Pre-clear
your browser session for `login.microsoftonline.com` if you encounter cached
single-tenant tokens.

### 2.6 Optimization flags for cross-tenant graphs
Cross-tenant diagrams tend to be large because each tenant brings its own set of subnets,
NSGs, and DNS zones. Recommended starting flags:

```
--tenantDirection LR              # tenants side-by-side
--edgeDirection TB                # resources stacked top-down within a tenant
--crossPeOptimization true true   # one bool per subscription — hide PEs that have no
                                  #   cross-tenant linkage to declutter
--privateDnsZonesOptimization true
```

Tune `--resourceGroupsEdgeLengthListBySubscription` upward (4–6) if your diagram has
visible edge crossings between tenants.

---

## 3. Bicep Mode — Pre-Deployment Visualization

### 3.1 The use case
You have written `.bicep` files for a new landing zone, multi-tier app, or hub-and-spoke
network. **Before deploying**, you want a diagram that shows exactly what will exist and
how the resources will connect — same notation as a live-mode diagram, but no Azure
subscription needed.

### 3.2 No Azure access required
Bicep mode runs entirely on local files:

- ✅ No `az login`.
- ✅ No `--authMethod` argument.
- ✅ Works on an air-gapped workstation.
- ✅ Works in a PR check job with no Azure credentials.

### 3.3 The `_cloudHorus` metadata block
Each parameters file must declare which **virtual** tenant / subscription / resource group
the template represents. CloudHorus uses this only for diagram grouping — these IDs are
never sent anywhere.

```jsonc
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",

  "_cloudHorus": {
    "tenant":        "design-tenant-1",
    "subscription":  "design-sub-prod",
    "resourceGroup": "rg-prod-network"
  },

  "parameters": {
    "location": { "value": "westeurope" }
  }
}
```

The values are **arbitrary strings** — pick something human-readable. They become labels
in the resulting diagram.

### 3.4 Argument alignment rules (Bicep mode)
The two lists must have the **same length and the same order**:

```
--bicepFiles        net.bicep   app.bicep   data.bicep
--parametersFiles   net.json    app.json    data.json
```

Each column = one template + its parameters. CloudHorus parses the `_cloudHorus` block in
each parameters file to assign that template to the correct tenant/subscription/RG bucket.

### 3.5 Example — single-tenant, multi-RG (cross-RG references)

```bash
python3 src/main.py \
  --bicepFiles \
    samples/bicep-scenarios/scenario2-crossrg-network.bicep \
    samples/bicep-scenarios/scenario2-crossrg-app.bicep \
    samples/bicep-scenarios/scenario2-crossrg-data.bicep \
  --parametersFiles \
    samples/bicep-scenarios/scenario2-crossrg-network.parameters.json \
    samples/bicep-scenarios/scenario2-crossrg-app.parameters.json \
    samples/bicep-scenarios/scenario2-crossrg-data.parameters.json
```

The parameters files share the same `tenant` and `subscription` but each declares a
different `resourceGroup`, so CloudHorus shows three RGs side-by-side with edges crossing
between them.

### 3.6 Example — cross-tenant, pre-deployment

This is the most powerful use case: visualize a future hub-and-spoke design that spans
two tenants, before any deployment happens.

```bash
python3 src/main.py \
  --bicepFiles \
    samples/bicep-scenarios/scenario3-crosstenant-network.bicep \
    samples/bicep-scenarios/scenario3-crosstenant-app.bicep \
    samples/bicep-scenarios/scenario3-crosstenant-remote.bicep \
  --parametersFiles \
    samples/bicep-scenarios/scenario3-crosstenant-network.parameters.json \
    samples/bicep-scenarios/scenario3-crosstenant-app.parameters.json \
    samples/bicep-scenarios/scenario3-crosstenant-remote.parameters.json
```

The three parameters files declare two distinct tenants in their `_cloudHorus` blocks
(e.g. `test-tenant-1` for network/app, `test-tenant-2` for remote). CloudHorus groups
resources by those labels and renders the cross-tenant edges automatically — same look
as a live cross-tenant scan.

### 3.7 Cross-tenant Bicep references — how to express them
A Bicep template in tenant A can declare a dependency on a resource in tenant B by:

- Using an **`existing` resource declaration** with the full ARM resource ID of the
  remote resource (the ID format encodes the subscription, which CloudHorus traces back
  to its tenant via the `_cloudHorus` metadata of the *other* template in the run).
- Wiring that `existing` reference into a Private Endpoint or VNet peering.

Examples are in the `scenario3-*.bicep` files. The diagram generator follows
`existing { ... id: '...' }` references and draws cross-tenant edges.

---

## 4. Validating Before You Deploy — Recommended Workflow

A repeatable pre-deployment review looks like this:

```bash
# 1. Lint / build the Bicep so you know it compiles
az bicep build --file infrastructure/main.bicep

# 2. Generate the CloudHorus diagram from the same files
python3 src/main.py \
  --bicepFiles infrastructure/main.bicep \
  --parametersFiles infrastructure/main.parameters.json

# 3. Open the resulting azure_resources_*.png in your PR description
```

Hook this into a PR check by running CloudHorus in a CI job (no Azure credentials needed
in Bicep mode — see [SECURITY.md §4](SECURITY.md#4-cicd-integration-quick-reference)) and
uploading the PNG as an artifact.

---

## 5. Common Pitfalls & Fixes

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `SubscriptionNotFound` in live mode | The subscription ID is wrong, or the identity has zero access (not even guest) | Verify the ID and check that the CloudHorus identity has at least `Reader` somewhere in that subscription. |
| Diagram missing resources from one tenant | Subscription listed under the wrong tenant column — silently skipped because home tenant mismatched | Re-align `--tenants` / `--subscriptions` positionally. Check logs for `home tenant is ... — skipping (guest access)`. |
| Bicep run produces an empty diagram | Missing `_cloudHorus` block in parameters file | Add the block (see §3.3). |
| Cross-tenant edges missing | Both templates list the same `tenant` value | Use distinct tenant labels in each parameters file. |
| CI/CD job hangs on auth | `--authMethod device-code` left as default in pipeline | Switch to `environment` or `service-principal`. |
| `PermissionError: ReadOnlyPolicy` raised | Code path attempted a write API | This is by design — file an issue if the call should be read-only. |
| Diagram unreadable in cross-tenant scan | Default layout too dense | Use `--tenantDirection LR`, raise `--resourceGroupsEdgeLengthListBySubscription`, enable `--crossPeOptimization`. |

---

## 6. References

- [SECURITY.md](SECURITY.md) — trust, permissions, execution model
- [BICEP_SUPPORT.md](BICEP_SUPPORT.md) — full Bicep mode reference
- [MULTIPLE_BICEP_TEMPLATES_GUIDE.md](MULTIPLE_BICEP_TEMPLATES_GUIDE.md) — multi-template
  mechanics in detail
- [samples/bicep-scenarios/README.md](../samples/bicep-scenarios/README.md) — runnable
  example commands for all 10 reference scenarios
