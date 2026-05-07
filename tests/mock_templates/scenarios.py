"""
Mock ARM Template Definitions for CloudHorus QA Testing.

Each function returns a dict (ARM template JSON) for a specific test scenario.
These bypass the Bicep build step and go directly into the graph generator.

Naming convention for IDs:
  Tenant:       test-tenant-{N}
  Subscription: test-sub-{N}        (e.g. test-sub-1, test-sub-2)
  Resource Group: test-rg-{scenario} (e.g. test-rg-network, test-rg-app)

All subnet IDs follow:
  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/
    virtualNetworks/{vnet}/subnets/{subnet}
"""

# ─── Constants ────────────────────────────────────────────────────────────────

SUB_1 = "test-sub-1"
SUB_2 = "test-sub-2"
TENANT_1 = "test-tenant-1"
TENANT_2 = "test-tenant-2"
RG_NETWORK = "test-rg-network"
RG_APP = "test-rg-app"
RG_DATA = "test-rg-data"
RG_CROSS = "test-rg-cross"
VNET_NAME = "test-vnet-01"


def _subnet_id(sub: str, rg: str, vnet: str, subnet: str) -> str:
    return (
        f"/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}"
    )


def _resource_id(sub: str, rg: str, provider: str, rtype: str, name: str) -> str:
    return f"/subscriptions/{sub}/resourceGroups/{rg}/providers/{provider}/{rtype}/{name}"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 1: Baseline — Single RG, VNet + subnets + resources + PEs
# ═══════════════════════════════════════════════════════════════════════════════


