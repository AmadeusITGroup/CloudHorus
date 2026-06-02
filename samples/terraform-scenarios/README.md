# Terraform Scenario Samples

This directory contains source-first Terraform scenarios that mirror the Bicep QA scenarios used by CloudHorus.

## Scenario 2: Cross-RG Parity

This Terraform sample mirrors the topology from `samples/bicep-scenarios/scenario2-crossrg-*`:

- `test-rg-network`: VNet with `pe_subnet`, `webapp_subnet`, `db_subnet`, and `aks_subnet`
- `test-rg-app`: App Service plan, Web App with cross-RG VNet integration, SQL private endpoint, and AKS with cross-RG subnet integration
- `test-rg-data`: Azure SQL server and storage account

Use it with CloudHorus in offline Terraform source mode:

```bash
python3 src/main.py \
  --terraformRootDirs \
    samples/terraform-scenarios/scenario2-crossrg-network \
    samples/terraform-scenarios/scenario2-crossrg-app \
    samples/terraform-scenarios/scenario2-crossrg-data \
  --terraformVarFiles \
    samples/terraform-scenarios/scenario2-crossrg-network/sample.tfvars \
    samples/terraform-scenarios/scenario2-crossrg-app/sample.tfvars \
    samples/terraform-scenarios/scenario2-crossrg-data/sample.tfvars \
  --scopeMetadataFiles \
    samples/terraform-scenarios/metadata/scenario2-crossrg-network.scope.json \
    samples/terraform-scenarios/metadata/scenario2-crossrg-app.scope.json \
    samples/terraform-scenarios/metadata/scenario2-crossrg-data.scope.json
```

Notes:

- `terraform init` is not required for CloudHorus offline parsing.
- If you do run Terraform locally, do not commit `.terraform/` or `.terraform.lock.hcl` runtime artifacts from these sample folders.