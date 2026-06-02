resource "azurerm_service_plan" "cross" {
  name                = var.service_plan_name
  location            = var.location
  resource_group_name = var.resource_group_name
  os_type             = "Linux"
  sku_name            = "B1"
}

resource "azurerm_linux_web_app" "cross" {
  name                = var.web_app_name
  location            = var.location
  resource_group_name = var.resource_group_name
  service_plan_id     = azurerm_service_plan.cross.id

  virtual_network_subnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.network_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name}/subnets/webapp_subnet"

  site_config {
    minimum_tls_version  = "1.2"
    vnet_route_all_enabled = true
  }
}

resource "azurerm_private_endpoint" "sql_cross" {
  name                = var.private_endpoint_name
  location            = var.location
  resource_group_name = var.resource_group_name
  subnet_id           = "/subscriptions/${var.subscription_id}/resourceGroups/${var.network_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name}/subnets/pe_subnet"

  private_service_connection {
    name                           = var.private_endpoint_name
    private_connection_resource_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.data_resource_group_name}/providers/Microsoft.Sql/servers/${var.sql_server_name}"
    is_manual_connection           = false
    subresource_names              = ["sqlServer"]
  }
}

resource "azurerm_kubernetes_cluster" "cross" {
  name                = var.aks_name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = var.aks_dns_prefix

  identity {
    type = "SystemAssigned"
  }

  default_node_pool {
    name           = "nodepool1"
    node_count     = 3
    vm_size        = "Standard_DS2_v2"
    vnet_subnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.network_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name}/subnets/aks_subnet"
  }
}