def baseline_network_template() -> dict:
    """
    Single RG with:
      - 1 VNet (4 subnets: AppGw, PE, WebApp, DB)
      - 1 NSG on AppGw subnet
      - 1 Route Table on WebApp subnet
      - 1 Web App with VNet integration to WebApp subnet
      - 1 App Service Plan
      - 1 SQL Server
      - 2 PEs (SQL + Storage) in PE subnet
      - 1 Private DNS Zone linked to VNet
      - 1 Bastion Host
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            # VNet with 4 subnets
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": VNET_NAME,
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {
                            "name": "AppGatewaySubnet",
                            "properties": {
                                "addressPrefix": "10.0.1.0/24",
                                "networkSecurityGroup": {
                                    "id": f"[resourceId('Microsoft.Network/networkSecurityGroups', 'test-nsg-appgw')]"
                                },
                            },
                        },
                        {
                            "name": "PrivateEndpointSubnet",
                            "properties": {
                                "addressPrefix": "10.0.2.0/24",
                                "privateEndpointNetworkPolicies": "Disabled",
                            },
                        },
                        {
                            "name": "WebAppSubnet",
                            "properties": {
                                "addressPrefix": "10.0.3.0/24",
                                "delegations": [
                                    {
                                        "name": "webapp-delegation",
                                        "properties": {"serviceName": "Microsoft.Web/serverFarms"},
                                    }
                                ],
                            },
                        },
                        {
                            "name": "DatabaseSubnet",
                            "properties": {
                                "addressPrefix": "10.0.4.0/24",
                                "serviceEndpoints": [{"service": "Microsoft.Sql"}],
                            },
                        },
                    ],
                },
                "dependsOn": [f"[resourceId('Microsoft.Network/networkSecurityGroups', 'test-nsg-appgw')]"],
            },
            # NSG
            {
                "type": "Microsoft.Network/networkSecurityGroups",
                "apiVersion": "2023-04-01",
                "name": "test-nsg-appgw",
                "location": "westeurope",
                "properties": {"securityRules": []},
            },
            # Route table
            {
                "type": "Microsoft.Network/routeTables",
                "apiVersion": "2023-04-01",
                "name": "test-rt-webapp",
                "location": "westeurope",
                "properties": {"routes": []},
            },
            # App Service Plan
            {
                "type": "Microsoft.Web/serverfarms",
                "apiVersion": "2022-09-01",
                "name": "test-asp-01",
                "location": "westeurope",
                "properties": {},
            },
            # Web App with VNet integration
            {
                "type": "Microsoft.Web/sites",
                "apiVersion": "2022-09-01",
                "name": "test-webapp-01",
                "location": "westeurope",
                "properties": {
                    "serverFarmId": f"[resourceId('Microsoft.Web/serverfarms', 'test-asp-01')]",
                    "virtualNetworkSubnetId": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "WebAppSubnet"),
                    "siteConfig": {"vnetRouteAllEnabled": True},
                },
                "dependsOn": [
                    f"[resourceId('Microsoft.Web/serverfarms', 'test-asp-01')]",
                    f"[resourceId('Microsoft.Network/virtualNetworks', '{VNET_NAME}')]",
                ],
            },
            # SQL Server
            {
                "type": "Microsoft.Sql/servers",
                "apiVersion": "2023-02-01-preview",
                "name": "test-sql-server-01",
                "location": "westeurope",
                "properties": {"administratorLogin": "sqladmin"},
            },
            # PE for SQL in PE subnet (same RG)
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-sql-01",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "PrivateEndpointSubnet")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-sql-01",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_NETWORK, "Microsoft.Sql", "servers", "test-sql-server-01"
                                ),
                                "groupIds": ["sqlServer"],
                            },
                        }
                    ],
                },
                "dependsOn": [
                    f"[resourceId('Microsoft.Network/virtualNetworks/subnets', '{VNET_NAME}', 'PrivateEndpointSubnet')]",
                    f"[resourceId('Microsoft.Sql/servers', 'test-sql-server-01')]",
                ],
            },
            # PE for Storage in PE subnet (same RG)
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-storage-01",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "PrivateEndpointSubnet")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-storage-01",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_NETWORK, "Microsoft.Storage", "storageAccounts", "teststorage01"
                                ),
                                "groupIds": ["blob"],
                            },
                        }
                    ],
                },
                "dependsOn": [
                    f"[resourceId('Microsoft.Network/virtualNetworks/subnets', '{VNET_NAME}', 'PrivateEndpointSubnet')]"
                ],
            },
            # Storage Account
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "teststorage01",
                "location": "westeurope",
                "properties": {},
            },
            # Private DNS Zone
            {
                "type": "Microsoft.Network/privateDnsZones",
                "apiVersion": "2020-06-01",
                "name": "privatelink.database.windows.net",
                "location": "global",
            },
            # Private DNS Zone VNet Link
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "apiVersion": "2020-06-01",
                "name": f"privatelink.database.windows.net/{VNET_NAME}-link",
                "location": "global",
                "properties": {
                    "registrationEnabled": False,
                    "virtualNetwork": {"id": f"[resourceId('Microsoft.Network/virtualNetworks', '{VNET_NAME}')]"},
                },
                "dependsOn": [
                    f"[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.database.windows.net')]",
                    f"[resourceId('Microsoft.Network/virtualNetworks', '{VNET_NAME}')]",
                ],
            },
            # Bastion Host
            {
                "type": "Microsoft.Network/bastionHosts",
                "apiVersion": "2023-04-01",
                "name": "test-bastion-01",
                "location": "westeurope",
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "IpConf",
                            "properties": {
                                "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "AzureBastionSubnet")},
                                "publicIPAddress": {
                                    "id": "[resourceId('Microsoft.Network/publicIPAddresses', 'test-bastion-pip')]"
                                },
                            },
                        }
                    ]
                },
                "dependsOn": [f"[resourceId('Microsoft.Network/virtualNetworks', '{VNET_NAME}')]"],
            },
            # Application Gateway
            {
                "type": "Microsoft.Network/applicationGateways",
                "apiVersion": "2023-04-01",
                "name": "test-appgw-01",
                "location": "westeurope",
                "properties": {
                    "gatewayIPConfigurations": [
                        {
                            "name": "appGwIpConfig",
                            "properties": {
                                "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "AppGatewaySubnet")}
                            },
                        }
                    ]
                },
                "dependsOn": [f"[resourceId('Microsoft.Network/virtualNetworks', '{VNET_NAME}')]"],
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 2: Cross-RG PE — PE in RG_APP connecting to subnet in RG_NETWORK
#  AND PE's privateLinkServiceConnection targets a service in RG_DATA
# ═══════════════════════════════════════════════════════════════════════════════


def cross_rg_network_template() -> dict:
    """RG_NETWORK: VNet + subnets (PE subnet, WebApp subnet, DB subnet)"""
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": VNET_NAME,
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {
                            "name": "pe_subnet",
                            "properties": {
                                "addressPrefix": "10.0.1.0/24",
                                "privateEndpointNetworkPolicies": "Disabled",
                            },
                        },
                        {
                            "name": "webapp_subnet",
                            "properties": {
                                "addressPrefix": "10.0.2.0/24",
                                "delegations": [
                                    {
                                        "name": "webapp-delegation",
                                        "properties": {"serviceName": "Microsoft.Web/serverFarms"},
                                    }
                                ],
                            },
                        },
                        {"name": "db_subnet", "properties": {"addressPrefix": "10.0.3.0/24"}},
                        {"name": "aks_subnet", "properties": {"addressPrefix": "10.0.4.0/23"}},
                    ],
                },
            },
        ],
    }


def cross_rg_app_template() -> dict:
    """
    RG_APP:
      - Web App with VNet integration to webapp_subnet in RG_NETWORK (cross-RG)
      - PE connecting to pe_subnet in RG_NETWORK with privateLinkServiceConnection to SQL in RG_DATA
      - AKS cluster with VNet integration to aks_subnet in RG_NETWORK
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            # App Service Plan
            {
                "type": "Microsoft.Web/serverfarms",
                "apiVersion": "2022-09-01",
                "name": "test-asp-cross",
                "location": "westeurope",
                "properties": {},
            },
            # Web App — VNet integration edge to cross-RG subnet
            {
                "type": "Microsoft.Web/sites",
                "apiVersion": "2022-09-01",
                "name": "test-webapp-cross",
                "location": "westeurope",
                "properties": {
                    "serverFarmId": f"[resourceId('Microsoft.Web/serverfarms', 'test-asp-cross')]",
                    "virtualNetworkSubnetId": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "webapp_subnet"),
                    "siteConfig": {"vnetRouteAllEnabled": True},
                },
                "dependsOn": [f"[resourceId('Microsoft.Web/serverfarms', 'test-asp-cross')]"],
            },
            # PE — subnet in RG_NETWORK, service connection to SQL in RG_DATA (cross-RG service)
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-sql-cross",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "pe_subnet")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-sql-cross",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_DATA, "Microsoft.Sql", "servers", "test-sql-data"
                                ),
                                "groupIds": ["sqlServer"],
                            },
                        }
                    ],
                },
                "dependsOn": [_subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "pe_subnet")],
            },
            # AKS cluster — VNet integration edge to cross-RG subnet
            {
                "type": "Microsoft.ContainerService/managedClusters",
                "apiVersion": "2023-07-01",
                "name": "test-aks-01",
                "location": "westeurope",
                "properties": {
                    "agentPoolProfiles": [
                        {
                            "name": "nodepool1",
                            "count": 3,
                            "vnetSubnetID": _subnet_id(SUB_1, RG_NETWORK, VNET_NAME, "aks_subnet"),
                        }
                    ]
                },
            },
        ],
    }


