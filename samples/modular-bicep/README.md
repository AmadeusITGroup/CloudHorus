# Modular Bicep Templates with Dependencies

This folder contains a comprehensive example of modular Bicep templates with dependencies, showcasing advanced Azure infrastructure patterns.

## 🏗️ Architecture Overview

The solution consists of two main templates:

### 1. **Core Infrastructure** (`main.bicep`)
- **Network Module**: VNet, subnets, NSGs, DNS zones, public IPs
- **Security Module**: Key Vault, Application Insights, Log Analytics, Managed Identity
- **Data Module**: SQL Server/Database, Storage Account, Cosmos DB with private endpoints
- **Compute Module**: App Service, Function App, AKS cluster, Application Gateway, Container Registry

### 2. **Dependent Services** (`main-dependent.bicep`)
- **Messaging**: Service Bus (queues, topics), Event Hub
- **Caching**: Redis Cache with private endpoint
- **Integration**: API Management, Logic Apps, Stream Analytics
- **Processing**: Container Instances leveraging existing infrastructure

## 📁 Project Structure

```
modular-bicep/
├── main.bicep                           # Core infrastructure template
├── main.parameters.json                 # Parameters for core template
├── main-dependent.bicep                 # Dependent services template
├── main-dependent.parameters.json       # Parameters for dependent template
├── deploy.sh                           # Bash deployment script
├── deploy.ps1                          # PowerShell deployment script
├── README.md                           # This file
└── modules/
    ├── network/
    │   └── network.bicep               # Network infrastructure module
    ├── security/
    │   └── security.bicep              # Security and monitoring module
    ├── data/
    │   └── data.bicep                  # Data services module
    └── compute/
        └── compute.bicep               # Compute services module
```

## 🌐 Network Architecture

### Subnets and Address Spaces
- **VNet**: `10.0.0.0/16`
- **Application Gateway Subnet**: `10.0.1.0/24`
- **Private Endpoint Subnet**: `10.0.2.0/24`
- **Web App Subnet**: `10.0.3.0/24`
- **AKS Subnet**: `10.0.4.0/24`
- **Database Subnet**: `10.0.5.0/24`

### Network Integration
- Application Gateway routes traffic to both App Service and AKS
- Private endpoints for all data services
- VNet integration for App Services and Function Apps
- Network Security Groups for traffic control

## 🔗 Resource Dependencies

### Core Template Dependencies
1. **Network** → **Security** → **Data** → **Compute**
2. Each module depends on outputs from previous modules
3. Proper dependency management ensures correct deployment order

### Dependent Template Dependencies
- References existing VNet, Storage Account, and Container Registry
- Creates services that extend the core infrastructure
- Maintains network isolation and security standards

## 🚀 Deployment Instructions

### Prerequisites
- Azure CLI installed and configured
- Appropriate Azure permissions
- PowerShell (for PowerShell script) or Bash (for shell script)

### Option 1: Using Bash Script
```bash
# Make the script executable
chmod +x deploy.sh

# Run the deployment
./deploy.sh
```

### Option 2: Using PowerShell Script
```powershell
# Run the deployment
./deploy.ps1
```

### Option 3: Manual Deployment
```bash
# Deploy core infrastructure first
az deployment group create \
    --resource-group myapp-dev-rg \
    --template-file main.bicep \
    --parameters @main.parameters.json

# Deploy dependent services second
az deployment group create \
    --resource-group myapp-dev-rg \
    --template-file main-dependent.bicep \
    --parameters @main-dependent.parameters.json
```

## 📊 Resources Created

### Core Infrastructure Template
- **Network**: VNet, 5 subnets, NSGs, public IP, DNS zones
- **Security**: Key Vault, App Insights, Log Analytics, Managed Identity
- **Data**: SQL Server/DB, Storage Account, Cosmos DB, Private Endpoints
- **Compute**: App Service Plan, Web App, Function App, AKS cluster, ACR, Application Gateway

### Dependent Services Template
- **Messaging**: Service Bus namespace, queue, topic, Event Hub
- **Caching**: Redis Cache with private endpoint
- **Integration**: API Management, Logic App, Stream Analytics job
- **Processing**: Container Instance with dependencies

## ⚙️ Configuration

### Core Template Parameters
- `location`: Azure region for deployment
- `environment`: Environment name (dev, test, prod)
- `appName`: Application name prefix
- Network address spaces for all subnets
- SKUs for various services
- AKS configuration (node count, VM size)

### Dependent Template Parameters
- References to existing core resources
- SKUs for new services (Redis, Service Bus, Event Hub)
- Service-specific configuration options

## 🔍 Key Features

### 1. **Modular Design**
- Separation of concerns across network, security, data, and compute
- Reusable modules with clear interfaces
- Parameterized for different environments

### 2. **Dependency Management**
- Proper resource dependencies using `dependsOn`
- Output/input parameter passing between modules
- Reference to existing resources in dependent template

### 3. **Network Security**
- Private endpoints for all data services
- Network Security Groups for traffic control
- VNet integration for compute services

### 4. **Application Gateway Integration**
- Routes traffic to both App Service and AKS
- Multiple backend pools and listeners
- Health probes and WAF protection

### 5. **AKS Integration**
- Dedicated subnet with proper network policies
- Integration with Container Registry
- RBAC enabled with system-assigned identity

### 6. **Monitoring and Security**
- Application Insights for telemetry
- Log Analytics workspace for centralized logging
- Key Vault for secrets management
- Managed Identity for secure access

## 🔧 Customization

### Network Configuration
- Modify subnet address spaces in parameters
- Add additional subnets in network module
- Configure NSG rules as needed

### Service Configuration
- Adjust SKUs based on requirements
- Add/remove services from modules
- Configure service-specific settings

### Security Configuration
- Modify Key Vault access policies
- Configure private endpoint settings
- Adjust NSG rules for security requirements

## 📈 Scaling Considerations

### Horizontal Scaling
- AKS cluster supports auto-scaling (min: 1, max: 5)
- App Service can scale based on metrics
- Function App scales automatically

### Vertical Scaling
- Modify VM sizes and SKUs in parameters
- Adjust database and cache tiers as needed
- Scale Application Gateway capacity

## 🛠️ Troubleshooting

### Common Issues
1. **Resource naming conflicts**: Ensure unique resource names
2. **Network connectivity**: Verify subnet configurations
3. **Permission issues**: Check RBAC assignments
4. **Dependency errors**: Review module dependencies

### Validation
```bash
# Validate templates before deployment
az deployment group validate \
    --resource-group myapp-dev-rg \
    --template-file main.bicep \
    --parameters @main.parameters.json
```

## 🔄 Updates and Maintenance

### Updating Templates
1. Modify individual modules as needed
2. Update parameters for configuration changes
3. Test in development environment first
4. Deploy with incremental mode for updates

### Adding New Services
1. Create new module or extend existing ones
2. Add appropriate parameters and outputs
3. Update main template to reference new module
4. Test thoroughly before production deployment

## 📝 Best Practices

- Use consistent naming conventions
- Implement proper tagging strategy
- Follow security best practices
- Document configuration changes
- Use version control for template management
- Test templates in development environment
- Monitor resource costs and performance

This modular approach provides a solid foundation for complex Azure infrastructures while maintaining flexibility and reusability.

