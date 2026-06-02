# Terraform Modular Sample

This sample provides a small AzureRM-focused Terraform layout that matches the current CloudHorus Terraform support.

It includes:

- Terraform source code split into two root stacks
- Reusable Terraform modules
- Prebuilt Terraform `show -json` fixtures for offline testing
- Scope metadata files aligned to the JSON fixtures

## Structure

```text
samples/terraform-modular/
├── modules/
│   ├── app/
│   └── network/
├── network-stack/
│   ├── main.tf
│   ├── variables.tf
│   ├── versions.tf
│   └── sample.tfvars
├── app-stack/
│   ├── main.tf
│   ├── variables.tf
│   ├── versions.tf
│   └── sample.tfvars
└── generated/
    ├── network.plan.json
    ├── network.scope.json
    ├── app.plan.json
    └── app.scope.json
```

## What This Sample Models

### Network Stack

- `azurerm_virtual_network`
- `azurerm_subnet`
- `azurerm_network_security_group`

### App Stack

- `azurerm_service_plan`
- `azurerm_linux_web_app`
- `azurerm_private_dns_zone`
- `azurerm_private_dns_zone_virtual_network_link`
- `azurerm_private_endpoint`

The app stack is intentionally separated from the network stack so CloudHorus can render two resource groups in the same subscription.

## Fastest Offline Test

Use the prebuilt plan JSON files.

```bash
python3 src/main.py \
  --terraformJsonFiles \
    samples/terraform-modular/generated/network.plan.json \
    samples/terraform-modular/generated/app.plan.json \
  --scopeMetadataFiles \
    samples/terraform-modular/generated/network.scope.json \
    samples/terraform-modular/generated/app.scope.json \
  --edgeDirection TB \
  --tenantDirection LR \
  --subnetOptimization false false \
  --peOptimization true true \
  --crossPeOptimization false false \
  --resourceGroupsEdgeLengthListBySubscription 4 4
```

## Terraform Source Test

If you want to test the raw Terraform source path, use the stack directories directly.

```bash
python3 src/main.py \
  --terraformRootDirs \
    samples/terraform-modular/network-stack \
    samples/terraform-modular/app-stack \
  --terraformVarFiles \
    samples/terraform-modular/network-stack/sample.tfvars \
    samples/terraform-modular/app-stack/sample.tfvars \
  --scopeMetadataFiles \
    samples/terraform-modular/generated/network.scope.json \
    samples/terraform-modular/generated/app.scope.json \
  --edgeDirection TB \
  --tenantDirection LR \
  --subnetOptimization false false \
  --peOptimization true true \
  --crossPeOptimization false false \
  --resourceGroupsEdgeLengthListBySubscription 4 4
```

## Notes

- The JSON files under `generated/` are hand-curated sample fixtures designed for CloudHorus testing.
- The source roots under `network-stack/` and `app-stack/` are included so you can inspect or extend the Terraform structure itself.
- The current desktop Web UI backend understands Terraform arguments, but the visible HTML/JS mode selector still needs a Terraform frontend mode before these can be picked directly from the UI.
- Until the UI frontend is exposed, use the CLI commands above.