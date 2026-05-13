# -*- coding: utf-8 -*-
"""
Integration example showing how to use the enhanced get_bastion_host_name function
with both Azure portal and Bicep template support.
"""

import json
import os
import sys

# Add the src directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))


def example_template_with_bastion_infrastructure():
    """Example ARM template with comprehensive Bastion Host infrastructure."""
    return {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "enterprise-hub-vnet",
                "location": "East US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.0.1.0/27"}},
                        {"name": "GatewaySubnet", "properties": {"addressPrefix": "10.0.2.0/27"}},
                        {"name": "management-subnet", "properties": {"addressPrefix": "10.0.10.0/24"}},
                    ],
                },
            },
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "dev-spoke-vnet",
                "location": "East US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.1.0.0/16"]},
                    "subnets": [{"name": "workload-subnet", "properties": {"addressPrefix": "10.1.1.0/24"}}],
                },
            },
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "prod-spoke-vnet",
                "location": "East US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.2.0.0/16"]},
                    "subnets": [
                        {"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.2.1.0/27"}},
                        {"name": "production-subnet", "properties": {"addressPrefix": "10.2.10.0/24"}},
                    ],
                },
            },
            {
                "type": "Microsoft.Network/publicIPAddresses",
                "name": "hub-bastion-pip",
                "location": "East US",
                "sku": {"name": "Standard"},
                "properties": {"publicIPAllocationMethod": "Static", "publicIPAddressVersion": "IPv4"},
            },
            {
                "type": "Microsoft.Network/publicIPAddresses",
                "name": "prod-bastion-pip",
                "location": "East US",
                "sku": {"name": "Standard"},
                "properties": {"publicIPAllocationMethod": "Static", "publicIPAddressVersion": "IPv4"},
            },
            {
                "type": "Microsoft.Network/bastionHosts",
                "name": "enterprise-hub-bastion",
                "location": "East US",
                "sku": {"name": "Standard"},
                "dependsOn": [
                    "[resourceId('Microsoft.Network/virtualNetworks', 'enterprise-hub-vnet')]",
                    "[resourceId('Microsoft.Network/publicIPAddresses', 'hub-bastion-pip')]",
                ],
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {
                                    "id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'enterprise-hub-vnet', 'AzureBastionSubnet')]"
                                },
                                "publicIPAddress": {
                                    "id": "[resourceId('Microsoft.Network/publicIPAddresses', 'hub-bastion-pip')]"
                                },
                            },
                        }
                    ]
                },
            },
            {
                "type": "Microsoft.Network/bastionHosts",
                "name": "production-bastion",
                "location": "East US",
                "sku": {"name": "Standard"},
                "dependsOn": [
                    "[resourceId('Microsoft.Network/virtualNetworks', 'prod-spoke-vnet')]",
                    "[resourceId('Microsoft.Network/publicIPAddresses', 'prod-bastion-pip')]",
                ],
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {
                                    "id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'prod-spoke-vnet', 'AzureBastionSubnet')]"
                                },
                                "publicIPAddress": {
                                    "id": "[resourceId('Microsoft.Network/publicIPAddresses', 'prod-bastion-pip')]"
                                },
                            },
                        }
                    ]
                },
            },
            # Note: dev-spoke-vnet has no Bastion Host (relies on hub)
        ]
    }


def demonstrate_enhanced_bastion_functionality():
    """Demonstrate the enhanced get_bastion_host_name functionality."""
    print("Enhanced get_bastion_host_name Function Demo")
    print("=" * 45)

    # Create example template
    template = example_template_with_bastion_infrastructure()

    # Save template for reference
    with open("example_bastion_template.json", "w") as f:
        json.dump(template, f, indent=2)
    print("Created example_bastion_template.json for reference")
    print()

    try:
        print("Example Usage Scenarios:")
        print("-" * 25)

        print("1. Azure Portal Mode (use_local_template=False):")
        print("   bastion_name = get_bastion_host_name(")
        print("       vnet_name='enterprise-hub-vnet',")
        print("       resource_group='networking-rg',")
        print("       subscription_id='12345678-1234-1234-1234-123456789012',")
        print("       use_local_template=False")
        print("   )")
        print("   # Queries Azure portal for actual Bastion Host linked to VNet")
        print()

        print("2. Bicep Template Mode (use_local_template=True):")
        print("   bastion_name = get_bastion_host_name(")
        print("       vnet_name='enterprise-hub-vnet',")
        print("       resource_group='networking-rg',")
        print("       subscription_id='12345678-1234-1234-1234-123456789012',")
        print("       use_local_template=True,")
        print("       template_data=template_data")
        print("   )")
        print("   # Analyzes Bicep template for Bastion Host configuration")
        print()

        print("3. Expected Results from Template Analysis:")
        print("   - enterprise-hub-vnet -> 'enterprise-hub-bastion'")
        print("   - prod-spoke-vnet -> 'production-bastion'")
        print("   - dev-spoke-vnet -> None (no Bastion Host)")
        print()

        print("4. Integration in Graph Generator:")
        print("   # Check which VNets have Bastion Hosts")
        print("   for vnet_name in vnet_list:")
        print("       bastion_name = get_bastion_host_name(")
        print("           vnet_name=vnet_name,")
        print("           resource_group=resource_group,")
        print("           subscription_id=subscription_id,")
        print("           use_local_template=use_bicep_template,")
        print("           template_data=template_data if use_bicep_template else None")
        print("       )")
        print("       if bastion_name:")
        print("           print(f'VNet {vnet_name} has Bastion Host: {bastion_name}')")
        print("       else:")
        print("           print(f'VNet {vnet_name} has no Bastion Host')")
        print()

        print("5. Bastion Host Template Analysis Logic:")
        print("   - Searches for Microsoft.Network/bastionHosts resources")
        print("   - Extracts VNet name from subnet references in ipConfigurations")
        print("   - Handles ARM resourceId() function calls")
        print("   - Handles full resource ID paths")
        print("   - Returns first matching Bastion Host name")
        print()

        print("Benefits of Dual-Mode Support:")
        print("- Azure Portal Mode: Real-time data, current infrastructure state")
        print("- Bicep Template Mode: Planned deployments, infrastructure validation")
        print("- Backwards Compatibility: Existing code continues to work")
        print("- Consistent API: Same function interface for both modes")
        print("- Enhanced Graph Generation: Complete network topology including secure access")

    except Exception as e:
        print("Error in demonstration: " + str(e))


if __name__ == "__main__":
    demonstrate_enhanced_bastion_functionality()
