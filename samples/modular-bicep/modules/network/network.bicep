@description('Location for all resources')
param location string

@description('Resource prefix for naming')
param resourcePrefix string

@description('Virtual Network address space')
param vnetAddressSpace string

@description('Application Gateway subnet address space')
param appGatewaySubnetAddressSpace string

@description('Private Endpoint subnet address space')
param privateEndpointSubnetAddressSpace string

@description('Web App subnet address space')
param webAppSubnetAddressSpace string

@description('AKS subnet address space')
param aksSubnetAddressSpace string

@description('Database subnet address space')
param databaseSubnetAddressSpace string

@description('Domain name for the application')
param domainName string

@description('Resource tags')
param tags object

// Variables
var vnetName = '${resourcePrefix}-vnet'
var appGatewayName = '${resourcePrefix}-appgw'
var nsgName = '${resourcePrefix}-nsg'
var aksNsgName = '${resourcePrefix}-aks-nsg'
var privateDnsZoneName = 'privatelink.azurewebsites.net'
var publicDnsZoneName = domainName

// Network Security Group for Application Gateway
resource networkSecurityGroup 'Microsoft.Network/networkSecurityGroups@2023-04-01' = {
  name: nsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowHTTPS'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1000
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowHTTP'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '80'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1010
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowAppGatewayProbes'
        properties: {
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '65200-65535'
          sourceAddressPrefix: 'GatewayManager'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1020
          direction: 'Inbound'
        }
      }
    ]
  }
}

// Network Security Group for AKS
resource aksNetworkSecurityGroup 'Microsoft.Network/networkSecurityGroups@2023-04-01' = {
  name: aksNsgName
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowAKSInbound'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'VirtualNetwork'
          access: 'Allow'
          priority: 1000
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowLoadBalancerInbound'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1010
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowAKSOutbound'
        properties: {
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'VirtualNetwork'
          access: 'Allow'
          priority: 1000
          direction: 'Outbound'
        }
      }
    ]
  }
}

// Virtual Network
resource virtualNetwork 'Microsoft.Network/virtualNetworks@2023-04-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressSpace
      ]
    }
    subnets: [
      {
        name: 'AppGatewaySubnet'
        properties: {
          addressPrefix: appGatewaySubnetAddressSpace
          networkSecurityGroup: {
            id: networkSecurityGroup.id
          }
        }
      }
      {
        name: 'PrivateEndpointSubnet'
        properties: {
          addressPrefix: privateEndpointSubnetAddressSpace
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'WebAppSubnet'
        properties: {
          addressPrefix: webAppSubnetAddressSpace
          delegations: [
            {
              name: 'webapp-delegation'
              properties: {
                serviceName: 'Microsoft.Web/serverFarms'
              }
            }
          ]
          serviceEndpoints: [
            {
              service: 'Microsoft.KeyVault'
            }
            {
              service: 'Microsoft.Storage'
            }
          ]
        }
      }
      {
        name: 'AKSSubnet'
        properties: {
          addressPrefix: aksSubnetAddressSpace
          networkSecurityGroup: {
            id: aksNetworkSecurityGroup.id
          }
        }
      }
      {
        name: 'DatabaseSubnet'
        properties: {
          addressPrefix: databaseSubnetAddressSpace
          serviceEndpoints: [
            {
              service: 'Microsoft.Sql'
            }
          ]
        }
      }
    ]
  }
}

// Public IP for Application Gateway
resource appGatewayPublicIP 'Microsoft.Network/publicIPAddresses@2023-04-01' = {
  name: '${appGatewayName}-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    dnsSettings: {
      domainNameLabel: '${resourcePrefix}-appgw'
    }
  }
}

// Private DNS Zone
resource privateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: privateDnsZoneName
  location: 'global'
  tags: tags
}

// Private DNS Zone Virtual Network Link
resource privateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: privateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: virtualNetwork.id
    }
  }
}

// Public DNS Zone
resource publicDnsZone 'Microsoft.Network/dnsZones@2018-05-01' = {
  name: publicDnsZoneName
  location: 'global'
  tags: tags
}

// Route Table for AKS
resource aksRouteTable 'Microsoft.Network/routeTables@2023-04-01' = {
  name: '${resourcePrefix}-aks-rt'
  location: location
  tags: tags
  properties: {
    routes: [
      {
        name: 'default-route'
        properties: {
          addressPrefix: '0.0.0.0/0'
          nextHopType: 'Internet'
        }
      }
    ]
  }
}

// Outputs
output vnetId string = virtualNetwork.id
output vnetName string = virtualNetwork.name
output appGatewaySubnetId string = '${virtualNetwork.id}/subnets/AppGatewaySubnet'
output privateEndpointSubnetId string = '${virtualNetwork.id}/subnets/PrivateEndpointSubnet'
output webAppSubnetId string = '${virtualNetwork.id}/subnets/WebAppSubnet'
output aksSubnetId string = '${virtualNetwork.id}/subnets/AKSSubnet'
output databaseSubnetId string = '${virtualNetwork.id}/subnets/DatabaseSubnet'
output appGatewayPublicIPId string = appGatewayPublicIP.id
output appGatewayPublicIP string = appGatewayPublicIP.properties.ipAddress
output privateDnsZoneId string = privateDnsZone.id
output publicDnsZoneId string = publicDnsZone.id
output aksRouteTableId string = aksRouteTable.id
