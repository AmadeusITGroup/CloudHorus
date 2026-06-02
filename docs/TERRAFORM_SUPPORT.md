# Terraform Input Support - Implementation Summary

## Overview

CloudHorus now supports Terraform as an offline input path in both the CLI and the Web UI.

This implementation adds Terraform as a new local-template source alongside the existing Bicep flow. The current slice is focused on **AzureRM Terraform resources** and keeps the existing renderer stable by normalizing Terraform input into the same offline `resources[]` shape already used by local template mode.

The preferred Terraform path is now **local source mode**: select a `main.tf` file for each stack, pair it with an aligned `.tfvars` file, and CloudHorus parses the HCL locally with `python-hcl2`. This path is fully offline and does **not** require Azure login or `terraform plan`. Advanced/manual workflows can still use Terraform JSON output from `terraform show -json`.

## What Changed

### 1. New Terraform Builder

CloudHorus now includes [src/core/terraform_builder.py](../src/core/terraform_builder.py), which:

- Loads Terraform `show -json` plan or state files
- Parses Terraform source directories directly from local HCL
- Loads aligned `.tfvars` values for offline source mode
- Walks nested local modules and resolves Terraform references into normalized resource state
- Filters to AzureRM managed resources
- Maps AzureRM resource types into the renderer's current Azure resource type model
- Resolves Terraform configuration references into renderer-friendly `dependsOn` and key network properties

Examples of mappings in the current implementation:

- `azurerm_virtual_network` -> `Microsoft.Network/virtualNetworks`
- `azurerm_subnet` -> `Microsoft.Network/virtualNetworks/subnets`
- `azurerm_linux_web_app` -> `Microsoft.Web/sites`
- `azurerm_private_endpoint` -> `Microsoft.Network/privateEndpoints`
- `azurerm_private_dns_zone` -> `Microsoft.Network/privateDnsZones`

### 2. Provider-Aware Local Template Document

CloudHorus now includes [src/cloudhorus/models/local_template_document.py](../src/cloudhorus/models/local_template_document.py), which introduces a provider-aware local document model.

This is the seam that allows offline inputs to come from more than one source format while still feeding the current renderer contract.

### 3. Generic Local Scope Metadata Parsing

CloudHorus now includes [src/core/local_input_metadata.py](../src/core/local_input_metadata.py), which parses scope metadata for offline inputs.

This supports:

- Existing Bicep `_cloudHorus` metadata
- A generic `scope` object for optional Terraform metadata files
- Synthesized defaults when no explicit scope metadata is provided

Default synthesized values are:

- `tenant`: `cloudhorus-tenant`
- `subscription`: `cloudhorus-subscription`
- `resourceGroup`: `cloudhorus-rg-{N}`

The Web UI Terraform flow currently relies on these synthesized defaults. Explicit scope metadata remains available through the CLI for advanced workflows.

### 4. CLI Support for Terraform Inputs

The CLI in [src/main.py](../src/main.py) now supports these Terraform-related arguments:

- `--terraformRootDirs`: preferred Terraform source mode; one working directory per stack
- `--terraformVarFiles`: optional list of `.tfvars` files aligned to `--terraformRootDirs`
- `--terraformJsonFiles`: advanced/manual mode using pre-generated Terraform JSON
- `--scopeMetadataFiles`: optional list of scope metadata files aligned to `--terraformJsonFiles` or `--terraformRootDirs`

Only one offline input mode can be selected at a time:

- `--bicepFiles`
- `--terraformJsonFiles`
- `--terraformRootDirs`

### 5. Generic Local Template Registration Path

The Azure utility layer in [src/core/azure_cli.py](../src/core/azure_cli.py) now exposes a generic local template registration path:

- `register_local_templates(...)`

This is used by the graph generator so offline modes no longer rely exclusively on inline Bicep rebuild logic.

### 6. Backend Graph Path Updated

The graph pipeline was updated in:

- [src/core/graph_generator.py](../src/core/graph_generator.py)
- [src/core/resource_processor.py](../src/core/resource_processor.py)
- [src/cloudhorus/services/graph_generator_service.py](../src/cloudhorus/services/graph_generator_service.py)

These changes allow local templates to be consumed from the registration layer, which is what makes Terraform integration possible without rewriting the renderer in the same PR.

