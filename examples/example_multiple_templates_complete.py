#!/usr/bin/env python3
"""
Complete example demonstrating multiple Bicep templates usage.
This example shows how to use the enhanced Azure CLI utility
to analyze multiple environments with proper mappings.
"""

import json


# Simulated template data (in practice, these would be loaded from files)
def get_sample_templates():
    """Create sample template data for demonstration"""

    # Production environment template
    prod_template = {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "prod-vnet-001",
                "location": "East US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.1.0.0/16"]},
                    "subnets": [
                        {"name": "AzureBastionSubnet", "properties": {"addressPrefix": "10.1.1.0/27"}},
                        {"name": "prod-subnet-001", "properties": {"addressPrefix": "10.1.2.0/24"}},
                        {"name": "prod-pe-subnet", "properties": {"addressPrefix": "10.1.3.0/24"}},
                    ],
                },
            },
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.database.windows.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.blob.core.windows.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.vault.azure.net"},
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.database.windows.net/prod-vnet-link",
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'prod-vnet-001')]"}
                },
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.blob.core.windows.net/prod-vnet-link",
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'prod-vnet-001')]"}
                },
            },
            {
                "type": "Microsoft.Network/bastionHosts",
                "name": "prod-bastion-001",
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {
                                    "id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'prod-vnet-001', 'AzureBastionSubnet')]"
                                }
                            },
                        }
                    ]
                },
            },
        ]
    }

    # Development environment template
    dev_template = {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "dev-vnet-001",
                "location": "Central US",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.2.0.0/16"]},
                    "subnets": [{"name": "dev-subnet-001", "properties": {"addressPrefix": "10.2.1.0/24"}}],
                },
            },
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.azurewebsites.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.database.windows.net"},
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.azurewebsites.net/dev-vnet-link",
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'dev-vnet-001')]"}
                },
            },
        ]
    }

    # Shared services template (no VNets, only DNS zones)
    shared_template = {
        "resources": [
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.servicebus.windows.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.redis.cache.windows.net"},
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.cognitiveservices.azure.com"},
        ]
    }

    # Staging environment template
    staging_template = {
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "name": "staging-vnet-001",
                "location": "West US 2",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.3.0.0/16"]},
                    "subnets": [{"name": "staging-subnet-001", "properties": {"addressPrefix": "10.3.1.0/24"}}],
                },
            },
            {"type": "Microsoft.Network/privateDnsZones", "name": "privatelink.database.windows.net"},
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "name": "privatelink.database.windows.net/staging-vnet-link",
                "properties": {
                    "virtualNetwork": {"id": "[resourceId('Microsoft.Network/virtualNetworks', 'staging-vnet-001')]"}
                },
            },
        ]
    }

    return {"prod": prod_template, "dev": dev_template, "shared": shared_template, "staging": staging_template}


