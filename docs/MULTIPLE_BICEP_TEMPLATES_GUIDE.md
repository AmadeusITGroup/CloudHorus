# Multiple Bicep Templates Support - User Guide

## Overview

The Azure CLI utility has been enhanced to support multiple Bicep templates with automatic mapping of resource groups to subscriptions and tenants. This allows you to analyze infrastructure across multiple environments (development, staging, production) with proper isolation and mapping.

## Key Features

### 1. Template Registration
- Register multiple Bicep templates (converted to ARM JSON) with their corresponding mappings
- Automatic discovery of tenant IDs from subscriptions
- Quick lookup mappings for efficient queries

### 2. Resource Group to Subscription Mapping
- Each resource group is mapped to a specific subscription
- Automatic validation ensures consistency
- Quick lookup for resource group existence checks

### 3. Subscription to Tenant Mapping
- Subscriptions are mapped to their respective tenants
- Support for cross-tenant scenarios
- Automatic tenant discovery when not provided

### 4. Enhanced Function Behavior
- All existing Azure CLI functions now support multiple template mode
- Backwards compatibility maintained for single template usage
- Intelligent fallback between template and portal modes

## Usage Guide

### Step 1: Prepare Your Templates

Convert your Bicep templates to ARM JSON format:

```bash
# For each Bicep template
az bicep build --file prod-infrastructure.bicep --outfile prod-template.json
az bicep build --file dev-infrastructure.bicep --outfile dev-template.json
az bicep build --file shared-services.bicep --outfile shared-template.json
```

### Step 2: Load Template Data

```python
import json
from src.core.azure_cli import AzureUtility

# Load template data
with open('prod-template.json', 'r') as f:
    prod_template = json.load(f)

with open('dev-template.json', 'r') as f:
    dev_template = json.load(f)

with open('shared-template.json', 'r') as f:
    shared_template = json.load(f)

templates_data = [prod_template, dev_template, shared_template]
```

### Step 3: Define Mappings

```python
# Define corresponding mappings (by index)
resource_groups = ["rg-prod-001", "rg-dev-001", "rg-shared-services"]
subscriptions = ["sub-prod-123", "sub-dev-456", "sub-shared-789"]

# Optional: Specify tenants (will be auto-discovered if not provided)
tenants = ["tenant-corporate", "tenant-corporate", "tenant-shared"]
```

### Step 4: Register Templates

```python
az = AzureUtility()

# Register multiple templates with mappings
success = az.register_multiple_bicep_templates(
    templates_data=templates_data,
    resource_groups=resource_groups,
    subscriptions=subscriptions,
    tenants=tenants  # Optional
)

if success:
    print("Templates registered successfully!")
else:
    print("Failed to register templates")
```

### Step 5: Use Enhanced Functions

Once templates are registered, all Azure CLI functions automatically support multiple template mode:

```python
# Check resource group existence with automatic mapping
rg_exists = az.is_resource_group_in_subscription(
    resource_group="rg-prod-001",
    subscription_id="sub-prod-123",
    use_local_template=True
)

# Get DNS zones for a specific resource group
dns_zones = az.get_private_dns_zones(
    resource_group="rg-prod-001",
    subscription_id="sub-prod-123",  # Will be validated against mapping
    use_local_template=True
)

# Check VNet DNS zone links across multiple resource groups
linked_zones = az.is_vnet_linked_to_private_dns_zone(
    vnet_name="prod-vnet",
    resource_groups=["rg-prod-001", "rg-shared-services"],
    subscription_id="sub-prod-123",
    use_local_template=True
)

# Get Bastion Host for a VNet
bastion_name = az.get_bastion_host_name(
    vnet_name="prod-vnet",
    resource_group="rg-prod-001",
    subscription_id="sub-prod-123",
    use_local_template=True
)
```

## New Helper Functions

### Mapping Queries

```python
# Get subscription for a resource group
subscription_id = az.get_subscription_for_resource_group("rg-prod-001")

# Get tenant for a subscription
tenant_id = az.get_tenant_for_subscription("sub-prod-123")

# Get template data for a resource group
template_data = az.get_template_data_for_resource_group("rg-prod-001")
```

### Registry Information

```python
# Check if multiple templates are registered
using_multiple = az.is_using_multiple_templates()

# Get all registered entities
all_rgs = az.get_all_registered_resource_groups()
all_subs = az.get_all_registered_subscriptions()
all_tenants = az.get_all_registered_tenants()
```

## Example: Multi-Environment Analysis

