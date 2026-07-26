"""Tests for plan-aware document building in `build_document_from_json`.

Unit tests live at the top of this file; the property tests of the design
(Properties 5, 6, 7, 8 and 19) are appended below them.

Covers Requirements 3.3, 3.5, 4.1, 4.4 and 10.1: reconstructed deletes join the
planned resources without duplicating a `replace` address, sensitive leaves are
masked before normalization, every resource carries a Change_Category, and the
template metadata carries the change model.
"""

import copy
import json
from typing import Any, Dict, List, Optional

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from core.plan_diff import CHANGE_CATEGORIES, ChangeExtractor, ChangeModel
from core.terraform_builder import _TERRAFORM_TO_RENDERER_TYPE, TerraformTemplateBuilder
from strategies.plan_json import (
    address_parts,
    azurerm_resource_values,
    plan_documents,
    sensitive_masks,
    terraform_types,
)

PROVIDER = "registry.terraform.io/hashicorp/azurerm"


# ─── Fixtures / helpers ───────────────────────────────────────────────────────


def _builder() -> TerraformTemplateBuilder:
    return TerraformTemplateBuilder()


def _change_entry(
    address: str,
    terraform_type: str,
    actions: List[str],
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    *,
    before_sensitive: Any = None,
    after_sensitive: Any = None,
    provider_name: str = PROVIDER,
    mode: str = "managed",
) -> Dict[str, Any]:
    """Build one `resource_changes` entry."""
    change: Dict[str, Any] = {"actions": actions, "before": before, "after": after}
    if before_sensitive is not None:
        change["before_sensitive"] = before_sensitive
    if after_sensitive is not None:
        change["after_sensitive"] = after_sensitive
    return {
        "address": address,
        "mode": mode,
        "type": terraform_type,
        "name": address.rsplit(".", 1)[-1],
        "provider_name": provider_name,
        "change": change,
    }


def _planned_resource(
    address: str,
    terraform_type: str,
    values: Dict[str, Any],
    sensitive_values: Any = None,
) -> Dict[str, Any]:
    """Build one `planned_values.root_module.resources` entry."""
    resource = {
        "address": address,
        "mode": "managed",
        "type": terraform_type,
        "name": address.rsplit(".", 1)[-1],
        "provider_name": PROVIDER,
        "values": values,
    }
    if sensitive_values is not None:
        resource["sensitive_values"] = sensitive_values
    return resource


