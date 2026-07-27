"""Unit tests for the Interactive Resource Inspector core foundations.

Covers Requirements 4.4, 7.13 and 12.10: the Attribute_Style table the
Inspector_Index carries, the Value_Bounds the run applies, and the data model
shapes of one Inspector_Record.
"""

import os
import subprocess
import sys

from core.inspector import (
    ATTRIBUTE_STATES,
    ATTRIBUTE_STYLES,
    MAX_ATTRIBUTE_ROWS,
    MAX_SCALAR_CHARS,
    MAX_TREE_DEPTH,
    TRUNCATION_MARKER,
    UNKNOWN_MARKER,
    AttributeEntry,
    AttributeStyle,
    InspectorIdentity,
    InspectorPayload,
    InspectorRecord,
)


class TestConstants:
    """The closed sets and the Value_Bounds the Inspector is built on."""

    def test_attribute_states_are_the_closed_set_in_canonical_order(self):
        assert ATTRIBUTE_STATES == ("added", "removed", "changed", "unchanged")

    def test_attribute_styles_cover_every_state_and_only_those_states(self):
        assert set(ATTRIBUTE_STYLES) == set(ATTRIBUTE_STATES)

    def test_attribute_styles_carry_the_plan_diff_colour_and_flag_tokens(self):
        assert ATTRIBUTE_STYLES["added"] == AttributeStyle(color="#107C10", flag="+", label="Added")
        assert ATTRIBUTE_STYLES["removed"] == AttributeStyle(color="#D13438", flag="-", label="Removed")
        assert ATTRIBUTE_STYLES["changed"] == AttributeStyle(color="#0078D4", flag="~", label="Changed")

    def test_unchanged_is_explicitly_styleless(self):
        assert ATTRIBUTE_STYLES["unchanged"] is None

    def test_style_payload_is_the_index_form(self):
        assert ATTRIBUTE_STYLES["changed"].to_payload() == {
            "color": "#0078D4",
            "flag": "~",
            "label": "Changed",
        }

    def test_value_bounds_match_the_specified_limits(self):
        assert MAX_ATTRIBUTE_ROWS == 500
        assert MAX_SCALAR_CHARS == 2048
        assert MAX_TREE_DEPTH == 12

    def test_markers_are_the_specified_literals(self):
        assert TRUNCATION_MARKER == "(truncated)"
        assert UNKNOWN_MARKER == "(known after apply)"

    def test_style_is_frozen(self):
        style = ATTRIBUTE_STYLES["added"]
        try:
            style.color = "#000000"
        except Exception:
            return
        raise AssertionError("AttributeStyle must be immutable")


