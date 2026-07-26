"""Unit tests for the plan diff change filter.

Covers Requirements 6.10 and 8.3 for ``parse_change_types``, and Requirements
6.3, 6.6 and 6.11 for ``ChangeFilter.apply`` direct selection plus container
retention.
"""

import copy

import pytest

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource
from core.plan_diff import (
    CHANGE_CATEGORIES,
    ChangeFilter,
    container_keys_in_value,
    parse_change_types,
    parse_resource_id_expression,
)

ACCEPTED = "create update replace delete unchanged"


class TestParseChangeTypesDefault:
    """``None`` means every Change_Category (Requirement 8.3)."""

    def test_none_selects_every_category(self):
        assert parse_change_types(None) == list(CHANGE_CATEGORIES)

    def test_none_returns_a_fresh_list_the_caller_may_mutate(self):
        first = parse_change_types(None)
        first.append("mutated")
        assert parse_change_types(None) == list(CHANGE_CATEGORIES)


class TestParseChangeTypesValidSelections:
    """Valid values pass through, normalized to canonical order without repeats."""

    @pytest.mark.parametrize("category", CHANGE_CATEGORIES)
    def test_each_category_is_accepted_on_its_own(self, category):
        assert parse_change_types([category]) == [category]

    def test_selection_is_returned_in_canonical_order(self):
        assert parse_change_types(["delete", "create", "replace"]) == ["create", "replace", "delete"]

    def test_repeated_values_are_deduplicated(self):
        assert parse_change_types(["update", "update"]) == ["update"]

    def test_order_does_not_affect_the_result(self):
        assert parse_change_types(["unchanged", "create"]) == parse_change_types(["create", "unchanged"])

    def test_a_tuple_selection_is_accepted(self):
        assert parse_change_types(("delete",)) == ["delete"]

    def test_a_bare_string_is_treated_as_a_single_value(self):
        assert parse_change_types("delete") == ["delete"]

    def test_an_empty_selection_selects_nothing(self):
        assert parse_change_types([]) == []


class TestParseChangeTypesInvalidSelections:
    """Anything outside the closed set raises, naming the accepted values (6.10)."""

    @pytest.mark.parametrize("value", ["foo", "Create", "CREATE", "", "no-op", "read"])
    def test_unknown_value_raises_value_error_naming_accepted_values(self, value):
        with pytest.raises(ValueError) as excinfo:
            parse_change_types([value])
        assert str(excinfo.value) == f"Invalid --changeTypes value '{value}'. Accepted values: {ACCEPTED}"

    def test_the_first_invalid_value_is_reported(self):
        with pytest.raises(ValueError) as excinfo:
            parse_change_types(["create", "bogus", "worse"])
        assert "'bogus'" in str(excinfo.value)

    def test_non_string_value_raises_value_error(self):
        with pytest.raises(ValueError) as excinfo:
            parse_change_types([None])
        assert str(excinfo.value) == f"Invalid --changeTypes value 'None'. Accepted values: {ACCEPTED}"

    def test_non_sequence_input_raises_value_error(self):
        with pytest.raises(ValueError) as excinfo:
            parse_change_types(42)
        assert str(excinfo.value) == f"Invalid --changeTypes value '42'. Accepted values: {ACCEPTED}"


class _DocumentFactory:
    """Small helpers building renderer documents shaped like builder output."""

    @staticmethod
    def resource(
        address,
        renderer_type,
        name,
        change_category=None,
        properties=None,
        depends_on=None,
    ):
        return LocalTemplateResource(
            address=address,
            provider_name="azurerm",
            source_type="terraform",
            renderer_type=renderer_type,
            name=name,
            properties=properties if properties is not None else {},
            depends_on=list(depends_on or []),
            change_category=change_category,
        )

    @staticmethod
    def document(resources, metadata=None):
        return LocalTemplateDocument(
            source_format="terraform",
            provider_name="azurerm",
            resources=list(resources),
            metadata=dict(metadata or {}),
        )


def _vnet(name, change_category="unchanged", subnets=None):
    properties = {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}
    if subnets is not None:
        properties["subnets"] = subnets
    return _DocumentFactory.resource(
        f"azurerm_virtual_network.{name}",
        "Microsoft.Network/virtualNetworks",
        name,
        change_category=change_category,
        properties=properties,
    )


def _subnet(vnet_name, subnet_name, change_category="unchanged"):
    return _DocumentFactory.resource(
        f"azurerm_subnet.{subnet_name}",
        "Microsoft.Network/virtualNetworks/subnets",
        f"{vnet_name}/{subnet_name}",
        change_category=change_category,
        properties={"addressPrefixes": ["10.0.1.0/24"]},
        depends_on=[f"[resourceId('Microsoft.Network/virtualNetworks', '{vnet_name}')]"],
    )


def _subnet_resource_id(vnet_name, subnet_name):
    return f"[resourceId('Microsoft.Network/virtualNetworks/subnets', '{vnet_name}', '{subnet_name}')]"


