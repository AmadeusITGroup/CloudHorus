#!/usr/bin/env python3
"""
Test script to demonstrate subnet resourceId handling in the Bicep template builder.

This script tests the subnet resource ID conversion functionality that transforms:
- "resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))/subnets/PrivateEndpointSubnet"
To:
- "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-we-tst-fdm-iqtrdv', 'fnd_pe')]"
"""

import json
import os
import tempfile

from src.core.bicep_builder import BicepTemplateBuilder


def create_test_bicep_with_subnets():
    """Create a test Bicep template with subnet references."""
    bicep_content = """
param vnetName string = 'vnet-default'
param subnetName string = 'default'
param privateEndpointSubnetName string = 'PrivateEndpointSubnet'

var vnetResourceId = resourceId('Microsoft.Network/virtualNetworks', vnetName)

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2021-05-01' = {
  name: 'pe-test'
  location: resourceGroup().location
  properties: {
    subnet: {
      id: resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))/subnets/PrivateEndpointSubnet
    }
    privateLinkServiceConnections: [
      {
        name: 'connection1'
        properties: {
          privateLinkServiceId: resourceId('Microsoft.Storage/storageAccounts', 'mystorageaccount')
        }
      }
    ]
  }
}

resource networkInterface 'Microsoft.Network/networkInterfaces@2021-05-01' = {
  name: 'nic-test'
  location: resourceGroup().location
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: {
            id: resourceId('Microsoft.Network/virtualNetworks', parameters('vnetName'))/subnets/default
          }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

// Another pattern with different formatting
resource vm 'Microsoft.Compute/virtualMachines@2021-11-01' = {
  name: 'vm-test'
  location: resourceGroup().location
  properties: {
    networkProfile: {
      networkInterfaces: [
        {
          id: resourceId('Microsoft.Network/networkInterfaces', 'nic-test')
          properties: {
            primary: true
            ipConfigurations: [
              {
                subnet: {
                  id: resourceId('Microsoft.Network/virtualNetworks', vnetName)/subnets/compute
                }
              }
            ]
          }
        }
      ]
    }
  }
}

output privateEndpointSubnet string = resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))/subnets/PrivateEndpointSubnet
output defaultSubnet string = resourceId('Microsoft.Network/virtualNetworks', parameters('vnetName'))/subnets/default
output computeSubnet string = resourceId('Microsoft.Network/virtualNetworks', vnetName)/subnets/compute
"""
    return bicep_content


def create_test_parameters_for_subnets():
    """Create test parameters for the subnet Bicep template."""
    parameters = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {
            "vnetName": {"value": "vnet-we-tst-fdm-iqtrdv"},
            "subnetName": {"value": "fnd_pe"},
            "privateEndpointSubnetName": {"value": "fnd_pe"},
        },
    }
    return parameters


def test_subnet_resourceid_conversion():
    """Test the subnet resourceId conversion functionality."""
    print("Testing Subnet ResourceId Conversion...")
    print("=" * 50)

    # Create temporary files
    with tempfile.NamedTemporaryFile(mode="w", suffix=".bicep", delete=False) as bicep_file:
        bicep_file.write(create_test_bicep_with_subnets())
        bicep_path = bicep_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as param_file:
        json.dump(create_test_parameters_for_subnets(), param_file, indent=2)
        param_path = param_file.name

    try:
        # Test the builder
        builder = BicepTemplateBuilder()

        print(f"Bicep file: {bicep_path}")
        print(f"Parameters file: {param_path}")
        print()

        # Build the template
        result_path = builder.build_bicep_template(bicep_path, param_path)

        if result_path:
            print(f"✅ Successfully built ARM template: {result_path}")

            # Load and analyze the result
            with open(result_path, "r") as f:
                result = json.load(f)

            print("\n🔍 Subnet ResourceId Conversion Analysis:")
            print("-" * 40)

            # Check resources for subnet references
            if "resources" in result:
                for i, resource in enumerate(result["resources"], 1):
                    resource_name = resource.get("name", "Unknown")
                    resource_type = resource.get("type", "Unknown")

                    print(f"\n{i}. {resource_type}: {resource_name}")

                    # Check for subnet references in properties
                    properties = resource.get("properties", {})
                    subnet_refs = find_subnet_references(properties)

                    if subnet_refs:
                        print(f"   📍 Subnet references found:")
                        for ref in subnet_refs:
                            print(f"      • {ref}")
                    else:
                        print(f"   ℹ️  No subnet references")

            # Check outputs for subnet references
            if "outputs" in result:
                print(f"\n📤 Output Subnet References:")
                print("-" * 25)
                for key, output in result["outputs"].items():
                    value = output.get("value", "N/A")
                    if "subnets" in str(value):
                        print(f"  {key}: {value}")
                        # Check if it's properly converted
                        if value.startswith("[resourceId(") and "/subnets" in value:
                            print(f"    ✅ Properly converted to resourceId function")
                        else:
                            print(f"    ❌ Not properly converted")

            print("\n🧪 Manual Test Cases:")
            print("-" * 20)

            # Test the subnet conversion method directly
            test_cases = [
                "resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))/subnets/PrivateEndpointSubnet",
                "resourceId('Microsoft.Network/virtualNetworks', parameters('vnetName'))/subnets/default",
                "resourceId('Microsoft.Network/virtualNetworks', 'vnet-we-tst-fdm-iqtrdv')/subnets/fnd_pe",
            ]

            param_values = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}
            variables = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}

            for test_case in test_cases:
                try:
                    result_val = builder._evaluate_subnet_resource_id(test_case, param_values, variables)
                    expected_pattern = "[resourceId('Microsoft.Network/virtualNetworks/subnets'"

                    if result_val.startswith(expected_pattern):
                        print(f"  ✅ {test_case[:50]}...")
                        print(f"     -> {result_val}")
                    else:
                        print(f"  ❌ {test_case[:50]}...")
                        print(f"     -> {result_val}")
                except Exception as e:
                    print(f"  ❌ {test_case[:50]}... -> Error: {e}")

            # Clean up result file
            os.unlink(result_path)

        else:
            print("❌ Failed to build ARM template")

    except Exception as e:
        print(f"❌ Error during testing: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Clean up temporary files
        try:
            os.unlink(bicep_path)
            os.unlink(param_path)
        except:
            pass


def find_subnet_references(obj, path=""):
    """Recursively find subnet references in an object."""
    subnet_refs = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            current_path = f"{path}.{key}" if path else key

            # Check if this is a subnet reference
            if key == "subnet" and isinstance(value, dict) and "id" in value:
                subnet_id = value["id"]
                if "subnets" in str(subnet_id):
                    subnet_refs.append(f"{current_path}.id: {subnet_id}")

            # Recursively check nested objects
            subnet_refs.extend(find_subnet_references(value, current_path))

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            current_path = f"{path}[{i}]" if path else f"[{i}]"
            subnet_refs.extend(find_subnet_references(item, current_path))

    return subnet_refs


if __name__ == "__main__":
    test_subnet_resourceid_conversion()
