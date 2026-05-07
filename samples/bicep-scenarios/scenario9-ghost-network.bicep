// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 9: Ghost Resources — Network RG with VNet + ghost Web App
//  RG: test-rg-network | SUB: test-sub-1 | TENANT: test-tenant-1
//  The ghost-webapp appears here because it depends on a subnet in this VNet
//  but actually belongs to test-rg-app
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID')
param subscriptionId string

@description('Resource group name')
param resourceGroupName string

@description('Location for all resources')
param location string = 'westeurope'

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'ghost-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'app-subnet'
        properties: {
          addressPrefix: '10.0.1.0/24'
        }
      }
    ]
  }
}

// GHOST: This web app appears here due to cross-RG dependency export
// but actually belongs to test-rg-app
resource ghostWebApp 'Microsoft.Web/sites@2022-09-01' = {
  name: 'ghost-webapp'
  location: location
  properties: {
    virtualNetworkSubnetId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/ghost-vnet/subnets/app-subnet'
  }
}
