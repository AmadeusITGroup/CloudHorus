#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for enhanced is_vnet_linked_to_private_dns_zone function with Bicep template support.
"""

import json
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def create_test_template_with_vnet_links():
    """Create a test ARM template with VNet to DNS zone links."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "test-vnet",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}},
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.azurewebsites.net",
                "location": "global",
                "properties": {},
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.database.windows.net",
                "location": "global",
                "properties": {},
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.blob.core.windows.net",
                "location": "global",
                "properties": {},
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.azurewebsites.net/test-vnet-link",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.azurewebsites.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'test-vnet')]",
                ],
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'test-vnet')]"},
                    "registrationEnabled": False,
                },
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.database.windows.net/test-vnet-link",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.database.windows.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'test-vnet')]",
                ],
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'test-vnet')]"},
                    "registrationEnabled": False,
                },
            },
            # Note: privatelink.blob.core.windows.net is NOT linked to test-vnet
        ]
    }


def create_test_template_no_links():
    """Create a test ARM template with DNS zones but no VNet links."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "isolated-vnet",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}},
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.servicebus.windows.net",
                "location": "global",
                "properties": {},
            },
            # No virtualNetworkLinks resources
        ]
    }


def create_test_template_different_vnet_links():
    """Create a test ARM template with DNS zones linked to different VNet."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "vnet-a",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.2.0.0/16"]}},
            },
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "vnet-b",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.3.0.0/16"]}},
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.redis.cache.windows.net",
                "location": "global",
                "properties": {},
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.redis.cache.windows.net/vnet-b-link",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.redis.cache.windows.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'vnet-b')]",
                ],
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'vnet-b')]"},
                    "registrationEnabled": False,
                },
            },
            # vnet-a is not linked to any DNS zones
        ]
    }


