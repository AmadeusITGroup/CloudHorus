# Bicep Template Support - Implementation Guide

## Overview

The Azure Resource Visualizer now supports building Bicep templates with parameters as an alternative to exporting ARM templates from Azure subscriptions. This feature allows you to visualize Azure resources defined in Bicep templates without needing to deploy them to Azure first.

## New Features Added

### 1. Command Line Arguments

Three new command-line arguments have been added to `main.py`:

- `--useLocalTemplate` (boolean, default: False): Enable Bicep template mode
- `--bicepFile` (string): Path to the Bicep template file
- `--parametersFile` (string): Path to the parameters file (JSON format)

### 2. Bicep Builder Module

A new module `src/core/bicep_builder.py` provides:

- **BicepTemplateBuilder class**: Main class for building Bicep templates
- **Template validation**: Validates Bicep files, parameters files, and Azure CLI availability
- **Parameter resolution**: Resolves ARM template parameter references to actual values
- **ARM template generation**: Converts Bicep to ARM template with populated values

### 3. Graph Generator Integration

Modified `src/core/graph_generator.py` to:

- Accept Bicep template parameters
- Conditionally handle Azure-specific function calls
- Support both Azure export and Bicep build modes
- Gracefully handle missing Azure connectivity in Bicep mode

## Usage Examples

### Basic Bicep Mode Usage

```bash
python3 src/main.py \
  --useLocalTemplate True \
  --bicepFile "path/to/template.bicep" \
  --parametersFile "path/to/parameters.json" \
  --subscriptions "local-bicep-subscription" \
  --tenants "local-bicep-tenant" \
  --resourcegroups "bicep-template" \
  --edgeDirection TB
```

### Traditional Azure Mode (unchanged)

```bash
python3 src/main.py \
  --subscriptions "subscription-id-1" "subscription-id-2" \
  --resourcegroups "rg-1" "rg-2" \
  --tenants "tenant-id-1" \
  --edgeDirection TB
```

## Bicep Template Requirements

### Bicep File Format
- Must be a valid `.bicep` file
- Should contain Azure resources with proper dependencies
- Can use parameters and ARM template functions

### Parameters File Format
```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "parameterName": {
      "value": "parameterValue"
    }
  }
}
```

## Implementation Details

### Bicep to ARM Conversion Process

1. **Validation**: Check Bicep CLI availability and file validity
2. **Build**: Convert Bicep template to ARM template using `az bicep build`
3. **Parameter Resolution**: Replace parameter references with actual values
4. **Template Generation**: Create ARM template with populated values (similar to `export_resource_group_template` with `SkipAllParameterization`)

### Azure Function Handling

In Bicep mode, Azure-specific functions are handled as follows:

- `get_subscription_name()`: Returns "Bicep Template"
- `get_resource_group_location()`: Returns "Bicep Template"
- `get_pe_subnet()`: Uses resource name directly
- `get_private_dns_zones_without_vnets()`: Returns empty list
- `is_vnet_linked_to_private_dns_zone()`: Returns empty list
- `get_bastion_host_name()`: Returns None
- `get_cross_resource_group_dependencies()`: Skipped

### Limitations in Bicep Mode

1. **Subnet Dependencies**: Advanced subnet dependency analysis is skipped
2. **Cross-Resource Group Analysis**: Not available without Azure connectivity
3. **Private Endpoint Optimization**: Simplified to use resource names directly
4. **DNS Zone Analysis**: Skipped in Bicep mode
5. **Bastion Host Detection**: Not available

## Example Files

### Example Bicep Template (`test-template.bicep`)

```bicep
@description('Location for all resources')
param location string = 'eastus'

@description('Storage account name')
param storageAccountName string

resource storageAccount 'Microsoft.Storage/storageAccounts@2021-04-01' = {
  name: storageAccountName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
}

resource appServicePlan 'Microsoft.Web/serverfarms@2021-02-01' = {
  name: '${storageAccountName}-asp'
  location: location
  sku: {
    name: 'B1'
  }
}
```

### Example Parameters File (`test-parameters.json`)

```json
{
  "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "location": {
      "value": "eastus"
    },
    "storageAccountName": {
      "value": "teststrg001"
    }
  }
}
```

## Prerequisites

1. **Azure CLI**: Must be installed and accessible via command line
2. **Bicep CLI**: Must be installed (usually comes with Azure CLI)
3. **Python Dependencies**: Same as existing project (graphviz, tqdm, etc.)

## Testing

To test the Bicep functionality:

1. Create a test Bicep file and parameters file
2. Run with `--useLocalTemplate True`
3. Verify that the generated graph contains the resources from your Bicep template

## Error Handling

The implementation includes comprehensive error handling for:

- Missing or invalid Bicep files
- Missing or invalid parameter files
- Azure CLI/Bicep CLI availability
- Template build failures
- Parameter resolution errors

## Future Enhancements

Potential improvements for future versions:

1. **Enhanced Parameter Resolution**: Support for more complex ARM template functions
2. **Bicep Resource Analysis**: Direct analysis of Bicep syntax for better dependency detection
3. **Multi-Template Support**: Support for multiple Bicep templates in a single visualization
4. **Template Validation**: Integration with Bicep linting and validation
5. **Resource Group Simulation**: Better simulation of Azure resource group behavior

## Troubleshooting

### Common Issues

1. **"Bicep CLI not available"**: Install Azure CLI and ensure `az bicep version` works
2. **"Failed to build template"**: Check Bicep file syntax with `az bicep build --file template.bicep`
3. **"Parameter not found"**: Ensure all parameters in Bicep file are defined in parameters file
4. **Import errors**: Ensure Python path includes the `src` directory

### Debug Mode

To enable debug logging, check the `utils/logger.py` configuration in the project.

