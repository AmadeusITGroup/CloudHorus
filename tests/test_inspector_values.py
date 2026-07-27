"""Unit tests for `TerraformTemplateBuilder._inspector_values_for`.

Covers the Change_Category resolution table and every fallback branch of
Requirement 6, the redaction reuse of Requirements 11.1 to 11.4, and the
Requirement 10.4 snapshot for a resource carrying no attribute map.

Properties 8 and 19 live in this file too (tasks 4.3 and 4.4); these units pin
the specific branches a property test only samples.
"""

import inspect
import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from cloudhorus.models.local_template_document import LocalTemplateResource
from core.terraform_builder import TerraformTemplateBuilder
from core.terraform_builder import build_terraform_template as build_terraform_template_wrapper

SENSITIVE = "(sensitive)"
ADDRESS = "azurerm_mssql_server.primary"


# ─── Helpers ──────────────────────────────────────────────────────────────────


class _RecordCollector(logging.Handler):
    """Collect the messages the singleton logger emits, which does not propagate."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[Any] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append((record.levelno, record.getMessage()))

    def warnings(self) -> List[str]:
        return [message for levelno, message in self.records if levelno == logging.WARNING]

    def messages(self, level: int) -> List[str]:
        """The messages emitted at exactly one level."""
        return [message for levelno, message in self.records if levelno == level]


@contextmanager
def captured_logs():
    """Attach a collecting handler to the singleton logger for the block."""
    logger = logging.getLogger("SingletonLogger")
    handler = _RecordCollector()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _builder() -> TerraformTemplateBuilder:
    return TerraformTemplateBuilder()


def _resource(
    values: Optional[Dict[str, Any]] = None,
    properties: Optional[Dict[str, Any]] = None,
    extra_fields: Optional[Dict[str, Any]] = None,
) -> LocalTemplateResource:
    """A normalized resource at :data:`ADDRESS`."""
    return LocalTemplateResource(
        address=ADDRESS,
        provider_name="azurerm",
        source_type="azurerm_mssql_server",
        renderer_type="Microsoft.Sql/servers",
        name="sql-primary",
        properties=properties or {},
        extra_fields=extra_fields or {},
        raw_values=values if values is not None else {"name": "sql-primary", "version": "12.0"},
    )


def _plan(
    change: Optional[Dict[str, Any]] = None,
    planned_values: Optional[Dict[str, Any]] = None,
    sensitive_values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A plan document carrying one change entry and one planned resource."""
    document: Dict[str, Any] = {
        "format_version": "1.0",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": ADDRESS,
                        "mode": "managed",
                        "type": "azurerm_mssql_server",
                        "name": "primary",
                        "provider_name": "azurerm",
                        "values": planned_values if planned_values is not None else {"name": "sql-primary"},
                        "sensitive_values": sensitive_values,
                    }
                ]
            }
        },
    }
    if change is not None:
        document["resource_changes"] = [
            {"address": ADDRESS, "mode": "managed", "type": "azurerm_mssql_server", "change": change}
        ]
    return document


# ─── The Change_Category table (Requirements 6.1 to 6.5) ──────────────────────


def test_create_leaves_the_before_snapshot_empty_and_redacts_the_after_object() -> None:
    """`create`: empty before, after from the redacted `change.after` (6.1, 11.1)."""
    plan = _plan(
        {
            "before": None,
            "after": {"name": "sql-primary", "administrator_login_password": "p@ss"},
            "after_sensitive": {"administrator_login_password": True},
        }
    )

    values = _builder()._inspector_values_for(plan, _resource(), "create")

    assert values["before"] == {}
    assert values["after"] == {"name": "sql-primary", "administrator_login_password": SENSITIVE}


def test_delete_takes_the_before_object_and_leaves_the_after_snapshot_empty() -> None:
    """`delete`: before from the redacted `change.before`, empty after (6.2)."""
    plan = _plan(
        {
            "before": {"name": "sql-primary", "administrator_login_password": "p@ss"},
            "before_sensitive": {"administrator_login_password": True},
            "after": None,
        }
    )

    values = _builder()._inspector_values_for(plan, _resource(), "delete")

    assert values["before"] == {"name": "sql-primary", "administrator_login_password": SENSITIVE}
    assert values["after"] == {}


def test_update_takes_both_sides_of_the_change_object_redacted_per_phase() -> None:
    """`update`: both phases from the change object, each against its own mask (6.3, 11.2, 11.4)."""
    plan = _plan(
        {
            "before": {"version": "12.0", "administrator_login_password": "old"},
            "before_sensitive": {"administrator_login_password": True},
            "after": {"version": "12.0", "administrator_login_password": "new"},
            "after_sensitive": {},
        }
    )

    values = _builder()._inspector_values_for(plan, _resource(), "update")

    # Flagged in the before phase only: the after phase keeps its own value (11.4).
    assert values["before"] == {"version": "12.0", "administrator_login_password": SENSITIVE}
    assert values["after"] == {"version": "12.0", "administrator_login_password": "new"}