class TestModulePurity:
    """The core stays a dictionary-in / dictionary-out transform chain."""

    def test_module_imports_no_graphviz_no_azure_and_no_pywebview(self):
        src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        probe = (
            "import sys; sys.path.insert(0, %r); import core.inspector; "
            "print('|'.join(sorted(sys.modules)))" % src_dir
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
        loaded = set(result.stdout.strip().split("|"))
        assert "graphviz" not in loaded
        assert "webview" not in loaded
        assert not any(name == "azure" or name.startswith("azure.") for name in loaded)


class TestAttributeEntry:
    """Attribute entries are immutable and keep an absent value absent."""

    def test_entry_is_frozen(self):
        entry = AttributeEntry(path="https_only", state="changed", before="false", after="true")
        try:
            entry.state = "added"
        except Exception:
            return
        raise AssertionError("AttributeEntry must be immutable")

    def test_added_entry_carries_the_after_value_only(self):
        entry = AttributeEntry(path="site_config.always_on", state="added", after="true")
        assert entry.before is None
        assert entry.to_payload() == {"path": "site_config.always_on", "state": "added", "after": "true"}

    def test_removed_entry_carries_the_before_value_only(self):
        entry = AttributeEntry(path="tags.owner", state="removed", before="platform")
        assert entry.after is None
        assert entry.to_payload() == {"path": "tags.owner", "state": "removed", "before": "platform"}

    def test_payload_round_trip_preserves_the_entry(self):
        entry = AttributeEntry(path="tags.owner", state="changed", before="platform", after="network")
        assert AttributeEntry.from_payload(entry.to_payload()) == entry

    def test_empty_string_value_survives_the_round_trip(self):
        entry = AttributeEntry(path="tags.owner", state="changed", before="", after="x")
        assert AttributeEntry.from_payload(entry.to_payload()) == entry


class TestInspectorIdentity:
    """The identity header of one Interaction_Layer element."""

    def test_identity_carries_the_record_header_fields(self):
        identity = InspectorIdentity(
            key="api-web-rg-app",
            kind="node",
            name="api-web",
            resource_type="Microsoft.Web/sites",
            resource_group="rg-app",
            address="module.app.azurerm_linux_web_app.api",
            change_category="update",
        )
        assert identity.key == "api-web-rg-app"
        assert identity.kind == "node"
        assert identity.resource_type == "Microsoft.Web/sites"
        assert identity.address == "module.app.azurerm_linux_web_app.api"
        assert identity.change_category == "update"

    def test_optional_identity_fields_default_to_absent(self):
        identity = InspectorIdentity(key="cluster_subnetapp", kind="subnet", name="app")
        assert identity.resource_type == ""
        assert identity.resource_group == ""
        assert identity.address is None
        assert identity.change_category is None


class TestInspectorRecord:
    """One Inspector_Record and its serialized form."""

    def test_record_defaults_leave_a_container_record_usable(self):
        record = InspectorRecord(key="cluster_vnetcore-vnet", kind="virtualNetwork", name="core-vnet")
        assert record.replacement is False
        assert record.attributes == []
        assert record.omitted_attributes == 0
        assert record.truncations == []

    def test_payload_uses_the_camel_case_keys_of_the_jsonl_line(self):
        record = InspectorRecord(
            key="api-web-rg-app",
            kind="node",
            name="api-web",
            resource_type="Microsoft.Web/sites",
            resource_group="rg-app",
            address="module.app.azurerm_linux_web_app.api",
            change_category="replace",
            replacement=True,
            attributes=[AttributeEntry(path="https_only", state="changed", before="false", after="true")],
            omitted_attributes=3,
            truncations=["rows"],
        )
        payload = record.to_payload()
        assert set(payload) == {
            "key",
            "kind",
            "name",
            "resourceType",
            "resourceGroup",
            "address",
            "changeCategory",
            "replacement",
            "attributes",
            "omittedAttributes",
            "truncations",
        }
        assert payload["resourceType"] == "Microsoft.Web/sites"
        assert payload["changeCategory"] == "replace"
        assert payload["replacement"] is True
        assert payload["omittedAttributes"] == 3
        assert payload["attributes"] == [
            {"path": "https_only", "state": "changed", "before": "false", "after": "true"}
        ]

    def test_payload_round_trip_preserves_the_record(self):
        record = InspectorRecord(
            key="cluster_subnetapp",
            kind="subnet",
            name="app",
            resource_type="Microsoft.Network/virtualNetworks/subnets",
            resource_group="rg-network",
            attributes=[AttributeEntry(path="address_prefixes.0", state="added", after="10.0.1.0/24")],
            truncations=["depth", "value"],
        )
        assert InspectorRecord.from_payload(record.to_payload()) == record

    def test_round_trip_keeps_an_absent_address_and_category_absent(self):
        record = InspectorRecord(key="db-rg-data", kind="node", name="db")
        rebuilt = InspectorRecord.from_payload(record.to_payload())
        assert rebuilt.address is None
        assert rebuilt.change_category is None


class TestInspectorPayload:
    """The payload carries the records of one run plus its collision count."""

    def test_empty_payload_reports_no_records_and_no_collisions(self):
        payload = InspectorPayload()
        assert payload.records == []
        assert payload.key_collisions == 0
        assert payload.record_count == 0

    def test_record_count_follows_the_record_list(self):
        payload = InspectorPayload(
            records=[
                InspectorRecord(key="a-rg", kind="node", name="a"),
                InspectorRecord(key="b-rg", kind="node", name="b"),
            ],
            key_collisions=1,
        )
        assert payload.record_count == 2
        assert payload.key_collisions == 1
