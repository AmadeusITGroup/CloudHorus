// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 5: Subnet Optimization — 8 subnets (3 used, 5 empty)
//  RG: test-rg-network | SUB: test-sub-1 | TENANT: test-tenant-1
//  subnetOptimization=True should hide the 5 empty subnets
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID')
param subscriptionId string

@description('Resource group name')
param resourceGroupName string

@description('Location for all resources')
param location string = 'westeurope'

// ── VNet with 8 subnets (3 used, 5 empty) ──────────────────────────────────
resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: 'opt-vnet'
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'used-subnet-1'
        properties: { addressPrefix: '10.0.1.0/24' }
      }
      {
        name: 'used-subnet-2'
        properties: { addressPrefix: '10.0.2.0/24' }
      }
      {
        name: 'used-subnet-3'
        properties: { addressPrefix: '10.0.3.0/24' }
      }
      {
        name: 'empty-subnet-1'
        properties: { addressPrefix: '10.0.4.0/24' }
      }
      {
        name: 'empty-subnet-2'
        properties: { addressPrefix: '10.0.5.0/24' }
      }
      {
        name: 'empty-subnet-3'
        properties: { addressPrefix: '10.0.6.0/24' }
      }
      {
        name: 'empty-subnet-4'
        properties: { addressPrefix: '10.0.7.0/24' }
      }
      {
        name: 'empty-subnet-5'
        properties: { addressPrefix: '10.0.8.0/24' }
      }
    ]
  }
}

// ── Web App in used-subnet-1 ─────────────────────────────────────────────────
resource webApp 'Microsoft.Web/sites@2022-09-01' = {
  name: 'webapp-in-subnet'
  location: location
  properties: {
    virtualNetworkSubnetId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/opt-vnet/subnets/used-subnet-1'
  }
}

// ── PE in used-subnet-2 ─────────────────────────────────────────────────────
resource pe 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-in-used-subnet'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/opt-vnet/subnets/used-subnet-2'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-in-used-subnet'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Storage/storageAccounts/optstorage01'
          groupIds: ['blob']
        }
      }
    ]
  }
  dependsOn: [
    vnet
  ]
}

// ── App Gateway in used-subnet-3 ────────────────────────────────────────────
resource appGw 'Microsoft.Network/applicationGateways@2023-04-01' = {
  name: 'appgw-in-subnet'
  location: location
  properties: {
    gatewayIPConfigurations: [
      {
        name: 'appGwIpConfig'
        properties: {
          subnet: {
            id: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/opt-vnet/subnets/used-subnet-3'
          }
        }
      }
    ]
  }
}

// ── Storage Account (PE target) ─────────────────────────────────────────────
resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'optstorage01'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {}
}
