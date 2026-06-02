location                    = "westeurope"
resource_group_name         = "rg-platform-network"
vnet_name                   = "core-vnet"
vnet_address_space          = ["10.10.0.0/16"]
subnet_name                 = "app"
subnet_prefixes             = ["10.10.1.0/24"]
network_security_group_name = "app-nsg"