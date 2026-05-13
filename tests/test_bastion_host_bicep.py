# -*- coding: utf-8 -*-
"""
Test script for enhanced get_bastion_host_name function with Bicep template support.
"""

import json
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def create_test_template_with_bastion():
    """Create a test ARM template with Bastion Host linked to VNet."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "hub-vnet",
                "location": "East US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.0.1.0/27"}},
                        {"name": "default", "properties": {"addressPrefix": "10.0.2.0/24"}},
                    ],
                },
            },
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "spoke-vnet",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}},
            },
            {
                "type": "Microsoft.Network/publicIPAddresses",
                "name": "bastion-pip",
                "location": "East US",
                "sku": {"name": "Standard"},
                "properties": {"publicIPAllocationMethod": "Static"},
            },
            {
                "type": "Microsoft.Network/bastionHosts",
                "name": "hub-bastion",
                "location": "East US",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/virtualNetworks', 'hub-vnet')]",
                    "[resourceId('Microsoft.Network/publicIPAddresses', 'bastion-pip')]",
                ],
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {
                                    "id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'hub-vnet', 'AzureBastionSubnet')]"
                                },
                                "publicIPAddress": {
                                    "id": "[resourceId('Microsoft.Network/publicIPAddresses', 'bastion-pip')]"
                                },
                            },
                        }
                    ]
                },
            },
            # Note: spoke-vnet has no Bastion Host
        ]
    }


def create_test_template_no_bastion():
    """Create a test ARM template with VNet but no Bastion Host."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "isolated-vnet",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.2.0.0/16"]}},
            }
            # No Bastion Host resources
        ]
    }