### 7. Web UI Added

The desktop UI now exposes Terraform as a visible offline mode across [cloudhorus_webui.py](../cloudhorus_webui.py), [webui/index.html](../webui/index.html), and [webui/app.js](../webui/app.js).

The current UI flow:

- lets the user select one `main.tf` file per Terraform stack
- requires an aligned `.tfvars` file list
- builds preview commands with `--terraformRootDirs` and `--terraformVarFiles`
- clearly marks Terraform mode as offline with no Azure login required

Advanced JSON-mode Terraform input remains available through the CLI.

## Current Scope

The current implementation supports:

- Terraform **source input** from local `main.tf` + `.tfvars` files without Azure login
- Terraform **JSON input** via `terraform show -json` for advanced/manual workflows
- AzureRM-focused normalization
- Optional offline scope metadata through separate JSON files
- A visible Terraform mode in the desktop Web UI
- Backward-compatible Bicep multi-template registration

The current implementation does **not** yet do the following:

- Full provider-neutral rendering across AWS/GCP/etc.
- Full regression coverage for all AzureRM resource types
- A complete replacement of the renderer's internal Azure-shaped data model

## Recommended Input Format

### Preferred: Terraform Source Mode

Use local Terraform source mode as the primary input when possible.

Why this is preferred:

- It is fully offline and does not require Azure login
- It does not require `terraform plan` or a pre-generated plan JSON file
- It matches the current desktop Web UI flow
- It reads local HCL, variables, and local modules directly

CloudHorus derives `--terraformRootDirs` from the parent directory of each selected `main.tf` file.

### Advanced/Manual: Terraform JSON

Use Terraform JSON when you already have exported plan or state artifacts and want to feed them directly to the CLI.

Generate a plan JSON like this:

```bash
terraform init
terraform plan -out=tfplan
terraform show -json tfplan > my-plan.json
```

You can also export state as JSON:

```bash
terraform show -json terraform.tfstate > my-state.json
```

## Example 1: Single Terraform Source Stack

### Terraform Command

```bash
python3 src/main.py \
  --terraformRootDirs ./samples/terraform-modular/network-stack \
  --terraformVarFiles ./samples/terraform-modular/network-stack/sample.tfvars \
  --edgeDirection TB \
  --tenantDirection LR \
  --maxSubnetPerline 4 \
  --resourcesEdgeLength 1 \
  --subnetOptimization false \
  --peOptimization true \
  --crossPeOptimization false \
  --resourceGroupsEdgeLengthListBySubscription 4
```

### Notes

- This path is fully offline. No Azure login is required.
- If no scope metadata is supplied, CloudHorus synthesizes `cloudhorus-*` tenant, subscription, and resource-group values.
- For one Terraform input document, provide one value for each per-subscription array flag.

## Example 2: Multiple Terraform Source Stacks

This is the current recommended equivalent of multi-template Bicep mode.

```bash
python3 src/main.py \
  --terraformRootDirs \
    ./samples/terraform-modular/network-stack \
    ./samples/terraform-modular/app-stack \
  --terraformVarFiles \
    ./samples/terraform-modular/network-stack/sample.tfvars \
    ./samples/terraform-modular/app-stack/sample.tfvars \
  --edgeDirection LR \
  --tenantDirection LR \
  --subnetOptimization true false \
  --peOptimization true true \
  --crossPeOptimization false false \
  --resourceGroupsEdgeLengthListBySubscription 5 4
```

Use this when:

- You split networking and application stacks into separate Terraform roots
- You want CloudHorus to render them in separate synthesized resource groups by default
- You want the same file-pairing flow used by the desktop UI

When a Terraform root includes adjacent scope metadata, CloudHorus now picks it up automatically in both CLI and Web UI. Supported conventions are:

- `scope.json` inside the Terraform root
- `cloudhorus.scope.json` inside the Terraform root
- `<stack-directory>.scope.json` inside the Terraform root
- `<stack-directory>.scope.json` in a sibling `metadata/` directory

### Example 2a: Scenario 2 Cross-RG Parity Sample

This bundled source sample mirrors `samples/bicep-scenarios/scenario2-crossrg-*` with the same tenant, subscription, and three resource groups.

