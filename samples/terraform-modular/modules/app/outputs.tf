output "web_app_id" {
  value = azurerm_linux_web_app.api.id
}

output "private_endpoint_id" {
  value = azurerm_private_endpoint.web_pe.id
}