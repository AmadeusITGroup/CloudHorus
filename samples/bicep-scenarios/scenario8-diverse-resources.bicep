// ═══════════════════════════════════════════════════════════════════════════════
//  SCENARIO 8: Diverse Resources — Many subnet-integrated resource types
//  RG: test-rg-network | SUB: test-sub-1 | TENANT: test-tenant-1
//  Tests: PostgreSQL, MySQL, APIM, Redis, Firewall handler coverage
// ═══════════════════════════════════════════════════════════════════════════════

@description('Subscription ID')
param subscriptionId string

@description('Resource group name')
param resourceGroupName string

@description('Location for all resources')
param location string = 'westeurope'

var vnetName = 'diverse-vnet'

// ── VNet with 6 subnets ─────────────────────────────────────────────────────
resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.0.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'postgres-subnet'
        properties: { addressPrefix: '10.0.1.0/24' }
      }
      {
        name: 'mysql-subnet'
        properties: { addressPrefix: '10.0.2.0/24' }
      }
      {
        name: 'apim-subnet'
        properties: { addressPrefix: '10.0.3.0/24' }
      }
      {
        name: 'redis-subnet'
        properties: { addressPrefix: '10.0.4.0/24' }
      }
      {
        name: 'aci-subnet'
        properties: { addressPrefix: '10.0.5.0/24' }
      }
      {
        name: 'firewall-subnet'
        properties: { addressPrefix: '10.0.6.0/24' }
      }
    ]
  }
}

// ── PostgreSQL Flexible Server ──────────────────────────────────────────────
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: 'test-postgres-flex'
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '14'
    network: {
      delegatedSubnetResourceId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/postgres-subnet'
    }
    storage: {
      storageSizeGB: 32
    }
  }
}

// ── MySQL Flexible Server ───────────────────────────────────────────────────
resource mysql 'Microsoft.DBforMySQL/flexibleServers@2023-06-30' = {
  name: 'test-mysql-flex'
  location: location
  sku: {
    name: 'Standard_B1ms'
    tier: 'Burstable'
  }
  properties: {
    version: '8.0.21'
    network: {
      delegatedSubnetResourceId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/mysql-subnet'
    }
    storage: {
      storageSizeGB: 20
    }
  }
}

// ── API Management ──────────────────────────────────────────────────────────
resource apim 'Microsoft.ApiManagement/service@2023-03-01-preview' = {
  name: 'test-apim'
  location: location
  sku: {
    name: 'Developer'
    capacity: 1
  }
  properties: {
    publisherEmail: 'admin@example.com'
    publisherName: 'Test Publisher'
    virtualNetworkConfiguration: {
      subnetResourceId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/apim-subnet'
    }
  }
}

// ── Redis Cache ─────────────────────────────────────────────────────────────
resource redis 'Microsoft.Cache/Redis@2023-08-01' = {
  name: 'test-redis'
  location: location
  properties: {
    sku: {
      name: 'Premium'
      family: 'P'
      capacity: 1
    }
    subnetId: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/redis-subnet'
  }
}

// ── Azure Firewall ──────────────────────────────────────────────────────────
resource firewall 'Microsoft.Network/azureFirewalls@2023-04-01' = {
  name: 'test-firewall'
  location: location
  properties: {
    ipConfigurations: [
      {
        name: 'fwIpConfig'
        properties: {
          subnet: {
            id: '/subscriptions/${subscriptionId}/resourceGroups/${resourceGroupName}/providers/Microsoft.Network/virtualNetworks/${vnetName}/subnets/firewall-subnet'
          }
        }
      }
    ]
  }
}