def cross_rg_data_template() -> dict:
    """RG_DATA: SQL Server (target of cross-RG PE from RG_APP)"""
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Sql/servers",
                "apiVersion": "2023-02-01-preview",
                "name": "test-sql-data",
                "location": "westeurope",
                "properties": {"administratorLogin": "sqladmin"},
            },
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "testdatastorage01",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 3: Cross-Tenant — PE in tenant-1 connecting to resource in tenant-2
# ═══════════════════════════════════════════════════════════════════════════════


def cross_tenant_network_template() -> dict:
    """Tenant-1 / Sub-1 / RG_NETWORK: VNet + subnets"""
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": "cross-tenant-vnet",
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.10.0.0/16"]},
                    "subnets": [
                        {
                            "name": "pe_cross_tenant",
                            "properties": {
                                "addressPrefix": "10.10.1.0/24",
                                "privateEndpointNetworkPolicies": "Disabled",
                            },
                        },
                        {"name": "app_subnet", "properties": {"addressPrefix": "10.10.2.0/24"}},
                    ],
                },
            },
        ],
    }


def cross_tenant_pe_template_local_first() -> dict:
    """
    Same as cross_tenant_pe_template but with the LOCAL (same-RG) PE listed
    FIRST in the resources list.  This triggers the merged-PE ordering bug:
    the first PE is hidden (same-RG only), polluting hidden_pe_nodes with the
    merged name; the second PE (cross-RG) then creates the node but its edges
    are skipped because the name is already in the hidden set.
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            # same-RG PE FIRST — triggers the bug when this PE is hidden
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-local-only",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "cross-tenant-vnet", "pe_cross_tenant")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-local-only",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_APP, "Microsoft.Storage", "storageAccounts", "localstorageaccount"
                                ),
                                "groupIds": ["blob"],
                            },
                        }
                    ],
                },
                "dependsOn": [],
            },
            # cross-RG PE SECOND — should survive and keep its edges
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-evhns-cross-tenant",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "cross-tenant-vnet", "pe_cross_tenant")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-evhns-cross-tenant",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_2, RG_CROSS, "Microsoft.EventHub", "namespaces", "evhns-cross-tenant-01"
                                ),
                                "groupIds": ["namespace"],
                            },
                        }
                    ],
                },
            },
            # Local storage (target of pe-local-only, same RG)
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "localstorageaccount",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


def cross_tenant_pe_template() -> dict:
    """
    Tenant-1 / Sub-1 / RG_APP:
      - PE connecting to subnet in RG_NETWORK (same tenant)
      - PE's privateLinkServiceConnection targets Event Hub in DIFFERENT subscription/tenant
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            # PE with cross-tenant service connection
            # NOTE: No dependsOn — real Bicep compiler strips cross-resource
            # dependsOn references.  The subnet relationship is captured via
            # properties.subnet.id which resource_processor parses.
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-evhns-cross-tenant",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "cross-tenant-vnet", "pe_cross_tenant")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-evhns-cross-tenant",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_2, RG_CROSS, "Microsoft.EventHub", "namespaces", "evhns-cross-tenant-01"
                                ),
                                "groupIds": ["namespace"],
                            },
                        }
                    ],
                },
            },
            # Another PE — same-tenant, same-RG service connection (no cross-RG dep)
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-local-only",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "cross-tenant-vnet", "pe_cross_tenant")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-local-only",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_APP, "Microsoft.Storage", "storageAccounts", "localstorageaccount"
                                ),
                                "groupIds": ["blob"],
                            },
                        }
                    ],
                },
                "dependsOn": [],
            },
            # Local storage (target of pe-local-only, same RG)
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "localstorageaccount",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