```python
def analyze_infrastructure():
    az = AzureUtility()

    # Register templates for prod, dev, and shared environments
    az.register_multiple_bicep_templates(
        templates_data=[prod_template, dev_template, shared_template],
        resource_groups=["rg-prod", "rg-dev", "rg-shared"],
        subscriptions=["sub-prod", "sub-dev", "sub-shared"],
        tenants=["tenant-corp", "tenant-corp", "tenant-shared"]
    )

    # Analyze each environment
    for rg in az.get_all_registered_resource_groups():
        subscription = az.get_subscription_for_resource_group(rg)
        tenant = az.get_tenant_for_subscription(subscription)

        print(f"Analyzing {rg} (Subscription: {subscription}, Tenant: {tenant})")

        # Get DNS zones
        dns_zones = az.get_private_dns_zones(rg, subscription, use_local_template=True)
        print(f"  DNS Zones: {[zone['name'] for zone in dns_zones]}")

        # Check for DNS zones without VNets
        isolated_zones = az.get_private_dns_zones_without_vnets(rg, subscription, use_local_template=True)
        if isolated_zones:
            print(f"  Isolated DNS Zones: {isolated_zones}")

        print()
```

## Migration from Single Template

### Before (Single Template)
```python
# Old way - single template
dns_zones = az.get_private_dns_zones(
    resource_group="my-rg",
    subscription_id="my-sub",
    use_local_template=True,
    template_data=single_template
)
```

### After (Multiple Templates)
```python
# New way - automatic template lookup
az.register_multiple_bicep_templates(
    templates_data=[template1, template2],
    resource_groups=["rg1", "rg2"],
    subscriptions=["sub1", "sub2"]
)

# Same function call, but now supports multiple templates
dns_zones = az.get_private_dns_zones(
    resource_group="rg1",
    subscription_id="sub1",
    use_local_template=True
    # No need to pass template_data - automatically resolved
)
```

## Best Practices

### 1. Consistent Naming Conventions
```python
# Use consistent naming patterns
resource_groups = [
    "rg-myapp-prod-001",
    "rg-myapp-dev-001",
    "rg-myapp-staging-001"
]

subscriptions = [
    "sub-myapp-prod",
    "sub-myapp-dev",
    "sub-myapp-staging"
]
```

### 2. Environment Separation
```python
# Separate environments clearly
prod_resources = ["rg-prod-network", "rg-prod-compute", "rg-prod-data"]
dev_resources = ["rg-dev-network", "rg-dev-compute", "rg-dev-data"]

# Register with appropriate mappings
az.register_multiple_bicep_templates(
    templates_data=[prod_template, dev_template],
    resource_groups=prod_resources + dev_resources,
    subscriptions=["sub-prod"] * 3 + ["sub-dev"] * 3
)
```

### 3. Error Handling
```python
# Always check registration success
if not az.register_multiple_bicep_templates(...):
    print("Failed to register templates")
    # Handle error appropriately
    return

# Validate mappings
for rg in resource_groups:
    if not az.get_subscription_for_resource_group(rg):
        print(f"Warning: No subscription mapping for {rg}")
```

### 4. Validation
```python
# Validate all mappings are correct
for rg, expected_sub in zip(resource_groups, subscriptions):
    actual_sub = az.get_subscription_for_resource_group(rg)
    if actual_sub != expected_sub:
        print(f"Mapping error: {rg} -> {actual_sub} (expected: {expected_sub})")
```

## Backwards Compatibility

The enhanced functions maintain full backwards compatibility:

- **Single template mode**: Pass `template_data` parameter as before
- **Portal mode**: Use `use_local_template=False` for live Azure queries
- **Multiple template mode**: Register templates first, then use `use_local_template=True`

## Error Scenarios

### Template Not Found
```python
# If resource group not in registered mappings
zones = az.get_private_dns_zones("unknown-rg", "sub-123", use_local_template=True)
# Returns: [] with warning message
```

### Subscription Mismatch
```python
# If subscription doesn't match resource group mapping
exists = az.is_resource_group_in_subscription("rg-prod", "wrong-sub", use_local_template=True)
# Returns: False with debug message
```

### No Templates Registered
```python
# If no templates registered but multiple template mode requested
zones = az.get_private_dns_zones("rg-test", "sub-test", use_local_template=True)
# Falls back to warning and returns empty result
```

## Performance Benefits

1. **Fast Lookups**: O(1) resource group to subscription mapping
2. **No Network Calls**: Template analysis is local and instant
3. **Efficient Memory Usage**: Templates loaded once and reused
4. **Batch Processing**: Analyze multiple environments efficiently

## Integration with Graph Generators

```python
def generate_multi_environment_graph():
    az = AzureUtility()

    # Register all environments
    az.register_multiple_bicep_templates(...)

    # Generate graph for each environment
    all_graphs = {}
    for rg in az.get_all_registered_resource_groups():
        subscription = az.get_subscription_for_resource_group(rg)

        # Use enhanced functions with automatic template resolution
        graph_data = analyze_environment(az, rg, subscription)
        all_graphs[rg] = graph_data

    return all_graphs
```

This enhancement provides a robust foundation for analyzing complex multi-environment Azure infrastructures while maintaining the simplicity and backwards compatibility of the existing API.

