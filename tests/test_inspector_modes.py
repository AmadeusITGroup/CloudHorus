"""The Inspector across every input mode, not only the Plan_Diff one.

The Inspector was built against a Terraform Plan_File, where a change entry gives
each attribute a before phase and an after phase and the panel can colour a row
`added`, `removed` or `changed`. Three of the four input modes have no plan at all:

* **Live** — the resource list comes from Azure, so there is no proposed change;
* **Bicep** — the ARM template the Bicep compiler emits, likewise;
* **Terraform source (HCL)** — configuration without a plan.

None of those can show a diff, and none of them should therefore lose the panel:
reading a resource's full configuration is worth doing on its own. The contract
this module pins is that every mode produces a populated Inspector_Record whose
rows all read `unchanged`, so the Operator sees the configuration with no colour
cues rather than an empty panel or no panel.

Where the values come from is one shared code path: `build_inspector_source_index`
indexes the resource entries of the resource group's template, whatever produced
that template, and `inspector_source_phases` uses a resource's `inspectorValues`
triple when the Terraform builder attached one and otherwise uses the entry's own
configuration on **both** sides. The absence of a plan is expressed as
`before == after`, which the Attribute_Differ already classifies as `unchanged`
for every path — so no mode needs a branch of its own, and this module is what
keeps that true.

Requirements covered: 2.1, 2.8, 4.4, 5.2, 5.5, 7.5, 10.1, 10.2, 10.3, 10.6, 10.7.
"""

import os
import sys
from typing import Any, Dict
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.graph_generator import (  # noqa: E402
    build_inspector_source_index,
    inspector_source_phases,
)
from core.inspector import (  # noqa: E402
    AFTER_KEY,
    BEFORE_KEY,
    INSPECTOR_VALUES_KEY,
    NODE_KIND,
    InspectorCollector,
)

RG = "rg-live"

#: The shape every no-plan mode hands the Inspector: an ARM resource entry. This is
#: what the Bicep compiler emits and what the live Azure export writes, and it
#: carries no `inspectorValues` triple, no `changeCategory` and no `address`.
ARM_ENTRY: Dict[str, Any] = {
    "type": "Microsoft.Storage/storageAccounts",
    "apiVersion": "2023-01-01",
    "name": "livestorage",
    "location": "westeurope",
    "sku": {"name": "Standard_LRS", "tier": "Standard"},
    "properties": {
        "accessTier": "Hot",
        "supportsHttpsTrafficOnly": True,
        "minimumTlsVersion": "TLS1_2",
        "networkAcls": {"defaultAction": "Deny", "ipRules": [{"value": "10.0.0.1"}]},
        "tags": {},
    },
}


def record_for(entry: Dict[str, Any], key: str = "livestorage-rg-live"):
    """Collect one node from `entry` and return the built Inspector_Record."""
    collector = InspectorCollector()
    collector.record_node(key, entry, RG)
    payload = collector.build_payload()
    assert payload.records, "the entry produced no Inspector_Record"
    return payload.records[0]


def paths_of(record) -> Dict[str, Any]:
    """The record's Attribute_Entry rows keyed by Attribute_Path."""
    return {entry.path: entry for entry in record.attributes}


