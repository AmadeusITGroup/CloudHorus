// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 3: Cross-Tenant — App RG with PEs (one cross-tenant, one local)
//  RG: test-rg-app | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID for this tenant')
param subscriptionId string

@description('Subscription ID for the remote tenant')
param remoteSubscriptionId string

@description('Network RG name')
param networkRg string

@description('App RG name')
param appRg string

@description('Remote RG name (in different tenant)')
param remoteRg string

@description('Location for all resources')
param location string = 'westeurope'

// ── PE with cross-tenant service connection ──────────────────────────────────
resource peCrossTenant 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-evhns-cross-tenant'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/cross-tenant-vnet/subnets/pe_cross_tenant'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-evhns-cross-tenant'
        properties: {
          privateLinkServiceId: '/subscriptions/${remoteSubscriptionId}/resourceGroups/${remoteRg}/providers/Microsoft.EventHub/namespaces/evhns-cross-tenant-01'
          groupIds: [
            'namespace'
          ]
        }
      }
    ]
  }
}

// ── PE with same-tenant, same-RG service connection (no cross-RG dep) ───────
resource peLocalOnly 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-local-only'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/cross-tenant-vnet/subnets/pe_cross_tenant'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-local-only'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/localstorageaccount'
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

// ── Local Storage (target of pe-local-only) ──────────────────────────────────
resource localStorage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'localstorageaccount'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {}
}