```bash
python3 src/main.py \
  --terraformRootDirs \
    ./samples/terraform-scenarios/scenario2-crossrg-network \
    ./samples/terraform-scenarios/scenario2-crossrg-app \
    ./samples/terraform-scenarios/scenario2-crossrg-data \
  --terraformVarFiles \
    ./samples/terraform-scenarios/scenario2-crossrg-network/sample.tfvars \
    ./samples/terraform-scenarios/scenario2-crossrg-app/sample.tfvars \
    ./samples/terraform-scenarios/scenario2-crossrg-data/sample.tfvars \
  --scopeMetadataFiles \
    ./samples/terraform-scenarios/metadata/scenario2-crossrg-network.scope.json \
    ./samples/terraform-scenarios/metadata/scenario2-crossrg-app.scope.json \
    ./samples/terraform-scenarios/metadata/scenario2-crossrg-data.scope.json
```

Use this when you want Terraform source mode to exercise the same cross-RG network, app, private endpoint, SQL, and AKS relationships as the Bicep Scenario 2 QA sample.

## Example 3: Terraform JSON Files

JSON mode remains available for advanced/manual CLI workflows.

```bash
python3 src/main.py \
  --terraformJsonFiles \
    ./examples/terraform/network.plan.json \
    ./examples/terraform/app.plan.json \
  --scopeMetadataFiles \
    ./examples/terraform/network.scope.json \
    ./examples/terraform/app.scope.json \
  --edgeDirection LR \
  --tenantDirection LR \
  --subnetOptimization true false \
  --peOptimization true true \
  --crossPeOptimization false false \
  --resourceGroupsEdgeLengthListBySubscription 5 4
```

### Example Scope Metadata File

```json
{
  "scope": {
    "provider": "azurerm",
    "tenant": "tenant-platform-001",
    "subscription": "sub-platform-001",
    "resourceGroup": "rg-platform-app"
  }
}
```

### Notes

- In offline mode, CLI alignment is based on the resolved local input list order.
- Scope metadata files are optional in both JSON mode and source mode.

### What CloudHorus Does Internally in Source Mode

For each Terraform root directory, CloudHorus will:

1. Parse Terraform HCL locally with `python-hcl2`
2. Load aligned `.tfvars` values
3. Walk local modules and resolve Terraform references into normalized resource state
4. Normalize the result into the existing renderer contract

### Requirements

- No Azure login is required for source mode
- Terraform CLI is not required for source mode
- The Terraform root directory must be valid
- If var files are provided, the count must match the number of root directories
- JSON mode still expects pre-generated Terraform JSON files

## Example 4: Reusing `_cloudHorus` Style Metadata

For backward-compatible metadata style, a scope file can also use `_cloudHorus`:

```json
{
  "_cloudHorus": {
    "tenant": "tenant-app-001",
    "subscription": "sub-app-001",
    "resourceGroup": "rg-app-prod"
  }
}
```

This makes the Terraform scope file compatible with the same metadata parsing approach already used in Bicep parameter files.

## Example 5: What Gets Normalized

Given Terraform resources like these:

```hcl
resource "azurerm_virtual_network" "core" {
  name                = "core-vnet"
  address_space       = ["10.10.0.0/16"]
  resource_group_name = "rg-platform-network"
  location            = "westeurope"
}

resource "azurerm_subnet" "app" {
  name                 = "app"
  resource_group_name  = "rg-platform-network"
  virtual_network_name = azurerm_virtual_network.core.name
  address_prefixes     = ["10.10.1.0/24"]
}

resource "azurerm_linux_web_app" "api" {
  name                = "api-web"
  resource_group_name = "rg-platform-app"
  location            = "westeurope"
  service_plan_id     = azurerm_service_plan.app.id
  virtual_network_subnet_id = azurerm_subnet.app.id
}
```

CloudHorus normalizes them into renderer-friendly Azure resource shapes like:

