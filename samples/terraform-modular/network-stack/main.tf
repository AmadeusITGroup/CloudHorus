module "network" {
  source = "../modules/network"

  location                    = var.location
  resource_group_name         = var.resource_group_name
  vnet_name                   = var.vnet_name
  vnet_address_space          = var.vnet_address_space
  subnet_name                 = var.subnet_name
  subnet_prefixes             = var.subnet_prefixes
  network_security_group_name = var.network_security_group_name
}