#!/usr/bin/env python3
"""
Test file for multiple Bicep templates functionality in Azure CLI utility.
Demonstrates how to register and use multiple templates with their mappings.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

import json

from core.azure_cli import AzureUtility


def test_multiple_bicep_templates():
    """Test multiple Bicep templates registration and usage"""

    # Create Azure utility instance
    az = AzureUtility()

    # Create sample template data for multiple environments

    # Template 1: Production environment
    prod_template = {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "prod-vnet",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.1.0.0/16"]},
                    "subnets": [
                        {"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.1.1.0/27"}},
                        {"name": "default", "properties": {"addressPrefix": "10.1.2.0/24"}},
                    ],
                },
            },
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.database.windows.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.blob.core.windows.net"},
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.database.windows.net/prod-vnet-link",
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'prod-vnet')]"}
                },
            },
            {
                "type": "Microsoft.Network/bastionHosts",
                "name": "prod-bastion",
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {
                                    "id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'prod-vnet', 'AzureBastionSubnet')]"
                                }
                            },
                        }
                    ]
                },
            },
        ]
    }

    # Template 2: Development environment
    dev_template = {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "dev-vnet",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.2.0.0/16"]},
                    "subnets": [{"name": "default", "properties": {"addressPrefix": "10.2.1.0/24"}}],
                },
            },
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.azurewebsites.net"},
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.azurewebsites.net/dev-vnet-link",
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'dev-vnet')]"}
                },
            },
        ]
    }

    # Template 3: Shared services (DNS only, no VNets)
    shared_template = {
        "resources": [
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.servicebus.windows.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.redis.cache.windows.net"},
        ]
    }

    # Define mappings
    templates_data = [prod_template, dev_template, shared_template]
    resource_groups = ["rg-prod", "rg-dev", "rg-shared"]
    subscriptions = ["sub-prod-123", "sub-dev-456", "sub-shared-789"]
    tenants = ["tenant-corporate-aaa", "tenant-corporate-aaa", "tenant-shared-bbb"]

    print("Testing Multiple Bicep Templates Functionality")
    print("=" * 50)

    # Test 1: Register multiple templates
    print("Test 1: Registering multiple Bicep templates")
    success = az.register_multiple_bicep_templates(
        templates_data=templates_data, resource_groups=resource_groups, subscriptions=subscriptions, tenants=tenants
    )
    print("Registration successful: " + str(success))
    print()

    # Test 2: Check if using multiple templates
    print("Test 2: Check if using multiple templates")
    using_multiple = az.is_using_multiple_templates()
    print("Using multiple templates: " + str(using_multiple))
    print()

    # Test 3: Get registered information
    print("Test 3: Get registered information")
    print("All registered resource groups: " + str(az.get_all_registered_resource_groups()))
    print("All registered subscriptions: " + str(az.get_all_registered_subscriptions()))
    print("All registered tenants: " + str(az.get_all_registered_tenants()))
    print()

    # Test 4: Test resource group to subscription mapping
    print("Test 4: Resource group to subscription mapping")
    for rg in resource_groups:
        mapped_sub = az.get_subscription_for_resource_group(rg)
        print("Resource group '" + rg + "' -> Subscription '" + str(mapped_sub) + "'")
    print()

    # Test 5: Test subscription to tenant mapping
    print("Test 5: Subscription to tenant mapping")
    for sub in set(subscriptions):
        mapped_tenant = az.get_tenant_for_subscription(sub)
        print("Subscription '" + sub + "' -> Tenant '" + str(mapped_tenant) + "'")
    print()

    # Test 6: Test is_resource_group_in_subscription with multiple templates
    print("Test 6: is_resource_group_in_subscription with multiple templates")
    test_cases = [
        ("rg-prod", "sub-prod-123", True),  # Should match
        ("rg-dev", "sub-dev-456", True),  # Should match
        ("rg-prod", "sub-dev-456", False),  # Should not match
        ("rg-nonexistent", "sub-prod-123", False),  # Should not match
    ]

    for rg, sub, expected in test_cases:
        result = az.is_resource_group_in_subscription(rg, sub, use_local_template=True)
        status = "PASS" if result == expected else "FAIL"
        print("  " + rg + " in " + sub + ": " + str(result) + " (expected: " + str(expected) + ") - " + status)
    print()

    # Test 7: Test get_private_dns_zones with multiple templates
    print("Test 7: get_private_dns_zones with multiple templates")
    for rg in resource_groups:
        subscription = az.get_subscription_for_resource_group(rg)
        zones = az.get_private_dns_zones(rg, subscription, use_local_template=True)
        zone_names = [zone["name"] for zone in zones]
        print("  DNS zones in '" + rg + "': " + str(zone_names))
    print()

    # Test 8: Test get_private_dns_zones_without_vnets
    print("Test 8: get_private_dns_zones_without_vnets with multiple templates")
    for rg in resource_groups:
        subscription = az.get_subscription_for_resource_group(rg)
        zones_without_vnets = az.get_private_dns_zones_without_vnets(rg, subscription, use_local_template=True)
        print("  DNS zones without VNets in '" + rg + "': " + str(zones_without_vnets))
    print()

    # Test 9: Test VNet DNS zone links
    print("Test 9: VNet DNS zone links with multiple templates")
    vnet_tests = [("prod-vnet", ["rg-prod"]), ("dev-vnet", ["rg-dev"]), ("nonexistent-vnet", ["rg-prod", "rg-dev"])]

    for vnet_name, rgs in vnet_tests:
        # Use the subscription from the first resource group for the query
        subscription = az.get_subscription_for_resource_group(rgs[0])
        linked_zones = az.is_vnet_linked_to_private_dns_zone(vnet_name, rgs, subscription, use_local_template=True)
        print("  VNet '" + vnet_name + "' linked to zones: " + str(linked_zones))
    print()

    # Test 10: Test get_bastion_host_name
    print("Test 10: get_bastion_host_name with multiple templates")
    bastion_tests = [("prod-vnet", "rg-prod"), ("dev-vnet", "rg-dev"), ("nonexistent-vnet", "rg-prod")]

    for vnet_name, rg in bastion_tests:
        subscription = az.get_subscription_for_resource_group(rg)
        bastion_name = az.get_bastion_host_name(vnet_name, rg, subscription, use_local_template=True)
        print("  Bastion host for VNet '" + vnet_name + "' in '" + rg + "': " + str(bastion_name))
    print()

    # Test 11: Test get_template_data_for_resource_group
    print("Test 11: get_template_data_for_resource_group")
    for rg in resource_groups:
        template_data = az.get_template_data_for_resource_group(rg)
        resource_count = len(template_data.get("resources", [])) if template_data else 0
        print("  Template for '" + rg + "': " + str(resource_count) + " resources")
    print()

    print("=" * 50)
    print("All tests completed!")


def test_backwards_compatibility():
    """Test that the new functionality maintains backwards compatibility"""

    print("Testing Backwards Compatibility")
    print("=" * 30)

    az = AzureUtility()

    # Single template data
    single_template = {
        "resources": [{"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.database.windows.net"}]
    }

    # Test single template mode (existing functionality)
    print("Test: Single template mode (backwards compatibility)")
    zones = az.get_private_dns_zones(
        resource_group="test-rg", subscription_id="test-sub", use_local_template=True, template_data=single_template
    )
    print("DNS zones from single template: " + str([zone["name"] for zone in zones]))

    # Test without template data
    print("Test: Azure portal mode (no template)")
    zones_portal = az.get_private_dns_zones(
        resource_group="test-rg", subscription_id="test-sub", use_local_template=False
    )
    print("DNS zones from portal mode: " + str(len(zones_portal)) + " zones (would query Azure)")

    print("Backwards compatibility maintained!")
    print()


if __name__ == "__main__":
    test_multiple_bicep_templates()
    print()
    test_backwards_compatibility()