def demonstrate_multiple_templates():
    """Demonstrate the complete workflow for multiple Bicep templates"""

    print("Multiple Bicep Templates - Complete Workflow Example")
    print("=" * 60)
    print()

    # For this demonstration, we'll use our simplified utility
    # In practice, you would use: from src.core.azure_cli import AzureUtility
    from test_multiple_templates_simple import SimplifiedAzureUtility

    az = SimplifiedAzureUtility()

    # Step 1: Get template data
    print("Step 1: Loading template data...")
    templates = get_sample_templates()
    print("✅ Loaded 4 environment templates (prod, dev, shared, staging)")
    print()

    # Step 2: Define environment mappings
    print("Step 2: Defining environment mappings...")

    # Define by order: templates, resource groups, subscriptions, tenants
    templates_data = [templates["prod"], templates["dev"], templates["shared"], templates["staging"]]

    resource_groups = [
        "rg-myapp-prod-001",  # Production
        "rg-myapp-dev-001",  # Development
        "rg-myapp-shared-001",  # Shared services
        "rg-myapp-staging-001",  # Staging
    ]

    subscriptions = [
        "12345678-1234-1234-1234-123456789001",  # Production subscription
        "12345678-1234-1234-1234-123456789002",  # Development subscription
        "12345678-1234-1234-1234-123456789003",  # Shared services subscription
        "12345678-1234-1234-1234-123456789004",  # Staging subscription
    ]

    tenants = [
        "tenant-corporate-aaa111",  # Corporate tenant (prod)
        "tenant-corporate-aaa111",  # Corporate tenant (dev)
        "tenant-shared-bbb222",  # Shared services tenant
        "tenant-corporate-aaa111",  # Corporate tenant (staging)
    ]

    print("Environment mappings:")
    for i, (rg, sub, tenant) in enumerate(zip(resource_groups, subscriptions, tenants)):
        env_name = ["Production", "Development", "Shared Services", "Staging"][i]
        print(f"  {env_name:15} | {rg:20} | {sub} | {tenant}")
    print()

    # Step 3: Register templates
    print("Step 3: Registering multiple templates...")
    success = az.register_multiple_bicep_templates(
        templates_data=templates_data, resource_groups=resource_groups, subscriptions=subscriptions, tenants=tenants
    )

    if not success:
        print("❌ Failed to register templates")
        return

    print("✅ Templates registered successfully")
    print()

    # Step 4: Verify registration
    print("Step 4: Verifying registration...")
    print(f"Using multiple templates: {az.is_using_multiple_templates()}")
    print(f"Registered resource groups: {len(az.get_all_registered_resource_groups())}")
    print(f"Registered subscriptions: {len(az.get_all_registered_subscriptions())}")
    print(f"Registered tenants: {len(az.get_all_registered_tenants())}")
    print()

    # Step 5: Test resource group to subscription mapping
    print("Step 5: Testing resource group to subscription mapping...")
    print("Resource Group → Subscription Mapping:")
    for rg in resource_groups:
        mapped_sub = az.get_subscription_for_resource_group(rg)
        print(f"  {rg} → {mapped_sub}")
    print()

    # Step 6: Test subscription to tenant mapping
    print("Step 6: Testing subscription to tenant mapping...")
    print("Subscription → Tenant Mapping:")
    for sub in az.get_all_registered_subscriptions():
        mapped_tenant = az.get_tenant_for_subscription(sub)
        print(f"  {sub} → {mapped_tenant}")
    print()

    # Step 7: Test resource group existence checks
    print("Step 7: Testing resource group existence with mappings...")
    test_cases = [
        # (resource_group, subscription, expected_result, description)
        ("rg-myapp-prod-001", "12345678-1234-1234-1234-123456789001", True, "Prod RG in correct subscription"),
        ("rg-myapp-dev-001", "12345678-1234-1234-1234-123456789002", True, "Dev RG in correct subscription"),
        ("rg-myapp-prod-001", "12345678-1234-1234-1234-123456789002", False, "Prod RG in wrong subscription"),
        ("rg-nonexistent", "12345678-1234-1234-1234-123456789001", False, "Non-existent RG"),
    ]

    print("Resource Group Existence Tests:")
    for rg, sub, expected, description in test_cases:
        result = az.is_resource_group_in_subscription(rg, sub, use_local_template=True)
        status = "✅ PASS" if result == expected else "❌ FAIL"
        print(f"  {status} | {description}")
        print(f"       Result: {result}, Expected: {expected}")
    print()

    # Step 8: Analyze each environment
    print("Step 8: Analyzing each environment...")
    print("Environment Analysis:")
    print("-" * 50)

    environments = [
        ("Production", "rg-myapp-prod-001"),
        ("Development", "rg-myapp-dev-001"),
        ("Shared Services", "rg-myapp-shared-001"),
        ("Staging", "rg-myapp-staging-001"),
    ]

    for env_name, rg in environments:
        print(f"\n{env_name} Environment ({rg}):")
        subscription = az.get_subscription_for_resource_group(rg)
        tenant = az.get_tenant_for_subscription(subscription)
        template_data = az.get_template_data_for_resource_group(rg)

        print(f"  Subscription: {subscription}")
        print(f"  Tenant: {tenant}")

        if template_data:
            resources = template_data.get("resources", [])
            resource_types = {}

            # Count resource types
            for resource in resources:
                res_type = resource.get("type", "Unknown")
                resource_types[res_type] = resource_types.get(res_type, 0) + 1

            print(f"  Resources: {len(resources)} total")
            for res_type, count in resource_types.items():
                print(f"    - {res_type}: {count}")

            # Check for VNets
            vnets = [r.get("name") for r in resources if r.get("type") == "Microsoft.Network/virtualNetworks"]
            if vnets:
                print(f"  Virtual Networks: {vnets}")

            # Check for DNS zones
            dns_zones = [r.get("name") for r in resources if r.get("type") == "Microsoft.Network/privateDnsZones"]
            if dns_zones:
                print(f"  Private DNS Zones: {dns_zones}")

            # Check for Bastion Hosts
            bastions = [r.get("name") for r in resources if r.get("type") == "Microsoft.Network/bastionHosts"]
            if bastions:
                print(f"  Bastion Hosts: {bastions}")

    print()
    print("=" * 60)
    print("✅ Multiple Bicep Templates demonstration completed successfully!")
    print()

    # Step 9: Show practical usage patterns
    print("Step 9: Practical usage patterns...")
    print()

    print("Pattern 1: Cross-environment resource discovery")
    print("Finding all environments with specific DNS zones:")
    target_zone = "privatelink.database.windows.net"

    for rg in az.get_all_registered_resource_groups():
        template_data = az.get_template_data_for_resource_group(rg)
        if template_data:
            dns_zones = [
                r.get("name")
                for r in template_data.get("resources", [])
                if r.get("type") == "Microsoft.Network/privateDnsZones"
            ]
            if target_zone in dns_zones:
                subscription = az.get_subscription_for_resource_group(rg)
                print(f"  ✅ {rg} (subscription: {subscription[:8]}...)")
    print()

    print("Pattern 2: Environment validation")
    print("Checking for environments without VNets (DNS-only):")

    for rg in az.get_all_registered_resource_groups():
        template_data = az.get_template_data_for_resource_group(rg)
        if template_data:
            has_vnets = any(
                r.get("type") == "Microsoft.Network/virtualNetworks" for r in template_data.get("resources", [])
            )
            has_dns = any(
                r.get("type") == "Microsoft.Network/privateDnsZones" for r in template_data.get("resources", [])
            )

            if not has_vnets and has_dns:
                print(f"  📍 {rg} - DNS-only environment")
    print()

    print("Pattern 3: Security analysis")
    print("Environments with Bastion Hosts (enhanced security):")

    for rg in az.get_all_registered_resource_groups():
        template_data = az.get_template_data_for_resource_group(rg)
        if template_data:
            bastions = [
                r.get("name")
                for r in template_data.get("resources", [])
                if r.get("type") == "Microsoft.Network/bastionHosts"
            ]
            if bastions:
                print(f"  🛡️ {rg} - Bastion: {bastions[0]}")
    print()


if __name__ == "__main__":
    demonstrate_multiple_templates()