```json
{
  "resources": [
    {
      "type": "Microsoft.Network/virtualNetworks",
      "name": "core-vnet",
      "properties": {
        "addressSpace": {
          "addressPrefixes": ["10.10.0.0/16"]
        }
      }
    },
    {
      "type": "Microsoft.Network/virtualNetworks/subnets",
      "name": "core-vnet/app",
      "properties": {
        "addressPrefix": "10.10.1.0/24"
      }
    },
    {
      "type": "Microsoft.Web/sites",
      "name": "api-web",
      "properties": {
        "virtualNetworkSubnetId": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'core-vnet', 'app')]"
      },
      "dependsOn": [
        "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'core-vnet', 'app')]"
      ]
    }
  ]
}
```

That is the compatibility layer that lets Terraform participate in the current rendering engine.

## Validation Performed

The Terraform slice was validated with:

```bash
python3 -m pytest tests/test_terraform_builder.py -v --tb=short
python3 -m pytest tests/test_multiple_templates_simple.py::test_multiple_bicep_templates -v --tb=short
python3 src/main.py \
  --terraformRootDirs samples/terraform-modular/network-stack samples/terraform-modular/app-stack \
  --terraformVarFiles samples/terraform-modular/network-stack/sample.tfvars samples/terraform-modular/app-stack/sample.tfvars \
  --edgeDirection TB \
  --tenantDirection LR \
  --maxSubnetPerline 4 \
  --resourcesEdgeLength 1 \
  --rankDebug false \
  --privateDnsZonesOptimization true
python3 -m py_compile \
  src/main.py \
  src/core/local_input_metadata.py \
  src/core/terraform_builder.py \
  src/core/graph_generator.py \
  src/core/resource_processor.py \
  src/core/azure_cli.py \
  src/cloudhorus/models/configuration.py \
  src/cloudhorus/services/graph_generator_service.py \
  cloudhorus_webui.py
```

## Key Files Added or Updated

### New Files

- [src/core/terraform_builder.py](../src/core/terraform_builder.py)
- [src/core/local_input_metadata.py](../src/core/local_input_metadata.py)
- [src/cloudhorus/models/local_template_document.py](../src/cloudhorus/models/local_template_document.py)
- [tests/test_terraform_builder.py](../tests/test_terraform_builder.py)

### Updated Files

- [src/main.py](../src/main.py)
- [src/core/graph_generator.py](../src/core/graph_generator.py)
- [src/core/resource_processor.py](../src/core/resource_processor.py)
- [src/core/azure_cli.py](../src/core/azure_cli.py)
- [src/cloudhorus/models/configuration.py](../src/cloudhorus/models/configuration.py)
- [src/cloudhorus/services/graph_generator_service.py](../src/cloudhorus/services/graph_generator_service.py)
- [cloudhorus_webui.py](../cloudhorus_webui.py)
- [webui/index.html](../webui/index.html)
- [webui/app.js](../webui/app.js)
- [webui/style.css](../webui/style.css)
- [requirements.txt](../requirements.txt)
- [pyproject.toml](../pyproject.toml)
- [setup.py](../setup.py)
- [launcher.sh](../launcher.sh)

## Limitations and Next Steps

### Current Limitations

1. The renderer still expects Azure-shaped resource types internally.
2. Terraform support is currently AzureRM-focused.
3. Not all AzureRM resource types are mapped yet.
4. Full provider-neutral multi-cloud rendering is not complete.
5. Advanced JSON-mode and explicit scope-metadata authoring are currently CLI-first workflows.

### Recommended Next Steps

1. Add more AzureRM resource mappings in `terraform_builder.py`
2. Add dedicated regression coverage for offline source-mode parsing and module resolution
3. Add CLI tests for Terraform input validation and scope metadata alignment
4. Extend the UI if explicit scope-metadata authoring is needed in Terraform mode
5. Continue moving the renderer toward a fully provider-neutral internal model

## Summary

This change does **not** yet fully replace the internal renderer model, but it does establish the first clean Terraform input seam in CloudHorus.

In practical terms, CloudHorus can now:

- Accept local `main.tf` + `.tfvars` as an offline input with no Azure login required
- Continue accepting Terraform JSON as an advanced/manual offline input
- Map AzureRM resources into the existing renderer pipeline
- Use explicit scope metadata when provided, or synthesize default scope values when it is not
- Expose Terraform source mode in the desktop UI
- Preserve existing Bicep offline behavior while sharing the same registration seam

That gives CloudHorus a working Terraform starting point without destabilizing the existing Azure and Bicep flows.