class TestNoPlanModesStillDescribeTheResource:
    """Live, Bicep and HCL: full configuration, every row `unchanged`."""

    def test_an_arm_entry_produces_a_populated_record(self):
        """Requirement 3.2: the panel is never empty just because there is no plan."""
        record = record_for(ARM_ENTRY)

        assert record.kind == NODE_KIND
        assert record.resource_group == RG
        assert record.attributes, "an ARM entry must still fill the panel"

    def test_every_row_reads_unchanged(self):
        """Requirement 7.5: before == after for every path, so nothing is coloured.

        This is the whole no-plan contract. A row that came out `added` would tell
        the Operator something changed when the mode cannot know that.
        """
        record = record_for(ARM_ENTRY)

        assert {entry.state for entry in record.attributes} == {"unchanged"}
        for entry in record.attributes:
            assert entry.before == entry.after

    def test_the_full_configuration_is_shown_not_only_the_mapped_properties(self):
        """Requirement 5.2: nested configuration reaches the panel as dotted paths."""
        paths = paths_of(record_for(ARM_ENTRY))

        assert paths["properties.accessTier"].after == "Hot"
        assert paths["properties.minimumTlsVersion"].after == "TLS1_2"
        # Nested maps and lists keep their structure as path segments.
        assert paths["properties.networkAcls.defaultAction"].after == "Deny"
        assert paths["properties.networkAcls.ipRules.0.value"].after == "10.0.0.1"
        # A boolean renders as its JSON form, not as Python's `True`.
        assert paths["properties.supportsHttpsTrafficOnly"].after == "true"
        # An empty map renders as `{}` rather than vanishing (Requirement 5.8).
        assert paths["properties.tags"].after == "{}"
        assert paths["sku.name"].after == "Standard_LRS"

    def test_no_change_category_is_claimed(self):
        """Requirements 10.3, 10.6: no plan means no Change_Category badge.

        The panel hides the badge and the Attribute_State legend for a record with
        no category, so the absence has to be a real `None` and not an invented
        `"unchanged"` category.
        """
        record = record_for(ARM_ENTRY)

        assert record.change_category is None
        assert record.replacement is False

    def test_the_identity_header_survives_without_a_terraform_address(self):
        """Requirement 5.5: name and type still identify the resource."""
        record = record_for(ARM_ENTRY)

        assert record.name == "livestorage"
        assert record.resource_type == "Microsoft.Storage/storageAccounts"
        # `address` is Terraform-only; the header simply omits it here.
        assert not record.address

    def test_a_resource_with_no_properties_map_is_still_described(self):
        """A minimal live entry keeps its identity fields as rows."""
        entry = {"type": "Microsoft.Network/bastionHosts", "name": "bastion-1", "location": "westeurope"}

        paths = paths_of(record_for(entry, "bastion-1"))

        assert paths["location"].after == "westeurope"
        assert all(entry.state == "unchanged" for entry in paths.values())


class TestSourcePhaseResolutionIsModeIndependent:
    """One code path serves all four modes; the plan only adds the triple."""

    def test_an_entry_without_the_triple_resolves_to_itself_on_both_sides(self):
        """Requirement 10.2: no plan is expressed as an identity diff."""
        before, after, unknown = inspector_source_phases(ARM_ENTRY)

        assert before == after
        assert not unknown

    def test_an_entry_with_the_triple_resolves_to_the_plan_phases(self):
        """The Plan_Diff mode keeps its real before and after."""
        entry = dict(ARM_ENTRY)
        entry[INSPECTOR_VALUES_KEY] = {
            BEFORE_KEY: {"access_tier": "Cool"},
            AFTER_KEY: {"access_tier": "Hot"},
        }

        before, after, _unknown = inspector_source_phases(entry)

        assert before == {"access_tier": "Cool"}
        assert after == {"access_tier": "Hot"}

    def test_the_source_index_is_built_the_same_way_for_an_arm_entry(self):
        """Requirement 10.1: the index keys on (name, renderer type) in every mode."""
        index = build_inspector_source_index([ARM_ENTRY])

        assert index[("livestorage", "Microsoft.Storage/storageAccounts")] is ARM_ENTRY


class TestTheToggleIsNotGatedByInputMode:
    """Requirements 2.1, 2.8: Inspector_Mode is available whatever the input is."""

    def test_the_configuration_field_is_mode_independent(self):
        from cloudhorus.models.configuration import VisualizationConfig

        assert VisualizationConfig().interactive_inspector is False
        assert VisualizationConfig(interactive_inspector=True).interactive_inspector is True

    @pytest.mark.parametrize(
        "mode_args",
        [
            ["--bicepFiles", "main.bicep"],
            ["--terraformRootDirs", "infra/"],
            ["--terraformJsonFiles", "plan.json"],
            [],
        ],
        ids=["bicep", "terraform-source", "terraform-json", "live"],
    )
    def test_the_flag_parses_alongside_every_input_mode(self, mode_args):
        """The CLI accepts `--interactiveInspector` with any input selection.

        The validation block rejects a bad value before any generation work starts,
        so a mode that refused the flag would exit here instead of parsing it.
        """
        import main

        argv = ["cloudhorus", *mode_args, "--interactiveInspector", "True"]
        with patch.object(sys, "argv", argv):
            namespace = main.parse_arguments()

        assert namespace.interactiveInspector == "True"
