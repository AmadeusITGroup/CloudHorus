// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 2: Cross-RG — App RG with Web App, PE (cross-RG deps), AKS
//  RG: test-rg-app | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID')
param subscriptionId string

@description('Network RG name')
param networkRg string

@description('Data RG name')
param dataRg string

@description('VNet name in network RG')
param vnetName string

@description('Location for all resources')
param location string = 'westeurope'

// ── App Service Plan ─────────────────────────────────────────────────────────
resource asp 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: 'test-asp-cross'
  location: location
  properties: {}
}

// ── Web App — VNet integration to cross-RG subnet ───────────────────────────
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: 'test-webapp-cross'
  location: location
  properties: {
    serverFarmId: asp.id
    virtualNetworkSubnetId: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/webapp_subnet'
    siteConfig: {
      vnetRouteAllEnabled: true
    }
  }
  dependsOn: [
    asp
  ]
}

// ── PE — subnet in RG_NETWORK, service connection to SQL in RG_DATA ─────────
resource peSqlCross 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-sql-cross'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/pe_subnet'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-sql-cross'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${dataRg}/providers/Microsoft.Sql/servers/test-sql-data'
          groupIds: [
            'sqlServer'
          ]
        }
      }
    ]
  }
}

// ── AKS — VNet integration to cross-RG subnet ──────────────────────────────
resource aks 'Microsoft.ContainerService/managedClusters@2023-07-01' = {
  name: 'test-aks-01'
  location: location
  properties: {
    agentPoolProfiles: [
      {
        name: 'nodepool1'
        count: 3
        vmSize: 'Standard_DS2_v2'
        mode: 'System'
        vnetSubnetID: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/aks_subnet'
      }
    ]
  }
}
