resource "azurerm_virtual_network" "scenario2" {
  name                = var.vnet_name
  location            = var.location
  resource_group_name = var.resource_group_name
  address_space       = var.vnet_address_space
}

resource "azurerm_subnet" "pe" {
  name                 = "pe_subnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.scenario2.name
  address_prefixes     = var.pe_subnet_prefix

  private_endpoint_network_policies = "Disabled"
}

resource "azurerm_subnet" "webapp" {
  name                 = "webapp_subnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.scenario2.name
  address_prefixes     = var.webapp_subnet_prefix

  delegation {
    name = "webapp-delegation"

    service_delegation {
      name = "Microsoft.Web/serverFarms"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/action",
      ]
    }
  }
}

resource "azurerm_subnet" "db" {
  name                 = "db_subnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.scenario2.name
  address_prefixes     = var.db_subnet_prefix
}

resource "azurerm_subnet" "aks" {
  name                 = "aks_subnet"
  resource_group_name  = var.resource_group_name
  virtual_network_name = azurerm_virtual_network.scenario2.name
  address_prefixes     = var.aks_subnet_prefix
}