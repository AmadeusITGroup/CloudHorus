"""Unit tests for sensitive value redaction in the Terraform plan builder.

Covers Requirement 10.1: values a plan marks sensitive through `before_sensitive`,
`after_sensitive` or a planned resource's `sensitive_values` become the literal
`(sensitive)`, and every other leaf survives untouched.
"""

from core.terraform_builder import TerraformTemplateBuilder

SENSITIVE = "(sensitive)"


def _builder() -> TerraformTemplateBuilder:
    return TerraformTemplateBuilder()


# ─── _redact_sensitive ────────────────────────────────────────────────────────


def test_redact_flags_only_masked_scalar_leaves() -> None:
    """A flagged leaf is replaced; siblings keep their exact values."""
    values = {"name": "db", "administrator_password": "p@ssw0rd", "port": 5432}
    mask = {"administrator_password": True, "port": False}

    redacted = _builder()._redact_sensitive(values, mask)

    assert redacted == {"name": "db", "administrator_password": SENSITIVE, "port": 5432}


def test_redact_leaves_values_untouched_when_mask_is_absent_or_empty() -> None:
    """No mask, a falsey mask, and an empty dict mask all preserve the tree."""
    builder = _builder()
    values = {"name": "db", "tags": {"env": "prod"}, "prefixes": ["10.0.0.0/24"]}

    assert builder._redact_sensitive(values, None) == values
    assert builder._redact_sensitive(values, False) == values
    assert builder._redact_sensitive(values, {}) == values


def test_redact_masks_whole_subtree_when_mask_is_true() -> None:
    """`True` above a container redacts the container as one opaque value."""
    values = {"identity": {"principal_id": "abc", "tenant_id": "def"}, "name": "app"}

    redacted = _builder()._redact_sensitive(values, {"identity": True})

    assert redacted == {"identity": SENSITIVE, "name": "app"}


def test_redact_walks_nested_dicts_and_lists_in_parallel() -> None:
    """Masks align with dict keys and list indices at any depth."""
    values = {
        "site_config": {"app_settings": [{"name": "URL", "value": "https://x"}, {"name": "KEY", "value": "s3cret"}]},
        "address_prefixes": ["10.0.1.0/24", "10.0.2.0/24"],
    }
    mask = {
        "site_config": {"app_settings": [{}, {"value": True}]},
        "address_prefixes": [False, False],
    }

    redacted = _builder()._redact_sensitive(values, mask)

    assert redacted["site_config"]["app_settings"][0] == {"name": "URL", "value": "https://x"}
    assert redacted["site_config"]["app_settings"][1] == {"name": "KEY", "value": SENSITIVE}
    assert redacted["address_prefixes"] == ["10.0.1.0/24", "10.0.2.0/24"]


def test_redact_tolerates_a_shorter_list_mask() -> None:
    """List entries beyond the mask length are not sensitive."""
    redacted = _builder()._redact_sensitive(["a", "b", "c"], [True])

    assert redacted == [SENSITIVE, "b", "c"]


def test_redact_tolerates_shape_mismatch_between_tree_and_mask() -> None:
    """A container mask over a scalar (or the reverse) flags nothing."""
    builder = _builder()

    assert builder._redact_sensitive("plain", {"name": True}) == "plain"
    assert builder._redact_sensitive(["a"], {"0": True}) == ["a"]


def test_redact_does_not_mutate_the_input_tree() -> None:
    """Redaction returns new containers instead of editing the plan in place."""
    values = {"secrets": {"password": "hunter2"}}

    redacted = _builder()._redact_sensitive(values, {"secrets": {"password": True}})

    assert redacted == {"secrets": {"password": SENSITIVE}}
    assert values == {"secrets": {"password": "hunter2"}}


# ─── _sensitive_mask_for ──────────────────────────────────────────────────────

