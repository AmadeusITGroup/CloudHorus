// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 4: Many PEs — App RG with 10 PEs (3 cross-RG, 7 same-RG)
//  RG: test-rg-app | SUB: test-sub-1 | TENANT: test-tenant-1
//  PE indices 0, 3, 7 have cross-RG deps to test-rg-data (EventHub)
//  Others target same-RG storage accounts
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID')
param subscriptionId string

@description('Network RG name')
param networkRg string

@description('App RG name')
param appRg string

@description('Data RG name')
param dataRg string

@description('Location for all resources')
param location string = 'westeurope'

// ── PE 00 — Cross-RG (EventHub in RG_DATA) ──────────────────────────────────
resource pe00 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-00'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_01'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-00'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${dataRg}/providers/Microsoft.EventHub/namespaces/evhns-svc-00'
          groupIds: ['namespace']
        }
      }
    ]
  }
}

// ── PE 01 — Same-RG (Storage in RG_APP) ─────────────────────────────────────
resource pe01 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-01'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_02'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-01'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/storage-svc-01'
          groupIds: ['blob']
        }
      }
    ]
  }
}

// ── PE 02 — Same-RG ─────────────────────────────────────────────────────────
resource pe02 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-02'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_03'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-02'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/storage-svc-02'
          groupIds: ['blob']
        }
      }
    ]
  }
}

// ── PE 03 — Cross-RG (EventHub in RG_DATA) ──────────────────────────────────
resource pe03 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-03'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_04'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-03'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${dataRg}/providers/Microsoft.EventHub/namespaces/evhns-svc-03'
          groupIds: ['namespace']
        }
      }
    ]
  }
}

// ── PE 04 — Same-RG ─────────────────────────────────────────────────────────
resource pe04 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-04'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_05'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-04'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/storage-svc-04'
          groupIds: ['blob']
        }
      }
    ]
  }
}

// ── PE 05 — Same-RG ─────────────────────────────────────────────────────────
resource pe05 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-05'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_01'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-05'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/storage-svc-05'
          groupIds: ['blob']
        }
      }
    ]
  }
}

// ── PE 06 — Same-RG ─────────────────────────────────────────────────────────
resource pe06 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-06'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_02'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-06'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/storage-svc-06'
          groupIds: ['blob']
        }
      }
    ]
  }
}

// ── PE 07 — Cross-RG (EventHub in RG_DATA) ──────────────────────────────────
resource pe07 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-07'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_03'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-07'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${dataRg}/providers/Microsoft.EventHub/namespaces/evhns-svc-07'
          groupIds: ['namespace']
        }
      }
    ]
  }
}

// ── PE 08 — Same-RG ─────────────────────────────────────────────────────────
resource pe08 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-08'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_04'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-08'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/storage-svc-08'
          groupIds: ['blob']
        }
      }
    ]
  }
}

// ── PE 09 — Same-RG ─────────────────────────────────────────────────────────
resource pe09 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: 'pe-svc-09'
  location: location
  properties: {
    subnet: {
      id: '/subscriptions/${subscriptionId}/resourceGroups/${networkRg}/providers/Microsoft.Network/virtualNetworks/many-pe-vnet/subnets/pe_05'
    }
    privateLinkServiceConnections: [
      {
        name: 'pe-svc-09'
        properties: {
          privateLinkServiceId: '/subscriptions/${subscriptionId}/resourceGroups/${appRg}/providers/Microsoft.Storage/storageAccounts/storage-svc-09'
          groupIds: ['blob']
        }
      }
    ]
  }
}
