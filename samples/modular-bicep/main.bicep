@description('Location for all resources')
param location string = 'eastus'

@description('Environment name (e.g., dev, test, prod)')
param environment string = 'dev'

@description('Application name prefix')
param appName string = 'myapp'

@description('Virtual Network address space')
param vnetAddressSpace string = '10.0.0.0/16'

@description('Application Gateway subnet address space')
param appGatewaySubnetAddressSpace string = '10.0.1.0/24'

@description('Private Endpoint subnet address space')
param privateEndpointSubnetAddressSpace string = '10.0.2.0/24'

@description('Web App subnet address space')
param webAppSubnetAddressSpace string = '10.0.3.0/24'

@description('AKS subnet address space')
param aksSubnetAddressSpace string = '10.0.4.0/24'

@description('Database subnet address space')
param databaseSubnetAddressSpace string = '10.0.5.0/24'

@description('Domain name for the application')
param domainName string = 'contoso.com'

@description('App Service Plan SKU')
param appServicePlanSku string = 'P1v3'

@description('SQL Database SKU')
param sqlDatabaseSku string = 'S2'

@description('Storage Account SKU')
param storageAccountSku string = 'Standard_ZRS'

@description('AKS node count')
param aksNodeCount int = 3

@description('AKS node VM size')
param aksNodeVMSize string = 'Standard_DS2_v2'

// Variables
var resourcePrefix = '${appName}-${environment}'
var tags = {
  Environment: environment
  Application: appName
  ManagedBy: 'Bicep'
}

// Deploy Network Infrastructure
module networkModule 'modules/network/network.bicep' = {
  name: 'networkDeployment'
  params: {
    location: location
    resourcePrefix: resourcePrefix
    vnetAddressSpace: vnetAddressSpace
    appGatewaySubnetAddressSpace: appGatewaySubnetAddressSpace
    privateEndpointSubnetAddressSpace: privateEndpointSubnetAddressSpace
    webAppSubnetAddressSpace: webAppSubnetAddressSpace
    aksSubnetAddressSpace: aksSubnetAddressSpace
    databaseSubnetAddressSpace: databaseSubnetAddressSpace
    domainName: domainName
    tags: tags
  }
}

// Deploy Security Infrastructure (depends on network)
module securityModule 'modules/security/security.bicep' = {
  name: 'securityDeployment'
  dependsOn: [
    networkModule
  ]
  params: {
    location: location
    resourcePrefix: resourcePrefix
    vnetId: networkModule.outputs.vnetId
    webAppSubnetId: networkModule.outputs.webAppSubnetId
    tags: tags
  }
}

// Deploy Data Infrastructure (depends on network and security)
module dataModule 'modules/data/data.bicep' = {
  name: 'dataDeployment'
  dependsOn: [
    networkModule
    securityModule
  ]
  params: {
    location: location
    resourcePrefix: resourcePrefix
    privateEndpointSubnetId: networkModule.outputs.privateEndpointSubnetId
    privateDnsZoneId: networkModule.outputs.privateDnsZoneId
    sqlDatabaseSku: sqlDatabaseSku
    storageAccountSku: storageAccountSku
    tags: tags
  }
}

// Deploy Compute Infrastructure (depends on all previous modules)
module computeModule 'modules/compute/compute.bicep' = {
  name: 'computeDeployment'
  dependsOn: [
    networkModule
    securityModule
    dataModule
  ]
  params: {
    location: location
    resourcePrefix: resourcePrefix
    appServicePlanSku: appServicePlanSku
    aksNodeCount: aksNodeCount
    aksNodeVMSize: aksNodeVMSize
    webAppSubnetId: networkModule.outputs.webAppSubnetId
    aksSubnetId: networkModule.outputs.aksSubnetId
    appGatewaySubnetId: networkModule.outputs.appGatewaySubnetId
    appGatewayPublicIPId: networkModule.outputs.appGatewayPublicIPId
    keyVaultUri: securityModule.outputs.keyVaultUri
    sqlServerFqdn: dataModule.outputs.sqlServerFqdn
    sqlDatabaseName: dataModule.outputs.sqlDatabaseName
    storageAccountName: dataModule.outputs.storageAccountName
    applicationInsightsInstrumentationKey: securityModule.outputs.applicationInsightsInstrumentationKey
    applicationInsightsConnectionString: securityModule.outputs.applicationInsightsConnectionString
    tags: tags
  }
}

// Outputs
output vnetId string = networkModule.outputs.vnetId
output appGatewayPublicIP string = networkModule.outputs.appGatewayPublicIP
output webAppUrl string = computeModule.outputs.webAppUrl
output aksClusterName string = computeModule.outputs.aksClusterName
output sqlServerFqdn string = dataModule.outputs.sqlServerFqdn
output keyVaultUri string = securityModule.outputs.keyVaultUri
output storageAccountName string = dataModule.outputs.storageAccountName
output applicationInsightsInstrumentationKey string = securityModule.outputs.applicationInsightsInstrumentationKey
