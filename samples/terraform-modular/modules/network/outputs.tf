output "vnet_id" {
  value = azurerm_virtual_network.core.id
}

output "subnet_id" {
  value = azurerm_subnet.app.id
}