def _names(document):
    return [resource.name for resource in document.resources]


class TestChangeFilterConstruction:
    """The filter always describes a subset of the closed category set."""

    def test_none_selects_every_category(self):
        assert ChangeFilter().selected == frozenset(CHANGE_CATEGORIES)
        assert ChangeFilter(None).is_identity()

    def test_partial_selection_is_not_identity(self):
        assert not ChangeFilter(["delete"]).is_identity()

    def test_unknown_values_are_dropped(self):
        assert ChangeFilter(["delete", "bogus"]).selected == frozenset({"delete"})

    def test_selection_order_and_repetition_do_not_matter(self):
        assert ChangeFilter(["delete", "create", "delete"]).selected == ChangeFilter(("create", "delete")).selected


class TestChangeFilterPurity:
    """``apply`` returns a new document and leaves its input untouched."""

    def test_returns_a_new_document_instance(self):
        document = _DocumentFactory.document([_vnet("vnet", "create")])
        result = ChangeFilter(["create"]).apply(document)
        assert result is not document
        assert result.resources[0] is not document.resources[0]

    def test_input_resources_are_not_mutated(self):
        subnet = _subnet("vnet", "web", "delete")
        document = _DocumentFactory.document([_vnet("vnet", "unchanged", subnets=[]), subnet])
        before = copy.deepcopy(document)

        ChangeFilter(["delete"]).apply(document)

        assert document.resources[0].properties == before.resources[0].properties
        assert document.resources[1].depends_on == before.resources[1].depends_on
        assert _names(document) == _names(before)

    def test_source_format_provider_and_metadata_are_carried_over(self):
        document = _DocumentFactory.document([_vnet("vnet", "create")], metadata={"changeCounts": {"create": 1}})
        result = ChangeFilter(["create"]).apply(document)
        assert result.source_format == "terraform"
        assert result.provider_name == "azurerm"
        assert result.metadata == {"changeCounts": {"create": 1}}
        assert result.metadata is not document.metadata

    def test_none_document_is_passed_through(self):
        assert ChangeFilter(["create"]).apply(None) is None


class TestChangeFilterIdentity:
    """Selecting every category keeps the document as is (Requirement 6.6)."""

    def test_every_category_is_an_identity_transform(self):
        resources = [
            _vnet("vnet", "unchanged"),
            _subnet("vnet", "web", "delete"),
            _DocumentFactory.resource("azurerm_storage_account.sa", "Microsoft.Storage/storageAccounts", "sa", "create"),
        ]
        document = _DocumentFactory.document(resources)

        result = ChangeFilter(CHANGE_CATEGORIES).apply(document)

        assert _names(result) == _names(document)
        assert [r.change_category for r in result.resources] == [r.change_category for r in document.resources]
        assert result.to_renderer_template() == document.to_renderer_template()

    def test_selection_from_parse_change_types_default_is_identity(self):
        document = _DocumentFactory.document([_vnet("vnet", "delete"), _subnet("vnet", "web", "create")])
        result = ChangeFilter(parse_change_types(None)).apply(document)
        assert result.to_renderer_template() == document.to_renderer_template()


class TestChangeFilterDirectSelection:
    """Pass 1: selected categories and uncategorized resources survive (6.3)."""

    def test_only_selected_categories_are_kept(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("a", "Microsoft.Storage/storageAccounts", "created", "create"),
                _DocumentFactory.resource("b", "Microsoft.Storage/storageAccounts", "updated", "update"),
                _DocumentFactory.resource("c", "Microsoft.Storage/storageAccounts", "deleted", "delete"),
                _DocumentFactory.resource("d", "Microsoft.Storage/storageAccounts", "replaced", "replace"),
                _DocumentFactory.resource("e", "Microsoft.Storage/storageAccounts", "kept", "unchanged"),
            ]
        )

        result = ChangeFilter(["delete", "replace"]).apply(document)

        assert _names(result) == ["deleted", "replaced"]

    def test_resource_order_is_preserved(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("a", "Microsoft.Storage/storageAccounts", "first", "create"),
                _DocumentFactory.resource("b", "Microsoft.Storage/storageAccounts", "second", "delete"),
                _DocumentFactory.resource("c", "Microsoft.Storage/storageAccounts", "third", "create"),
            ]
        )

        assert _names(ChangeFilter(["create"]).apply(document)) == ["first", "third"]

    def test_uncategorized_legacy_resources_are_always_kept(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("a", "Microsoft.Storage/storageAccounts", "legacy", None),
                _DocumentFactory.resource("b", "Microsoft.Storage/storageAccounts", "created", "create"),
            ]
        )

        assert _names(ChangeFilter(["delete"]).apply(document)) == ["legacy"]

    def test_empty_selection_keeps_nothing_but_legacy_resources(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("a", "Microsoft.Storage/storageAccounts", "created", "create"),
                _DocumentFactory.resource("b", "Microsoft.Storage/storageAccounts", "legacy", None),
            ]
        )

        assert _names(ChangeFilter([]).apply(document)) == ["legacy"]

    def test_an_empty_document_stays_empty(self):
        result = ChangeFilter(["delete"]).apply(_DocumentFactory.document([]))
        assert result.resources == []


