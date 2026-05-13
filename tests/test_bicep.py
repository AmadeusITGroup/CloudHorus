#!/usr/bin/env python3
"""
Test script for Bicep functionality
"""

import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from core.bicep_builder import build_bicep_template


def test_bicep_builder():
    """Test the Bicep builder functionality"""
    print("Testing Bicep builder...")

    # Test file paths
    bicep_file = "test-template.bicep"
    parameters_file = "test-parameters.json"

    # Test file validation
    from core.bicep_builder import BicepTemplateBuilder

    builder = BicepTemplateBuilder()

    print(f"Checking Bicep CLI availability...")
    if not builder.validate_bicep_cli():
        print("❌ Bicep CLI not available. Please install Azure CLI with Bicep.")
        return False

    print(f"Validating files...")
    if not builder.validate_files(bicep_file, parameters_file):
        print("❌ File validation failed.")
        return False

    print(f"Building Bicep template...")
    result = build_bicep_template(bicep_file, parameters_file)

    if result:
        print(f"✅ Successfully built template: {result}")
        return True
    else:
        print("❌ Failed to build template")
        return False


if __name__ == "__main__":
    test_bicep_builder()
