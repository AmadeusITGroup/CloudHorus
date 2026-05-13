# -*- coding: utf-8 -*-
"""
Integration example showing how to use the enhanced is_vnet_linked_to_private_dns_zone function
with both Azure portal and Bicep template support.
"""

import json
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def example_template_with_complex_vnet_links():
    """Example ARM template with complex VNet to DNS zone linking patterns."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "hub-vnet",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}},
            },
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "spoke-vnet",
                "location": "East US",
                "properties": {"addressSpace": {"addressPrefixes": ["10.1.0.0/16"]}},
            },
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
            {
                "type": "Microsoft.Network/privateDnsZones",
                "name": "privatelink.servicebus.windows.net",
                "location": "global",
                "properties": {},
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.azurewebsites.net/hub-vnet-link",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.azurewebsites.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'hub-vnet')]",
                ],
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'hub-vnet')]"},
                    "registrationEnabled": False,
                },
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.azurewebsites.net/spoke-vnet-link",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.azurewebsites.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'spoke-vnet')]",
                ],
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'spoke-vnet')]"},
                    "registrationEnabled": False,
                },
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.database.windows.net/hub-vnet-link",
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.database.windows.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'hub-vnet')]",
                ],
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'hub-vnet')]"},
                    "registrationEnabled": False,
                },
            },
            # Note: privatelink.servicebus.windows.net has no links
            # Note: spoke-vnet is only linked to privatelink.azurewebsites.net
        ]
    }


def demonstrate_enhanced_functionality():
    """Demonstrate the enhanced is_vnet_linked_to_private_dns_zone functionality."""
    print("Enhanced is_vnet_linked_to_private_dns_zone Function Demo")
    print("=" * 60)

    # Create example template
    template = example_template_with_complex_vnet_links()

    # Save template for reference
    with open("example_vnet_links_template.json", "w") as f:
        json.dump(template, f, indent=2)
    print("Created example_vnet_links_template.json for reference")
    print()

    try:
        # Import the enhanced function (mock version for demo)
        # In real usage, you would import from azure_cli:
        # from core.azure_cli import is_vnet_linked_to_private_dns_zone

        # For demonstration, we'll simulate the function calls
        print("Example Usage Scenarios:")
        print("-" * 25)

        print("1. Azure Portal Mode (use_local_template=False):")
        print("   linked_zones = is_vnet_linked_to_private_dns_zone(")
        print("       vnet_name='hub-vnet',")
        print("       resource_groups=['networking-rg'],")
        print("       subscription_id='12345678-1234-1234-1234-123456789012',")
        print("       use_local_template=False")
        print("   )")
        print("   # Queries Azure portal for actual DNS zone links")
        print()

        print("2. Bicep Template Mode (use_local_template=True):")
        print("   linked_zones = is_vnet_linked_to_private_dns_zone(")
        print("       vnet_name='hub-vnet',")
        print("       resource_groups=['networking-rg'],")
        print("       subscription_id='12345678-1234-1234-1234-123456789012',")
        print("       use_local_template=True,")
        print("       template_data=template_data")
        print("   )")
        print("   # Analyzes Bicep template for DNS zone links")
        print()

        print("3. Expected Results from Template Analysis:")
        print("   - hub-vnet links: ['privatelink.azurewebsites.net', 'privatelink.database.windows.net']")
        print("   - spoke-vnet links: ['privatelink.azurewebsites.net']")
        print("   - unlinked zones: ['privatelink.servicebus.windows.net']")
        print()

        print("4. Integration in Graph Generator:")
        print("   # Check if VNets are linked to specific DNS zones")
        print("   for vnet_name in vnet_list:")
        print("       linked_zones = is_vnet_linked_to_private_dns_zone(")
        print("           vnet_name=vnet_name,")
        print("           resource_groups=resource_groups,")
        print("           subscription_id=subscription_id,")
        print("           use_local_template=use_bicep_template,")
        print("           template_data=template_data if use_bicep_template else None")
        print("       )")
        print("       if linked_zones:")
        print("           print(f'VNet {vnet_name} is linked to: {linked_zones}')")
        print()

        print("Benefits of Dual-Mode Support:")
        print("- Azure Portal Mode: Real-time data, current state")
        print("- Bicep Template Mode: Planned deployments, template validation")
        print("- Backwards Compatibility: Existing code continues to work")
        print("- Consistent API: Same function interface for both modes")

    except Exception as e:
        print("Error in demonstration: " + str(e))


if __name__ == "__main__":
    demonstrate_enhanced_functionality()