class TestChangeFilterContainerRetention:
    """Pass 2: containers of a kept resource come back (Requirement 6.11)."""

    def test_depends_on_resource_id_readmits_vnet_and_subnet(self):
        web_app = _DocumentFactory.resource(
            "azurerm_linux_web_app.app",
            "Microsoft.Web/sites",
            "app",
            "create",
            depends_on=[_subnet_resource_id("vnet", "web")],
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "web"), web_app])

        result = ChangeFilter(["create"]).apply(document)

        assert _names(result) == ["vnet", "vnet/web", "app"]

    def test_virtual_network_subnet_id_property_readmits_containers(self):
        app = _DocumentFactory.resource(
            "azurerm_linux_web_app.app",
            "Microsoft.Web/sites",
            "app",
            "delete",
            properties={"virtualNetworkSubnetId": _subnet_resource_id("vnet", "web")},
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "web"), app])

        assert _names(ChangeFilter(["delete"]).apply(document)) == ["vnet", "vnet/web", "app"]

    def test_private_endpoint_subnet_id_property_readmits_containers(self):
        endpoint = _DocumentFactory.resource(
            "azurerm_private_endpoint.pe",
            "Microsoft.Network/privateEndpoints",
            "pe",
            "create",
            properties={"subnet": {"id": _subnet_resource_id("vnet", "data")}},
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "data"), endpoint])

        assert _names(ChangeFilter(["create"]).apply(document)) == ["vnet", "vnet/data", "pe"]

    def test_aks_agent_pool_profile_subnet_id_readmits_containers(self):
        aks = _DocumentFactory.resource(
            "azurerm_kubernetes_cluster.aks",
            "Microsoft.ContainerService/managedClusters",
            "aks",
            "replace",
            properties={"agentPoolProfiles": [{"name": "nodepool1", "vnetSubnetID": _subnet_resource_id("vnet", "aks")}]},
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "aks"), aks])

        assert _names(ChangeFilter(["replace"]).apply(document)) == ["vnet", "vnet/aks", "aks"]

    def test_bastion_ip_configuration_subnet_id_readmits_containers(self):
        bastion = _DocumentFactory.resource(
            "azurerm_bastion_host.bastion",
            "Microsoft.Network/bastionHosts",
            "bastion",
            "create",
            properties={
                "ipConfigurations": [
                    {"name": "ipconfig", "properties": {"subnet": {"id": _subnet_resource_id("vnet", "AzureBastionSubnet")}}}
                ]
            },
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "AzureBastionSubnet"), bastion])

        assert _names(ChangeFilter(["create"]).apply(document)) == ["vnet", "vnet/AzureBastionSubnet", "bastion"]

    def test_application_gateway_ip_configuration_readmits_containers(self):
        gateway = _DocumentFactory.resource(
            "azurerm_application_gateway.agw",
            "Microsoft.Network/applicationGateways",
            "agw",
            "update",
            properties={
                "gatewayIPConfigurations": [
                    {"name": "gateway", "properties": {"subnet": {"id": _subnet_resource_id("vnet", "agw")}}}
                ]
            },
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "agw"), gateway])

        assert _names(ChangeFilter(["update"]).apply(document)) == ["vnet", "vnet/agw", "agw"]

    def test_raw_azure_subnet_id_readmits_containers(self):
        raw_id = (
            "/subscriptions/0000/resourceGroups/rg/providers/Microsoft.Network"
            "/virtualNetworks/vnet/subnets/web"
        )
        app = _DocumentFactory.resource(
            "azurerm_linux_web_app.app",
            "Microsoft.Web/sites",
            "app",
            "create",
            properties={"virtualNetworkSubnetId": raw_id},
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "web"), app])

        assert _names(ChangeFilter(["create"]).apply(document)) == ["vnet", "vnet/web", "app"]

    def test_name_relation_readmits_a_subnet_referenced_by_name(self):
        app = _DocumentFactory.resource(
            "azurerm_linux_web_app.app",
            "Microsoft.Web/sites",
            "app",
            "create",
            properties={"virtualNetworkSubnetId": "vnet/web"},
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "web"), app])

        assert _names(ChangeFilter(["create"]).apply(document)) == ["vnet", "vnet/web", "app"]

    def test_a_retained_subnet_readmits_its_parent_vnet(self):
        document = _DocumentFactory.document([_vnet("vnet", "unchanged"), _subnet("vnet", "web", "delete")])

        assert _names(ChangeFilter(["delete"]).apply(document)) == ["vnet", "vnet/web"]

    def test_container_matching_is_case_insensitive(self):
        app = _DocumentFactory.resource(
            "azurerm_linux_web_app.app",
            "Microsoft.Web/sites",
            "app",
            "create",
            depends_on=[_subnet_resource_id("VNET", "WEB")],
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "web"), app])

        assert _names(ChangeFilter(["create"]).apply(document)) == ["vnet", "vnet/web", "app"]

    def test_unreferenced_containers_stay_dropped(self):
        document = _DocumentFactory.document(
            [
                _vnet("vnet"),
                _subnet("vnet", "web"),
                _subnet("vnet", "idle"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "create",
                    depends_on=[_subnet_resource_id("vnet", "web")],
                ),
            ]
        )

        assert _names(ChangeFilter(["create"]).apply(document)) == ["vnet", "vnet/web", "app"]

    def test_only_containers_are_readmitted(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("azurerm_service_plan.plan", "Microsoft.Web/serverfarms", "plan", "unchanged"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "create",
                    depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan')]"],
                ),
            ]
        )

        assert _names(ChangeFilter(["create"]).apply(document)) == ["app"]

    def test_readmitted_resources_keep_their_change_category(self):
        document = _DocumentFactory.document([_vnet("vnet", "unchanged"), _subnet("vnet", "web", "delete")])

        result = ChangeFilter(["delete"]).apply(document)

        assert [(r.name, r.change_category) for r in result.resources] == [
            ("vnet", "unchanged"),
            ("vnet/web", "delete"),
        ]