def test_replace_takes_both_sides_of_the_change_object() -> None:
    """`replace` resolves exactly like `update` (6.4)."""
    plan = _plan({"before": {"sku": "S0"}, "after": {"sku": "S1"}})

    values = _builder()._inspector_values_for(plan, _resource(), "replace")

    assert values["before"] == {"sku": "S0"}
    assert values["after"] == {"sku": "S1"}


def test_unchanged_puts_the_same_redacted_attribute_map_on_both_sides() -> None:
    """`unchanged`: one tree both sides, so every entry lands `unchanged` (6.5, 11.7)."""
    plan = _plan(
        {"before": {"sku": "S0"}, "after": {"sku": "S0"}},
        sensitive_values={"administrator_login_password": True},
    )
    resource = _resource({"name": "sql-primary", "administrator_login_password": "p@ss"})

    values = _builder()._inspector_values_for(plan, resource, "unchanged")

    expected = {"name": "sql-primary", "administrator_login_password": SENSITIVE}
    assert values["before"] == expected
    assert values["after"] == expected


def test_after_phase_mask_falls_back_to_the_planned_sensitive_values() -> None:
    """The after mask resolution is the one `_sensitive_mask_for` already implements (11.2)."""
    plan = _plan(
        {"before": {"sku": "S0"}, "after": {"sku": "S1", "administrator_login_password": "p@ss"}},
        sensitive_values={"administrator_login_password": True},
    )

    values = _builder()._inspector_values_for(plan, _resource(), "update")

    assert values["after"] == {"sku": "S1", "administrator_login_password": SENSITIVE}


# ─── Fallback branches (Requirements 6.7, 6.8, 6.9) ───────────────────────────


def test_missing_after_object_falls_back_to_the_attribute_map_and_logs_the_address() -> None:
    """`create` with no `change.after`: the redacted attribute map, address logged (6.7)."""
    plan = _plan({"before": None})
    resource = _resource({"name": "sql-primary", "version": "12.0"})

    with captured_logs() as handler:
        values = _builder()._inspector_values_for(plan, resource, "create")

    assert values["before"] == {}
    assert values["after"] == {"name": "sql-primary", "version": "12.0"}
    assert any(ADDRESS in message for message in handler.warnings())


def test_null_after_object_is_treated_as_absent_for_update() -> None:
    """An explicitly null `change.after` walks the same 6.7 fallback."""
    plan = _plan({"before": {"sku": "S0"}, "after": None})

    with captured_logs() as handler:
        values = _builder()._inspector_values_for(plan, _resource(), "update")

    assert values["before"] == {"sku": "S0"}
    assert values["after"] == {"name": "sql-primary", "version": "12.0"}
    assert any(ADDRESS in message for message in handler.warnings())


def test_missing_before_object_empties_the_before_snapshot_and_logs_the_address() -> None:
    """`update` with no `change.before`: empty before, address logged (6.8)."""
    plan = _plan({"after": {"sku": "S1"}})

    with captured_logs() as handler:
        values = _builder()._inspector_values_for(plan, _resource(), "update")

    assert values["before"] == {}
    assert values["after"] == {"sku": "S1"}
    assert any(ADDRESS in message for message in handler.warnings())


def test_missing_before_object_empties_the_before_snapshot_for_delete() -> None:
    """`delete` with no `change.before` keeps both snapshots empty (6.8)."""
    plan = _plan({"after": None})

    with captured_logs() as handler:
        values = _builder()._inspector_values_for(plan, _resource(), "delete")

    assert values["before"] == {}
    assert values["after"] == {}
    assert any(ADDRESS in message for message in handler.warnings())


def test_no_change_object_uses_the_attribute_map_on_both_sides_and_logs_at_debug() -> None:
    """A resource with no change entry: one tree both sides, no warning (6.9).

    An input with no plan data carries no change entry for *any* resource, so this
    branch is the normal case rather than an anomaly: the address is recorded at
    debug level and the volume is reported once per document by
    `_attach_inspector_values`.
    """
    plan = _plan()
    resource = _resource({"name": "sql-primary", "version": "12.0"})

    with captured_logs() as handler:
        values = _builder()._inspector_values_for(plan, resource, "unchanged")

    assert values["before"] == values["after"] == {"name": "sql-primary", "version": "12.0"}
    assert handler.warnings() == []
    assert any(ADDRESS in message for message in handler.messages(logging.DEBUG))


