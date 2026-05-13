// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 9: Ghost Resources — App RG (real owner of ghost-webapp)
//  RG: test-rg-app | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID')
param subscriptionId string

@description('Network RG name (where VNet lives)')
param networkRg string

@description('Location for all resources')
param location string = 'westeurope'

// This is the REAL owner of ghost-webapp
resource ghostWebApp 'Microsoft.Web/sites@2022-09-01' = {
  name: 'ghost-webapp'
  location: location
  properties: {
    virtualNetworkSubnetId: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/ghost-vnet/subnets/app-subnet'
  }
}

resource asp 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: 'ghost-asp'
  location: location
  properties: {}
}