class TestResourceIdExpressionParsing:
    """The container reference parser matches the builder's own expressions."""

    def test_parses_type_and_multi_part_name(self):
        assert parse_resource_id_expression(_subnet_resource_id("vnet", "web")) == (
            "Microsoft.Network/virtualNetworks/subnets",
            "vnet/web",
        )

    def test_unescapes_doubled_single_quotes(self):
        expression = "[resourceId('Microsoft.Network/virtualNetworks', 'it''s')]"
        assert parse_resource_id_expression(expression) == ("Microsoft.Network/virtualNetworks", "it's")

    @pytest.mark.parametrize("value", ["", "vnet/web", None, 42, "[reference('x')]"])
    def test_non_expressions_return_none(self, value):
        assert parse_resource_id_expression(value) is None

    def test_subnet_reference_also_yields_the_parent_vnet(self):
        keys = container_keys_in_value(_subnet_resource_id("vnet", "web"))
        assert keys == {
            ("microsoft.network/virtualnetworks/subnets", "vnet/web"),
            ("microsoft.network/virtualnetworks", "vnet"),
        }

    def test_vnet_resource_id_yields_only_the_vnet(self):
        keys = container_keys_in_value("[resourceId('Microsoft.Network/virtualNetworks', 'vnet')]")
        assert keys == {("microsoft.network/virtualnetworks", "vnet")}

    def test_unrelated_reference_yields_nothing(self):
        assert container_keys_in_value("[resourceId('Microsoft.Web/serverfarms', 'plan')]") == set()


def _embedded_subnet(subnet_name, address_prefix="10.0.1.0/24"):
    """Return an embedded subnet entry shaped like the builder produces."""
    return {"name": subnet_name, "properties": {"addressPrefixes": [address_prefix]}}


def _embedded_subnet_names(document, vnet_name="vnet"):
    for resource in document.resources:
        if resource.renderer_type == "Microsoft.Network/virtualNetworks" and resource.name == vnet_name:
            return [entry.get("name") for entry in resource.properties.get("subnets", [])]
    return None


