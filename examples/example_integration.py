#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example showing how to integrate the enhanced get_private_dns_zones_without_vnets
function in your graph_generator.py
"""

import json
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.azure_cli import get_private_dns_zones_without_vnets


def example_integration():
    """
    Example showing how to use the enhanced function in graph_generator.py
    """

    print("Example: Integration with Graph Generator")
    print("=" * 50)

    # Example template data (this would come from your Bicep template file)
    sample_template = {
        "resources": [
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.azurewebsites.net",
                "location": "global",
                "properties": {},
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.database.windows.net",
                "location": "global",
                "properties": {},
            },
            {"type": "Microsoft.Storage/storageAccounts", "name": "examplestorage", "location": "East US"},
        ]
    }

    # Example usage in graph_generator.py context
    resource_group = "example-rg"
    subscription_id = "example-subscription"
    use_local_template = True  # Set based on your parameter

    print(f"Analyzing resource group: {resource_group}")
    print(f"Using local template: {use_local_template}")

    # Call the enhanced function
    dns_zones_without_vnets = get_private_dns_zones_without_vnets(
        resource_group=resource_group,
        subscription_id=subscription_id,
        use_local_template=use_local_template,
        template_data=sample_template,
    )

    print(f"DNS zones found without VNets: {dns_zones_without_vnets}")

    # This is how you would integrate it in your graph_generator.py
    integration_code = """
    # In your generate_resource_graph function, around where you process resources:
    
    # Load your template data (this part already exists in your code)
    try:
        with open(output_file, 'r') as file:
            template = json.load(file)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        logger.error(f"Failed to load template file {output_file}: {e}")
        continue
    
    # NEW: Get DNS zones without VNets using the enhanced function
    dns_zones_without_vnets = get_private_dns_zones_without_vnets(
        resource_group=resourceGroup,
        subscription_id=subscription_id,
        use_local_template=use_local_template,
        template_data=template if use_local_template else None
    )
    
    # Process the DNS zones (add to your graph as needed)
    for dns_zone in dns_zones_without_vnets:
        # Add logic to include these DNS zones in your graph visualization
        logger.info(f"Adding orphaned DNS zone to graph: {dns_zone}")
        # Your existing graph node creation logic here...
    """

    print("\nIntegration Example:")
    print(integration_code)


if __name__ == "__main__":
    example_integration()