def test_an_unrecognized_category_resolves_like_unchanged() -> None:
    """An out-of-set category keeps the helper total: the map on both sides."""
    plan = _plan({"before": {"sku": "S0"}, "after": {"sku": "S1"}})

    values = _builder()._inspector_values_for(plan, _resource(), "exploded")

    assert values["before"] == values["after"] == {"name": "sql-primary", "version": "12.0"}


def test_a_fully_resolved_change_entry_logs_nothing() -> None:
    """Both phases present: no warning, so the fallback logs stay diagnostic."""
    plan = _plan({"before": {"sku": "S0"}, "after": {"sku": "S1"}})

    with captured_logs() as handler:
        _builder()._inspector_values_for(plan, _resource(), "update")

    assert handler.warnings() == []


# ─── after_unknown (Requirement 6.6) ──────────────────────────────────────────


def test_after_unknown_is_carried_through_untouched() -> None:
    """The unknown mask reaches the triple exactly as the plan wrote it (6.6)."""
    unknown = {"fully_qualified_domain_name": True, "identity": [{"principal_id": True}]}
    plan = _plan({"before": {"sku": "S0"}, "after": {"sku": "S1"}, "after_unknown": unknown})

    values = _builder()._inspector_values_for(plan, _resource(), "update")

    assert values["afterUnknown"] == unknown
    assert values["afterUnknown"] is unknown


def test_the_unknown_key_is_absent_when_the_plan_carries_no_mask() -> None:
    """No `after_unknown`, no key: the payload stays lean."""
    plan = _plan({"before": {"sku": "S0"}, "after": {"sku": "S1"}, "after_unknown": None})

    values = _builder()._inspector_values_for(plan, _resource(), "update")

    assert "afterUnknown" not in values


# ─── No attribute map (Requirement 10.4) ──────────────────────────────────────


def test_a_resource_with_no_attribute_map_is_described_by_properties_and_extra_fields() -> None:
    """Legacy_Mode snapshot: the Renderer_Template `properties` plus the extra fields (10.4)."""
    resource = _resource(
        values={},
        properties={"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}},
        extra_fields={"location": "westeurope", "tags": {"env": "prod"}, "kind": None},
    )

    values = _builder()._inspector_values_for({}, resource, None)

    assert values["before"] == values["after"] == {
        "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}},
        "location": "westeurope",
        "tags": {"env": "prod"},
    }


def test_a_renderer_resource_dict_is_accepted_as_the_snapshot_source() -> None:
    """The collector hands renderer entries and Azure dicts to the same helper (10.4, 10.5)."""
    renderer_resource = {
        "type": "Microsoft.Network/virtualNetworks",
        "name": "vnet-hub",
        "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}},
        "location": "westeurope",
        "dependsOn": ["[resourceId('x')]"],
    }

    values = _builder()._inspector_values_for({}, renderer_resource, None)

    assert values["before"] == values["after"] == {
        "properties": {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}},
        "location": "westeurope",
    }


def test_no_resource_yields_no_inspector_values() -> None:
    """A resource the builder cannot describe leaves `inspector_values` unset."""
    assert _builder()._inspector_values_for(_plan(), None, "create") is None


# ─── No extra Plan_File read (Requirement 6.10) ───────────────────────────────


def test_resolution_reuses_the_cached_sensitivity_index() -> None:
    """The helper adds no second index: `_sensitive_indexes` is built once per document (6.10)."""
    plan = _plan({"before": {"sku": "S0"}, "after": {"sku": "S1"}})
    builder = _builder()
    calls: List[int] = []
    original = builder._sensitive_indexes

    def counting_indexes(document: Dict[str, Any]):
        if builder._sensitive_cache is None or builder._sensitive_cache[0] != id(document):
            calls.append(id(document))
        return original(document)

    builder._sensitive_indexes = counting_indexes  # type: ignore[method-assign]

    for _ in range(3):
        builder._inspector_values_for(plan, _resource(), "update")

    assert len(calls) == 1

# ─── Builder entry points (Requirements 1.5, 10.1) ────────────────────────────
#
# `collect_inspector_values` is trailing and defaulted on `build_document_from_json` and on
# `build_terraform_template`. With it `False` the helper is never called, every resource keeps
# `inspector_values` at `None`, and the written Renderer_Template is byte-identical to the one
# the release preceding this feature writes for the same arguments.

VNET_ADDRESS = "azurerm_virtual_network.core"


