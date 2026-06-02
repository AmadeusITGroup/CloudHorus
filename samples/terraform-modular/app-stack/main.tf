module "app" {
  source = "../modules/app"

  location              = var.location
  resource_group_name   = var.resource_group_name
  service_plan_name     = var.service_plan_name
  web_app_name          = var.web_app_name
  private_dns_zone_name = var.private_dns_zone_name
  dns_link_name         = var.dns_link_name
  private_endpoint_name = var.private_endpoint_name
  vnet_id               = var.vnet_id
  subnet_id             = var.subnet_id
}