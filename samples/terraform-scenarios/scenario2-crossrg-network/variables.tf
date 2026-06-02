variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "vnet_name" {
  type = string
}

variable "vnet_address_space" {
  type = list(string)
}

variable "pe_subnet_prefix" {
  type = list(string)
}

variable "webapp_subnet_prefix" {
  type = list(string)
}

variable "db_subnet_prefix" {
  type = list(string)
}

variable "aks_subnet_prefix" {
  type = list(string)
}