class TestChangeFilterEmbeddedSubnetPruning:
    """Pass 3: a dropped subnet leaves no embedded entry behind (6.4, 6.7)."""

    def test_dropped_subnet_entry_is_removed_from_the_vnet(self):
        document = _DocumentFactory.document(
            [
                _vnet("vnet", "unchanged", subnets=[_embedded_subnet("web"), _embedded_subnet("idle")]),
                _subnet("vnet", "web", "delete"),
                _subnet("vnet", "idle", "create"),
            ]
        )

        result = ChangeFilter(["delete"]).apply(document)

        assert _names(result) == ["vnet", "vnet/web"]
        assert _embedded_subnet_names(result) == ["web"]

    def test_kept_subnet_entries_survive_untouched(self):
        document = _DocumentFactory.document(
            [
                _vnet("vnet", "unchanged", subnets=[_embedded_subnet("web"), _embedded_subnet("data")]),
                _subnet("vnet", "web", "delete"),
                _subnet("vnet", "data", "delete"),
            ]
        )

        result = ChangeFilter(["delete"]).apply(document)

        assert _embedded_subnet_names(result) == ["web", "data"]
        assert result.resources[0].properties["subnets"][0]["properties"] == {"addressPrefixes": ["10.0.1.0/24"]}

    def test_entry_matching_is_case_insensitive(self):
        document = _DocumentFactory.document(
            [
                _vnet("VNET", "delete", subnets=[_embedded_subnet("WEB")]),
                _subnet("vnet", "web", "create"),
            ]
        )

        result = ChangeFilter(["delete"]).apply(document)

        assert _embedded_subnet_names(result, "VNET") == []

    def test_entries_without_a_matching_subnet_resource_are_left_alone(self):
        document = _DocumentFactory.document(
            [
                _vnet("vnet", "delete", subnets=[_embedded_subnet("inline"), _embedded_subnet("web")]),
                _subnet("vnet", "web", "create"),
            ]
        )

        result = ChangeFilter(["delete"]).apply(document)

        assert _names(result) == ["vnet"]
        assert _embedded_subnet_names(result) == ["inline"]

    def test_malformed_entries_are_preserved(self):
        document = _DocumentFactory.document(
            [
                _vnet("vnet", "delete", subnets=["web", {"noName": True}, 42]),
                _subnet("vnet", "web", "create"),
            ]
        )

        result = ChangeFilter(["delete"]).apply(document)

        assert result.resources[0].properties["subnets"] == [{"noName": True}, 42]

    def test_identity_selection_never_prunes_entries(self):
        document = _DocumentFactory.document(
            [
                _vnet("vnet", "unchanged", subnets=[_embedded_subnet("web")]),
                _subnet("vnet", "web", "delete"),
            ]
        )

        result = ChangeFilter(CHANGE_CATEGORIES).apply(document)

        assert result.to_renderer_template() == document.to_renderer_template()

    def test_input_document_keeps_its_embedded_entries(self):
        document = _DocumentFactory.document(
            [
                _vnet("vnet", "unchanged", subnets=[_embedded_subnet("web"), _embedded_subnet("idle")]),
                _subnet("vnet", "web", "delete"),
                _subnet("vnet", "idle", "create"),
            ]
        )

        ChangeFilter(["delete"]).apply(document)

        assert _embedded_subnet_names(document) == ["web", "idle"]


class TestChangeFilterEdgePruning:
    """Pass 4: references to resources outside the kept set go away (6.7)."""

    def test_depends_on_entry_pointing_at_a_dropped_resource_is_dropped(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("azurerm_service_plan.plan", "Microsoft.Web/serverfarms", "plan", "unchanged"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "create",
                    depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan')]"],
                ),
            ]
        )

        result = ChangeFilter(["create"]).apply(document)

        assert _names(result) == ["app"]
        assert result.resources[0].depends_on == []

    def test_depends_on_entry_pointing_at_a_kept_resource_survives(self):
        plan_reference = "[resourceId('Microsoft.Web/serverfarms', 'plan')]"
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("azurerm_service_plan.plan", "Microsoft.Web/serverfarms", "plan", "create"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "create",
                    depends_on=[plan_reference],
                ),
            ]
        )

        result = ChangeFilter(["create"]).apply(document)

        assert _names(result) == ["plan", "app"]
        assert result.resources[1].depends_on == [plan_reference]

    def test_reference_to_a_resource_absent_from_the_document_is_preserved(self):
        external = "[resourceId('Microsoft.Web/serverfarms', 'external')]"
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("azurerm_service_plan.plan", "Microsoft.Web/serverfarms", "plan", "unchanged"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "create",
                    depends_on=[external],
                ),
            ]
        )

        result = ChangeFilter(["create"]).apply(document)

        assert result.resources[0].depends_on == [external]

    def test_subnet_depends_on_survives_because_its_vnet_is_readmitted(self):
        document = _DocumentFactory.document([_vnet("vnet", "unchanged"), _subnet("vnet", "web", "delete")])

        result = ChangeFilter(["delete"]).apply(document)

        assert result.resources[1].depends_on == ["[resourceId('Microsoft.Network/virtualNetworks', 'vnet')]"]

    def test_subnet_id_property_pointing_at_a_kept_subnet_survives(self):
        reference = _subnet_resource_id("vnet", "web")
        app = _DocumentFactory.resource(
            "azurerm_linux_web_app.app",
            "Microsoft.Web/sites",
            "app",
            "create",
            properties={"virtualNetworkSubnetId": reference},
        )
        document = _DocumentFactory.document([_vnet("vnet"), _subnet("vnet", "web"), app])

        result = ChangeFilter(["create"]).apply(document)

        assert result.resources[2].properties == {"virtualNetworkSubnetId": reference}

    def test_subnet_id_property_pointing_at_a_dropped_subnet_is_removed(self):
        aks = _DocumentFactory.resource(
            "azurerm_kubernetes_cluster.aks",
            "Microsoft.ContainerService/managedClusters",
            "aks",
            "create",
            properties={
                "virtualNetworkSubnetId": _subnet_resource_id("vnet", "gone"),
                "agentPoolProfiles": [{"name": "pool", "vnetSubnetID": _subnet_resource_id("vnet", "gone")}],
                "sku": {"name": "Standard"},
            },
        )
        dropped = {("microsoft.network/virtualnetworks/subnets", "vnet/gone")}

        ChangeFilter._prune_edges([aks], dropped)

        assert aks.properties == {"agentPoolProfiles": [{"name": "pool"}], "sku": {"name": "Standard"}}

    def test_input_document_keeps_its_depends_on_entries(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("azurerm_service_plan.plan", "Microsoft.Web/serverfarms", "plan", "unchanged"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "create",
                    depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan')]"],
                ),
            ]
        )

        ChangeFilter(["create"]).apply(document)

        assert document.resources[1].depends_on == ["[resourceId('Microsoft.Web/serverfarms', 'plan')]"]

    def test_identity_selection_never_prunes_references(self):
        document = _DocumentFactory.document(
            [
                _DocumentFactory.resource("azurerm_service_plan.plan", "Microsoft.Web/serverfarms", "plan", "unchanged"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "create",
                    depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan')]"],
                ),
            ]
        )

        result = ChangeFilter(CHANGE_CATEGORIES).apply(document)

        assert result.to_renderer_template() == document.to_renderer_template()