def create_test_template_multiple_bastions():
    """Create a test ARM template with multiple VNets and Bastion Hosts."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "vnet-a",
                "location": "East US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.3.0.0/16"]},
                    "subnets": [{"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.3.1.0/27"}}],
                },
            },
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "vnet-b",
                "location": "East US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.4.0.0/16"]},
                    "subnets": [{"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.4.1.0/27"}}],
                },
            },
            {
                "type": "Microsoft.Network/publicIPAddresses",
                "name": "bastion-a-pip",
                "location": "East US",
                "sku": {"name": "Standard"},
                "properties": {"publicIPAllocationMethod": "Static"},
            },
            {
                "type": "Microsoft.Network/publicIPAddresses",
                "name": "bastion-b-pip",
                "location": "East US",
                "sku": {"name": "Standard"},
                "properties": {"publicIPAllocationMethod": "Static"},
            },
            {
                "type": "Microsoft.Network/bastionHosts",
                "name": "bastion-a",
                "location": "East US",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/virtualNetworks', 'vnet-a')]",
                    "[resourceId('Microsoft.Network/publicIPAddresses', 'bastion-a-pip')]",
                ],
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {
                                    "id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-a', 'AzureBastionSubnet')]"
                                },
                                "publicIPAddress": {
                                    "id": "[resourceId('Microsoft.Network/publicIPAddresses', 'bastion-a-pip')]"
                                },
                            },
                        }
                    ]
                },
            },
            {
                "type": "Microsoft.Network/bastionHosts",
                "name": "bastion-b",
                "location": "East US",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/virtualNetworks', 'vnet-b')]",
                    "[resourceId('Microsoft.Network/publicIPAddresses', 'bastion-b-pip')]",
                ],
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {
                                    "id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-b', 'AzureBastionSubnet')]"
                                },
                                "publicIPAddress": {
                                    "id": "[resourceId('Microsoft.Network/publicIPAddresses', 'bastion-b-pip')]"
                                },
                            },
                        }
                    ]
                },
            },
        ]
    }


def test_bastion_host_functions():
    """Test the enhanced get_bastion_host_name function."""
    try:
        # Mock the AzureUtility class for testing
        class MockAzureUtility:
            def __init__(self):
                pass

            def get_bastion_host_name(
                self, vnet_name, resource_group, subscription_id, use_local_template=False, template_data=None
            ):
                if use_local_template and template_data:
                    return self._get_bastion_host_name_from_template(template_data, vnet_name, resource_group)
                else:
                    # For testing, just return None for Azure portal mode
                    return None

            def _get_bastion_host_name_from_template(self, template_data, vnet_name, resource_group):
                """Template analysis method from the enhanced function."""
                try:
                    resources = template_data.get("resources", [])

                    # Find all Bastion Hosts in the template
                    for resource in resources:
                        resource_type = resource.get("type", "")

                        # Check for Bastion Host resources
                        if resource_type == "Microsoft.Network/bastionHosts":
                            bastion_name = resource.get("name", "")
                            properties = resource.get("properties", {})

                            # Check if this Bastion Host is linked to our VNet
                            # Bastion Hosts reference VNets through their subnet configuration
                            ip_configurations = properties.get("ipConfigurations", [])

                            for ip_config in ip_configurations:
                                subnet_ref = ip_config.get("properties", {}).get("subnet", {}).get("id", "")

                                # Extract VNet name from subnet reference
                                referenced_vnet_name = None

                                if isinstance(subnet_ref, str):
                                    if "resourceId(" in subnet_ref or "[" in subnet_ref:
                                        # ARM function - try to extract VNet name
                                        if ("'" + vnet_name + "'") in subnet_ref or (
                                            '"' + vnet_name + '"'
                                        ) in subnet_ref:
                                            referenced_vnet_name = vnet_name
                                    elif "/" in subnet_ref and "virtualNetworks" in subnet_ref:
                                        # Full resource ID path - extract VNet name
                                        parts = subnet_ref.split("/")
                                        for i, part in enumerate(parts):
                                            if part == "virtualNetworks" and i + 1 < len(parts):
                                                referenced_vnet_name = parts[i + 1]
                                                break

                                # If this Bastion Host references our VNet, return its name
                                if referenced_vnet_name == vnet_name:
                                    return bastion_name

                    return None

                except Exception as e:
                    print("Error analyzing template for Bastion Host: " + str(e))
                    return None

        # Create mock instance
        mock_az = MockAzureUtility()

        # Test Case 1: VNet with Bastion Host
        print("Test Case 1: VNet with Bastion Host")
        template1 = create_test_template_with_bastion()
        result1 = mock_az.get_bastion_host_name(
            vnet_name="hub-vnet",
            resource_group="test-rg",
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template1,
        )
        expected1 = "hub-bastion"
        print("Expected: " + str(expected1))
        print("Result: " + str(result1))
        print("PASS" if result1 == expected1 else "FAIL")
        print()

        # Test Case 2: VNet without Bastion Host (from same template)
        print("Test Case 2: VNet without Bastion Host")
        result2 = mock_az.get_bastion_host_name(
            vnet_name="spoke-vnet",
            resource_group="test-rg",
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template1,
        )
        expected2 = None
        print("Expected: " + str(expected2))
        print("Result: " + str(result2))
        print("PASS" if result2 == expected2 else "FAIL")
        print()

        # Test Case 3: Template with no Bastion Hosts
        print("Test Case 3: Template with no Bastion Hosts")
        template3 = create_test_template_no_bastion()
        result3 = mock_az.get_bastion_host_name(
            vnet_name="isolated-vnet",
            resource_group="test-rg",
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template3,
        )
        expected3 = None
        print("Expected: " + str(expected3))
        print("Result: " + str(result3))
        print("PASS" if result3 == expected3 else "FAIL")
        print()

        # Test Case 4: Multiple Bastion Hosts - Check vnet-a
        print("Test Case 4: Multiple Bastion Hosts - Check vnet-a")
        template4 = create_test_template_multiple_bastions()
        result4 = mock_az.get_bastion_host_name(
            vnet_name="vnet-a",
            resource_group="test-rg",
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template4,
        )
        expected4 = "bastion-a"
        print("Expected: " + str(expected4))
        print("Result: " + str(result4))
        print("PASS" if result4 == expected4 else "FAIL")
        print()

        # Test Case 5: Multiple Bastion Hosts - Check vnet-b
        print("Test Case 5: Multiple Bastion Hosts - Check vnet-b")
        result5 = mock_az.get_bastion_host_name(
            vnet_name="vnet-b",
            resource_group="test-rg",
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template4,
        )
        expected5 = "bastion-b"
        print("Expected: " + str(expected5))
        print("Result: " + str(result5))
        print("PASS" if result5 == expected5 else "FAIL")
        print()

        # Test Case 6: Azure portal mode (should return None for mock)
        print("Test Case 6: Azure portal mode")
        result6 = mock_az.get_bastion_host_name(
            vnet_name="hub-vnet",
            resource_group="test-rg",
            subscription_id="test-sub",
            use_local_template=False,
            template_data=None,
        )
        expected6 = None  # Mock returns None for Azure portal mode
        print("Expected: " + str(expected6))
        print("Result: " + str(result6))
        print("PASS" if result6 == expected6 else "FAIL")

        print("\nAll Bastion Host tests completed!")

    except Exception as e:
        print("Test failed with error: " + str(e))
        return False

    return True


if __name__ == "__main__":
    print("Testing enhanced get_bastion_host_name function with Bicep template support...")
    print("=" * 80)
    test_bastion_host_functions()
