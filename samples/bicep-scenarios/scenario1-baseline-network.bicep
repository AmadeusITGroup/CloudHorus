// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 1: Baseline — Single RG, VNet + subnets + resources + PEs
//  RG: test-rg-network | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID for resource references')
param subscriptionId string

@description('Resource group name')
param resourceGroupName string

@description('VNet name')
param vnetName string

@description('Location for all resources')
param location string = 'westeurope'

// ── NSG ──────────────────────────────────────────────────────────────────────
resource nsgAppGw 'Microsoft.Network/networkSecurityGroups@2023-04-01' = {
  name: 'test-nsg-appgw'
  location: location
  properties: {
    securityRules: []
  }
}

// ── Route Table ──────────────────────────────────────────────────────────────
resource routeTable 'Microsoft.Network/routeTables@2023-04-01' = {
  name: 'test-rt-webapp'
  location: location
  properties: {
    routes: []
  }
}

// ── VNet with 4 subnets ─────────────────────────────────────────────────────
resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'AppGatewaySubnet'
        properties: {
          addressPrefix: '10.0.1.0/24'
          networkSecurityGroup: {
            id: nsgAppGw.id
          }
        }
      }
      {
        name: 'PrivateEndpointSubnet'
        properties: {
          addressPrefix: '10.0.2.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'WebAppSubnet'
        properties: {
          addressPrefix: '10.0.3.0/24'
          delegations: [
            {
              name: 'webapp-delegation'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
        }
      }
      {
        name: 'DatabaseSubnet'
        properties: {
          addressPrefix: '10.0.4.0/24'
          serviceEndpoints: [
            {
              service: 'Microsoft.Sql'
            }
          ]
        }
      }
    ]
  }
  dependsOn: [
    nsgAppGw
  ]
}

// ── App Service Plan ─────────────────────────────────────────────────────────
resource asp 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: 'test-asp-01'
  location: location
  properties: {}
}

// ── Web App with VNet Integration ────────────────────────────────────────────
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: 'test-webapp-01'
  location: location
  properties: {
    serverFarmId: asp.id
    virtualNetworkSubnetId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/WebAppSubnet'
    siteConfig: {
      vnetRouteAllEnabled: true
    }
  }
  dependsOn: [
    asp
    vnet
  ]
}

// ── SQL Server ───────────────────────────────────────────────────────────────
resource sqlServer 'Microsoft.Sql/servers@2023-02-01-preview' = {
  name: 'test-sql-server-01'
  location: location
  properties: {
    administratorLogin: 'sqladmin'
  }
}

// ── PE for SQL ───────────────────────────────────────────────────────────────
resource peSql 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-sql-01'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/PrivateEndpointSubnet'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-sql-01'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Sql/servers/test-sql-server-01'
          groupIds: [
            'sqlServer'
          ]
        }
      }
    ]
  }
  dependsOn: [
    vnet
    sqlServer
  ]
}

// ── PE for Storage ───────────────────────────────────────────────────────────
resource peStorage 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-storage-01'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/PrivateEndpointSubnet'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-storage-01'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Storage/storageAccounts/teststorage01'
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
  dependsOn: [
    vnet
  ]
}

// ── Storage Account ──────────────────────────────────────────────────────────
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'teststorage01'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {}
}

// ── Private DNS Zone ─────────────────────────────────────────────────────────
resource dnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.database.windows.net'
  location: 'global'
}

// ── DNS Zone VNet Link ───────────────────────────────────────────────────────
resource dnsVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: dnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

// ── Bastion Host ─────────────────────────────────────────────────────────────
resource bastion 'Microsoft.Network/bastionHosts@2023-04-01' = {
  name: 'test-bastion-01'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'IpConf'
        properties: {
          subnet: {
            id: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/AzureBastionSubnet'
          }
          publicIPAddress: {
            id: resourceId('Microsoft.Network/publicIPAddresses', 'test-bastion-pip')
          }
        }
      }
    ]
  }
  dependsOn: [
    vnet
  ]
}

// ── Application Gateway ─────────────────────────────────────────────────────
resource appGw 'Microsoft.Network/applicationGateways@2023-04-01' = {
  name: 'test-appgw-01'
  location: location
  properties: {
    gatewayIPConfigurations: [
      {
        name: 'appGwIpConfig'
        properties: {
          subnet: {
            id: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/AppGatewaySubnet'
          }
        }
      }
    ]
  }
  dependsOn: [
    vnet
  ]
}
