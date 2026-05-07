#!/usr/bin/env python3
"""
Test script to reproduce the authentication error with non-registered resource groups.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def test_authentication_error_scenario():
    """Test scenarios that might trigger authentication errors."""
    print("Testing authentication error scenarios...")

    try:
        from core.azure_cli import AzureUtility

        # Create Azure utility instance
        azure_util = AzureUtility()

        # Mock template data
        template_data = {
            "resources": [
                {
                    "type": "Microsoft.Network/privateDnsZones",
                    "name": "privatelink.database.windows.net",
                    "properties": {},
                }
            ]
        }

        # Register multiple templates
        templates = [template_data]
        resource_groups = ["bicep-template"]
        subscriptions = ["12345678-1234-1234-1234-123456789012"]
        tenants = ["87654321-4321-4321-4321-210987654321"]

        print("Registering templates...")
        azure_util.register_multiple_bicep_templates(templates, resource_groups, subscriptions, tenants)

        # Test 1: Check with non-registered resource group
        print("\n=== Test 1: Non-registered resource group ===")
        try:
            result = azure_util.is_resource_group_in_subscription(
                resource_group="non-registered-rg",  # This RG is not registered
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=True,
            )
            print(f"✓ Test 1 passed. Result: {result}")
        except Exception as e:
            print(f"✗ Test 1 failed with authentication error: {str(e)}")
            return False

        # Test 2: Check with use_local_template=False (should not call auth)
        print("\n=== Test 2: Azure portal mode (should not be used in template mode) ===")
        try:
            # This should trigger authentication if not properly handled
            result = azure_util.is_resource_group_in_subscription(
                resource_group="bicep-template",
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=False,  # This will try to call Azure
            )
            print(f"✗ Test 2 unexpectedly succeeded: {result}")
            return False
        except Exception as e:
            if "ChainedTokenCredential" in str(e):
                print(f"✓ Test 2 correctly failed with expected authentication error: {str(e)}")
            else:
                print(f"✗ Test 2 failed with unexpected error: {str(e)}")
                return False

        # Test 3: Check template mode functions that might trigger Azure calls
        print("\n=== Test 3: Template mode DNS functions ===")
        try:
            # This should stay in template mode
            dns_zones = azure_util.get_private_dns_zones(
                resource_group="bicep-template",
                subscription_id="12345678-1234-1234-1234-123456789012",
                use_local_template=True,
            )
            print(f"✓ Test 3 passed. Found {len(dns_zones)} DNS zones")
        except Exception as e:
            if "ChainedTokenCredential" in str(e):
                print(f"✗ Test 3 failed with authentication error (BUG!): {str(e)}")
                return False
            else:
                print(f"✗ Test 3 failed with unexpected error: {str(e)}")
                return False

        return True

    except Exception as e:
        print(f"ERROR during setup: {str(e)}")
        return False


if __name__ == "__main__":
    print("=== Testing Authentication Error Scenarios ===")

    success = test_authentication_error_scenario()

    if success:
        print("\n✓ All tests passed - authentication properly handled")
    else:
        print("\n✗ Authentication error reproduced - need to fix")