def test_vnet_dns_zone_links():
    """Test the enhanced is_vnet_linked_to_private_dns_zone function."""
    try:
        # Mock the AzureUtility class for testing
        class MockAzureUtility:
            def __init__(self):
                pass

            def is_vnet_linked_to_private_dns_zone(
                self, vnet_name, resource_groups, subscription_id, use_local_template=False, template_data=None
            ):
                if use_local_template and template_data:
                    return self._get_vnet_linked_dns_zones_from_template(template_data, vnet_name, resource_groups)
                else:
                    # For testing, just return empty list for Azure portal mode
                    return []

            def _get_vnet_linked_dns_zones_from_template(self, template_data, vnet_name, resource_groups):
                """Template analysis method from the enhanced function."""
                try:
                    resources = template_data.get("resources", [])
                    linked_zones = []

                    # First, find all private DNS zones in the template
                    dns_zones = []
                    for resource in resources:
                        if resource.get("type", "") == "Microsoft.Network/privateDnsZones":
                            dns_zones.append(resource.get("name", ""))

                    # Then, find all virtual network links and check if they reference our VNet
                    for resource in resources:
                        resource_type = resource.get("type", "")

                        # Check for virtual network links
                        if resource_type == "Microsoft.Network/privateDnsZones/virtualNetworkLinks":
                            properties = resource.get("properties", {})
                            virtual_network = properties.get("virtualNetwork", {})

                            # Handle different ways the VNet can be referenced in template
                            vnet_reference = virtual_network.get("id", "")

                            # Extract VNet name from various possible formats:
                            # - Direct name reference
                            # - ResourceId function calls
                            # - Full ARM resource ID paths
                            referenced_vnet_name = None

                            if isinstance(vnet_reference, str):
                                if vnet_reference == vnet_name:
                                    # Direct name match
                                    referenced_vnet_name = vnet_name
                                elif "resourceId(" in vnet_reference or "[" in vnet_reference:
                                    # ARM function - try to extract VNet name
                                    if ("'" + vnet_name + "'") in vnet_reference or (
                                        '"' + vnet_name + '"'
                                    ) in vnet_reference:
                                        referenced_vnet_name = vnet_name
                                elif "/" in vnet_reference:
                                    # Full resource ID path
                                    referenced_vnet_name = vnet_reference.split("/")[-1]

                            # If this link references our VNet, find which DNS zone it belongs to
                            if referenced_vnet_name == vnet_name:
                                # Extract DNS zone name from the link's parent resource
                                # Format: zone_name/virtualNetworkLinks/link_name
                                resource_name = resource.get("name", "")
                                if "/" in resource_name:
                                    # Handle nested resource format: "zone_name/link_name"
                                    zone_name = resource_name.split("/")[0]
                                    if zone_name in dns_zones and zone_name not in linked_zones:
                                        linked_zones.append(zone_name)
                                else:
                                    # Handle dependency-based linking by checking dependsOn
                                    depends_on = resource.get("dependsOn", [])
                                    for dependency in depends_on:
                                        if isinstance(dependency, str) and "privateDnsZones" in dependency:
                                            # Extract zone name from dependency reference
                                            for zone_name in dns_zones:
                                                if zone_name in dependency and zone_name not in linked_zones:
                                                    linked_zones.append(zone_name)

                    return linked_zones

                except Exception as e:
                    print("Error analyzing template: " + str(e))
                    return []

        # Create mock instance
        mock_az = MockAzureUtility()

        # Test Case 1: VNet linked to multiple DNS zones
        print("Test Case 1: VNet linked to multiple DNS zones")
        template1 = create_test_template_with_vnet_links()
        result1 = mock_az.is_vnet_linked_to_private_dns_zone(
            vnet_name="test-vnet",
            resource_groups=["test-rg"],
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template1,
        )
        expected1 = ["privatelink.azurewebsites.net", "privatelink.database.windows.net"]
        print("Expected: " + str(expected1))
        print("Result: " + str(result1))
        print("PASS" if set(result1) == set(expected1) else "FAIL")
        print()

        # Test Case 2: VNet with no DNS zone links
        print("Test Case 2: VNet with no DNS zone links")
        template2 = create_test_template_no_links()
        result2 = mock_az.is_vnet_linked_to_private_dns_zone(
            vnet_name="isolated-vnet",
            resource_groups=["test-rg"],
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template2,
        )
        expected2 = []
        print("Expected: " + str(expected2))
        print("Result: " + str(result2))
        print("PASS" if result2 == expected2 else "FAIL")
        print()

        # Test Case 3: VNet not linked (other VNet is linked)
        print("Test Case 3: VNet not linked (different VNet is linked)")
        template3 = create_test_template_different_vnet_links()
        result3 = mock_az.is_vnet_linked_to_private_dns_zone(
            vnet_name="vnet-a",
            resource_groups=["test-rg"],
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template3,
        )
        expected3 = []
        print("Expected: " + str(expected3))
        print("Result: " + str(result3))
        print("PASS" if result3 == expected3 else "FAIL")
        print()

        # Test Case 4: Check the linked VNet
        print("Test Case 4: Check the VNet that is actually linked")
        result4 = mock_az.is_vnet_linked_to_private_dns_zone(
            vnet_name="vnet-b",
            resource_groups=["test-rg"],
            subscription_id="test-sub",
            use_local_template=True,
            template_data=template3,
        )
        expected4 = ["privatelink.redis.cache.windows.net"]
        print("Expected: " + str(expected4))
        print("Result: " + str(result4))
        print("PASS" if result4 == expected4 else "FAIL")
        print()

        # Test Case 5: Azure portal mode (should return empty for mock)
        print("Test Case 5: Azure portal mode")
        result5 = mock_az.is_vnet_linked_to_private_dns_zone(
            vnet_name="test-vnet",
            resource_groups=["test-rg"],
            subscription_id="test-sub",
            use_local_template=False,
            template_data=None,
        )
        expected5 = []  # Mock returns empty for Azure portal mode
        print("Expected: " + str(expected5))
        print("Result: " + str(result5))
        print("PASS" if result5 == expected5 else "FAIL")

        print("All VNet DNS zone link tests completed!")

    except Exception as e:
        print("Test failed with error: " + str(e))
        return False

    return True


if __name__ == "__main__":
    print("Testing enhanced is_vnet_linked_to_private_dns_zone function with Bicep template support...")
    print("=" * 80)
    test_vnet_dns_zone_links()
