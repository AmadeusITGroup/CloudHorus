#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for subnet format pattern handling in the enhanced Bicep builder
Tests the conversion of format('{0}/subnets/SubnetName', resourceId(...)) patterns
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.bicep_builder import BicepTemplateBuilder


def test_subnet_format_patterns():
    """Test various subnet format patterns and their conversion"""

    # Create test ARM template with subnet format patterns
    arm_template = {
        "parameters": {"vnetName": {"type": "string", "defaultValue": "vnet-we-tst-fdm-iqtrdv"}},
        "variables": {"vnetName": "[parameters('vnetName')]", "subnetName": "fnd_pe"},
        "resources": [
            {
                "type": "Microsoft.Network/privateEndpoints",
                "name": "test-pe",
                "properties": {
                    "subnet": {
                        "id": "[format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))]"
                    }
                },
            },
            {
                "type": "Microsoft.Network/privateEndpoints",
                "name": "test-pe-2",
                "properties": {
                    "subnet": {
                        "id": "[format('{0}/subnets/{1}', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')), variables('subnetName'))]"
                    }
                },
            },
        ],
    }

    # Create parameter file
    parameters = {"vnetName": {"value": "vnet-we-tst-fdm-iqtrdv"}}

    # Create temporary files
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as template_file:
        json.dump(arm_template, template_file, indent=2)
        template_path = template_file.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as param_file:
        json.dump({"parameters": parameters}, param_file, indent=2)
        param_path = param_file.name

    try:
        # Create BicepTemplateBuilder instance
        builder = BicepTemplateBuilder()

        # Test the enhancement
        print("Testing subnet format pattern conversion...")
        print("=" * 60)

        # Process the template
        result = builder.build_bicep_from_arm(template_path, param_path)

        if result:
            print("[SUCCESS] Bicep template generated successfully!")
            print("\nTesting specific subnet format patterns:")

            # Read the generated template to check conversion
            with open(result, "r") as f:
                bicep_content = f.read()

            print("\nGenerated Bicep content:")
            print("-" * 40)
            print(bicep_content)
            print("-" * 40)

            # Check for expected conversions
            expected_patterns = [
                "resourceId('Microsoft.Network/virtualNetworks/subnets'",
                "'vnet-we-tst-fdm-iqtrdv'",
                "'WebAppSubnet'",
            ]

            success = True
            for pattern in expected_patterns:
                if pattern not in bicep_content:
                    print(f"[FAIL] Expected pattern not found: {pattern}")
                    success = False
                else:
                    print(f"[PASS] Found expected pattern: {pattern}")

            if success:
                print("\n[SUCCESS] All subnet format patterns converted successfully!")
            else:
                print("\n[WARNING] Some patterns were not converted as expected")

        else:
            print("[FAIL] Failed to generate Bicep template")

    except Exception as e:
        print(f"[ERROR] Error during test: {e}")
        import traceback

        traceback.print_exc()

    finally:
        # Clean up temporary files
        try:
            os.unlink(template_path)
            os.unlink(param_path)
            if result and os.path.exists(result):
                print(f"\nGenerated Bicep file: {result}")
                # Don't delete the result file so we can inspect it
        except:
            pass


def test_individual_format_evaluation():
    """Test the format evaluation function directly"""

    print("\nTesting individual format evaluation...")
    print("=" * 50)

    builder = BicepTemplateBuilder()

    # Test parameters and variables
    param_values = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}

    variables = {"vnetName": "vnet-we-tst-fdm-iqtrdv", "subnetName": "fnd_pe"}

    # Test cases
    test_cases = [
        {
            "expression": "format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))",
            "expected": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-we-tst-fdm-iqtrdv', 'WebAppSubnet')]",
        },
        {
            "expression": "format('{0}/subnets/{1}', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')), variables('subnetName'))",
            "expected": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-we-tst-fdm-iqtrdv', 'fnd_pe')]",
        },
    ]

    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest Case {i}:")
        print(f"Input:    {test_case['expression']}")
        print(f"Expected: {test_case['expected']}")

        try:
            # Remove outer brackets if present
            expression = test_case["expression"]
            if expression.startswith("[") and expression.endswith("]"):
                expression = expression[1:-1]

            result = builder._evaluate_arm_expression(expression, param_values, variables)
            print(f"Result:   {result}")

            if result == test_case["expected"]:
                print("[PASS]")
            else:
                print("[FAIL]")

        except Exception as e:
            print(f"[ERROR]: {e}")
            import traceback

            traceback.print_exc()


if __name__ == "__main__":
    print("Subnet Format Pattern Conversion Test")
    print("====================================")

    # Test individual function evaluation
    test_individual_format_evaluation()

    # Test full template processing
    test_subnet_format_patterns()

    print("\nTest completed!")