def _multi_resource_plan() -> Dict[str, Any]:
    """A two-resource plan: a created virtual network and an updated SQL server."""
    return {
        "format_version": "1.0",
        "terraform_version": "1.6.6",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": VNET_ADDRESS,
                        "mode": "managed",
                        "type": "azurerm_virtual_network",
                        "name": "core",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "vnet-core",
                            "resource_group_name": "rg-core",
                            "location": "westeurope",
                            "address_space": ["10.0.0.0/16"],
                        },
                    },
                    {
                        "address": ADDRESS,
                        "mode": "managed",
                        "type": "azurerm_mssql_server",
                        "name": "primary",
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": {
                            "name": "sql-primary",
                            "resource_group_name": "rg-core",
                            "location": "westeurope",
                            "version": "12.0",
                            "administrator_login_password": "new",
                        },
                        "sensitive_values": {"administrator_login_password": True},
                    },
                ]
            }
        },
        "resource_changes": [
            {
                "address": VNET_ADDRESS,
                "mode": "managed",
                "type": "azurerm_virtual_network",
                "provider_name": "registry.terraform.io/hashicorp/azurerm",
                "change": {
                    "actions": ["create"],
                    "before": None,
                    "after": {"name": "vnet-core", "address_space": ["10.0.0.0/16"]},
                },
            },
            {
                "address": ADDRESS,
                "mode": "managed",
                "type": "azurerm_mssql_server",
                "provider_name": "registry.terraform.io/hashicorp/azurerm",
                "change": {
                    "actions": ["update"],
                    "before": {"version": "12.0", "administrator_login_password": "old"},
                    "after": {"version": "12.0", "administrator_login_password": "new"},
                    "before_sensitive": {"administrator_login_password": True},
                    "after_sensitive": {"administrator_login_password": True},
                },
            },
        ],
    }


def _write_plan(tmp_path, name: str = "plan.json") -> str:
    """Write the shared plan document to disk and return its path."""
    path = tmp_path / name
    path.write_text(json.dumps(_multi_resource_plan()), encoding="utf-8")
    return str(path)


def _explode(*_args: Any, **_kwargs: Any) -> None:
    """Stand-in for an Inspector helper that must not be reached."""
    raise AssertionError("the Inspector-disabled path called an Inspector helper")


def _forbid_inspector_helpers(monkeypatch) -> None:
    """Make every Inspector entry point of the builder fatal when called."""
    monkeypatch.setattr(TerraformTemplateBuilder, "_inspector_values_for", _explode)
    monkeypatch.setattr(TerraformTemplateBuilder, "_attach_inspector_values", _explode)


class TestEntryPointSignatures:
    """The keyword is trailing and defaulted, and no pre-existing parameter moved."""

    def test_build_document_from_json_takes_the_keyword_last(self) -> None:
        parameters = inspect.signature(TerraformTemplateBuilder.build_document_from_json).parameters
        assert list(parameters) == ["self", "terraform_json", "change_model", "collect_inspector_values"]
        assert parameters["collect_inspector_values"].default is False

    def test_build_terraform_template_takes_the_keyword_last(self) -> None:
        parameters = inspect.signature(TerraformTemplateBuilder.build_terraform_template).parameters
        assert list(parameters) == [
            "self",
            "terraform_json_file",
            "output_file",
            "change_types",
            "collect_inspector_values",
        ]
        assert parameters["collect_inspector_values"].default is False

    def test_the_wrapper_keeps_change_types_third_and_defaults_the_keyword(self) -> None:
        parameters = inspect.signature(build_terraform_template_wrapper).parameters
        assert list(parameters) == [
            "terraform_json_file",
            "output_file",
            "change_types",
            "collect_inspector_values",
        ]
        assert parameters["collect_inspector_values"].default is False


