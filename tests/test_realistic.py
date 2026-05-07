#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Realistic test for the actual format flow
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.bicep_builder import BicepTemplateBuilder


def test_realistic_flow():
    """Test the actual flow with resolved resourceId"""

    print("Test: Realistic Format Flow")
    print("=" * 40)

    builder = BicepTemplateBuilder()

    # Test parameters and variables
    param_values = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}
    variables = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}

    # The format string and resolved args as they would be in the real flow
    format_string = "{0}/subnets/WebAppSubnet"
    # This is what the resourceId argument resolves to
    format_args = ["resourceId('Microsoft.Network/virtualNetworks', 'vnet-we-tst-fdm-iqtrdv')"]

    print(f"Format string: {format_string}")
    print(f"Format args: {format_args}")

    try:
        result = builder._handle_subnet_format_pattern(format_string, format_args, param_values, variables)
        print(f"Subnet pattern result: {result}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


def test_full_format_evaluation():
    """Test the complete format evaluation"""

    print("\nTest: Full Format Evaluation")
    print("=" * 40)

    builder = BicepTemplateBuilder()

    # Test parameters and variables
    param_values = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}
    variables = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}

    # The complete expression
    expression = (
        "format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))"
    )

    print(f"Expression: {expression}")

    try:
        result = builder._evaluate_format(expression, param_values, variables)
        print(f"Final result: {result}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_realistic_flow()
    test_full_format_evaluation()
