#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple test for direct ARM expression evaluation
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.bicep_builder import BicepTemplateBuilder


def test_direct_arm_evaluation():
    """Test _evaluate_arm_expression directly"""

    print("Test: Direct ARM Expression Evaluation")
    print("=" * 50)

    builder = BicepTemplateBuilder()

    # Test parameters and variables
    param_values = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}
    variables = {"vnetName": "vnet-we-tst-fdm-iqtrdv"}

    # Test expression - note: this should NOT have brackets
    expression = (
        "format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))"
    )

    print(f"Expression: {expression}")
    print(f"Starts with 'format('? {expression.startswith('format(')}")

    try:
        result = builder._evaluate_arm_expression(expression, param_values, variables)
        print(f"Result: {result}")

        if "resourceId('Microsoft.Network/virtualNetworks/subnets'" in result:
            print("SUCCESS: Subnet pattern was converted!")
        else:
            print("FAIL: Subnet pattern was not converted")

    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_direct_arm_evaluation()