class TestDisabledPath:
    """Inspector_Mode off: no helper call, no field, no key."""

    def test_the_default_leaves_inspector_values_unset_on_every_resource(self) -> None:
        document = _builder().build_document_from_json(_multi_resource_plan())

        assert document.resources
        assert [resource.inspector_values for resource in document.resources] == [None, None]

    def test_the_default_emits_no_inspector_values_key(self) -> None:
        document = _builder().build_document_from_json(_multi_resource_plan())

        template = document.to_renderer_template()

        assert all("inspectorValues" not in resource for resource in template["resources"])

    def test_the_default_never_calls_the_helper(self, monkeypatch) -> None:
        _forbid_inspector_helpers(monkeypatch)

        document = _builder().build_document_from_json(_multi_resource_plan())

        assert [resource.inspector_values for resource in document.resources] == [None, None]

    def test_an_explicit_false_never_calls_the_helper(self, monkeypatch) -> None:
        _forbid_inspector_helpers(monkeypatch)

        document = _builder().build_document_from_json(
            _multi_resource_plan(), collect_inspector_values=False
        )

        assert all(resource.inspector_values is None for resource in document.resources)

    def test_the_written_template_matches_the_pre_feature_template(self, tmp_path, monkeypatch) -> None:
        """The disabled path is the pre-feature path: same bytes, helpers unreachable (1.5)."""
        plan = _write_plan(tmp_path)
        legacy_output = str(tmp_path / "legacy.json")
        disabled_output = str(tmp_path / "disabled.json")

        _forbid_inspector_helpers(monkeypatch)

        # The pre-feature call shape: three positional arguments, no keyword.
        assert build_terraform_template_wrapper(plan, legacy_output, None) == legacy_output
        assert (
            build_terraform_template_wrapper(plan, disabled_output, None, False) == disabled_output
        )

        legacy_bytes = (tmp_path / "legacy.json").read_bytes()
        assert legacy_bytes == (tmp_path / "disabled.json").read_bytes()
        assert b"inspectorValues" not in legacy_bytes

    def test_a_plan_without_resource_changes_stays_on_the_legacy_branch(self, tmp_path, monkeypatch) -> None:
        """The no-`resource_changes` branch forwards the keyword and stays untouched (1.5)."""
        plan_document = _multi_resource_plan()
        plan_document.pop("resource_changes")
        path = tmp_path / "legacy-plan.json"
        path.write_text(json.dumps(plan_document), encoding="utf-8")
        output = str(tmp_path / "out.json")

        _forbid_inspector_helpers(monkeypatch)

        assert build_terraform_template_wrapper(str(path), output) == output
        template = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
        assert template["resources"]
        assert all("inspectorValues" not in resource for resource in template["resources"])
        assert all("changeCategory" not in resource for resource in template["resources"])


class TestEnabledPath:
    """Inspector_Mode on: every resource carries the redacted triple."""

    def test_the_keyword_populates_inspector_values_on_every_resource(self) -> None:
        document = _builder().build_document_from_json(
            _multi_resource_plan(), collect_inspector_values=True
        )

        assert document.resources
        assert all(resource.inspector_values is not None for resource in document.resources)
        assert all(
            {"before", "after"} <= set(resource.inspector_values) for resource in document.resources
        )

    def test_the_written_template_carries_the_category_resolved_triple(self, tmp_path) -> None:
        """The keyword reaches the helper after the categories are assigned (1.5, 10.1)."""
        plan = _write_plan(tmp_path)
        output = str(tmp_path / "enabled.json")

        assert build_terraform_template_wrapper(plan, output, None, True) == output

        template = json.loads((tmp_path / "enabled.json").read_text(encoding="utf-8"))
        by_name = {resource["name"]: resource for resource in template["resources"]}

        # `create` resolves to an empty before snapshot, `update` to both redacted sides.
        assert by_name["vnet-core"]["inspectorValues"]["before"] == {}
        assert by_name["vnet-core"]["inspectorValues"]["after"] == {
            "name": "vnet-core",
            "address_space": ["10.0.0.0/16"],
        }
        assert by_name["sql-primary"]["inspectorValues"] == {
            "before": {"version": "12.0", "administrator_login_password": SENSITIVE},
            "after": {"version": "12.0", "administrator_login_password": SENSITIVE},
        }

    def test_the_enabled_template_differs_from_the_disabled_one_only_by_the_new_keys(
        self, tmp_path
    ) -> None:
        """Inspector_Mode adds `inspectorValues` and `address`, and nothing else.

        `address` joined `inspectorValues` with the coverage extension: the panel
        header shows the Terraform address (Requirement 5.5), so it has to reach the
        Renderer_Template. Like `inspectorValues` it is emitted only when the toggle
        is on, which is what keeps the disabled Renderer_Template byte-identical
        (Requirements 1.5, 10.1).
        """
        plan = _write_plan(tmp_path)
        disabled_output = str(tmp_path / "disabled.json")
        enabled_output = str(tmp_path / "enabled.json")

        build_terraform_template_wrapper(plan, disabled_output, None, False)
        build_terraform_template_wrapper(plan, enabled_output, None, True)

        disabled = json.loads((tmp_path / "disabled.json").read_text(encoding="utf-8"))
        enabled = json.loads((tmp_path / "enabled.json").read_text(encoding="utf-8"))

        for resource in enabled["resources"]:
            assert "inspectorValues" in resource
            assert resource.pop("address"), "the enabled path must publish the address"
            resource.pop("inspectorValues")
        assert enabled == disabled

        # The disabled template carries neither key, so the addition is opt-in.
        for resource in disabled["resources"]:
            assert "inspectorValues" not in resource
            assert "address" not in resource


