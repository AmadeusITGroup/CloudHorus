#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive test for the subnet format enhancement
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.bicep_builder import BicepTemplateBuilder


def test_comprehensive_subnet_formats():
    """Test all the subnet format patterns we support"""

    print("Comprehensive Subnet Format Test")
    print("=" * 50)

    builder = BicepTemplateBuilder()

    # Test parameters and variables
    param_values = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}
    variables = {"vnetName": "vnet-we-tst-fdm-iqtrdv", "subnetName": "fnd_pe"}

    test_cases = [
        {
            "name": "Fixed subnet name",
            "expression": "format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))",
            "expected_vnet": "vnet-we-tst-fdm-iqtrdv",
            "expected_subnet": "WebAppSubnet",
        },
        {
            "name": "Variable subnet name",
            "expression": "format('{0}/subnets/{1}', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')), variables('subnetName'))",
            "expected_vnet": "vnet-we-tst-fdm-iqtrdv",
            "expected_subnet": "fnd_pe",
        },
        {
            "name": "Parameter-based VNet",
            "expression": "format('{0}/subnets/DefaultSubnet', resourceId('Microsoft.Network/virtualNetworks', parameters('vnetName')))",
            "expected_vnet": "vnet-we-tst-fdm-iqtrdv",
            "expected_subnet": "DefaultSubnet",
        },
    ]

    all_passed = True

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['name']}")
        print(f"Input: {test_case['expression']}")

        try:
            result = builder._evaluate_arm_expression(test_case["expression"], param_values, variables)
            print(f"Result: {result}")

            # Check if the result contains the expected parts
            expected_vnet = test_case["expected_vnet"]
            expected_subnet = test_case["expected_subnet"]

            if (
                f"'{expected_vnet}'" in result
                and f"'{expected_subnet}'" in result
                and "resourceId('Microsoft.Network/virtualNetworks/subnets'" in result
            ):
                print("PASS: All expected components found")
            else:
                print("FAIL: Missing expected components")
                all_passed = False

        except Exception as e:
            print(f"ERROR: {e}")
            all_passed = False
            import traceback

            traceback.print_exc()

    print(f"\n{'='*50}")
    if all_passed:
        print("SUCCESS: All subnet format patterns work correctly!")
        print("\nYour enhancement is complete. The format() function now properly:")
        print("1. Detects subnet format patterns like format('{0}/subnets/SubnetName', resourceId(...))")
        print("2. Extracts VNet names from resourceId expressions")
        print("3. Converts them to proper resourceId('Microsoft.Network/virtualNetworks/subnets', ...) format")
        print("4. Handles both fixed subnet names and variable subnet names")
    else:
        print("FAILURE: Some test cases failed")


if __name__ == "__main__":
    test_comprehensive_subnet_formats()