def cross_tenant_remote_template() -> dict:
    """Tenant-2 / Sub-2 / RG_CROSS: the Event Hub namespace targeted by cross-tenant PE"""
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.EventHub/namespaces",
                "apiVersion": "2023-01-01-preview",
                "name": "evhns-cross-tenant-01",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 4: Many PEs (stress test for PE optimization flags)
# ═══════════════════════════════════════════════════════════════════════════════


def many_pe_network_template() -> dict:
    """VNet with pe_01..pe_05 subnets"""
    subnets = [
        {
            "name": f"pe_{i:02d}",
            "properties": {"addressPrefix": f"10.0.{i}.0/24", "privateEndpointNetworkPolicies": "Disabled"},
        }
        for i in range(1, 6)
    ]
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": "many-pe-vnet",
                "location": "westeurope",
                "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}, "subnets": subnets},
            }
        ],
    }


def many_pe_app_template(num_pe: int = 10, cross_rg_indices: list = None) -> dict:
    """
    RG_APP with many PEs, some with cross-RG dependencies, some without.

    Args:
        num_pe: Total number of PEs to generate
        cross_rg_indices: Indices of PEs that have cross-RG service connections.
                          If None, defaults to [0, 3, 7] (3 out of 10).
    """
    if cross_rg_indices is None:
        cross_rg_indices = [0, 3, 7]

    resources = []
    for i in range(num_pe):
        subnet_name = f"pe_{(i % 5) + 1:02d}"
        pe_name = f"pe-svc-{i:02d}"

        if i in cross_rg_indices:
            # Cross-RG: service in RG_DATA (different RG)
            service_id = _resource_id(SUB_1, RG_DATA, "Microsoft.EventHub", "namespaces", f"evhns-svc-{i:02d}")
        else:
            # Same-RG: service in RG_APP itself (no cross-RG dependency)
            service_id = _resource_id(SUB_1, RG_APP, "Microsoft.Storage", "storageAccounts", f"storage-svc-{i:02d}")

        resources.append(
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": pe_name,
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "many-pe-vnet", subnet_name)},
                    "privateLinkServiceConnections": [
                        {
                            "name": pe_name,
                            "properties": {
                                "privateLinkServiceId": service_id,
                                "groupIds": ["namespace" if i in cross_rg_indices else "blob"],
                            },
                        }
                    ],
                },
                "dependsOn": [_subnet_id(SUB_1, RG_NETWORK, "many-pe-vnet", subnet_name)],
            }
        )

    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": resources,
    }


