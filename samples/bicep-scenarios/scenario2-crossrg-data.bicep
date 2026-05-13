// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 2: Cross-RG — Data RG with SQL Server (PE target)
//  RG: test-rg-data | SUB: test-sub-1 | TENANT: test-tenant-1
// ═══════════════════════════════════════════════════════════════════════════════

@description('Location for all resources')
param location string = 'westeurope'

resource sqlServer 'Microsoft.Sql/servers@2023-02-01-preview' = {
  name: 'test-sql-data'
  location: location
  properties: {
    administratorLogin: 'sqladmin'
  }
}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: 'testdatastorage01'
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {}
}
