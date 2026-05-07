#!/usr/bin/env python3
"""
Example usage of Azure Resource Visualizer with Bicep template support
"""

import os
import subprocess
import sys


def run_bicep_example():
    """Run an example using Bicep template mode"""

    print("=" * 60)
    print("Azure Resource Visualizer - Bicep Template Example")
    print("=" * 60)

    # Check if we're in the right directory
    if not os.path.exists("src/main.py"):
        print("❌ Please run this script from the AAA-Generator root directory")
        return False

    # Check if example files exist
    bicep_file = "test-template.bicep"
    params_file = "test-parameters.json"

    if not os.path.exists(bicep_file):
        print(f"❌ Bicep template file not found: {bicep_file}")
        print("Please ensure the example files are in the current directory")
        return False

    if not os.path.exists(params_file):
        print(f"❌ Parameters file not found: {params_file}")
        print("Please ensure the example files are in the current directory")
        return False

    print(f"✅ Found Bicep template: {bicep_file}")
    print(f"✅ Found parameters file: {params_file}")

    # Build the command
    cmd = [
        sys.executable,
        "src/main.py",
        "--useLocalTemplate",
        "True",
        "--bicepFile",
        bicep_file,
        "--parametersFile",
        params_file,
        "--subscriptions",
        "local-bicep-subscription",
        "--tenants",
        "local-bicep-tenant",
        "--resourcegroups",
        "bicep-template",
        "--edgeDirection",
        "TB",
        "--subnetOptimization",
        "False",
        "--rankDebug",
        "False",
        "--peOptimization",
        "True",
        "--privateDnsZonesOptimization",
        "True",
    ]

    print("\n" + "=" * 60)
    print("Running command:")
    print(" ".join(cmd))
    print("=" * 60)

    try:
        # Run the command
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=os.getcwd())

        if result.returncode == 0:
            print("✅ Command executed successfully!")
            print("\nOutput:")
            print(result.stdout)
        else:
            print("❌ Command failed!")
            print("\nError output:")
            print(result.stderr)
            print("\nStandard output:")
            print(result.stdout)
            return False

    except Exception as e:
        print(f"❌ Failed to run command: {e}")
        return False

    print("\n" + "=" * 60)
    print("Example completed! Check for generated graph files.")
    print("=" * 60)

    return True


def run_azure_example():
    """Show example of traditional Azure mode"""

    print("\n" + "=" * 60)
    print("Traditional Azure Mode Example")
    print("=" * 60)

    print("To use traditional Azure export mode, run:")
    print("")

    cmd_str = """python3 src/main.py \\
  --subscriptions "your-subscription-id-1" "your-subscription-id-2" \\
  --resourcegroups "your-rg-1" "your-rg-2" \\
  --tenants "your-tenant-id" \\
  --edgeDirection TB \\
  --subnetOptimization False \\
  --peOptimization True True"""

    print(cmd_str)
    print("")
    print("Note: Replace the placeholder values with your actual Azure subscription IDs,")
    print("resource group names, and tenant ID.")


if __name__ == "__main__":
    print("Azure Resource Visualizer - Usage Examples")
    print("This script demonstrates both Bicep and Azure modes\n")

    # Run Bicep example
    success = run_bicep_example()

    # Show Azure example
    run_azure_example()

    if success:
        print("\n🎉 All examples completed successfully!")
    else:
        print("\n⚠️  Some examples had issues. Please check the error messages above.")
