// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 3: Cross-Tenant — Network RG with VNet (Tenant-1 / Sub-1)
//  RG: test-rg-network | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Location for all resources')
param location string = 'westeurope'

resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'cross-tenant-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.10.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'pe_cross_tenant'
        properties: {
          addressPrefix: '10.10.1.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'app_subnet'
        properties: {
          addressPrefix: '10.10.2.0/24'
        }
      }
    ]
  }
}