class TestChangeFilterFixpointAndOrder:
    """Passes 3 and 4 depend only on the kept set, so the transform settles."""

    @staticmethod
    def _rich_document():
        return _DocumentFactory.document(
            [
                _vnet("vnet", "unchanged", subnets=[_embedded_subnet("web"), _embedded_subnet("idle")]),
                _subnet("vnet", "web", "delete"),
                _subnet("vnet", "idle", "create"),
                _DocumentFactory.resource("azurerm_service_plan.plan", "Microsoft.Web/serverfarms", "plan", "unchanged"),
                _DocumentFactory.resource(
                    "azurerm_linux_web_app.app",
                    "Microsoft.Web/sites",
                    "app",
                    "delete",
                    properties={"virtualNetworkSubnetId": _subnet_resource_id("vnet", "web")},
                    depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan')]"],
                ),
            ]
        )

    def test_applying_the_same_selection_twice_changes_nothing(self):
        document = self._rich_document()
        change_filter = ChangeFilter(["delete"])

        once = change_filter.apply(document)
        twice = change_filter.apply(once)

        assert twice.to_renderer_template() == once.to_renderer_template()

    def test_selection_order_and_repetition_produce_the_same_document(self):
        document = self._rich_document()

        first = ChangeFilter(["delete", "create", "delete"]).apply(document)
        second = ChangeFilter(("create", "delete")).apply(document)

        assert first.to_renderer_template() == second.to_renderer_template()

    def test_pruning_leaves_no_reference_to_a_dropped_resource(self):
        result = ChangeFilter(["delete"]).apply(self._rich_document())

        assert _names(result) == ["vnet", "vnet/web", "app"]
        assert _embedded_subnet_names(result) == ["web"]
        assert result.resources[2].depends_on == []
        assert result.resources[2].properties == {"virtualNetworkSubnetId": _subnet_resource_id("vnet", "web")}

# ─── Property 13: Filter completeness ────────────────────────────────────────

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from core.plan_diff import CONTAINER_RENDERER_TYPES  # noqa: E402
from strategies.plan_json import change_filters  # noqa: E402

#: Renderer types that are never re-admitted as a container, so their fate is
#: decided by the direct selection pass alone.
_LEAF_RENDERER_TYPES = (
    "Microsoft.Web/sites",
    "Microsoft.Storage/storageAccounts",
    "Microsoft.ContainerService/managedClusters",
    "Microsoft.Network/privateEndpoints",
    "Microsoft.Web/serverfarms",
)

#: How a leaf resource can point at the subnet that contains it.
_REFERENCE_MECHANISMS = (
    "none",
    "dependsOn",
    "virtualNetworkSubnetId",
    "subnetId",
    "agentPoolProfiles",
    "nameRelation",
)


def _is_container(resource):
    """True when the resource is a virtual network or a subnet."""
    return resource.renderer_type in CONTAINER_RENDERER_TYPES


def _leaf_properties(mechanism, vnet_name, subnet_name):
    """Return the properties wiring a leaf resource to ``<vnet>/<subnet>``."""
    if mechanism == "virtualNetworkSubnetId":
        return {"virtualNetworkSubnetId": _subnet_resource_id(vnet_name, subnet_name)}
    if mechanism == "subnetId":
        return {"subnet": {"id": _subnet_resource_id(vnet_name, subnet_name)}}
    if mechanism == "agentPoolProfiles":
        return {
            "agentPoolProfiles": [
                {"name": "nodepool1", "vnetSubnetID": _subnet_resource_id(vnet_name, subnet_name)}
            ]
        }
    if mechanism == "nameRelation":
        return {"virtualNetworkSubnetId": f"{vnet_name}/{subnet_name}"}
    return {}