def many_pe_data_template(cross_rg_indices: list = None) -> dict:
    """
    RG_DATA: EventHub namespace targets for cross-RG PEs generated by
    many_pe_app_template().  Include this template in templates_by_rg so
    that the cross-RG PE connections are recognised by
    get_cross_resource_group_dependencies().
    """
    if cross_rg_indices is None:
        cross_rg_indices = [0, 3, 7]
    resources = []
    for i in cross_rg_indices:
        resources.append(
            {
                "type": "Microsoft.EventHub/namespaces",
                "apiVersion": "2023-01-01-preview",
                "name": f"evhns-svc-{i:02d}",
                "location": "westeurope",
                "properties": {},
            }
        )
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": resources,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 5: Empty subnets / Subnet optimization
# ═══════════════════════════════════════════════════════════════════════════════


def subnet_with_infra_only_template() -> dict:
    """
    VNet with 4 subnets:
      - integrated-subnet: has a Web App with VNet integration → should survive subnetOptimization
      - infra-only-subnet: has NSG + route table but NO VNet integration → should be hidden
      - pe-subnet: has a PE with no VNet integration → should be hidden
      - empty-subnet: completely empty → should be hidden
    Tests that subnetOptimization correctly hides subnets whose only residents
    are infrastructure resources (NSGs, route tables) without VNet integration.
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": "infra-vnet",
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {"name": "integrated-subnet", "properties": {"addressPrefix": "10.0.1.0/24"}},
                        {"name": "infra-only-subnet", "properties": {"addressPrefix": "10.0.2.0/24"}},
                        {
                            "name": "pe-subnet",
                            "properties": {
                                "addressPrefix": "10.0.3.0/24",
                                "privateEndpointNetworkPolicies": "Disabled",
                            },
                        },
                        {"name": "empty-subnet", "properties": {"addressPrefix": "10.0.4.0/24"}},
                    ],
                },
            },
            # Web App with VNet integration to integrated-subnet
            {
                "type": "Microsoft.Web/sites",
                "apiVersion": "2022-09-01",
                "name": "webapp-integrated",
                "location": "westeurope",
                "properties": {
                    "virtualNetworkSubnetId": _subnet_id(SUB_1, RG_NETWORK, "infra-vnet", "integrated-subnet")
                },
                "dependsOn": [],
            },
            # NSG attached to infra-only-subnet (creates a dependency on the subnet)
            {
                "type": "Microsoft.Network/networkSecurityGroups",
                "apiVersion": "2023-04-01",
                "name": "nsg-infra-only",
                "location": "westeurope",
                "properties": {},
                "dependsOn": [
                    "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'infra-vnet', 'infra-only-subnet')]"
                ],
            },
            # Route table attached to infra-only-subnet
            {
                "type": "Microsoft.Network/routeTables",
                "apiVersion": "2023-04-01",
                "name": "rt-infra-only",
                "location": "westeurope",
                "properties": {},
                "dependsOn": [
                    "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'infra-vnet', 'infra-only-subnet')]"
                ],
            },
            # PE in pe-subnet — no VNet integration, just sits in the subnet
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-no-integration",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "infra-vnet", "pe-subnet")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-no-integration",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_NETWORK, "Microsoft.Storage", "storageAccounts", "infrastorage01"
                                ),
                                "groupIds": ["blob"],
                            },
                        }
                    ],
                },
                "dependsOn": [],
            },
            # Storage account (PE target)
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "infrastorage01",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


def subnet_optimization_template() -> dict:
    """
    VNet with 8 subnets: 3 have resources, 5 are empty.
    Tests that subnetOptimization=True hides empty subnets.
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": "opt-vnet",
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {"name": "used-subnet-1", "properties": {"addressPrefix": "10.0.1.0/24"}},
                        {"name": "used-subnet-2", "properties": {"addressPrefix": "10.0.2.0/24"}},
                        {"name": "used-subnet-3", "properties": {"addressPrefix": "10.0.3.0/24"}},
                        {"name": "empty-subnet-1", "properties": {"addressPrefix": "10.0.4.0/24"}},
                        {"name": "empty-subnet-2", "properties": {"addressPrefix": "10.0.5.0/24"}},
                        {"name": "empty-subnet-3", "properties": {"addressPrefix": "10.0.6.0/24"}},
                        {"name": "empty-subnet-4", "properties": {"addressPrefix": "10.0.7.0/24"}},
                        {"name": "empty-subnet-5", "properties": {"addressPrefix": "10.0.8.0/24"}},
                    ],
                },
            },
            # Web App in used-subnet-1
            {
                "type": "Microsoft.Web/sites",
                "apiVersion": "2022-09-01",
                "name": "webapp-in-subnet",
                "location": "westeurope",
                "properties": {"virtualNetworkSubnetId": _subnet_id(SUB_1, RG_NETWORK, "opt-vnet", "used-subnet-1")},
                "dependsOn": [],
            },
            # PE in used-subnet-2
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-in-used-subnet",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "opt-vnet", "used-subnet-2")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-in-used-subnet",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_NETWORK, "Microsoft.Storage", "storageAccounts", "optstorage01"
                                ),
                                "groupIds": ["blob"],
                            },
                        }
                    ],
                },
                "dependsOn": [
                    f"[resourceId('Microsoft.Network/virtualNetworks/subnets', 'opt-vnet', 'used-subnet-2')]"
                ],
            },
            # App Gateway in used-subnet-3
            {
                "type": "Microsoft.Network/applicationGateways",
                "apiVersion": "2023-04-01",
                "name": "appgw-in-subnet",
                "location": "westeurope",
                "properties": {
                    "gatewayIPConfigurations": [
                        {
                            "name": "appGwIpConfig",
                            "properties": {
                                "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "opt-vnet", "used-subnet-3")}
                            },
                        }
                    ]
                },
                "dependsOn": [],
            },
            # Storage account (PE target, same RG)
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "optstorage01",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 6: Private DNS Zones — multiple zones linked/not linked to VNet
# ═══════════════════════════════════════════════════════════════════════════════