PLAN = {
    "format_version": "1.0",
    "planned_values": {
        "root_module": {
            "resources": [
                {
                    "address": "azurerm_mssql_server.db",
                    "mode": "managed",
                    "type": "azurerm_mssql_server",
                    "name": "db",
                    "provider_name": "registry.terraform.io/hashicorp/azurerm",
                    "values": {"name": "db-sql", "administrator_login_password": "p@ss"},
                    "sensitive_values": {"administrator_login_password": True},
                }
            ],
            "child_modules": [
                {
                    "address": "module.web",
                    "resources": [
                        {
                            "address": "module.web.azurerm_linux_web_app.api",
                            "mode": "managed",
                            "type": "azurerm_linux_web_app",
                            "name": "api",
                            "provider_name": "registry.terraform.io/hashicorp/azurerm",
                            "values": {"name": "api-web"},
                            "sensitive_values": {"custom_domain_verification_id": True},
                        }
                    ],
                }
            ],
        }
    },
    "resource_changes": [
        {
            "address": "azurerm_mssql_server.db",
            "mode": "managed",
            "type": "azurerm_mssql_server",
            "name": "db",
            "provider_name": "registry.terraform.io/hashicorp/azurerm",
            "change": {
                "actions": ["update"],
                "before": {"name": "db-sql", "administrator_login_password": "old"},
                "after": {"name": "db-sql", "administrator_login_password": "p@ss"},
                "before_sensitive": {"administrator_login_password": True},
                "after_sensitive": {"administrator_login_password": True, "name": False},
            },
        },
        {
            "address": "azurerm_storage_account.gone",
            "mode": "managed",
            "type": "azurerm_storage_account",
            "name": "gone",
            "provider_name": "registry.terraform.io/hashicorp/azurerm",
            "change": {
                "actions": ["delete"],
                "before": {"name": "goneacct", "primary_access_key": "abc"},
                "after": None,
                "before_sensitive": {"primary_access_key": True},
            },
        },
    ],
}


def test_mask_for_after_phase_uses_after_sensitive() -> None:
    mask = _builder()._sensitive_mask_for(PLAN, "azurerm_mssql_server.db", "after")

    assert mask == {"administrator_login_password": True, "name": False}


def test_mask_for_before_phase_uses_before_sensitive() -> None:
    mask = _builder()._sensitive_mask_for(PLAN, "azurerm_storage_account.gone", "before")

    assert mask == {"primary_access_key": True}


def test_mask_for_before_phase_does_not_fall_back_to_sensitive_values() -> None:
    """`sensitive_values` describes the planned (after) state only."""
    plan = {
        "planned_values": PLAN["planned_values"],
        "resource_changes": [
            {
                "address": "azurerm_mssql_server.db",
                "change": {"actions": ["update"], "after_sensitive": {"administrator_login_password": True}},
            }
        ],
    }

    assert _builder()._sensitive_mask_for(plan, "azurerm_mssql_server.db", "before") is None


def test_mask_for_after_phase_falls_back_to_planned_sensitive_values() -> None:
    """Without `after_sensitive`, the planned resource's own markers apply."""
    plan = {
        "planned_values": PLAN["planned_values"],
        "resource_changes": [{"address": "azurerm_mssql_server.db", "change": {"actions": ["update"]}}],
    }

    mask = _builder()._sensitive_mask_for(plan, "azurerm_mssql_server.db", "after")

    assert mask == {"administrator_login_password": True}


def test_mask_for_resolves_addresses_inside_child_modules() -> None:
    mask = _builder()._sensitive_mask_for(PLAN, "module.web.azurerm_linux_web_app.api", "after")

    assert mask == {"custom_domain_verification_id": True}


def test_mask_for_returns_none_for_unknown_address_phase_or_malformed_plan() -> None:
    builder = _builder()

    assert builder._sensitive_mask_for(PLAN, "azurerm_subnet.missing", "after") is None
    assert builder._sensitive_mask_for(PLAN, "azurerm_mssql_server.db", "during") is None
    assert builder._sensitive_mask_for({"resource_changes": "not-a-list"}, "azurerm_subnet.app", "after") is None
    assert builder._sensitive_mask_for({}, "azurerm_subnet.app", "before") is None


def test_mask_and_redact_compose_for_a_planned_resource() -> None:
    """The resolved mask redacts exactly the flagged leaf of the planned values."""
    builder = _builder()
    values = PLAN["planned_values"]["root_module"]["resources"][0]["values"]

    mask = builder._sensitive_mask_for(PLAN, "azurerm_mssql_server.db", "after")
    redacted = builder._redact_sensitive(values, mask)

    assert redacted == {"name": "db-sql", "administrator_login_password": SENSITIVE}

# ─── _build_resource_properties over a redacted nested block ──────────────────
#
# A mask may flag a whole nested block (`ip_configuration: True`), in which case
# `_redact_sensitive` replaces the entire list with the literal `(sensitive)`. The property
# builder must then simply not mine that block for subnet or service ids instead of assuming a
# list of dicts (Requirements 10.1, 12.8), while a normal block still yields the same properties
# as before (Requirement 8.1).