class TestWrapperPositionalSignature:
    """The module-level wrapper keeps `change_types` third and takes the keyword fourth."""

    def test_change_types_still_works_positionally(self, tmp_path) -> None:
        plan = _write_plan(tmp_path)
        output = str(tmp_path / "filtered.json")

        assert build_terraform_template_wrapper(plan, output, ["update"]) == output

        template = json.loads((tmp_path / "filtered.json").read_text(encoding="utf-8"))
        assert [resource["name"] for resource in template["resources"]] == ["sql-primary"]
        assert all("inspectorValues" not in resource for resource in template["resources"])

    def test_the_keyword_works_positionally_alongside_change_types(self, tmp_path) -> None:
        plan = _write_plan(tmp_path)
        output = str(tmp_path / "filtered-enabled.json")

        assert build_terraform_template_wrapper(plan, output, ["update"], True) == output

        template = json.loads((tmp_path / "filtered-enabled.json").read_text(encoding="utf-8"))
        assert [resource["name"] for resource in template["resources"]] == ["sql-primary"]
        assert template["resources"][0]["inspectorValues"]["before"] == {
            "version": "12.0",
            "administrator_login_password": SENSITIVE,
        }

    def test_the_two_argument_call_still_writes_the_template(self, tmp_path) -> None:
        plan = _write_plan(tmp_path)
        output = str(tmp_path / "two-arg.json")

        assert build_terraform_template_wrapper(plan, output) == output
        assert json.loads((tmp_path / "two-arg.json").read_text(encoding="utf-8"))["resources"]

# ─── Property-based coverage ──────────────────────────────────────────────────
#
# Properties 8 and 19 both drive `_inspector_values_for`, so they share the
# reference redaction below: an independent walk of the documented mask semantics
# (`True` flags the whole subtree beneath it, an absent key flags nothing, a mask
# shallower than the tree leaves the rest untouched) that reports both the
# redacted tree and the Attribute_Paths carrying the Redaction_Literal.

from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from core.inspector import (  # noqa: E402
    REDACTION_LITERAL,
    ROOT_PATH,
    UNKNOWN_MARKER,
    InspectorIdentity,
    build_record,
    diff_attributes,
    flatten_values,
    render_scalar,
)
from strategies.inspector_trees import change_entries, sensitivity_masks  # noqa: E402


def _join(prefix: str, segment: str) -> str:
    """Join one Attribute_Path segment onto a prefix, as `flatten_values` does."""
    return segment if prefix == ROOT_PATH else f"{prefix}.{segment}"


def _reference_redaction(values: Any, mask: Any, prefix: str = ROOT_PATH):
    """Return `(redacted tree, flagged Attribute_Paths)` for one phase.

    Derived from the mask semantics of Requirements 11.1 to 11.4 rather than from
    the builder: a scalar truthy mask flags the whole subtree at its own
    Attribute_Path, a dictionary mask matches by key and flags nothing for an
    absent key, a list mask matches by index and flags nothing past its end, and
    a mask whose shape does not match the tree flags nothing.
    """
    if mask is None:
        return values, set()
    if not isinstance(mask, (dict, list)):
        if mask:
            return REDACTION_LITERAL, {prefix}
        return values, set()
    if isinstance(values, dict) and isinstance(mask, dict):
        redacted: Dict[Any, Any] = {}
        flagged: set = set()
        for key, child in values.items():
            if key in mask:
                child_value, child_flagged = _reference_redaction(
                    child, mask[key], _join(prefix, str(key))
                )
                redacted[key] = child_value
                flagged |= child_flagged
            else:
                redacted[key] = child
        return redacted, flagged
    if isinstance(values, list) and isinstance(mask, list):
        items: List[Any] = []
        flagged = set()
        for index, item in enumerate(values):
            item_value, item_flagged = _reference_redaction(
                item, mask[index] if index < len(mask) else None, _join(prefix, str(index))
            )
            items.append(item_value)
            flagged |= item_flagged
        return items, flagged
    return values, set()


def _flagged_paths(mask: Any) -> set:
    """The Attribute_Paths an `after_unknown` mask flags, ancestors included."""
    if mask is None:
        return set()
    return {path for path, flag in flatten_values(mask).items() if flag is True}


def _is_flagged(path: str, flagged: set) -> bool:
    """Whether `path` or one of its ancestor containers is flagged by the mask."""
    if not flagged:
        return False
    if ROOT_PATH in flagged:
        return True
    candidate = path
    while True:
        if candidate in flagged:
            return True
        cut = candidate.rfind(".")
        if cut == -1:
            return False
        candidate = candidate[:cut]