def _plan(
    change_entries: Optional[List[Dict[str, Any]]] = None,
    planned_resources: Optional[List[Dict[str, Any]]] = None,
    configuration: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a minimal plan document around the given change and planned entries."""
    plan: Dict[str, Any] = {
        "format_version": "1.2",
        "terraform_version": "1.7.5",
        "planned_values": {"root_module": {"resources": list(planned_resources or [])}},
    }
    if change_entries is not None:
        plan["resource_changes"] = list(change_entries)
    if configuration is not None:
        plan["configuration"] = configuration
    return plan


def _model(plan: Dict[str, Any]) -> ChangeModel:
    return ChangeExtractor().extract(plan.get("resource_changes"))


def _by_name(document) -> Dict[str, Any]:
    return {resource.name: resource for resource in document.resources}


# ─── Legacy path (change_model is None) ───────────────────────────────────────


def test_legacy_path_is_untouched_when_no_change_model_is_supplied() -> None:
    """Without a model, no resource carries a category and no change metadata appears."""
    plan = _plan(
        [_change_entry("azurerm_storage_account.data", "azurerm_storage_account", ["update"], {"name": "stdata"})],
        planned_resources=[_planned_resource("azurerm_storage_account.data", "azurerm_storage_account", {"name": "stdata"})],
    )

    template = _builder().build_document_from_json(plan).to_renderer_template()

    assert all("changeCategory" not in resource for resource in template["resources"])
    assert set(template["metadata"]) == {"terraformVersion", "formatVersion"}


# ─── Delete merging and deduplication (Requirement 3.3) ───────────────────────


def test_deleted_resource_is_appended_to_the_planned_resources() -> None:
    """A delete absent from planned_values still reaches the document."""
    plan = _plan(
        [
            _change_entry("azurerm_storage_account.keep", "azurerm_storage_account", ["no-op"], {"name": "stkeep"}),
            _change_entry("azurerm_redis_cache.gone", "azurerm_redis_cache", ["delete"], {"name": "redis-gone"}),
        ],
        planned_resources=[_planned_resource("azurerm_storage_account.keep", "azurerm_storage_account", {"name": "stkeep"})],
    )

    document = _builder().build_document_from_json(plan, change_model=_model(plan))

    categories = {resource.name: resource.change_category for resource in document.resources}
    assert categories == {"stkeep": "unchanged", "redis-gone": "delete"}


def test_replace_address_appears_once_with_the_planned_values() -> None:
    """A replace present in both sources keeps the planned values and one entry."""
    address = "azurerm_storage_account.data"
    plan = _plan(
        [
            _change_entry(
                address,
                "azurerm_storage_account",
                ["delete", "create"],
                {"name": "st-old"},
                {"name": "st-new"},
            )
        ],
        planned_resources=[_planned_resource(address, "azurerm_storage_account", {"name": "st-new"})],
    )

    document = _builder().build_document_from_json(plan, change_model=_model(plan))

    assert [(resource.name, resource.change_category) for resource in document.resources] == [("st-new", "replace")]


def test_planned_values_document_is_not_mutated_by_the_change_path() -> None:
    """Building with a model leaves the input plan document untouched."""
    plan = _plan(
        [_change_entry("azurerm_redis_cache.gone", "azurerm_redis_cache", ["delete"], {"name": "redis-gone"})],
        planned_resources=[_planned_resource("azurerm_storage_account.keep", "azurerm_storage_account", {"name": "stkeep"})],
    )
    snapshot = _plan(
        [_change_entry("azurerm_redis_cache.gone", "azurerm_redis_cache", ["delete"], {"name": "redis-gone"})],
        planned_resources=[_planned_resource("azurerm_storage_account.keep", "azurerm_storage_account", {"name": "stkeep"})],
    )

    _builder().build_document_from_json(plan, change_model=_model(plan))

    assert plan == snapshot


# ─── Sensitive redaction before normalization (Requirement 10.1) ──────────────


def test_planned_resource_sensitive_leaves_are_masked_from_after_sensitive() -> None:
    """`after_sensitive` masks planned leaves; other leaves survive untouched."""
    address = "azurerm_storage_account.data"
    plan = _plan(
        [
            _change_entry(
                address,
                "azurerm_storage_account",
                ["update"],
                {"name": "stdata"},
                {"name": "stdata", "primary_access_key": "secret"},
                after_sensitive={"primary_access_key": True},
            )
        ],
        planned_resources=[
            _planned_resource(
                address,
                "azurerm_storage_account",
                {"name": "stdata", "location": "westeurope", "primary_access_key": "secret"},
            )
        ],
    )

    resource = _builder().build_document_from_json(plan, change_model=_model(plan)).resources[0]

    assert resource.raw_values["primary_access_key"] == "(sensitive)"
    assert resource.raw_values["location"] == "westeurope"
    assert resource.name == "stdata"


def test_planned_resource_falls_back_to_its_own_sensitive_values() -> None:
    """A plan without `after_sensitive` still masks through `sensitive_values`."""
    address = "azurerm_storage_account.data"
    plan = _plan(
        [_change_entry(address, "azurerm_storage_account", ["update"], {"name": "stdata"}, {"name": "stdata"})],
        planned_resources=[
            _planned_resource(
                address,
                "azurerm_storage_account",
                {"name": "stdata", "primary_access_key": "secret"},
                sensitive_values={"primary_access_key": True},
            )
        ],
    )

    resource = _builder().build_document_from_json(plan, change_model=_model(plan)).resources[0]

    assert resource.raw_values["primary_access_key"] == "(sensitive)"


def test_reconstructed_delete_is_masked_from_before_sensitive() -> None:
    """A deleted resource is masked against `before_sensitive`, not `after_sensitive`."""
    plan = _plan(
        [
            _change_entry(
                "azurerm_redis_cache.gone",
                "azurerm_redis_cache",
                ["delete"],
                {"name": "redis-gone", "primary_access_key": "secret", "location": "westeurope"},
                None,
                before_sensitive={"primary_access_key": True},
            )
        ]
    )

    resource = _builder().build_document_from_json(plan, change_model=_model(plan)).resources[0]

    assert resource.raw_values["primary_access_key"] == "(sensitive)"
    assert resource.raw_values["location"] == "westeurope"


# ─── Change categories (Requirement 4.1) ──────────────────────────────────────


def test_planned_resource_absent_from_resource_changes_defaults_to_unchanged() -> None:
    """A resource the plan never mentions still carries a category."""
    plan = _plan(
        [],
        planned_resources=[_planned_resource("azurerm_storage_account.data", "azurerm_storage_account", {"name": "stdata"})],
    )

    document = _builder().build_document_from_json(plan, change_model=_model(plan))

    assert [resource.change_category for resource in document.resources] == ["unchanged"]


def test_each_category_reaches_the_renderer_template() -> None:
    """create, update, replace, delete and unchanged all surface as changeCategory."""
    plan = _plan(
        [
            _change_entry("azurerm_storage_account.new", "azurerm_storage_account", ["create"], None, {"name": "st-new"}),
            _change_entry("azurerm_storage_account.mod", "azurerm_storage_account", ["update"], {"name": "st-mod"}, {"name": "st-mod"}),
            _change_entry("azurerm_storage_account.rep", "azurerm_storage_account", ["delete", "create"], {"name": "st-rep"}, {"name": "st-rep"}),
            _change_entry("azurerm_storage_account.same", "azurerm_storage_account", ["no-op"], {"name": "st-same"}, {"name": "st-same"}),
            _change_entry("azurerm_redis_cache.gone", "azurerm_redis_cache", ["delete"], {"name": "redis-gone"}),
        ],
        planned_resources=[
            _planned_resource("azurerm_storage_account.new", "azurerm_storage_account", {"name": "st-new"}),
            _planned_resource("azurerm_storage_account.mod", "azurerm_storage_account", {"name": "st-mod"}),
            _planned_resource("azurerm_storage_account.rep", "azurerm_storage_account", {"name": "st-rep"}),
            _planned_resource("azurerm_storage_account.same", "azurerm_storage_account", {"name": "st-same"}),
        ],
    )

    template = _builder().build_document_from_json(plan, change_model=_model(plan)).to_renderer_template()

    assert {resource["name"]: resource["changeCategory"] for resource in template["resources"]} == {
        "st-new": "create",
        "st-mod": "update",
        "st-rep": "replace",
        "st-same": "unchanged",
        "redis-gone": "delete",
    }


# ─── Metadata (Requirement 4.4) ───────────────────────────────────────────────


def test_metadata_carries_counts_a_round_trippable_model_and_the_not_displayed_key() -> None:
    """Plan_Diff_Mode metadata extends the legacy keys without replacing them."""
    plan = _plan(
        [_change_entry("azurerm_storage_account.data", "azurerm_storage_account", ["update"], {"name": "stdata"}, {"name": "stdata"})],
        planned_resources=[_planned_resource("azurerm_storage_account.data", "azurerm_storage_account", {"name": "stdata"})],
    )
    model = _model(plan)

    metadata = _builder().build_document_from_json(plan, change_model=model).to_renderer_template()["metadata"]

    assert metadata["terraformVersion"] == "1.7.5"
    assert metadata["formatVersion"] == "1.2"
    assert metadata["changeCounts"] == {"create": 0, "update": 1, "replace": 0, "delete": 0, "unchanged": 0}
    assert metadata["changesNotDisplayed"] == []
    round_tripped = ChangeModel.from_metadata(metadata["changeModel"])
    assert round_tripped.records == model.records
    assert round_tripped.counts == model.counts


def test_change_without_a_resource_entry_is_reported_as_not_displayed() -> None:
    """A record that reaches no document resource is listed with its reason."""
    plan = _plan(
        [
            _change_entry("azurerm_storage_account.data", "azurerm_storage_account", ["update"], {"name": "stdata"}, {"name": "stdata"}),
            # A create the plan never wrote into planned_values: no resource entry exists.
            _change_entry("azurerm_redis_cache.ghost", "azurerm_redis_cache", ["create"], None, {"name": "redis-ghost"}),
        ],
        planned_resources=[_planned_resource("azurerm_storage_account.data", "azurerm_storage_account", {"name": "stdata"})],
    )

    metadata = _builder().build_document_from_json(plan, change_model=_model(plan)).metadata

    assert metadata["changesNotDisplayed"] == [
        {
            "address": "azurerm_redis_cache.ghost",
            "terraformType": "azurerm_redis_cache",
            "category": "create",
            "reason": "no-resource-entry",
        }
    ]


# ─── Dependency edges of deleted resources (Requirement 3.5) ──────────────────


def test_deleted_resource_keeps_its_configuration_backed_dependency_edges() -> None:
    """A reconstructed delete gets the same dependsOn expressions as a survivor."""
    plan = _plan(
        [
            _change_entry(
                "azurerm_subnet.app",
                "azurerm_subnet",
                ["delete"],
                {"name": "snet-app", "virtual_network_name": "vnet-hub", "address_prefixes": ["10.0.1.0/24"]},
            )
        ],
        planned_resources=[
            _planned_resource(
                "azurerm_virtual_network.hub", "azurerm_virtual_network", {"name": "vnet-hub", "address_space": ["10.0.0.0/16"]}
            )
        ],
        configuration={
            "root_module": {
                "resources": [
                    {
                        "address": "azurerm_subnet.app",
                        "expressions": {"virtual_network_name": {"references": ["azurerm_virtual_network.hub"]}},
                    }
                ]
            }
        },
    )

    document = _builder().build_document_from_json(plan, change_model=_model(plan))

    subnet = _by_name(document)["vnet-hub/snet-app"]
    assert subnet.change_category == "delete"
    assert subnet.depends_on == ["[resourceId('Microsoft.Network/virtualNetworks', 'vnet-hub')]"]


def test_references_to_addresses_absent_from_the_document_drop_out() -> None:
    """A dependency on an address no resource represents yields no edge."""
    plan = _plan(
        [_change_entry("azurerm_redis_cache.gone", "azurerm_redis_cache", ["delete"], {"name": "redis-gone"})],
        configuration={
            "root_module": {
                "resources": [
                    {
                        "address": "azurerm_redis_cache.gone",
                        "expressions": {"subnet_id": {"references": ["azurerm_subnet.missing"]}},
                    }
                ]
            }
        },
    )

    document = _builder().build_document_from_json(plan, change_model=_model(plan))

    assert document.resources[0].depends_on == []


def test_plan_without_a_configuration_block_renders_deletes_without_edges() -> None:
    """A destroy plan lacking `configuration` still builds, just without edges."""
    plan = _plan([_change_entry("azurerm_redis_cache.gone", "azurerm_redis_cache", ["delete"], {"name": "redis-gone"})])

    document = _builder().build_document_from_json(plan, change_model=_model(plan))

    assert [(resource.name, resource.change_category, resource.depends_on) for resource in document.resources] == [
        ("redis-gone", "delete", [])
    ]

# ══════════════════════════════════════════════════════════════════════════════
# Property tests
# ══════════════════════════════════════════════════════════════════════════════


# ─── Property 8 ───────────────────────────────────────────────────────────────


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(plan=plan_documents(max_resources=4))
def test_property_8_change_model_round_trips_through_the_renderer_template(plan):
    """For any Change_Model, the Renderer_Template carries it back unchanged.

    Feature: terraform-plan-diff-visualization, Property 8: Change_Model round
    trip through the Renderer_Template — for any Change_Model, serializing it
    into the Renderer_Template and parsing the template ``metadata`` back yields
    a Change_Model equal to the original, the per-category counts appear under
    the ``metadata`` key, and each resource entry carries ``changeCategory``
    exactly when its resource holds a Change_Category and omits the key
    otherwise.

    The round trip runs through the real Renderer_Template, JSON-serialized and
    parsed back, so serialization fidelity is part of what is checked.

    **Validates: Requirements 4.1, 4.2, 4.4, 12.7**
    """
    model = ChangeExtractor().extract(plan.get("resource_changes"))
    document = _builder().build_document_from_json(plan, change_model=model)

    # Through the real renderer contract, JSON-serialized and parsed back.
    template = json.loads(json.dumps(document.to_renderer_template()))
    metadata = template["metadata"]

    # Per-category counts under the metadata key, one entry per category.
    assert metadata["changeCounts"] == model.counts
    assert set(metadata["changeCounts"]) == set(CHANGE_CATEGORIES)

    # The parsed model equals the original.
    round_tripped = ChangeModel.from_metadata(metadata["changeModel"])
    assert round_tripped == model
    assert round_tripped.records == model.records
    assert round_tripped.counts == model.counts
    assert round_tripped.warnings == model.warnings
    assert round_tripped.present_categories() == model.present_categories()
    assert round_tripped.has_changes() == model.has_changes()
    for address, record in model.records.items():
        assert round_tripped.category_for(address) == record.category
        assert round_tripped.records[address].actions == record.actions

    # changeCategory is emitted exactly when the resource holds a category.
    assert len(template["resources"]) == len(document.resources)
    for emitted, resource in zip(template["resources"], document.resources):
        assert ("changeCategory" in emitted) == (resource.change_category is not None)
        assert emitted.get("changeCategory") == resource.change_category
        assert resource.change_category in CHANGE_CATEGORIES

    # The other half of "omits the key otherwise": the same plan without a model.
    legacy = json.loads(json.dumps(_builder().build_document_from_json(plan).to_renderer_template()))
    assert all("changeCategory" not in emitted for emitted in legacy["resources"])
    assert "changeModel" not in legacy.get("metadata", {})

# ─── Property 5 ───────────────────────────────────────────────────────────────


def _expected_display_name(terraform_type: str, address: str, before: Dict[str, Any]) -> str:
    """Mirror `_build_resource_name` for a resource reconstructed from `before`.

    The reconstruction hands the Terraform address to the builder as the entry `name`, so a
    `before` object without a `name` value displays as the address (Requirement 3.4).
    """
    base = before.get("name") or address
    if terraform_type == "azurerm_subnet":
        vnet_name = before.get("virtual_network_name")
        if vnet_name and base:
            return f"{vnet_name}/{base}"
    if terraform_type == "azurerm_private_dns_zone_virtual_network_link":
        zone_name = before.get("private_dns_zone_name")
        if zone_name and base:
            return f"{zone_name}/{base}"
    return str(base)


def _expected_renderer_type(terraform_type: str) -> str:
    """Mirror the Terraform-type-to-renderer-type mapping of `_normalize_resource`."""
    mapped = _TERRAFORM_TO_RENDERER_TYPE.get(terraform_type)
    return mapped if mapped is not None else f"Terraform.Azurerm/{terraform_type.replace('azurerm_', '', 1)}"


def _strip_before_names(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the plan whose delete entries carry a `before` without `name`."""
    stripped = copy.deepcopy(plan)
    for entry in stripped.get("resource_changes") or []:
        change = entry.get("change") or {}
        if change.get("actions") == ["delete"] and isinstance(change.get("before"), dict):
            change["before"].pop("name", None)
    return stripped


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(plan=plan_documents(max_resources=5), strip_delete_names=st.booleans())
def test_property_5_deletes_are_reconstructed_exactly_once_from_before(plan, strip_delete_names):
    """For any Plan_File, deletes and replaces each yield exactly one entry.

    Feature: terraform-plan-diff-visualization, Property 5: Delete reconstruction
    completeness and address uniqueness — for any Plan_File, every address whose
    Change_Category is ``delete`` or ``replace`` and that maps to a supported
    renderer type appears exactly once among the resource entries of the
    Renderer_Template, and for ``delete`` addresses absent from ``planned_values``
    the entry is derived from the change entry's ``before`` object, using the
    Terraform address as displayed name whenever ``before`` carries no ``name``.

    The strategy keeps delete addresses out of ``planned_values``, mirroring the
    post-apply state a real plan describes, so reconstruction is the only way
    those addresses can reach the document. ``strip_delete_names`` removes the
    ``name`` value from every delete ``before`` object to exercise the address
    fallback of Requirement 3.4.

    **Validates: Requirements 3.1, 3.3, 3.4**
    """
    if strip_delete_names:
        plan = _strip_before_names(plan)

    model = _model(plan)
    document = _builder().build_document_from_json(plan, change_model=model)
    template = document.to_renderer_template()

    # Renderer entries are emitted in document order, one per resource.
    assert len(template["resources"]) == len(document.resources)
    emitted_by_address: Dict[str, List[Dict[str, Any]]] = {}
    for resource, emitted in zip(document.resources, template["resources"]):
        emitted_by_address.setdefault(resource.address, []).append(emitted)

    planned_by_address = {
        resource["address"]: resource
        for resource in plan["planned_values"]["root_module"]["resources"]
    }
    change_by_address = {entry["address"]: entry for entry in plan.get("resource_changes") or []}

    destructive = [record for record in model.records.values() if record.category in {"delete", "replace"}]
    for record in destructive:
        # Exactly one resource entry per destructive address (Requirements 3.1, 3.3).
        entries = emitted_by_address.get(record.address, [])
        assert len(entries) == 1, f"{record.address} yielded {len(entries)} entries"

        if record.category == "replace":
            # A replace lives in planned_values; the planned entry is the one kept.
            assert record.address in planned_by_address
            continue

        # A delete is absent from planned_values, so its entry comes from `before`.
        assert record.address not in planned_by_address
        before = change_by_address[record.address]["change"]["before"]
        resource = next(item for item in document.resources if item.address == record.address)

        assert resource.raw_values == before
        assert resource.name == _expected_display_name(record.terraform_type, record.address, before)
        assert entries[0]["name"] == resource.name
        assert entries[0]["type"] == _expected_renderer_type(record.terraform_type)

        if "name" not in before:
            # Requirement 3.4: the address carries the display name.
            assert record.address in resource.name

# ─── Property 6 ───────────────────────────────────────────────────────────────


@st.composite
def _reconstructable_resources(draw) -> tuple:
    """Draw an ``(address, terraform_type, values)`` triple usable through both paths.

    The values block always carries a ``name``, which is what lets the two paths agree on the
    displayed name: the address fallback of Requirement 3.4 is Property 5's subject, not this
    one. Types come from the full pool, mapped and unmapped alike.
    """
    address, terraform_type, resource_name = draw(address_parts(types=terraform_types()))
    values = draw(azurerm_resource_values(terraform_type=terraform_type, resource_name=resource_name))
    return address, terraform_type, values


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(spec=_reconstructable_resources())
def test_property_6_reconstruction_normalizes_exactly_like_planned_values(spec):
    """For any resource value object, both entry paths normalize identically.

    Feature: terraform-plan-diff-visualization, Property 6: Reconstruction uses
    the same normalization as planned values — for any Terraform resource value
    object, the resource entry produced by reconstructing it from a delete
    entry's ``before`` object is equal — in ``type``, ``name``, ``properties``,
    and extra fields — to the entry produced by supplying the identical value
    object through ``planned_values``.

    The same value object is fed twice: once as a planned resource carrying a
    ``no-op`` change, once as a ``delete`` change whose ``before`` holds it while
    ``planned_values`` stays empty. Only the Change_Category may differ.

    **Validates: Requirements 3.2**
    """
    address, terraform_type, values = spec

    planned_plan = _plan(
        [_change_entry(address, terraform_type, ["no-op"], copy.deepcopy(values), copy.deepcopy(values))],
        planned_resources=[_planned_resource(address, terraform_type, copy.deepcopy(values))],
    )
    delete_plan = _plan([_change_entry(address, terraform_type, ["delete"], copy.deepcopy(values))])

    planned_document = _builder().build_document_from_json(planned_plan, change_model=_model(planned_plan))
    delete_document = _builder().build_document_from_json(delete_plan, change_model=_model(delete_plan))

    # Both paths yield exactly one resource for the address.
    assert len(planned_document.resources) == 1
    assert len(delete_document.resources) == 1
    planned_resource, delete_resource = planned_document.resources[0], delete_document.resources[0]

    # Same renderer type mapping (Requirement 3.2), and the mapping is the documented one.
    assert delete_resource.renderer_type == planned_resource.renderer_type
    assert delete_resource.renderer_type == _expected_renderer_type(terraform_type)
    assert delete_resource.source_type == planned_resource.source_type == terraform_type

    # Same displayed name, properties, extra fields and retained raw values.
    assert delete_resource.name == planned_resource.name
    assert delete_resource.properties == planned_resource.properties
    assert delete_resource.extra_fields == planned_resource.extra_fields
    assert delete_resource.raw_values == planned_resource.raw_values
    assert delete_resource.address == planned_resource.address == address
    assert delete_resource.provider_name == planned_resource.provider_name

    # The categories are the one legitimate difference; everything else agrees.
    assert planned_resource.change_category == "unchanged"
    assert delete_resource.change_category == "delete"

    planned_emitted = planned_resource.to_renderer_resource()
    delete_emitted = delete_resource.to_renderer_resource()
    assert planned_emitted.pop("changeCategory") == "unchanged"
    assert delete_emitted.pop("changeCategory") == "delete"
    assert delete_emitted == planned_emitted

# ─── Property 7 ───────────────────────────────────────────────────────────────

#: An address the plan references but never represents, in `planned_values` or in `resource_changes`.
_PHANTOM_ADDRESS = "azurerm_key_vault.__absent__"


def _config_entry(plan: Dict[str, Any], address: str) -> Optional[Dict[str, Any]]:
    """Return the `configuration.root_module.resources` entry of an address, if any."""
    root_module = (plan.get("configuration") or {}).get("root_module") or {}
    for entry in root_module.get("resources") or []:
        if entry.get("address") == address:
            return entry
    return None


def _collect_references(node: Any) -> List[str]:
    """Mirror `_extract_references`: every `references` string in an expressions tree, in order."""
    references: List[str] = []
    if isinstance(node, dict):
        value = node.get("references")
        if isinstance(value, list):
            references.extend(reference for reference in value if isinstance(reference, str))
        for child in node.values():
            references.extend(_collect_references(child))
    elif isinstance(node, list):
        for item in node:
            references.extend(_collect_references(item))
    return references


def _resolve_target(reference: str, represented: Dict[str, Any]) -> Optional[str]:
    """Mirror `_resolve_reference_target`: exact address, else the longest address prefix."""
    if reference in represented:
        return reference
    for candidate in sorted(represented, key=len, reverse=True):
        if reference.startswith(f"{candidate}."):
            return candidate
    return None


def _expected_resource_id(renderer_type: str, resource_name: str) -> str:
    """Mirror `_resource_id_expression` for the expected `dependsOn` entries."""
    segments = [segment.replace("'", "''") for segment in resource_name.split("/") if segment]
    quoted = ", ".join(f"'{segment}'" for segment in segments)
    return f"[resourceId('{renderer_type}', {quoted})]" if quoted else f"[resourceId('{renderer_type}')]"


def _expected_depends_on(plan: Dict[str, Any], address: str, represented: Dict[str, Any]) -> List[str]:
    """The dependency expressions an address must carry, given the addresses still represented."""
    entry = _config_entry(plan, address)
    references = list(dict.fromkeys(_collect_references((entry or {}).get("expressions") or {})))

    depends_on: List[str] = []
    for reference in references:
        target = _resolve_target(reference, represented)
        if target is None or target == address:
            continue
        expression = _expected_resource_id(*represented[target])
        if expression not in depends_on:
            depends_on.append(expression)
    return depends_on


@st.composite
def _plans_with_a_deleted_dependent(draw) -> tuple:
    """Draw a plan holding a delete whose configuration references present and absent addresses.

    Three post-processing steps turn a generated plan into the shape this property needs:

    1. One address is promoted to ``delete``: its ``change`` becomes ``{"actions": ["delete"],
       "before": <values>}`` and its ``planned_values`` entry is removed, mirroring the
       post-apply state a real plan describes.
    2. Optionally another address is *orphaned* - dropped from both ``planned_values`` and
       ``resource_changes`` while its ``configuration`` entry survives - so the plan references an
       address no resource entry represents.
    3. Reference expressions are injected into the deleted resource's configuration entry: one to
       a surviving address, one to the orphaned address, one to a phantom address.

    ``with_configuration`` is drawn as well, so the documented limitation (a destroy plan without
    a ``configuration`` block yields no edges) is part of the generated space.
    """
    plan = draw(plan_documents(min_resources=2, max_resources=5, with_configuration=draw(st.booleans())))

    change_entries = plan["resource_changes"]
    planned = plan["planned_values"]["root_module"]["resources"]
    addresses = [entry["address"] for entry in change_entries]

    # 1. Promote one address to a delete absent from planned_values.
    deleted_address = draw(st.sampled_from(addresses))
    values = next((item["values"] for item in planned if item["address"] == deleted_address), None)
    deleted_entry = next(entry for entry in change_entries if entry["address"] == deleted_address)
    if values is None:
        values = (deleted_entry.get("change") or {}).get("before") or {}
    deleted_entry["change"] = {"actions": ["delete"], "before": copy.deepcopy(values)}
    plan["planned_values"]["root_module"]["resources"] = [
        item for item in planned if item["address"] != deleted_address
    ]

    # 2. Optionally orphan another address: referenced by the configuration, represented nowhere.
    others = [address for address in addresses if address != deleted_address]
    orphan_address = draw(st.sampled_from(others)) if others and draw(st.booleans()) else None
    if orphan_address is not None:
        plan["planned_values"]["root_module"]["resources"] = [
            item for item in plan["planned_values"]["root_module"]["resources"] if item["address"] != orphan_address
        ]
        plan["resource_changes"] = [entry for entry in change_entries if entry["address"] != orphan_address]

    # 3. Wire the deleted resource to a survivor, to the orphan and to a phantom address.
    config_entry = _config_entry(plan, deleted_address)
    if config_entry is not None:
        expressions = config_entry.setdefault("expressions", {})
        survivors = [address for address in others if address != orphan_address]
        if survivors:
            expressions["survivor_id"] = {"references": [draw(st.sampled_from(survivors))]}
        if orphan_address is not None:
            expressions["orphan_id"] = {"references": [orphan_address]}
        if draw(st.booleans()):
            expressions["phantom_id"] = {"references": [_PHANTOM_ADDRESS]}

    return plan, deleted_address, orphan_address


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(spec=_plans_with_a_deleted_dependent())
def test_property_7_deleted_resource_dependency_references_are_preserved(spec):
    """For any plan, a delete keeps the edges whose targets remain and loses the others.

    Feature: terraform-plan-diff-visualization, Property 7: Dependency references
    of deleted resources are preserved — for any Plan_File whose deleted resources
    declare dependency references in ``configuration``, every reference pointing
    at an address still represented in the document appears as a ``dependsOn``
    resourceId expression on the reconstructed delete resource, and every
    reference pointing at an address no longer represented appears in no
    ``dependsOn`` entry.

    The expected edge list is recomputed from the plan's ``configuration`` block
    and the addresses the document actually represents, using the same reference
    resolution the builder applies, so both halves of the property are checked at
    once: preservation and drop-out. A plan drawn without a ``configuration``
    block exercises the documented limitation — deletes then carry no edges at
    all rather than failing the build.

    **Validates: Requirements 3.5**
    """
    plan, deleted_address, orphan_address = spec

    document = _builder().build_document_from_json(plan, change_model=_model(plan))

    represented = {resource.address: (resource.renderer_type, resource.name) for resource in document.resources}

    # The reconstructed delete reached the document, and the orphan did not.
    assert deleted_address in represented
    deleted_resource = next(resource for resource in document.resources if resource.address == deleted_address)
    assert deleted_resource.change_category == "delete"
    if orphan_address is not None:
        assert orphan_address not in represented

    every_expression = {_expected_resource_id(*target) for target in represented.values()}

    for resource in document.resources:
        if resource.change_category != "delete":
            continue

        # Preserved references and dropped references, in one equality.
        assert resource.depends_on == _expected_depends_on(plan, resource.address, represented)

        # Every retained edge points at a resource the document represents.
        assert set(resource.depends_on) <= every_expression
        assert len(set(resource.depends_on)) == len(resource.depends_on)

        if "configuration" not in plan:
            # Documented limitation: a destroy plan without `configuration` yields no edges.
            assert resource.depends_on == []

    # The renderer template carries the same edges the document holds.
    template = document.to_renderer_template()
    for resource, emitted in zip(document.resources, template["resources"]):
        assert emitted.get("dependsOn", []) == resource.depends_on

# ─── Property 19 ──────────────────────────────────────────────────────────────

#: Everything-sensitive mask, used as the *wrong* phase's mask so a phase mix-up is visible.
_MASK_EVERYTHING = True


def _assert_leaf_redaction(original: Any, mask: Any, redacted: Any, path: str = "values") -> None:
    """Assert `redacted` masks exactly the leaves `mask` flags, leaf by leaf.

    The mask mirrors the value tree: dictionaries match by key (an absent key flags nothing),
    lists match by index (a missing index flags nothing), and a truthy scalar flags the whole
    subtree beneath it. Both halves of Property 19 are checked in one walk: a flagged position
    must hold the literal `(sensitive)`, an unflagged position must hold its original value,
    byte for byte.
    """
    if not isinstance(mask, (dict, list)):
        if mask is None or not bool(mask):
            assert redacted == original, f"{path}: unflagged value was modified"
        else:
            assert redacted == "(sensitive)", f"{path}: flagged value was not masked"
        return

    if isinstance(mask, dict) and isinstance(original, dict):
        assert set(redacted) == set(original), f"{path}: keys changed during redaction"
        for key, child in original.items():
            child_path = f"{path}.{key}"
            if key in mask:
                _assert_leaf_redaction(child, mask[key], redacted[key], child_path)
            else:
                assert redacted[key] == child, f"{child_path}: unflagged key was modified"
        return

    if isinstance(mask, list) and isinstance(original, list):
        assert len(redacted) == len(original), f"{path}: list length changed during redaction"
        for index, item in enumerate(original):
            _assert_leaf_redaction(
                item, mask[index] if index < len(mask) else None, redacted[index], f"{path}[{index}]"
            )
        return

    # The mask does not mirror the value tree here, so it flags nothing at this position.
    assert redacted == original, f"{path}: value modified by a mask of a different shape"


@st.composite
def _sensitive_specs(draw) -> tuple:
    """Draw an ``(address, terraform_type, values, mask)`` quadruple with an aligned mask.

    A resource's sensitivity map is an object in every Terraform plan - the attribute names are
    always known - so a scalar root mask is normalized into a per-attribute object. Whole-subtree
    flags still occur, both at the top level and nested, which is how Terraform marks opaque
    objects.
    """
    address, terraform_type, resource_name = draw(address_parts(types=terraform_types()))
    values, mask = draw(
        sensitive_masks(values=azurerm_resource_values(terraform_type=terraform_type, resource_name=resource_name))
    )
    if not isinstance(mask, dict):
        mask = {key: True for key in values}
    return address, terraform_type, values, mask


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(spec=_sensitive_specs())
def test_property_19_sensitive_leaves_are_masked_and_others_are_untouched(spec):
    """For any value tree and parallel mask, flagged leaves are masked and the rest survive.

    Feature: terraform-plan-diff-visualization, Property 19: Sensitive leaves are
    masked and non-sensitive leaves are untouched — for any Terraform value tree
    and any parallel sensitivity mask, every value whose mask leaf is ``true`` is
    replaced by the literal string ``(sensitive)`` in the Renderer_Template, and
    every value whose mask leaf is absent or ``false`` is preserved unchanged.

    The same ``(value_tree, mask)`` pair is fed through all three mask sources the
    builder resolves: a planned resource's ``after_sensitive``, a planned
    resource's own ``sensitive_values`` when the change entry carries no
    ``after_sensitive``, and a reconstructed delete's ``before_sensitive``. In
    each case the opposite phase carries an everything-sensitive mask, so using
    the wrong phase would mask the whole tree and fail the walk.

    **Validates: Requirements 10.1**
    """
    address, terraform_type, values, mask = spec
    builder = _builder()

    # ── Planned resource, masked through `after_sensitive` ────────────────────
    planned_plan = _plan(
        [
            _change_entry(
                address,
                terraform_type,
                ["update"],
                copy.deepcopy(values),
                copy.deepcopy(values),
                before_sensitive=_MASK_EVERYTHING,
                after_sensitive=copy.deepcopy(mask),
            )
        ],
        planned_resources=[_planned_resource(address, terraform_type, copy.deepcopy(values))],
    )
    assert builder._sensitive_mask_for(planned_plan, address, "after") == mask

    planned_resource = builder.build_document_from_json(planned_plan, change_model=_model(planned_plan)).resources[0]
    _assert_leaf_redaction(values, mask, planned_resource.raw_values)

    # ── Planned resource, falling back to its own `sensitive_values` ──────────
    fallback_plan = _plan(
        [
            _change_entry(
                address,
                terraform_type,
                ["update"],
                copy.deepcopy(values),
                copy.deepcopy(values),
                before_sensitive=_MASK_EVERYTHING,
            )
        ],
        planned_resources=[
            _planned_resource(address, terraform_type, copy.deepcopy(values), sensitive_values=copy.deepcopy(mask))
        ],
    )
    assert builder._sensitive_mask_for(fallback_plan, address, "after") == mask

    fallback_resource = builder.build_document_from_json(fallback_plan, change_model=_model(fallback_plan)).resources[0]
    _assert_leaf_redaction(values, mask, fallback_resource.raw_values)

    # ── Reconstructed delete, masked through `before_sensitive` ───────────────
    delete_plan = _plan(
        [
            _change_entry(
                address,
                terraform_type,
                ["delete"],
                copy.deepcopy(values),
                None,
                before_sensitive=copy.deepcopy(mask),
                after_sensitive=_MASK_EVERYTHING,
            )
        ]
    )
    assert builder._sensitive_mask_for(delete_plan, address, "before") == mask

    delete_resource = builder.build_document_from_json(delete_plan, change_model=_model(delete_plan)).resources[0]
    assert delete_resource.change_category == "delete"
    _assert_leaf_redaction(values, mask, delete_resource.raw_values)

    # ── The redaction survives serialization into the Renderer_Template ───────
    for resource in (planned_resource, fallback_resource, delete_resource):
        emitted = json.loads(json.dumps(resource.to_renderer_resource()))
        assert emitted["type"] == _expected_renderer_type(terraform_type)
        assert emitted["name"] == resource.name
        # Redacted properties are derived from the redacted value tree, never from the raw one.
        _assert_leaf_redaction(values, mask, resource.raw_values)
