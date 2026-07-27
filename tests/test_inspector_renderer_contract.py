"""Unit tests for the additive `inspector_values` field on the renderer contract.

Covers Requirements 1.5 and 10.1: the field is trailing and defaulted, the
`inspectorValues` key is emitted only when the field is set, and a legacy
resource's emitted dict stays key-for-key identical.
"""

from dataclasses import fields

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource

INSPECTOR_VALUES = {
    "before": {"sku": "S1"},
    "after": {"sku": "P1v2"},
    "afterUnknown": {"id": True},
}


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

    def test_inspector_values_defaults_to_none(self):
        assert _resource().inspector_values is None

    def test_inspector_values_is_the_last_field(self):
        assert [f.name for f in fields(LocalTemplateResource)][-1] == "inspector_values"

    def test_inspector_values_follows_change_category(self):
        names = [f.name for f in fields(LocalTemplateResource)]
        assert names[names.index("change_category") + 1] == "inspector_values"

    def test_positional_construction_without_inspector_values_still_works(self):
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
            "update",
        )
        assert resource.change_category == "update"
        assert resource.inspector_values is None


class TestKeyOmission:
    """No inspector values means the emitted dict is key-for-key the legacy shape."""

    def test_key_is_omitted_when_inspector_values_is_none(self):
        assert "inspectorValues" not in _resource().to_renderer_resource()

    def test_legacy_resource_emits_the_pre_feature_dict(self):
        resource = _resource(
            depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan-1')]"],
            extra_fields={"apiVersion": "2023-01-01", "location": "westeurope"},
            raw_values={"name": "app-web", "sku": "S1"},
        )
        assert resource.to_renderer_resource() == {
            "type": "Microsoft.Web/sites",
            "name": "app-web",
            "properties": {"serverFarmId": "plan-1"},
            "dependsOn": ["[resourceId('Microsoft.Web/serverfarms', 'plan-1')]"],
            "apiVersion": "2023-01-01",
            "location": "westeurope",
        }

    def test_legacy_plan_diff_resource_emits_the_pre_feature_dict(self):
        resource = _resource(change_category="replace")
        assert resource.to_renderer_resource() == {
            "type": "Microsoft.Web/sites",
            "name": "app-web",
            "properties": {"serverFarmId": "plan-1"},
            "changeCategory": "replace",
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
    """Set inspector values surface as `inspectorValues`."""

    def test_key_is_emitted_when_inspector_values_is_set(self):
        resource = _resource(inspector_values=INSPECTOR_VALUES)
        assert resource.to_renderer_resource()["inspectorValues"] == INSPECTOR_VALUES

    def test_empty_snapshots_are_emitted_because_the_field_is_not_none(self):
        resource = _resource(inspector_values={"before": {}, "after": {}, "afterUnknown": {}})
        assert resource.to_renderer_resource()["inspectorValues"] == {
            "before": {},
            "after": {},
            "afterUnknown": {},
        }

    def test_document_forwards_the_inspector_values_per_resource(self):
        document = LocalTemplateDocument(
            source_format="terraform-json",
            provider_name="azurerm",
            resources=[
                _resource(name="app-web", inspector_values=INSPECTOR_VALUES),
                _resource(name="app-api", inspector_values=None),
            ],
        )
        template = document.to_renderer_template()
        assert template["resources"][0]["inspectorValues"] == INSPECTOR_VALUES
        assert "inspectorValues" not in template["resources"][1]


class TestKeyOrdering:
    """`inspectorValues` trails `changeCategory` and every earlier key."""

    def test_inspector_values_is_the_last_emitted_key(self):
        resource = _resource(
            depends_on=["[resourceId('Microsoft.Web/serverfarms', 'plan-1')]"],
            extra_fields={"apiVersion": "2023-01-01", "location": "westeurope"},
            change_category="update",
            inspector_values=INSPECTOR_VALUES,
        )
        assert list(resource.to_renderer_resource()) == [
            "type",
            "name",
            "properties",
            "dependsOn",
            "apiVersion",
            "location",
            "changeCategory",
            "inspectorValues",
        ]

    def test_inspector_values_trails_without_depends_on_or_extra_fields(self):
        resource = _resource(inspector_values=INSPECTOR_VALUES)
        assert list(resource.to_renderer_resource()) == [
            "type",
            "name",
            "properties",
            "inspectorValues",
        ]

    def test_an_extra_field_named_inspector_values_is_overridden_by_the_field(self):
        resource = _resource(
            extra_fields={"inspectorValues": {"before": {}}},
            inspector_values=INSPECTOR_VALUES,
        )
        emitted = resource.to_renderer_resource()
        assert emitted["inspectorValues"] == INSPECTOR_VALUES
        assert list(emitted).count("inspectorValues") == 1