# ─── Property 8: Redaction fidelity ───────────────────────────────────────────
# Feature: interactive-resource-inspector, Property 8: Redaction fidelity — for
# any attribute tree and any parallel sensitivity mask, every Attribute_Path the
# mask flags carries the Redaction_Literal `(sensitive)` as the value of that
# phase, every Attribute_Path the mask leaves unflagged or absent carries the
# rendered value the unredacted tree produces, a path flagged in one phase only
# keeps the other phase's value as that phase's redaction produces it, and a path
# flagged in both phases is classified `unchanged` with the Redaction_Literal on
# both sides.


@st.composite
def _redaction_cases(draw):
    """One attribute tree with two masks aligned to it, one per phase.

    The after mask reaches the builder either as `change.after_sensitive` or as
    the planned resource's own `sensitive_values`, which is the two-step after
    phase resolution of Requirement 11.2.
    """
    tree, before_mask = draw(sensitivity_masks())
    after_mask = draw(sensitivity_masks(values=st.just(tree)).map(lambda pair: pair[1]))
    after_mask_source = draw(st.sampled_from(("change", "planned")))
    return tree, before_mask, after_mask, after_mask_source


@settings(max_examples=200, deadline=None)
@given(case=_redaction_cases())
def test_property_8_redaction_fidelity(case) -> None:
    """Property 8: Redaction fidelity.

    Both phases of the resolved triple equal the redaction of the same tree
    against that phase's mask, path for path: the flagged paths carry the
    Redaction_Literal, the unflagged ones carry the value the unredacted tree
    produces, a path flagged in one phase only keeps the other phase's own
    redaction, and a path flagged in both phases lands `unchanged` with the
    literal on both sides.

    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.7, 14.8**
    """
    tree, before_mask, after_mask, after_mask_source = case

    change: Dict[str, Any] = {
        "actions": ["update"],
        "before": tree,
        "before_sensitive": before_mask,
        "after": tree,
    }
    planned_sensitive = None
    if after_mask_source == "change":
        change["after_sensitive"] = after_mask
    else:
        planned_sensitive = after_mask
    plan = _plan(change, planned_values=tree, sensitive_values=planned_sensitive)

    values = _builder()._inspector_values_for(plan, _resource(dict(tree)), "update")

    before_reference, before_flagged = _reference_redaction(tree, before_mask)
    after_reference, after_flagged = _reference_redaction(tree, after_mask)

    # Each phase is redacted against its own mask, and only against its own mask.
    assert values["before"] == before_reference
    assert values["after"] == after_reference

    flat_plain = flatten_values(tree)
    flat_before = flatten_values(values["before"])
    flat_after = flatten_values(values["after"])

    for flagged, flat in ((before_flagged, flat_before), (after_flagged, flat_after)):
        # Every flagged Attribute_Path carries the Redaction_Literal.
        for path in flagged:
            assert flat[path] == REDACTION_LITERAL
        # Every other Attribute_Path carries the value the unredacted tree produces.
        for path, value in flat.items():
            if path in flagged:
                continue
            assert path in flat_plain
            assert render_scalar(value) == render_scalar(flat_plain[path])

    entries = {entry.path: entry for entry in diff_attributes(values["before"], values["after"])}

    # A path flagged in one phase only keeps the other phase's own redaction.
    for path in before_flagged - after_flagged:
        assert entries[path].before == REDACTION_LITERAL
        if path in flat_after:
            assert entries[path].after == render_scalar(flat_after[path])
    for path in after_flagged - before_flagged:
        assert entries[path].after == REDACTION_LITERAL
        if path in flat_before:
            assert entries[path].before == render_scalar(flat_before[path])

    # A path flagged in both phases is unchanged with the literal on both sides.
    for path in before_flagged & after_flagged:
        assert entries[path].state == "unchanged"
        assert entries[path].before == entries[path].after == REDACTION_LITERAL


# ─── Property 19: Before and after resolution ─────────────────────────────────
# Feature: interactive-resource-inspector, Property 19: Before and after
# resolution follows the category table — for any Change_Category and any change
# entry, the resolved Config_Snapshot pair equals the reference table (empty
# before and redacted `change.after` for `create`, redacted `change.before` and
# empty after for `delete`, both redacted sides for `update` and `replace`, the
# redacted attribute map on both sides for `unchanged` and for a resource with no
# change entry), a missing `change.after` for `create`, `update` or `replace`
# falls back to the redacted attribute map with the address logged, a missing
# `change.before` for `update`, `replace` or `delete` yields an empty before
# snapshot with the address logged, every Attribute_Path the entry reports as not
# yet known carries the Unknown_Marker as its After_Value, and the `replacement`
# marker is set exactly for `replace`.


