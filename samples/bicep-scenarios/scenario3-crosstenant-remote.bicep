// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 3: Cross-Tenant — Remote RG with Event Hub (Tenant-2 / Sub-2)
//  RG: test-rg-cross | SUB: test-sub-2 | TENANT: test-tenant-2
// ═══════════════════════════════════════════════════════════════════════════════

@description('Location for all resources')
param location string = 'westeurope'

resource eventHub 'Microsoft.EventHub/namespaces@2023-01-01-preview' = {
  name: 'evhns-cross-tenant-01'
  location: location
  properties: {}
}