def dns_zones_template() -> dict:
    """
    Tests privateDnsZonesOptimization:
      - 1 VNet
      - 3 DNS zones linked to VNet (should aggregate when optimization=True)
      - 2 DNS zones NOT linked to VNet (should show individually regardless)
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": "dns-vnet",
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [{"name": "default", "properties": {"addressPrefix": "10.0.1.0/24"}}],
                },
            },
            # 3 DNS zones linked to VNet
            {
                "type": "Microsoft.Network/privateDnsZones",
                "apiVersion": "2020-06-01",
                "name": "privatelink.database.windows.net",
                "location": "global",
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "apiVersion": "2020-06-01",
                "name": "privatelink.blob.core.windows.net",
                "location": "global",
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "apiVersion": "2020-06-01",
                "name": "privatelink.vaultcore.azure.net",
                "location": "global",
            },
            # VNet links
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "apiVersion": "2020-06-01",
                "name": "privatelink.database.windows.net/dns-vnet-link",
                "location": "global",
                "properties": {
                    "virtualNetwork": {"id": f"[resourceId('Microsoft.Network/virtualNetworks', 'dns-vnet')]"},
                    "registrationEnabled": False,
                },
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.database.windows.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'dns-vnet')]",
                ],
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "apiVersion": "2020-06-01",
                "name": "privatelink.blob.core.windows.net/dns-vnet-link",
                "location": "global",
                "properties": {
                    "virtualNetwork": {"id": f"[resourceId('Microsoft.Network/virtualNetworks', 'dns-vnet')]"},
                    "registrationEnabled": False,
                },
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.blob.core.windows.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'dns-vnet')]",
                ],
            },
            {
                "type": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
                "apiVersion": "2020-06-01",
                "name": "privatelink.vaultcore.azure.net/dns-vnet-link",
                "location": "global",
                "properties": {
                    "virtualNetwork": {"id": f"[resourceId('Microsoft.Network/virtualNetworks', 'dns-vnet')]"},
                    "registrationEnabled": False,
                },
                "dependsOn": [
                    "[resourceId('Microsoft.Network/privateDnsZones', 'privatelink.vaultcore.azure.net')]",
                    "[resourceId('Microsoft.Network/virtualNetworks', 'dns-vnet')]",
                ],
            },
            # 2 DNS zones NOT linked to VNet (no virtualNetworkLinks)
            {
                "type": "Microsoft.Network/privateDnsZones",
                "apiVersion": "2020-06-01",
                "name": "privatelink.redis.cache.windows.net",
                "location": "global",
            },
            {
                "type": "Microsoft.Network/privateDnsZones",
                "apiVersion": "2020-06-01",
                "name": "privatelink.servicebus.windows.net",
                "location": "global",
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 7: VNet integration edge regression scenario
#  PE has VNet integration (cross-RG subnet) but NO cross-RG service connection
# ═══════════════════════════════════════════════════════════════════════════════


def vnet_integration_edge_network_template() -> dict:
    """RG_NETWORK: VNet with subnets"""
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": "vnet-integration-test",
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {
                            "name": "pe_subnet",
                            "properties": {
                                "addressPrefix": "10.0.1.0/24",
                                "privateEndpointNetworkPolicies": "Disabled",
                            },
                        },
                        {"name": "webapp_subnet", "properties": {"addressPrefix": "10.0.2.0/24"}},
                    ],
                },
            }
        ],
    }


def vnet_integration_edge_app_template() -> dict:
    """
    RG_APP:
      - Web App with VNet integration to webapp_subnet in RG_NETWORK (cross-RG) → should create royalblue edge
      - PE to pe_subnet in RG_NETWORK with privateLinkServiceConnection to service in RG_APP (same-RG, NOT cross-RG dep)
        → crossPeOptimization should NOT remove this PE because it has a VNet integration edge
      - PE to pe_subnet in RG_NETWORK with NO privateLinkServiceConnection to external service
        → crossPeOptimization + subnetOptimization: this PE previously disappeared (the bug!)
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Web/serverfarms",
                "apiVersion": "2022-09-01",
                "name": "asp-vnet-edge",
                "location": "westeurope",
                "properties": {},
            },
            # Web App → cross-RG VNet integration
            {
                "type": "Microsoft.Web/sites",
                "apiVersion": "2022-09-01",
                "name": "webapp-vnet-edge",
                "location": "westeurope",
                "properties": {
                    "serverFarmId": f"[resourceId('Microsoft.Web/serverfarms', 'asp-vnet-edge')]",
                    "virtualNetworkSubnetId": _subnet_id(SUB_1, RG_NETWORK, "vnet-integration-test", "webapp_subnet"),
                },
                "dependsOn": [f"[resourceId('Microsoft.Web/serverfarms', 'asp-vnet-edge')]"],
            },
            # PE with VNet integration (cross-RG subnet) and same-RG service connection
            # crossPeOptimization sees no cross-RG dep → but VNet integration must be preserved
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": "pe-with-vnet-integration",
                "location": "westeurope",
                "properties": {
                    "subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, "vnet-integration-test", "pe_subnet")},
                    "privateLinkServiceConnections": [
                        {
                            "name": "pe-with-vnet-integration",
                            "properties": {
                                "privateLinkServiceId": _resource_id(
                                    SUB_1, RG_APP, "Microsoft.Storage", "storageAccounts", "appstorage01"
                                ),
                                "groupIds": ["blob"],
                            },
                        }
                    ],
                },
                "dependsOn": [_subnet_id(SUB_1, RG_NETWORK, "vnet-integration-test", "pe_subnet")],
            },
            # Storage (same-RG target for the PE above)
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "appstorage01",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 8: Multiple resource types in subnets
#  (PostgreSQL, MySQL, APIM, Container Instance, Redis, etc.)
# ═══════════════════════════════════════════════════════════════════════════════


