#!/usr/bin/env python3
"""
Example script showing how to use the enhanced Bicep builder for subnet resolution
"""

import json
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from core.bicep_builder import BicepTemplateBuilder


def demonstrate_subnet_resolution():
    """Demonstrate how to use the enhanced Bicep builder with subnet resolution."""

    print("Enhanced Bicep Builder - Subnet Resolution Demo")
    print("=" * 80)

    # Example: Building a Bicep template with parameters
    builder = BicepTemplateBuilder()

    # Check if we have a Bicep file and parameters to test with
    bicep_file = "main.bicep"  # Adjust path as needed
    parameters_file = "main.parameters.json"  # Adjust path as needed

    if not (os.path.exists(bicep_file) and os.path.exists(parameters_file)):
        print(f"Bicep files not found. Simulating with built template...")
        demonstrate_with_built_template()
        return

    print(f"Building Bicep template: {bicep_file}")
    print(f"Using parameters: {parameters_file}")

    # Build the template
    output_file = builder.build_bicep_template(bicep_file, parameters_file)

    if output_file:
        print(f"Successfully built template: {output_file}")

        # Process the built template for subnet dependencies
        process_template_for_subnets(output_file)
    else:
        print("Failed to build template")


def demonstrate_with_built_template():
    """Demonstrate using the existing built template."""

    template_file = "main-built-template.json"

    if not os.path.exists(template_file):
        print(f"Built template {template_file} not found.")
        return

    print(f"Processing built template: {template_file}")
    process_template_for_subnets(template_file)


def process_template_for_subnets(template_file):
    """Process a template file and extract subnet dependencies."""

    try:
        with open(template_file, "r") as f:
            template = json.load(f)

        print(f"\nProcessing template with {len(template.get('resources', []))} resources")

        # Simulate the workflow that get_subnet_implicit_dependencies would use
        from core.resource_processor import extract_subnet_name_from_id

        subnet_dependencies = {}

        # Resource type mapping (similar to what's in resource_processor.py)
        resource_handlers = {
            "Microsoft.Network/privateEndpoints": lambda p: p.get("subnet", {}).get("id") if p.get("subnet") else None,
            "Microsoft.Web/sites": lambda p: p.get("virtualNetworkSubnetId") if "virtualNetworkSubnetId" in p else None,
            "Microsoft.Network/applicationGateways": lambda p: (
                p.get("gatewayIPConfigurations", [{}])[0].get("properties", {}).get("subnet", {}).get("id")
                if p.get("gatewayIPConfigurations")
                else None
            ),
            "Microsoft.ContainerService/managedClusters": lambda p: (
                p.get("agentPoolProfiles", [{}])[0].get("vnetSubnetID") if p.get("agentPoolProfiles") else None
            ),
        }

        print("\\nExtracting subnet dependencies:")
        print("-" * 40)

        for resource in template.get("resources", []):
            resource_type = resource.get("type", "")
            resource_name = resource.get("name", "unknown")
            properties = resource.get("properties", {})

            # Check if this resource type has subnet dependencies
            if resource_type in resource_handlers:
                subnet_id = resource_handlers[resource_type](properties)

                if subnet_id:
                    print(f"Resource: {resource_name} ({resource_type})")
                    print(f"  Raw subnet ID: {subnet_id}")

                    # Extract subnet name using our enhanced function
                    subnet_name = extract_subnet_name_from_id(subnet_id)

                    if subnet_name:
                        subnet_dependencies[resource_name] = subnet_name
                        print(f"  ✅ Extracted subnet: {subnet_name}")
                    else:
                        print(f"  ❌ Could not extract subnet name")
                    print()

        # Summary
        print("Summary:")
        print(f"Total subnet dependencies found: {len(subnet_dependencies)}")
        for resource_name, subnet_name in subnet_dependencies.items():
            print(f"  {resource_name} -> {subnet_name}")

        if not subnet_dependencies:
            print("  No subnet dependencies found or resolved")
            print("  This could mean:")
            print("    1. No resources have subnet dependencies")
            print("    2. ARM template references need to be pre-resolved by Bicep builder")
            print("    3. The template needs to be processed with parameter values")

        return subnet_dependencies

    except Exception as e:
        print(f"Error processing template: {e}")
        return {}


def show_usage_instructions():
    """Show instructions for using the enhanced subnet resolution."""

    print("\\n" + "=" * 80)
    print("USAGE INSTRUCTIONS")
    print("=" * 80)

    print("""
To use the enhanced subnet resolution in your application:

1. Use BicepTemplateBuilder to build your Bicep templates with parameters:
   
   ```python
   from core.bicep_builder import BicepTemplateBuilder
   
   builder = BicepTemplateBuilder()
   output_file = builder.build_bicep_template('main.bicep', 'main.parameters.json')
   ```

2. The builder will now resolve complex ARM template references like:
   [reference(resourceId('Microsoft.Resources/deployments', 'networkDeployment'), '2022-09-01').outputs.privateEndpointSubnetId.value]
   
   Into actual subnet resource IDs that can be processed by get_subnet_implicit_dependencies()

3. The enhanced resource_processor.extract_subnet_name_from_id() function handles:
   - Standard Azure resource IDs
   - Resolved deployment output references  
   - Various subnet ID formats

4. Your existing get_subnet_implicit_dependencies() function will now work with
   built templates that contain complex reference functions.

Key improvements:
- ✅ Resolves deployment output references
- ✅ Handles complex ARM template functions
- ✅ Provides meaningful subnet names from resource IDs
- ✅ Maintains backward compatibility with existing code
""")


if __name__ == "__main__":
    demonstrate_subnet_resolution()
    show_usage_instructions()
