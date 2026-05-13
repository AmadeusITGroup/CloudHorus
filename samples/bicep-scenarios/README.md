# Bicep Scenario Files for CloudHorus QA Testing

These Bicep templates mirror the 10 mock scenarios from `tests/mock_templates/scenarios.py`.
Use them directly in the CloudHorus UI (Bicep Template Mode) or via CLI.

## Scenarios & CLI Commands

### Scenario 1: Baseline — Single RG (VNet + PEs + DNS + Bastion + AppGw)
```bash
python3 src/main.py \
  --bicepFiles samples/bicep-scenarios/scenario1-baseline-network.bicep \
  --parametersFiles samples/bicep-scenarios/scenario1-baseline-network.parameters.json
```

### Scenario 2: Cross-RG — PE in RG_APP → subnet in RG_NETWORK → service in RG_DATA
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

### Scenario 3: Cross-Tenant — PE in tenant-1 → EventHub in tenant-2
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

### Scenario 4: Many PEs — 10 PEs stress test (3 cross-RG, 7 same-RG)
```bash
python3 src/main.py \
  --bicepFiles \
    samples/bicep-scenarios/scenario4-manype-network.bicep \
    samples/bicep-scenarios/scenario4-manype-app.bicep \
  --parametersFiles \
    samples/bicep-scenarios/scenario4-manype-network.parameters.json \
    samples/bicep-scenarios/scenario4-manype-app.parameters.json
```

### Scenario 5: Subnet Optimization — 8 subnets (3 used, 5 empty)
```bash
python3 src/main.py \
  --bicepFiles samples/bicep-scenarios/scenario5-subnet-optimization.bicep \
  --parametersFiles samples/bicep-scenarios/scenario5-subnet-optimization.parameters.json
```
Toggle `--subnetOptimization true` to see empty subnets get hidden.

### Scenario 6: Private DNS Zones — 3 linked + 2 unlinked
```bash
python3 src/main.py \
  --bicepFiles samples/bicep-scenarios/scenario6-dns-zones.bicep \
  --parametersFiles samples/bicep-scenarios/scenario6-dns-zones.parameters.json
```
Toggle `--privateDnsZonesOptimization true/false` to see aggregation behavior.

### Scenario 7: VNet Integration Edge Regression — cross-RG subnet + same-RG PE
```bash
python3 src/main.py \
  --bicepFiles \
    samples/bicep-scenarios/scenario7-vnet-regression-network.bicep \
    samples/bicep-scenarios/scenario7-vnet-regression-app.bicep \
  --parametersFiles \
    samples/bicep-scenarios/scenario7-vnet-regression-network.parameters.json \
    samples/bicep-scenarios/scenario7-vnet-regression-app.parameters.json
```

### Scenario 8: Diverse Resources — PostgreSQL, MySQL, APIM, Redis, Firewall
```bash
python3 src/main.py \
  --bicepFiles samples/bicep-scenarios/scenario8-diverse-resources.bicep \
  --parametersFiles samples/bicep-scenarios/scenario8-diverse-resources.parameters.json
```

### Scenario 9: Ghost Resources — duplicate Web App across 2 RGs
```bash
python3 src/main.py \
  --bicepFiles \
    samples/bicep-scenarios/scenario9-ghost-network.bicep \
    samples/bicep-scenarios/scenario9-ghost-app.bicep \
  --parametersFiles \
    samples/bicep-scenarios/scenario9-ghost-network.parameters.json \
    samples/bicep-scenarios/scenario9-ghost-app.parameters.json
```

### Scenario 10: No VNet — standalone resources only
```bash
python3 src/main.py \
  --bicepFiles samples/bicep-scenarios/scenario10-no-vnet.bicep \
  --parametersFiles samples/bicep-scenarios/scenario10-no-vnet.parameters.json
```

## File Inventory

| Scenario | Bicep Files | What it tests |
|----------|-------------|---------------|
| 1 | `scenario1-baseline-network` | Full single-RG: VNet, 4 subnets, NSG, RT, WebApp, SQL, 2 PEs, DNS, Bastion, AppGw |
| 2 | `scenario2-crossrg-{network,app,data}` | Cross-RG PE subnet + service connection, AKS VNet integration |
| 3 | `scenario3-crosstenant-{network,app,remote}` | Cross-tenant PE dependency (2 tenants, 2 subscriptions) |
| 4 | `scenario4-manype-{network,app}` | 10 PEs on 5 subnets, PE/crossPE optimization stress test |
| 5 | `scenario5-subnet-optimization` | 8 subnets (3 used, 5 empty) for subnetOptimization |
| 6 | `scenario6-dns-zones` | 5 DNS zones (3 linked, 2 unlinked) for privateDnsZonesOptimization |
| 7 | `scenario7-vnet-regression-{network,app}` | VNet integration edge regression (cross-RG subnet, same-RG PE) |
| 8 | `scenario8-diverse-resources` | PostgreSQL, MySQL, APIM, Redis, Firewall subnet handlers |
| 9 | `scenario9-ghost-{network,app}` | Ghost resource deduplication |
| 10 | `scenario10-no-vnet` | Standalone resources without VNet |

## Notes

- These require `az bicep` to be installed for compilation
- Parameters files contain test IDs (test-sub-1, test-rg-network, etc.)
- For real Azure use, replace parameter values with actual subscription/RG IDs
- Multi-RG scenarios: order of `--bicepFiles` must match `--parametersFiles`

## Cross-Tenant / Cross-Subscription Support (`_cloudHorus` Metadata)

Each parameters file includes an optional `_cloudHorus` metadata block that tells
CloudHorus which Azure tenant, subscription, and resource group a template belongs to:

```json
{
  "_cloudHorus": {
    "tenant": "my-tenant-id",
    "subscription": "my-subscription-id",
    "resourceGroup": "my-rg-name"
  },
  "parameters": { ... }
}
```

**Behavior:**
- When `_cloudHorus` is present, CloudHorus uses those values to build the graph hierarchy
  (tenant cluster → subscription cluster → resource group cluster).
- When absent, defaults to `cloudhorus-tenant`, `cloudhorus-subscription`, `cloudhorus-rg-{N}`.
- This enables cross-tenant and cross-subscription Bicep scenarios (e.g., Scenario 3) where
  different templates belong to different tenants — each tenant gets its own visual cluster.
- The `_cloudHorus` key uses an underscore prefix, which ARM ignores, so parameter files
  remain valid for Azure deployments.

