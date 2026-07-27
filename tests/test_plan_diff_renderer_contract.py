"""Unit tests for the additive `change_category` field on the renderer contract.

Covers Requirements 4.1, 4.2 and 4.3.
"""

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource


def _resource(**overrides):
    defaults = {
        "address": "azurerm_linux_web_app.api",
        "provider_name": "registry.terraform.io/hashicorp/azurerm",
        "source_type": "azurerm_linux_web_app",
        "renderer_type": "Microsoft.Web/sites",
        "name": "app-web",
        "properties": {"serverFarmId": "plan-1"},
    }
    defaults.update(overrides)
    return LocalTemplateResource(**defaults)


class TestFieldShape:
    """The field is trailing and defaulted so legacy constructions still work."""

    def test_change_category_defaults_to_none(self):
        assert _resource().change_category is None

    def test_positional_construction_without_change_category_still_works(self):
        resource = LocalTemplateResource(
            "azurerm_virtual_network.core",
            "registry.terraform.io/hashicorp/azurerm",
            "azurerm_virtual_network",
            "Microsoft.Network/virtualNetworks",
            "vnet-core",
            {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}},
            ["[resourceId('Microsoft.Network/virtualNetworks', 'vnet-hub')]"],
            {"apiVersion": "2023-01-01"},
            {"name": "vnet-core"},
        )
        assert resource.change_category is None

    def test_change_category_trails_every_pre_plan_diff_field(self):
        from dataclasses import fields

        names = [f.name for f in fields(LocalTemplateResource)]
        assert names.index("change_category") == names.index("raw_values") + 1


class TestKeyOmission:
    """No change category means the emitted dict is key-for-key the legacy shape."""

    def test_key_is_omitted_when_change_category_is_none(self):
        assert "changeCategory" not in _resource().to_renderer_resource()

    def test_emitted_dict_is_identical_to_the_legacy_shape(self):
        resource = _resource(
            depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan-1')]"],
            extra_fields={"apiVersion": "2023-01-01", "location": "westeurope"},
        )
        assert resource.to_renderer_resource() == {
            "type": "Microsoft.Web/sites",
            "name": "app-web",
            "properties": {"serverFarmId": "plan-1"},
            "dependsOn": ["[resourceId('Microsoft.Web/serverfarms', 'plan-1')]"],
            "apiVersion": "2023-01-01",
            "location": "westeurope",
        }

    def test_document_template_is_unchanged_for_legacy_resources(self):
        document = LocalTemplateDocument(
            source_format="terraform-json",
            provider_name="azurerm",
            resources=[_resource()],
        )
        template = document.to_renderer_template()
        assert "metadata" not in template
        assert template["resources"] == [
            {
                "type": "Microsoft.Web/sites",
                "name": "app-web",
                "properties": {"serverFarmId": "plan-1"},
            }
        ]


class TestKeyEmission:
    """A set change category surfaces as `changeCategory`."""

    def test_key_is_emitted_when_change_category_is_set(self):
        resource = _resource(change_category="delete")
        assert resource.to_renderer_resource()["changeCategory"] == "delete"

    def test_unchanged_is_emitted_because_it_is_not_none(self):
        resource = _resource(change_category="unchanged")
        assert resource.to_renderer_resource()["changeCategory"] == "unchanged"

    def test_document_forwards_the_change_category_per_resource(self):
        document = LocalTemplateDocument(
            source_format="terraform-json",
            provider_name="azurerm",
            resources=[
                _resource(name="app-web", change_category="replace"),
                _resource(name="app-api", change_category=None),
            ],
            metadata={"changeCounts": {"replace": 1}},
        )
        template = document.to_renderer_template()
        assert template["resources"][0]["changeCategory"] == "replace"
        assert "changeCategory" not in template["resources"][1]
        assert template["metadata"] == {"changeCounts": {"replace": 1}}


class TestKeyOrdering:
    """`changeCategory` trails `dependsOn` and every extra field."""

    def test_change_category_is_the_last_emitted_key(self):
        resource = _resource(
            depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan-1')]"],
            extra_fields={"apiVersion": "2023-01-01", "location": "westeurope"},
            change_category="update",
        )
        assert list(resource.to_renderer_resource()) == [
            "type",
            "name",
            "properties",
            "dependsOn",
            "apiVersion",
            "location",
            "changeCategory",
        ]

    def test_change_category_trails_even_without_depends_on_or_extra_fields(self):
        resource = _resource(change_category="create")
        assert list(resource.to_renderer_resource()) == ["type", "name", "properties", "changeCategory"]

    def test_an_extra_field_named_change_category_is_overridden_by_the_field(self):
        resource = _resource(extra_fields={"changeCategory": "create"}, change_category="delete")
        emitted = resource.to_renderer_resource()
        assert emitted["changeCategory"] == "delete"
        assert list(emitted).count("changeCategory") == 1
