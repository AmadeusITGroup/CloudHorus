#!/usr/bin/env python3
"""
Test script to reproduce the exact authentication error scenario.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def test_bicep_template_resource_group():
    """Test the exact scenario that was causing the authentication error."""
    print("Testing bicep-template resource group scenario...")

    try:
        from core.azure_cli import AzureUtility

        # Create Azure utility instance
        azure_util = AzureUtility()

        # Mock template data similar to what you might have
        template_data = {
            "resources": [
                {
                    "type": "Microsoft.Network/privateDnsZones",
                    "name": "privatelink.database.windows.net",
                    "properties": {},
                },
                {"type": "Microsoft.Network/virtualNetworks", "name": "test-vnet", "properties": {}},
            ]
        }

        # Register the template with "bicep-template" as the resource group name
        templates = [template_data]
        resource_groups = ["bicep-template"]
        subscriptions = ["12345678-1234-1234-1234-123456789012"]
        tenants = ["87654321-4321-4321-4321-210987654321"]

        print("Registering bicep-template...")
        success = azure_util.register_multiple_bicep_templates(templates, resource_groups, subscriptions, tenants)

        if not success:
            print("ERROR: Failed to register templates")
            return False

        print("✓ Templates registered successfully")

        # Test the exact function call that was failing
        print("Testing is_resource_group_in_subscription with bicep-template...")
        try:
            result = azure_util.is_resource_group_in_subscription(
                resource_group="bicep-template",
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=True,
            )
            print(f"✓ Success! Result: {result}")
        except Exception as e:
            print(f"✗ ERROR (this is the bug): {str(e)}")
            if "ChainedTokenCredential" in str(e):
                print("This is the authentication error you reported!")
                return False

        # Test all other functions that might trigger authentication
        print("\nTesting other functions with bicep-template...")

        # Test private DNS zones
        try:
            dns_zones = azure_util.get_private_dns_zones(
                resource_group="bicep-template",
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=True,
            )
            print(f"✓ get_private_dns_zones: Found {len(dns_zones)} zones")
        except Exception as e:
            print(f"✗ get_private_dns_zones failed: {str(e)}")
            if "ChainedTokenCredential" in str(e):
                return False

        # Test private DNS zones without VNets
        try:
            dns_zones_no_vnet = azure_util.get_private_dns_zones_without_vnets(
                resource_group="bicep-template",
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=True,
            )
            print(f"✓ get_private_dns_zones_without_vnets: Found {len(dns_zones_no_vnet)} zones")
        except Exception as e:
            print(f"✗ get_private_dns_zones_without_vnets failed: {str(e)}")
            if "ChainedTokenCredential" in str(e):
                return False

        # Test bastion host
        try:
            bastion = azure_util.get_bastion_host_name(
                vnet_name="test-vnet",
                resource_group="bicep-template",
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=True,
            )
            print(f"✓ get_bastion_host_name: Found bastion: {bastion}")
        except Exception as e:
            print(f"✗ get_bastion_host_name failed: {str(e)}")
            if "ChainedTokenCredential" in str(e):
                return False

        # Test VNet linked to DNS zones
        try:
            linked_zones = azure_util.is_vnet_linked_to_private_dns_zone(
                vnet_name="test-vnet",
                resource_groups=["bicep-template"],
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=True,
            )
            print(f"✓ is_vnet_linked_to_private_dns_zone: Found {len(linked_zones)} linked zones")
        except Exception as e:
            print(f"✗ is_vnet_linked_to_private_dns_zone failed: {str(e)}")
            if "ChainedTokenCredential" in str(e):
                return False

        return True

    except Exception as e:
        print(f"ERROR during setup: {str(e)}")
        return False


if __name__ == "__main__":
    print("=== Testing Exact bicep-template Scenario ===")

    success = test_bicep_template_resource_group()

    if success:
        print("\n✓ All tests passed - no authentication errors")
        print("The authentication issue has been fixed!")
    else:
        print("\n✗ Authentication error reproduced")
        print("The issue still exists and needs further investigation.")