@st.composite
def filterable_documents(
    draw,
    categories=None,
    max_vnets=2,
    max_subnets_per_vnet=2,
    max_leaves=3,
):
    """Draw a renderer document shaped like plan-diff builder output.

    Every resource carries a Change_Category drawn from ``categories``, virtual
    networks carry the embedded ``properties["subnets"]`` entries of their
    subnets, and leaf resources point at a subnet through one of the reference
    mechanisms the filter understands. Addresses and names are unique, so a
    resource set can be compared by address.
    """
    pool = list(categories or CHANGE_CATEGORIES)
    category = st.sampled_from(pool)

    resources = []
    subnet_paths = []

    for vnet_position in range(draw(st.integers(min_value=0, max_value=max_vnets))):
        vnet_name = f"vnet{vnet_position}"
        subnet_names = [
            f"sub{vnet_position}{position}"
            for position in range(draw(st.integers(min_value=0, max_value=max_subnets_per_vnet)))
        ]
        resources.append(
            _vnet(
                vnet_name,
                draw(category),
                subnets=[_embedded_subnet(name) for name in subnet_names],
            )
        )
        for subnet_name in subnet_names:
            resources.append(_subnet(vnet_name, subnet_name, draw(category)))
            subnet_paths.append((vnet_name, subnet_name))

    for leaf_position in range(draw(st.integers(min_value=0, max_value=max_leaves))):
        renderer_type = draw(st.sampled_from(_LEAF_RENDERER_TYPES))
        mechanism = draw(st.sampled_from(_REFERENCE_MECHANISMS)) if subnet_paths else "none"
        vnet_name, subnet_name = draw(st.sampled_from(subnet_paths)) if subnet_paths else ("", "")
        resources.append(
            _DocumentFactory.resource(
                f"azurerm_leaf.leaf{leaf_position}",
                renderer_type,
                f"leaf{leaf_position}",
                change_category=draw(category),
                properties=_leaf_properties(mechanism, vnet_name, subnet_name),
                depends_on=(
                    [_subnet_resource_id(vnet_name, subnet_name)] if mechanism == "dependsOn" else []
                ),
            )
        )

    counts = {name: 0 for name in CHANGE_CATEGORIES}
    for resource in resources:
        if resource.change_category in counts:
            counts[resource.change_category] += 1

    return _DocumentFactory.document(resources, metadata={"changeCounts": counts})


def _addresses(document, containers=True):
    return [
        resource.address
        for resource in document.resources
        if containers or not _is_container(resource)
    ]


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    document=filterable_documents(),
    selection=change_filters(),
    extra=st.lists(st.sampled_from(CHANGE_CATEGORIES), unique=True),
)
def test_property_13_filter_completeness(document, selection, extra):
    """Property 13: Filter completeness.

    The displayed non-container resources are exactly the resources whose
    Change_Category belongs to the selection (uncategorized resources always
    survive), and a selection covering every Change_Category present in the
    document displays the same resource set as an unfiltered run.

    **Validates: Requirements 6.3, 6.6, 12.3**
    """
    selected = frozenset(selection)
    result = ChangeFilter(selection).apply(document)

    expected = [
        resource.address
        for resource in document.resources
        if not _is_container(resource)
        and (resource.change_category is None or resource.change_category in selected)
    ]
    assert _addresses(result, containers=False) == expected

    present = {
        resource.change_category
        for resource in document.resources
        if resource.change_category is not None
    }
    covering = sorted(present | set(extra))
    covered = ChangeFilter(covering).apply(document)

    assert _addresses(covered) == _addresses(document)
    assert covered.to_renderer_template() == ChangeFilter(None).apply(document).to_renderer_template()

# ─── Property 14: Filter idempotence ─────────────────────────────────────────


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(document=filterable_documents(), selection=change_filters())
def test_property_14_filter_idempotence(document, selection):
    """Property 14: Filter idempotence.

    Applying a selection to the result of applying the same selection yields the
    same displayed resource set as applying it once, so the transform is a
    fixpoint: the container-retention, embedded-subnet-pruning and edge-pruning
    passes depend only on the kept set.

    **Validates: Requirements 6.4, 12.4**
    """
    change_filter = ChangeFilter(selection)

    once = change_filter.apply(document)
    twice = change_filter.apply(once)

    assert _addresses(twice) == _addresses(once)
    assert _addresses(twice, containers=False) == _addresses(once, containers=False)
    assert twice.to_renderer_template() == once.to_renderer_template()

# ─── Property 15: Filter order independence ──────────────────────────────────


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    document=filterable_documents(),
    selection=change_filters(shuffled=True),
    data=st.data(),
)
def test_property_15_filter_order_independence(document, selection, data):
    """Property 15: Filter order independence.

    Two selections holding the same Change_Categories in different order display
    the same resource set, so the transform depends on the selected set only and
    never on the order the categories were supplied in.

    **Validates: Requirements 6.5, 12.5**
    """
    reordered = data.draw(st.permutations(selection).map(list))
    assert set(reordered) == set(selection)

    first = ChangeFilter(selection).apply(document)
    second = ChangeFilter(reordered).apply(document)

    assert _addresses(second) == _addresses(first)
    assert _addresses(second, containers=False) == _addresses(first, containers=False)
    assert second.to_renderer_template() == first.to_renderer_template()

