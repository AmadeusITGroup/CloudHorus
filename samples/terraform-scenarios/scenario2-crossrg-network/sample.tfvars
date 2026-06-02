location           = "westeurope"
resource_group_name = "test-rg-network"
vnet_name          = "test-vnet-01"
vnet_address_space = ["10.0.0.0/16"]
pe_subnet_prefix   = ["10.0.1.0/24"]
webapp_subnet_prefix = ["10.0.2.0/24"]
db_subnet_prefix   = ["10.0.3.0/24"]
aks_subnet_prefix  = ["10.0.4.0/23"]