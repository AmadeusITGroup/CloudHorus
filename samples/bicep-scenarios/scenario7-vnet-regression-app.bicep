// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 7: VNet Integration Edge Regression — App RG
//  RG: test-rg-app | SUB: test-sub-1 | TENANT: test-tenant-1
//  Tests: PE with VNet integration (cross-RG subnet) but same-RG service conn
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID')
param subscriptionId string

@description('Network RG name')
param networkRg string

@description('App RG name')
param appRg string

@description('Location for all resources')
param location string = 'westeurope'

// ── App Service Plan ─────────────────────────────────────────────────────────
resource asp 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: 'asp-vnet-edge'
  location: location
  properties: {}
}

// ── Web App — cross-RG VNet integration ─────────────────────────────────────
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: 'webapp-vnet-edge'
  location: location
  properties: {
    serverFarmId: asp.id
    virtualNetworkSubnetId: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/vnet-integration-test/subnets/webapp_subnet'
  }
  dependsOn: [
    asp
  ]
}

// ── PE — cross-RG subnet, same-RG service connection ────────────────────────
resource pe 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-with-vnet-integration'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/vnet-integration-test/subnets/pe_subnet'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-with-vnet-integration'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/appstorage01'
          groupIds: ['blob']
        }
      }
    ]
  }
}

// ── Storage (same-RG target for PE) ─────────────────────────────────────────
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'appstorage01'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {}
}
