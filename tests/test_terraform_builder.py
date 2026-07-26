"""Tests for Terraform JSON normalization into local template resources."""

import pytest

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
    assert vnet["properties"]["subnets"] == [
        {
            "name": "app",
            "properties": {
                "addressPrefix": "10.10.1.0/24",
            },
        }
    ]

    subnet = resources["Microsoft.Network/virtualNetworks/subnets:core-vnet/app"]
    assert subnet["properties"]["addressPrefix"] == "10.10.1.0/24"

    web_app = resources["Microsoft.Web/sites:api-web"]
    assert web_app["properties"]["virtualNetworkSubnetId"] == (
        "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'core-vnet', 'app')]"
    )
    assert web_app["dependsOn"] == [
        "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'core-vnet', 'app')]"
    ]


def test_terraform_builder_maps_aks_and_sql_resources() -> None:
    """Terraform JSON should preserve AKS subnet integration and Azure SQL server types."""
    builder = TerraformTemplateBuilder()

    terraform_plan = {
        "format_version": "1.0",
        "terraform_version": "1.8.5",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "azurerm_subnet.aks",
                        "mode": "managed",
                        "type": "azurerm_subnet",
                        "name": "aks",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "aks_subnet",
                            "virtual_network_name": "test-vnet-01",
                            "address_prefixes": ["10.0.4.0/23"],
                        },
                    },
                    {
                        "address": "azurerm_kubernetes_cluster.aks",
                        "mode": "managed",
                        "type": "azurerm_kubernetes_cluster",
                        "name": "aks",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "test-aks-01",
                            "location": "westeurope",
                            "default_node_pool": [
                                {
                                    "name": "nodepool1",
                                    "vnet_subnet_id": "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'test-vnet-01', 'aks_subnet')]",
                                }
                            ],
                        },
                    },
                    {
                        "address": "azurerm_mssql_server.sql",
                        "mode": "managed",
                        "type": "azurerm_mssql_server",
                        "name": "sql",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "test-sql-data",
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
                        "address": "azurerm_subnet.aks",
                        "expressions": {
                            "virtual_network_name": {
                                "constant_value": "test-vnet-01",
                            }
                        },
                    },
                    {
                        "address": "azurerm_kubernetes_cluster.aks",
                        "expressions": {
                            "default_node_pool": [
                                {
                                    "vnet_subnet_id": {
                                        "references": [
                                            "azurerm_subnet.aks.id",
                                            "azurerm_subnet.aks",
                                        ]
                                    }
                                }
                            ]
                        },
                    },
                    {
                        "address": "azurerm_mssql_server.sql",
                        "expressions": {
                            "name": {"constant_value": "test-sql-data"},
                        },
                    },
                ]
            }
        },
    }

    document = builder.build_document_from_json(terraform_plan)
    template = document.to_renderer_template()

    resources = {resource["type"] + ":" + resource["name"]: resource for resource in template["resources"]}

    aks = resources["Microsoft.ContainerService/managedClusters:test-aks-01"]
    assert aks["properties"]["agentPoolProfiles"][0]["vnetSubnetID"] == (
        "[resourceId('Microsoft.Network/virtualNetworks/subnets', 'test-vnet-01', 'aks_subnet')]"
    )

    sql = resources["Microsoft.Sql/servers:test-sql-data"]
    assert sql["type"] == "Microsoft.Sql/servers"


@pytest.mark.parametrize(
    ("content", "type_name"),
    [
        ("null", "NoneType"),
        ("[]", "list"),
        ("[1, 2, 3]", "list"),
        ("42", "int"),
        ("3.5", "float"),
        ('"plan"', "str"),
        ("true", "bool"),
    ],
)
def test_load_terraform_json_rejects_non_object_documents(tmp_path, content: str, type_name: str) -> None:
    """A Plan_File holding valid JSON that is not an object raises ValueError naming the type.

    Requirement 9.9: every Plan_File content that parses as JSON either yields a
    Change_Model or fails with `ValueError`, never another exception type.
    """
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(content, encoding="utf-8")

    builder = TerraformTemplateBuilder()

    with pytest.raises(ValueError) as error:
        builder.load_terraform_json(str(plan_file))

    assert type_name in str(error.value)


def test_build_terraform_template_reports_non_object_plan_file(tmp_path) -> None:
    """The build path reports a non-object Plan_File instead of crashing.

    Requirement 12.8: the builder's error path returns `None` and writes no template.
    """
    plan_file = tmp_path / "plan.json"
    plan_file.write_text("[]", encoding="utf-8")
    output_file = tmp_path / "template.json"

    result = TerraformTemplateBuilder().build_terraform_template(str(plan_file), str(output_file))

    assert result is None
    assert not output_file.exists()
