#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for subnet format pattern handling
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.bicep_builder import BicepTemplateBuilder


def test_format_evaluation():
    """Test the format evaluation function directly"""

    print("Testing individual format evaluation...")
    print("=" * 50)

    builder = BicepTemplateBuilder()

    # Test parameters and variables
    param_values = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}

    variables = {"vnetName": "vnet-we-tst-fdm-iqtrdv", "subnetName": "fnd_pe"}

    # Test cases
    test_cases = [
        {
            "name": "Simple subnet format",
            "expression": "format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))",
            "expected": "resourceId('Microsoft.Network/virtualNetworks/subnets'",
        },
        {
            "name": "Parameterized subnet format",
            "expression": "format('{0}/subnets/{1}', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')), variables('subnetName'))",
            "expected": "resourceId('Microsoft.Network/virtualNetworks/subnets'",
        },
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}: {test_case['name']}")
        print(f"Input: {test_case['expression']}")

        try:
            # Remove outer brackets if present
            expression = test_case["expression"]
            if expression.startswith("[") and expression.endswith("]"):
                expression = expression[1:-1]

            result = builder._evaluate_arm_expression(expression, param_values, variables)
            print(f"Result: {result}")

            if test_case["expected"] in result:
                print("PASS: Contains expected pattern")
            else:
                print("FAIL: Does not contain expected pattern")

        except Exception as e:
            print(f"ERROR: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    print("Subnet Format Pattern Test")
    print("=" * 30)

    test_format_evaluation()

    print("\nTest completed!")
