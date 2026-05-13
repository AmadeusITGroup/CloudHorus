// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 7: VNet Integration Edge Regression — Network RG
//  RG: test-rg-network | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Location for all resources')
param location string = 'westeurope'

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'vnet-integration-test'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'pe_subnet'
        properties: {
          addressPrefix: '10.0.1.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'webapp_subnet'
        properties: {
          addressPrefix: '10.0.2.0/24'
        }
      }
    ]
  }
}