# ─── Property 16: Filter monotonicity ────────────────────────────────────────


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    document=filterable_documents(),
    selection=change_filters(include_full=False),
)
def test_property_16_filter_monotonicity(document, selection):
    """Property 16: Filter monotonicity.

    A selection that excludes at least one Change_Category never displays more
    resources than the unfiltered run. Equality stays reachable because a
    container holding a displayed resource comes back through the retention pass
    (Requirement 6.11), so the assertion is ``<=`` rather than ``<``.

    **Validates: Requirements 12.9**
    """
    assert set(selection) != set(CHANGE_CATEGORIES)

    unfiltered = ChangeFilter(None).apply(document)
    filtered = ChangeFilter(selection).apply(document)

    assert len(_addresses(filtered)) <= len(_addresses(unfiltered))
    assert len(_addresses(filtered, containers=False)) <= len(_addresses(unfiltered, containers=False))
    assert set(_addresses(filtered)) <= set(_addresses(unfiltered))

# ─── Property 17: Edge and container integrity after filtering ────────────────

from core.plan_diff import (  # noqa: E402
    SUBNET_TYPE,
    VIRTUAL_NETWORK_TYPE,
    container_key,
    iter_subnet_id_slots,
    subnet_key,
    virtual_network_key,
)


def _identity(resource):
    """Return the case-insensitive identity of any resource, container or not."""
    return container_key(resource.renderer_type, resource.name)


def _reference_values(resource):
    """Yield every reference value of a resource: ``dependsOn`` and subnet ids."""
    for entry in resource.depends_on or []:
        yield entry
    for slot in iter_subnet_id_slots(resource.properties):
        yield slot.value


def _target_keys(value):
    """Return the resource identities one reference value points at."""
    keys = set(container_keys_in_value(value))
    parsed = parse_resource_id_expression(value)
    if parsed is not None:
        keys.add(container_key(parsed[0], parsed[1]))
    return keys


def _required_container_keys(resource):
    """Return the containers a resource needs before it can render.

    A reference through ``dependsOn`` or through a subnet-id-bearing property
    names its container directly; a subnet additionally needs the virtual
    network named in the ``"<vnet>/<subnet>"`` half of its own name.
    """
    keys = set()
    for value in _reference_values(resource):
        keys |= _target_keys(value)
    if resource.renderer_type == SUBNET_TYPE:
        vnet_name, separator, subnet_name = str(resource.name or "").partition("/")
        if separator and vnet_name and subnet_name:
            keys.add(virtual_network_key(vnet_name))
    return keys


def _embedded_names(resource):
    """Return the embedded ``properties["subnets"]`` names of a virtual network."""
    if resource.renderer_type != VIRTUAL_NETWORK_TYPE:
        return []
    properties = resource.properties if isinstance(resource.properties, dict) else {}
    entries = properties.get("subnets")
    if not isinstance(entries, list):
        return []
    return [entry.get("name") for entry in entries if isinstance(entry, dict) and entry.get("name")]


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(document=filterable_documents(), selection=change_filters())
def test_property_17_edge_and_container_integrity(document, selection):
    """Property 17: Edge and container integrity after filtering.

    Every dependency reference surviving the filter resolves to a displayed
    resource, so no dangling edge materializes an orphan root node
    (Requirement 6.7). Every container of a displayed resource is retained,
    including the subnet entry embedded in its virtual network's properties,
    while a container holding no displayed resource is dropped together with
    that embedded entry (Requirement 6.11).

    **Validates: Requirements 6.7, 6.11**
    """
    selected = frozenset(selection)
    result = ChangeFilter(selection).apply(document)

    all_keys = {_identity(resource) for resource in document.resources}
    kept_keys = {_identity(resource) for resource in result.resources}

    # Requirement 6.7 - no surviving reference points outside the kept set.
    for resource in result.resources:
        for value in _reference_values(resource):
            for key in _target_keys(value):
                if key in all_keys:
                    assert key in kept_keys, f"{resource.name} still references dropped {key}"

    # Requirement 6.11 - every container a displayed resource needs is retained.
    demanded = set()
    for resource in document.resources:
        if _identity(resource) in kept_keys:
            demanded |= _required_container_keys(resource)
    for key in demanded:
        if key in all_keys:
            assert key in kept_keys, f"container {key} of a displayed resource was dropped"

    # Requirement 6.11 - a container holding nothing displayed is dropped.
    for resource in document.resources:
        if not _is_container(resource) or _identity(resource) in kept_keys:
            continue
        assert _identity(resource) not in demanded
        assert resource.change_category not in selected

    # Requirement 6.11 - embedded subnet entries follow their subnet resource.
    originals = {_identity(resource): resource for resource in document.resources}
    for vnet in result.resources:
        if vnet.renderer_type != VIRTUAL_NETWORK_TYPE:
            continue
        expected = [
            name
            for name in _embedded_names(originals[_identity(vnet)])
            if subnet_key(vnet.name, name) not in all_keys or subnet_key(vnet.name, name) in kept_keys
        ]
        assert _embedded_names(vnet) == expected