def _entry_plan(entry: Dict[str, Any]) -> Dict[str, Any]:
    """A plan document carrying one generated change entry and its planned resource."""
    plan: Dict[str, Any] = {
        "format_version": "1.0",
        "planned_values": {
            "root_module": {
                "resources": [
                    {
                        "address": entry["address"],
                        "mode": "managed",
                        "type": entry["type"],
                        "name": entry["name"],
                        "provider_name": "registry.terraform.io/hashicorp/azurerm",
                        "values": entry["values"],
                    }
                ]
            }
        },
    }
    if entry["change"] is not None:
        plan["resource_changes"] = [
            {
                "address": entry["address"],
                "mode": "managed",
                "type": entry["type"],
                "name": entry["name"],
                "change": entry["change"],
            }
        ]
    return plan


def _entry_resource(entry: Dict[str, Any]) -> LocalTemplateResource:
    """The normalized resource of one generated change entry."""
    return LocalTemplateResource(
        address=entry["address"],
        provider_name="azurerm",
        source_type=entry["type"],
        renderer_type="Microsoft.Network/virtualNetworks",
        name=entry["name"],
        raw_values=dict(entry["values"]),
    )


def _phase_reference(entry: Dict[str, Any], phase: str):
    """The redacted phase object of a change entry, or `None` when the plan omits it."""
    change = entry["change"]
    if change is None:
        return None
    raw = change.get(phase)
    if not isinstance(raw, dict):
        return None
    return _reference_redaction(raw, change.get(f"{phase}_sensitive"))[0]


@settings(max_examples=200, deadline=None)
@given(entry=change_entries())
def test_property_19_before_and_after_resolution_follows_the_category_table(entry) -> None:
    """Property 19: Before and after resolution follows the category table.

    Every Change_Category and every combination of a present, null and absent
    change phase is resolved against the reference table, the two fallback
    branches log the address, the unknown mask travels through untouched and
    surfaces as the Unknown_Marker, and the `replacement` marker is set exactly
    for `replace`.

    **Validates: Requirements 4.4, 4.9, 6.1, 6.2, 6.3, 6.4, 6.6, 6.7, 6.8, 6.9, 10.4**
    """
    category = entry["category"]
    plan = _entry_plan(entry)
    resource = _entry_resource(entry)
    change = entry["change"]

    with captured_logs() as handler:
        values = _builder()._inspector_values_for(plan, resource, category)

    after_mask = None if change is None else change.get("after_sensitive")
    redacted_map = _reference_redaction(dict(entry["values"]), after_mask)[0]
    before_object = _phase_reference(entry, "before")
    after_object = _phase_reference(entry, "after")

    if category == "create":
        expected_before: Any = {}
        expected_after: Any = redacted_map if after_object is None else after_object
        missing = ["after"] if after_object is None else []
    elif category == "delete":
        expected_before = {} if before_object is None else before_object
        expected_after = {}
        missing = ["before"] if before_object is None else []
    elif category in ("update", "replace"):
        expected_before = {} if before_object is None else before_object
        expected_after = redacted_map if after_object is None else after_object
        missing = [
            phase
            for phase, resolved in (("before", before_object), ("after", after_object))
            if resolved is None
        ]
    else:
        expected_before = redacted_map
        expected_after = redacted_map
        missing = []

    assert values["before"] == expected_before
    assert values["after"] == expected_after

    # A phase the Change_Category requires but the entry omits is the anomaly: it warns,
    # naming the address and nothing else. A resource with no change entry at all is the
    # normal plan-less case: it is recorded at debug and never warns.
    if missing:
        assert any(entry["address"] in message for message in handler.warnings())
    else:
        assert handler.warnings() == []
    if change is None and category not in ("create", "delete", "update", "replace"):
        assert any(entry["address"] in message for message in handler.messages(logging.DEBUG))

    # The unknown mask travels untouched, and only when the plan carries one.
    unknown = None if change is None else change.get("after_unknown")
    if unknown is None:
        assert "afterUnknown" not in values
    else:
        assert values["afterUnknown"] is unknown

    # Every Attribute_Path the entry reports as not yet known carries the marker.
    flagged = _flagged_paths(values.get("afterUnknown"))
    for attribute in diff_attributes(values["before"], values["after"], unknown=unknown):
        if _is_flagged(attribute.path, flagged) and not (
            attribute.before == REDACTION_LITERAL and attribute.after == REDACTION_LITERAL
        ):
            assert attribute.after == UNKNOWN_MARKER

    # The replacement marker is set exactly for `replace`.
    identity = InspectorIdentity(
        key=f"{entry['name']}-rg",
        kind="node",
        name=entry["name"],
        address=entry["address"],
        change_category=category,
    )
    record = build_record(identity, values["before"], values["after"], unknown)
    assert record.replacement is (category == "replace")
