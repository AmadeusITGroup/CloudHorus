#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for the enhanced get_private_dns_zones_without_vnets function
"""

import json
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.azure_cli import get_private_dns_zones_without_vnets


def test_bicep_template_dns_zones():
    """Test the Bicep template functionality for DNS zones without VNets"""

    print("Testing Bicep Template DNS Zone Analysis")
    print("=" * 50)

    # Test case 1: Template with DNS zones but no VNets (should return DNS zones)
    template_with_dns_no_vnets = {
        "resources": [
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.azurewebsites.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.database.windows.net"},
            {"type": "Microsoft.Storage/storageAccounts", "name": "mystorageaccount"},
        ]
    }

    # Test case 2: Template with both DNS zones and VNets (should return empty)
    template_with_dns_and_vnets = {
        "resources": [
            {"type": "Microsoft.Network/virtualNetworks", "name": "my-vnet"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.azurewebsites.net"},
        ]
    }

    # Test case 3: Template with no DNS zones and no VNets (should return empty)
    template_no_dns_no_vnets = {
        "resources": [{"type": "Microsoft.Storage/storageAccounts", "name": "mystorageaccount"}]
    }

    test_cases = [
        {
            "name": "DNS zones without VNets",
            "template": template_with_dns_no_vnets,
            "expected": ["privatelink.azurewebsites.net", "privatelink.database.windows.net"],
        },
        {"name": "DNS zones with VNets", "template": template_with_dns_and_vnets, "expected": []},
        {"name": "No DNS zones, no VNets", "template": template_no_dns_no_vnets, "expected": []},
    ]

    all_passed = True

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['name']}")

        try:
            result = get_private_dns_zones_without_vnets(
                resource_group="test-rg",
                subscription_id="test-subscription",
                use_local_template=True,
                template_data=test_case["template"],
            )

            print(f"Expected: {test_case['expected']}")
            print(f"Result:   {result}")

            if set(result) == set(test_case["expected"]):
                print("PASS: Results match expected output")
            else:
                print("FAIL: Results do not match expected output")
                all_passed = False

        except Exception as e:
            print(f"ERROR: {e}")
            all_passed = False

    print(f"\n{'='*50}")
    if all_passed:
        print("SUCCESS: All Bicep template tests passed!")
        print("\nThe enhanced function now supports:")
        print("1. Azure portal scanning (original functionality)")
        print("2. Bicep template analysis (new functionality)")
        print("3. Proper detection of DNS zones in templates without VNets")
    else:
        print("FAILURE: Some tests failed")


if __name__ == "__main__":
    test_bicep_template_dns_zones()