def diverse_resources_template() -> dict:
    """
    VNet with many subnet-integrated resource types to test handler coverage.
    """
    vnet = "diverse-vnet"
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": vnet,
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {"name": "postgres-subnet", "properties": {"addressPrefix": "10.0.1.0/24"}},
                        {"name": "mysql-subnet", "properties": {"addressPrefix": "10.0.2.0/24"}},
                        {"name": "apim-subnet", "properties": {"addressPrefix": "10.0.3.0/24"}},
                        {"name": "redis-subnet", "properties": {"addressPrefix": "10.0.4.0/24"}},
                        {"name": "aci-subnet", "properties": {"addressPrefix": "10.0.5.0/24"}},
                        {"name": "firewall-subnet", "properties": {"addressPrefix": "10.0.6.0/24"}},
                    ],
                },
            },
            # PostgreSQL Flexible Server
            {
                "type": "Microsoft.DBforPostgreSQL/flexibleServers",
                "apiVersion": "2022-12-01",
                "name": "test-postgres-flex",
                "location": "westeurope",
                "properties": {
                    "network": {"delegatedSubnetResourceId": _subnet_id(SUB_1, RG_NETWORK, vnet, "postgres-subnet")}
                },
            },
            # MySQL Flexible Server
            {
                "type": "Microsoft.DBforMySQL/flexibleServers",
                "apiVersion": "2023-06-30",
                "name": "test-mysql-flex",
                "location": "westeurope",
                "properties": {
                    "network": {"delegatedSubnetResourceId": _subnet_id(SUB_1, RG_NETWORK, vnet, "mysql-subnet")}
                },
            },
            # API Management
            {
                "type": "Microsoft.ApiManagement/service",
                "apiVersion": "2023-03-01-preview",
                "name": "test-apim",
                "location": "westeurope",
                "properties": {
                    "virtualNetworkConfiguration": {
                        "subnetResourceId": _subnet_id(SUB_1, RG_NETWORK, vnet, "apim-subnet")
                    }
                },
            },
            # Redis Cache
            {
                "type": "Microsoft.Cache/Redis",
                "apiVersion": "2023-08-01",
                "name": "test-redis",
                "location": "westeurope",
                "properties": {"subnetId": _subnet_id(SUB_1, RG_NETWORK, vnet, "redis-subnet")},
            },
            # Azure Firewall
            {
                "type": "Microsoft.Network/azureFirewalls",
                "apiVersion": "2023-04-01",
                "name": "test-firewall",
                "location": "westeurope",
                "properties": {
                    "ipConfigurations": [
                        {
                            "name": "fwIpConfig",
                            "properties": {"subnet": {"id": _subnet_id(SUB_1, RG_NETWORK, vnet, "firewall-subnet")}},
                        }
                    ]
                },
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 9: Ghost resources — resource appears in wrong RG's export
# ═══════════════════════════════════════════════════════════════════════════════


def ghost_resource_network_template() -> dict:
    """
    RG_NETWORK: VNet + subnets.
    Also "ghost" exports a Web App that actually belongs to RG_APP
    (because it depends on a subnet here).
    The graph generator should suppress this duplicate.
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Network/virtualNetworks",
                "apiVersion": "2023-04-01",
                "name": "ghost-vnet",
                "location": "westeurope",
                "properties": {
                    "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                    "subnets": [
                        {"name": "app-subnet", "properties": {"addressPrefix": "10.0.1.0/24"}},
                    ],
                },
            },
            # GHOST: This web app actually belongs to RG_APP but shows up here
            # because Azure's template export includes cross-RG dependencies
            {
                "type": "Microsoft.Web/sites",
                "apiVersion": "2022-09-01",
                "name": "ghost-webapp",
                "location": "westeurope",
                "properties": {"virtualNetworkSubnetId": _subnet_id(SUB_1, RG_NETWORK, "ghost-vnet", "app-subnet")},
                "dependsOn": [],
            },
        ],
    }


def ghost_resource_app_template() -> dict:
    """
    RG_APP: The REAL owner of ghost-webapp.
    This webapp should be rendered here, not in RG_NETWORK.
    """
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Web/sites",
                "apiVersion": "2022-09-01",
                "name": "ghost-webapp",
                "location": "westeurope",
                "properties": {"virtualNetworkSubnetId": _subnet_id(SUB_1, RG_NETWORK, "ghost-vnet", "app-subnet")},
                "dependsOn": [],
            },
            {
                "type": "Microsoft.Web/serverfarms",
                "apiVersion": "2022-09-01",
                "name": "ghost-asp",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 10: Minimal — just resources, no VNet
# ═══════════════════════════════════════════════════════════════════════════════


def no_vnet_template() -> dict:
    """RG with only standalone resources (no VNet, no subnets)"""
    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "resources": [
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": "standalone-storage",
                "location": "westeurope",
                "properties": {},
            },
            {
                "type": "Microsoft.Sql/servers",
                "apiVersion": "2023-02-01-preview",
                "name": "standalone-sql",
                "location": "westeurope",
                "properties": {},
            },
            {
                "type": "Microsoft.Insights/components",
                "apiVersion": "2020-02-02",
                "name": "standalone-appinsights",
                "location": "westeurope",
                "properties": {},
            },
            {
                "type": "Microsoft.KeyVault/vaults",
                "apiVersion": "2023-02-01",
                "name": "standalone-kv",
                "location": "westeurope",
                "properties": {},
            },
        ],
    }