_REDACTED_BLOCK_CASES = [
    (
        "azurerm_kubernetes_cluster",
        "default_node_pool",
        "agentPoolProfiles",
        [{"name": "np1", "vnet_subnet_id": "/subnets/aks"}],
        [{"name": "np1", "vnetSubnetID": "/subnets/aks"}],
    ),
    (
        "azurerm_private_endpoint",
        "private_service_connection",
        "privateLinkServiceConnections",
        [{"private_connection_resource_id": "/storageAccounts/sa1"}],
        [{"properties": {"privateLinkServiceId": "/storageAccounts/sa1"}}],
    ),
    (
        "azurerm_bastion_host",
        "ip_configuration",
        "ipConfigurations",
        [{"name": "ipconfig", "subnet_id": "/subnets/bastion"}],
        [{"name": "ipconfig", "properties": {"subnet": {"id": "/subnets/bastion"}}}],
    ),
    (
        "azurerm_application_gateway",
        "gateway_ip_configuration",
        "gatewayIPConfigurations",
        [{"name": "gateway", "subnet_id": "/subnets/appgw"}],
        [{"name": "gateway", "properties": {"subnet": {"id": "/subnets/appgw"}}}],
    ),
]


def test_build_resource_properties_mines_a_normal_block() -> None:
    """Legacy parity: a list of block objects still produces the same renderer properties."""
    builder = _builder()

    for terraform_type, block_key, property_key, block, expected in _REDACTED_BLOCK_CASES:
        properties = builder._build_resource_properties(terraform_type, {"name": "res", block_key: block})

        assert properties[property_key] == expected, terraform_type


def test_build_resource_properties_skips_a_redacted_block() -> None:
    """A block replaced by `(sensitive)` yields no ids and raises nothing."""
    builder = _builder()

    for terraform_type, block_key, property_key, _block, _expected in _REDACTED_BLOCK_CASES:
        properties = builder._build_resource_properties(terraform_type, {"name": "res", block_key: SENSITIVE})

        assert property_key not in properties, terraform_type


def test_build_resource_properties_skips_non_dict_entries_inside_a_block() -> None:
    """A partially redacted block keeps its object entries and ignores the scalar ones."""
    builder = _builder()

    for terraform_type, block_key, property_key, block, expected in _REDACTED_BLOCK_CASES:
        properties = builder._build_resource_properties(
            terraform_type, {"name": "res", block_key: [SENSITIVE, *block, None]}
        )

        assert properties[property_key] == expected, terraform_type


def test_build_resource_properties_keeps_unredacted_siblings_of_a_redacted_block() -> None:
    """A private endpoint whose connection block is masked keeps its subnet reference."""
    properties = _builder()._build_resource_properties(
        "azurerm_private_endpoint",
        {"name": "pe", "subnet_id": "/subnets/data", "private_service_connection": SENSITIVE},
    )

    assert properties == {"subnet": {"id": "/subnets/data"}}


def test_document_builds_when_a_plan_marks_a_whole_block_sensitive() -> None:
    """End to end: an opaque sensitive block renders a masked resource instead of crashing."""
    values = {
        "name": "bastion-hub",
        "location": "westeurope",
        "ip_configuration": [{"name": "ipconfig", "subnet_id": "/subnets/AzureBastionSubnet"}],
    }
    plan = {
        "format_version": "1.0",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": "azurerm_bastion_host.hub",
                        "mode": "managed",
                        "type": "azurerm_bastion_host",
                        "name": "hub",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": values,
                    }
                ]
            }
        },
        "resource_changes": [
            {
                "address": "azurerm_bastion_host.hub",
                "mode": "managed",
                "type": "azurerm_bastion_host",
                "name": "hub",
                "provider_name": "registry.terraform.io/hashicorp/azurerm",
                "change": {
                    "actions": ["update"],
                    "before": values,
                    "after": values,
                    "after_sensitive": {"ip_configuration": True},
                },
            }
        ],
    }

    from core.plan_diff import ChangeExtractor

    document = _builder().build_document_from_json(plan, change_model=ChangeExtractor().extract(plan["resource_changes"]))

    resource = document.resources[0]
    assert resource.change_category == "update"
    assert resource.raw_values["ip_configuration"] == SENSITIVE
    assert "ipConfigurations" not in resource.properties

    emitted = resource.to_renderer_resource()
    assert emitted["type"] == "Microsoft.Network/bastionHosts"
    assert emitted["name"] == "bastion-hub"
    assert emitted["changeCategory"] == "update"
