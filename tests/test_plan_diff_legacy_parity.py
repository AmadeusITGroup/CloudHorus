"""Property test for legacy Renderer_Template parity.

Feature: terraform-plan-diff-visualization, Property 9: Legacy inputs produce an
unchanged Renderer_Template.

The pre-feature serializer is pinned here as ``legacy_renderer_template``, copied
verbatim from the revision preceding this feature (``LocalTemplateResource.
to_renderer_resource`` / ``LocalTemplateDocument.to_renderer_template`` before the
optional ``change_category`` field was added). Comparing the current output
against that pinned reference is what makes "identical to the release preceding
this feature" checkable inside the test suite.

Legacy input families covered:

- Terraform JSON documents without a ``resource_changes`` array, built through the
  real ``TerraformTemplateBuilder.build_document_from_json``.
- Bicep and Terraform source documents, represented by synthesized legacy
  ``LocalTemplateDocument`` values: those builders reach the renderer contract
  through the very same serializer, with no Change_Category ever set.
"""

from typing import Any, Dict, List

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource
from core.terraform_builder import TerraformTemplateBuilder
from strategies.plan_json import nested_value_trees, plan_documents, resource_names

_LEGACY_SOURCE_FORMATS = ("bicep", "terraform-source-hcl", "terraform-state-json", "terraform-plan-json")


# ─── Pinned pre-feature serializer ────────────────────────────────────────────


def legacy_renderer_resource(resource: LocalTemplateResource) -> Dict[str, Any]:
    """The pre-feature ``to_renderer_resource`` body, verbatim."""
    emitted = {
        "type": resource.renderer_type,
        "name": resource.name,
        "properties": resource.properties,
    }
    if resource.depends_on:
        emitted["dependsOn"] = resource.depends_on
    for key, value in resource.extra_fields.items():
        if value is not None:
            emitted[key] = value
    return emitted


def legacy_renderer_template(document: LocalTemplateDocument) -> Dict[str, Any]:
    """The pre-feature ``to_renderer_template`` body, verbatim."""
    template = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "resources": [legacy_renderer_resource(resource) for resource in document.resources],
    }
    if document.metadata:
        template["metadata"] = document.metadata
    return template


# ─── Legacy document strategies ───────────────────────────────────────────────


def _build_from_plan_json(terraform_json: Dict[str, Any]) -> LocalTemplateDocument:
    return TerraformTemplateBuilder().build_document_from_json(terraform_json)


def terraform_json_documents() -> st.SearchStrategy[LocalTemplateDocument]:
    """Documents produced by the legacy Terraform JSON path (no ``resource_changes``)."""
    return plan_documents(with_resource_changes=False).map(_build_from_plan_json)


@st.composite
def synthesized_legacy_resources(draw: st.DrawFn) -> LocalTemplateResource:
    """A legacy resource as Bicep and Terraform source builders construct it."""
    name = draw(resource_names())
    return LocalTemplateResource(
        address=draw(resource_names()),
        provider_name="azurerm",
        source_type=draw(st.sampled_from(["azurerm_virtual_network", "azurerm_subnet", "azurerm_linux_web_app"])),
        renderer_type=draw(
            st.sampled_from(
                [
                    "Microsoft.Network/virtualNetworks",
                    "Microsoft.Network/virtualNetworks/subnets",
                    "Microsoft.Web/sites",
                ]
            )
        ),
        name=name,
        properties=draw(nested_value_trees(max_leaves=4)),
        depends_on=draw(st.lists(st.text(max_size=12), max_size=3)),
        extra_fields=draw(
            st.dictionaries(
                st.sampled_from(["apiVersion", "location", "sku", "kind"]),
                st.one_of(st.none(), st.text(max_size=8), st.integers(min_value=0, max_value=10)),
                max_size=4,
            )
        ),
        raw_values={"name": name},
    )


def synthesized_legacy_documents() -> st.SearchStrategy[LocalTemplateDocument]:
    """Legacy documents standing in for the Bicep and Terraform source families."""
    return st.builds(
        LocalTemplateDocument,
        source_format=st.sampled_from(_LEGACY_SOURCE_FORMATS),
        provider_name=st.just("azurerm"),
        resources=st.lists(synthesized_legacy_resources(), max_size=4),
        metadata=st.dictionaries(
            st.sampled_from(["terraformVersion", "formatVersion", "sourceRoot", "varFiles"]),
            st.one_of(st.none(), st.text(max_size=8), st.lists(st.text(max_size=6), max_size=2)),
            max_size=3,
        ),
    )


def legacy_documents() -> st.SearchStrategy[LocalTemplateDocument]:
    return st.one_of(terraform_json_documents(), synthesized_legacy_documents())


# ─── Property 9 ───────────────────────────────────────────────────────────────


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(document=legacy_documents())
def test_property_9_legacy_inputs_produce_an_unchanged_renderer_template(document):
    """For any legacy input, the Renderer_Template equals the pre-feature template.

    Feature: terraform-plan-diff-visualization, Property 9: Legacy inputs produce
    an unchanged Renderer_Template — for any Bicep input, Terraform source input,
    or Terraform JSON document without a ``resource_changes`` array, the
    Renderer_Template produced with this feature present is equal to the
    Renderer_Template produced by the code path preceding this feature, key for
    key and value for value, including the ``type``, ``name``, ``properties`` and
    ``dependsOn`` entries.

    **Validates: Requirements 4.3, 8.1**
    """
    # A legacy input never carries a Change_Category.
    assert all(resource.change_category is None for resource in document.resources)

    produced = document.to_renderer_template()
    expected = legacy_renderer_template(document)

    # Key for key and value for value, in the same order.
    assert produced == expected
    assert list(produced) == list(expected)

    produced_resources: List[Dict[str, Any]] = produced["resources"]
    expected_resources: List[Dict[str, Any]] = expected["resources"]
    assert len(produced_resources) == len(expected_resources)

    for produced_resource, expected_resource, resource in zip(
        produced_resources, expected_resources, document.resources
    ):
        assert list(produced_resource) == list(expected_resource)
        assert "changeCategory" not in produced_resource
        assert produced_resource["type"] == resource.renderer_type
        assert produced_resource["name"] == resource.name
        assert produced_resource["properties"] == resource.properties
        assert produced_resource.get("dependsOn") == (resource.depends_on or None)

    # Metadata carries no plan diff payload for a legacy input.
    assert not {"changeCounts", "changeModel", "changesNotDisplayed"} & set(produced.get("metadata", {}))
