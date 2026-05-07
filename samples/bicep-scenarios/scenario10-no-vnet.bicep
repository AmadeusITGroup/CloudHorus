// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 10: Minimal — No VNet, only standalone resources
//  RG: test-rg-network | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Location for all resources')
param location string = 'westeurope'

resource storage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'standalonestorage'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {}
}

resource sqlServer 'Microsoft.Sql/servers@2023-02-01-preview' = {
  name: 'standalone-sql'
  location: location
  properties: {
    administratorLogin: 'sqladmin'
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'standalone-appinsights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: 'standalone-kv'
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
  }
}
