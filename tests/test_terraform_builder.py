"""Tests for Terraform JSON normalization into local template resources."""

from core.terraform_builder import TerraformTemplateBuilder


def test_terraform_builder_normalizes_azurerm_resources() -> None:
    """Terraform JSON should normalize into the existing local-template contract."""
    builder = TerraformTemplateBuilder()

    terraform_plan = {
        "format_version": "1.0",
        "terraform_version": "1.8.5",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "azurerm_virtual_network.core",
                        "mode": "managed",
                        "type": "azurerm_virtual_network",
                        "name": "core",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "core-vnet",
                            "location": "westeurope",
                            "address_space": ["10.10.0.0/16"],
                        },
                    },
                    {
                        "address": "azurerm_subnet.app",
                        "mode": "managed",
                        "type": "azurerm_subnet",
                        "name": "app",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "app",
                            "virtual_network_name": "core-vnet",
                            "address_prefixes": ["10.10.1.0/24"],
                        },
                    },
                    {
                        "address": "azurerm_linux_web_app.api",
                        "mode": "managed",
                        "type": "azurerm_linux_web_app",
                        "name": "api",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "api-web",
                            "location": "westeurope",
                        },
                    },
                ]
            }
        },
        "configuration": {
            "root_module": {
                "resources": [
                    {
                        "address": "azurerm_virtual_network.core",
                        "expressions": {
                            "name": {"constant_value": "core-vnet"},
                        },
                    },
                    {
                        "address": "azurerm_subnet.app",
                        "expressions": {
                            "virtual_network_name": {
                                "references": [
                                    "azurerm_virtual_network.core.name",
                                    "azurerm_virtual_network.core",
                                ]
                            }
                        },
                    },
                    {
                        "address": "azurerm_linux_web_app.api",
                        "expressions": {
                            "virtual_network_subnet_id": {
                                "references": [
                                    "azurerm_subnet.app.id",
                                    "azurerm_subnet.app",
                                ]
                            }
                        },
                    },
                ]
            }
        },
    }

    document = builder.build_document_from_json(terraform_plan)
    template = document.to_renderer_template()

    resources = {resource["type"] + ":" + resource["name"]: resource for resource in template["resources"]}

    vnet = resources["Microsoft.Network/virtualNetworks:core-vnet"]
    assert vnet["properties"]["addressSpace"]["addressPrefixes"] == ["10.10.0.0/16"]

    subnet = resources["Microsoft.Network/virtualNetworks/subnets:core-vnet/app"]
    assert subnet["properties"]["addressPrefix"] == "10.10.1.0/24"

    web_app = resources["Microsoft.Web/sites:api-web"]
    assert web_app["properties"]["virtualNetworkSubnetId"] == (
        "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'core-vnet', 'app')]"
    )
    assert web_app["dependsOn"] == [
        "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'core-vnet', 'app')]"
    ]