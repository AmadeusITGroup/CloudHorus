"""Unit tests for the plan-diff entry points.

Section 1 covers the `build_terraform_template` orchestration (task 5.4): the legacy
path when `resource_changes` is absent, Change_Model extraction plus filtering when it
is present, the empty-array report, and the exception guard returning `None`
(Requirements 1.1, 1.2, 6.9, 9.1, 9.3, 9.5).

Section 2 covers malformed plan input (task 5.10): truncated JSON reporting the file path
and the parse position, a document carrying neither `planned_values` nor `values`, and an
empty `resource_changes` array emitting `Plan contains no resource changes`
(Requirements 9.2, 9.3, 9.5). `build_terraform_template` returning `None` is the signal
`main.py` turns into the non-zero exit; the exit code itself is asserted in Section 3.

Section 3 covers the CLI argument surface of `src/main.py` (task 9.3): the
plan/source mutual-exclusion message and its non-zero exit, a missing plan path, an
invalid `--changeTypes` value listing the accepted values, the `--changeTypes` default
and its forwarding into the service layer, the argparse inventory snapshot that guards
every pre-existing argument, and the PNG output path pattern
(Requirements 1.5, 1.6, 6.10, 8.2, 8.3, 8.5).
"""

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

import main  # noqa: E402  (src/main.py, on sys.path through tests/conftest.py)
from core.plan_diff import CHANGE_CATEGORIES
from core.terraform_builder import TerraformTemplateBuilder
from core.terraform_builder import build_terraform_template as build_terraform_template_wrapper

PROVIDER = "registry.terraform.io/hashicorp/azurerm"


# ---------------------------------------------------------------------------
# Shared plan fixtures
# ---------------------------------------------------------------------------


def _planned_resource(address: str, terraform_type: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Build one `planned_values.root_module.resources` entry."""
    return {
        "address": address,
        "mode": "managed",
        "type": terraform_type,
        "name": address.rsplit(".", 1)[-1],
        "provider_name": PROVIDER,
        "values": values,
    }


def _change_entry(
    address: str,
    terraform_type: str,
    actions: List[str],
    before: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one `resource_changes` entry."""
    return {
        "address": address,
        "mode": "managed",
        "type": terraform_type,
        "name": address.rsplit(".", 1)[-1],
        "provider_name": PROVIDER,
        "change": {"actions": actions, "before": before, "after": None},
    }


def _plan(resource_changes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Build a plan with two planned resources and an optional `resource_changes` array."""
    document: Dict[str, Any] = {
        "format_version": "1.2",
        "terraform_version": "1.7.5",
        "planned_values": {
            "root_module": {
                "resources": [
                    _planned_resource(
                        "azurerm_storage_account.new",
                        "azurerm_storage_account",
                        {"name": "stnew", "location": "westeurope", "resource_group_name": "rg-app"},
                    ),
                    _planned_resource(
                        "azurerm_route_table.kept",
                        "azurerm_route_table",
                        {"name": "rt-kept", "location": "westeurope", "resource_group_name": "rg-app"},
                    ),
                ]
            }
        },
    }
    if resource_changes is not None:
        document["resource_changes"] = resource_changes
    return document


def _diff_plan() -> Dict[str, Any]:
    """A plan whose changes cover create, unchanged and a reconstructed delete."""
    return _plan(
        [
            _change_entry("azurerm_storage_account.new", "azurerm_storage_account", ["create"]),
            _change_entry("azurerm_route_table.kept", "azurerm_route_table", ["no-op"]),
            _change_entry(
                "azurerm_network_security_group.gone",
                "azurerm_network_security_group",
                ["delete"],
                before={"name": "nsg-gone", "location": "westeurope", "resource_group_name": "rg-app"},
            ),
        ]
    )


def _write_plan(tmp_path, document: Dict[str, Any], name: str = "plan.json") -> str:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def _read_template(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _categories(template: Dict[str, Any]) -> Dict[str, str]:
    return {resource["name"]: resource.get("changeCategory") for resource in template["resources"]}


@pytest.fixture
def builder() -> TerraformTemplateBuilder:
    return TerraformTemplateBuilder()


# ---------------------------------------------------------------------------
# Section 1 - build_terraform_template orchestration (task 5.4)
# ---------------------------------------------------------------------------


class TestLegacyPathWithoutResourceChanges:
    """A plan without `resource_changes` keeps the exact legacy behaviour."""

    def test_output_matches_the_legacy_document(self, builder, tmp_path):
        document = _plan()
        plan_file = _write_plan(tmp_path, document)

        output_file = builder.build_terraform_template(plan_file, str(tmp_path / "out.json"))

        expected = builder.build_document_from_json(document).to_renderer_template()
        assert _read_template(output_file) == expected

    def test_no_change_keys_are_emitted(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _plan())

        template = _read_template(builder.build_terraform_template(plan_file))

        assert all("changeCategory" not in resource for resource in template["resources"])
        assert "changeCounts" not in template["metadata"]
        assert "changeModel" not in template["metadata"]

    def test_change_types_are_ignored_without_resource_changes(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _plan())

        with_filter = _read_template(builder.build_terraform_template(plan_file, change_types=["delete"]))
        without_filter = _read_template(builder.build_terraform_template(plan_file))

        assert with_filter == without_filter


class TestPlanDiffMode:
    """A plan with `resource_changes` gains categories, metadata and delete nodes."""

    def test_every_resource_carries_its_category(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        template = _read_template(builder.build_terraform_template(plan_file))

        assert _categories(template) == {
            "stnew": "create",
            "rt-kept": "unchanged",
            "nsg-gone": "delete",
        }

    def test_change_metadata_is_written(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        metadata = _read_template(builder.build_terraform_template(plan_file))["metadata"]

        assert metadata["changeCounts"] == {
            "create": 1,
            "update": 0,
            "replace": 0,
            "delete": 1,
            "unchanged": 1,
        }
        assert set(metadata["changeCounts"]) == set(CHANGE_CATEGORIES)
        assert {record["address"] for record in metadata["changeModel"]["records"]} == {
            "azurerm_storage_account.new",
            "azurerm_route_table.kept",
            "azurerm_network_security_group.gone",
        }
        assert metadata["changesNotDisplayed"] == []

    def test_change_types_restrict_the_written_resources(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        template = _read_template(builder.build_terraform_template(plan_file, change_types=["delete"]))

        assert _categories(template) == {"nsg-gone": "delete"}

    def test_full_selection_is_an_identity_filter(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        selected = _read_template(builder.build_terraform_template(plan_file, change_types=list(CHANGE_CATEGORIES)))
        unfiltered = _read_template(builder.build_terraform_template(plan_file))

        assert selected == unfiltered

    def test_empty_selection_result_keeps_the_template_contract(self, builder, tmp_path):
        # An unmatched selection still writes a valid, empty-resource template.
        plan_file = _write_plan(tmp_path, _diff_plan())

        template = _read_template(builder.build_terraform_template(plan_file, change_types=["update"]))

        assert template["resources"] == []
        assert template["metadata"]["changeCounts"]["update"] == 0


class TestEmptyResourceChanges:
    """An empty `resource_changes` array is Plan_Diff_Mode with nothing to show."""

    def test_message_is_reported(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _plan([]))

        with patch.object(builder, "logger") as mock_logger:
            builder.build_terraform_template(plan_file)

        messages = [str(call.args[0]) for call in mock_logger.info.call_args_list]
        assert "Plan contains no resource changes" in messages

    def test_every_resource_is_unchanged(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _plan([]))

        template = _read_template(builder.build_terraform_template(plan_file))

        assert set(_categories(template).values()) == {"unchanged"}
        assert template["metadata"]["changeCounts"] == {category: 0 for category in CHANGE_CATEGORIES}

    def test_non_empty_changes_do_not_report_the_message(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        with patch.object(builder, "logger") as mock_logger:
            builder.build_terraform_template(plan_file)

        messages = [str(call.args[0]) for call in mock_logger.info.call_args_list]
        assert "Plan contains no resource changes" not in messages


class TestOutputFileContract:
    """The temp-file contract is the same in both modes."""

    @pytest.mark.parametrize("resource_changes", [None, []])
    def test_a_temp_file_is_created_when_no_output_is_given(self, builder, tmp_path, resource_changes):
        plan_file = _write_plan(tmp_path, _plan(resource_changes))

        output_file = builder.build_terraform_template(plan_file)

        assert output_file is not None
        assert output_file.endswith(".json")
        assert os.path.exists(output_file)
        os.unlink(output_file)

    def test_the_given_output_path_is_used(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())
        target = str(tmp_path / "explicit.json")

        assert builder.build_terraform_template(plan_file, target, ["create"]) == target
        assert _categories(_read_template(target)) == {"stnew": "create"}


class TestExceptionGuard:
    """Every documented input failure is logged and returns None."""

    def test_missing_file_returns_none(self, builder, tmp_path):
        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(str(tmp_path / "absent.json")) is None

        assert mock_logger.error.called

    def test_invalid_change_type_returns_none(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(plan_file, None, ["destroy"]) is None

        assert mock_logger.error.called

    def test_document_without_value_sections_returns_none(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, {"format_version": "1.2", "resource_changes": []})

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(plan_file) is None

        assert mock_logger.error.called

    @pytest.mark.parametrize("document", [None, [], 3, "plan"])
    def test_non_object_document_returns_none(self, builder, tmp_path, document):
        # A valid JSON document that is not an object is reported, never crashed
        # (Requirement 12.8): the loader raises ValueError, which the guard catches.
        plan_file = _write_plan(tmp_path, document)

        with pytest.raises(ValueError, match="must be a JSON object"):
            builder.load_terraform_json(plan_file)

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(plan_file) is None

        assert mock_logger.error.called


class TestModuleLevelWrapper:
    """The convenience wrapper keeps its positional signature."""

    def test_single_positional_argument_still_works(self, tmp_path):
        plan_file = _write_plan(tmp_path, _plan())

        output_file = build_terraform_template_wrapper(plan_file)

        assert output_file is not None
        assert _read_template(output_file)["resources"]
        os.unlink(output_file)

    def test_change_types_is_the_third_positional_argument(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())
        target = str(tmp_path / "wrapped.json")

        assert build_terraform_template_wrapper(plan_file, target, ["delete"]) == target
        assert _categories(_read_template(target)) == {"nsg-gone": "delete"}

# ---------------------------------------------------------------------------
# Section 2 - malformed plan input (task 5.10)
# ---------------------------------------------------------------------------


def _logged_errors(mock_logger) -> List[str]:
    return [str(call.args[0]) for call in mock_logger.error.call_args_list]


class TestTruncatedJson:
    """Text that is not valid JSON is reported with its path and parse position (9.2)."""

    @staticmethod
    def _truncate(tmp_path, document: Dict[str, Any]) -> str:
        payload = json.dumps(document)
        path = tmp_path / "truncated.json"
        path.write_text(payload[: len(payload) // 2], encoding="utf-8")
        return str(path)

    def test_loader_raises_a_decode_error_carrying_the_position(self, builder, tmp_path):
        plan_file = self._truncate(tmp_path, _diff_plan())

        with pytest.raises(json.JSONDecodeError) as failure:
            builder.load_terraform_json(plan_file)

        assert failure.value.lineno >= 1
        assert failure.value.colno >= 1
        assert failure.value.pos >= 0

    def test_report_names_the_file_path_and_the_parse_position(self, builder, tmp_path):
        plan_file = self._truncate(tmp_path, _diff_plan())

        with pytest.raises(json.JSONDecodeError) as failure:
            builder.load_terraform_json(plan_file)
        position = failure.value

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(plan_file) is None

        errors = _logged_errors(mock_logger)
        assert len(errors) == 1
        report = errors[0]
        assert plan_file in report
        assert f"line {position.lineno}" in report
        assert f"column {position.colno}" in report
        assert f"char {position.pos}" in report

    @pytest.mark.parametrize("payload", ["", "not json", "{", '{"planned_values": {', "{,}"])
    def test_no_output_file_is_written_for_unparsable_text(self, builder, tmp_path, payload):
        plan_file = tmp_path / "broken.json"
        plan_file.write_text(payload, encoding="utf-8")
        target = str(tmp_path / "never-written.json")

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(str(plan_file), target) is None

        assert str(plan_file) in _logged_errors(mock_logger)[0]
        assert not os.path.exists(target)


class TestMissingValueSections:
    """A document with neither `planned_values` nor `values` names both keys (9.3)."""

    @pytest.mark.parametrize(
        "document",
        [
            {"format_version": "1.2"},
            {"format_version": "1.2", "resource_changes": []},
            {"format_version": "1.2", "planned_values": None, "values": None},
            {"format_version": "1.2", "planned_values": [], "values": "root"},
        ],
    )
    def test_loader_raises_a_value_error_naming_the_missing_keys(self, builder, tmp_path, document):
        plan_file = _write_plan(tmp_path, document)

        with pytest.raises(ValueError) as failure:
            builder.load_terraform_json(plan_file)

        message = str(failure.value)
        assert "planned_values" in message
        assert "values" in message

    def test_report_names_the_file_path_and_the_missing_keys(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, {"format_version": "1.2", "resource_changes": []})

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(plan_file) is None

        report = _logged_errors(mock_logger)[0]
        assert plan_file in report
        assert "planned_values" in report
        assert "values" in report

    def test_a_document_with_only_values_is_accepted(self, builder, tmp_path):
        # `values` alone is a state document, not a malformed plan.
        document = {
            "format_version": "1.2",
            "values": {
                "root_module": {
                    "resources": [
                        _planned_resource(
                            "azurerm_storage_account.state",
                            "azurerm_storage_account",
                            {"name": "ststate", "location": "westeurope", "resource_group_name": "rg-app"},
                        )
                    ]
                }
            },
        }
        plan_file = _write_plan(tmp_path, document)

        assert builder.load_terraform_json(plan_file) == document
        assert builder.build_terraform_template(plan_file, str(tmp_path / "state.json")) is not None


class TestEmptyResourceChangesReport:
    """An empty `resource_changes` array reports the message and still renders (9.5)."""

    def test_the_message_is_reported_exactly_once_and_the_run_succeeds(self, builder, tmp_path):
        plan_file = _write_plan(tmp_path, _plan([]))
        target = str(tmp_path / "empty-changes.json")

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(plan_file, target) == target

        messages = [str(call.args[0]) for call in mock_logger.info.call_args_list]
        assert messages.count("Plan contains no resource changes") == 1
        assert not mock_logger.error.called
        assert {resource["changeCategory"] for resource in _read_template(target)["resources"]} == {"unchanged"}

    def test_a_non_list_resource_changes_value_does_not_report_the_message(self, builder, tmp_path):
        # A type mismatch is a warning inside the extractor, not the empty-plan report (9.8).
        document = _plan()
        document["resource_changes"] = {}
        plan_file = _write_plan(tmp_path, document)

        with patch.object(builder, "logger") as mock_logger:
            assert builder.build_terraform_template(plan_file, str(tmp_path / "mismatch.json")) is not None

        messages = [str(call.args[0]) for call in mock_logger.info.call_args_list]
        assert "Plan contains no resource changes" not in messages


# ---------------------------------------------------------------------------
# Section 3 - CLI argument surface (task 9.3)
# ---------------------------------------------------------------------------

FAKE_PNG = os.path.join("azure_resources_20250101_120000", "azure_resources_20250101_120000.png")

ACCEPTED_VALUES_MESSAGE = f"Accepted values: {' '.join(CHANGE_CATEGORIES)}"

# The argparse inventory as it stood before this feature: option string -> (nargs, default).
# Requirement 8.2 forbids any change to a name, an arity, or a default, so this table is a
# snapshot: touching a legacy argument fails here, and adding one has to be declared here.
LEGACY_ARGUMENTS: Dict[str, Tuple[Any, Any]] = {
    "--subscriptions": ("+", None),
    "--resourcegroups": ("+", None),
    "--tenants": ("+", None),
    "--subnetOptimization": ("+", None),
    "--edgeDirection": (None, "TB"),
    "--tenantDirection": (None, "LR"),
    "--maxSubnetPerline": (None, 4),
    "--rankDebug": (None, "False"),
    "--peOptimization": ("+", None),
    "--resourcesEdgeLength": ("+", "1"),
    "--resourceGroupsEdgeLengthListBySubscription": ("+", None),
    "--privateDnsZonesOptimization": (None, "True"),
    "--crossPeOptimization": ("+", None),
    "--bicepFiles": ("+", None),
    "--parametersFiles": ("+", None),
    "--terraformJsonFiles": ("+", None),
    "--terraformRootDirs": ("+", None),
    "--terraformVarFiles": ("+", None),
    "--scopeMetadataFiles": ("+", None),
    "--discoverResourceGroups": ("*", None),
    "--exportDrawio": (None, "False"),
    "--authMethod": (None, "device-code"),
    "--nonInteractive": (None, "False"),
}

LEGACY_CHOICES: Dict[str, Optional[List[str]]] = {
    "--edgeDirection": ["TB", "BT", "LR", "RL"],
    "--tenantDirection": ["TB", "LR"],
    "--authMethod": ["device-code", "service-principal", "environment"],
}


@pytest.fixture(autouse=True)
def preserved_environment():
    """Keep the CLI's environment side effects out of the rest of the suite."""
    watched = ("CLOUDHORUS_NON_INTERACTIVE", "CLOUDHORUS_AUTH_METHOD")
    snapshot = {name: os.environ.get(name) for name in watched}
    yield
    for name, value in snapshot.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _build_parser() -> argparse.ArgumentParser:
    """Return the parser that `parse_arguments` builds, without parsing anything."""
    captured: Dict[str, argparse.ArgumentParser] = {}

    def capture(self, *args, **kwargs):
        captured["parser"] = self
        return argparse.Namespace()

    with patch.object(argparse.ArgumentParser, "parse_args", capture):
        main.parse_arguments()

    return captured["parser"]


def _argument_inventory() -> Dict[str, Tuple[Any, Any]]:
    """Map every option string to its `(nargs, default)` pair."""
    return {
        action.option_strings[0]: (action.nargs, action.default)
        for action in _build_parser()._actions
        if action.option_strings and action.dest != "help"
    }


def _parse(argv: List[str]) -> argparse.Namespace:
    with patch.object(sys, "argv", ["cloudhorus", *argv]):
        return main.parse_arguments()


class CliRun:
    """The observable outcome of one `main.main()` invocation."""

    def __init__(self, exit_code: int, logger, service):
        self.exit_code = exit_code
        self.errors = [str(call.args[0]) for call in logger.error.call_args_list]
        self.warnings = [str(call.args[0]) for call in logger.warning.call_args_list]
        self.infos = [str(call.args[0]) for call in logger.info.call_args_list]
        self.generate_graph = service.generate_graph.call_args
        self.generated = service.generate_graph.called

    def logged(self, needle: str) -> bool:
        return any(needle in message for message in self.errors + self.warnings + self.infos)


def _run_cli(argv: List[str], png_path: str = FAKE_PNG) -> CliRun:
    """Run the CLI end to end with the generator service replaced by a double.

    Everything up to `GraphGeneratorService` is the real `main.main()` code path:
    argument parsing, mode detection, mutual exclusion, path checks, `--changeTypes`
    validation and the configuration hand-off. `--nonInteractive true` only skips the
    banner and its sleep.
    """
    with (
        patch.object(sys, "argv", ["cloudhorus", *argv, "--nonInteractive", "true"]),
        patch.object(main, "logger") as logger,
        patch.object(main, "GraphGeneratorService") as service_class,
    ):
        service = service_class.return_value
        service.validate.return_value = True
        service.generate_graph.return_value = png_path

        exit_code = 0
        try:
            main.main()
        except SystemExit as signal:
            exit_code = signal.code

        return CliRun(exit_code, logger, service)


class TestArgparseInventory:
    """Every pre-existing argument keeps its name, arity and default (8.2)."""

    def test_the_snapshot_matches_the_parser(self):
        inventory = _argument_inventory()

        assert {name: inventory[name] for name in LEGACY_ARGUMENTS} == LEGACY_ARGUMENTS

    def test_only_declared_arguments_were_added(self):
        # `--interactiveInspector` is the interactive-resource-inspector feature's one
        # addition (its own spec, Requirement 2.2); every other addition must be declared here.
        inventory = _argument_inventory()

        assert set(inventory) - set(LEGACY_ARGUMENTS) == {"--changeTypes", "--interactiveInspector"}

    def test_no_pre_existing_argument_was_removed(self):
        assert set(LEGACY_ARGUMENTS) <= set(_argument_inventory())

    def test_constrained_arguments_keep_their_accepted_values(self):
        choices = {
            action.option_strings[0]: action.choices
            for action in _build_parser()._actions
            if action.option_strings and action.dest != "help"
        }

        assert {name: choices[name] for name in LEGACY_CHOICES} == LEGACY_CHOICES
        assert choices["--changeTypes"] is None

    def test_maxsubnetperline_keeps_its_integer_type(self):
        # The one legacy argument whose value is coerced; a silent change to `str`
        # would slip past a name/nargs/default comparison.
        assert _parse([]).maxSubnetPerline == 4


class TestChangeTypesArgument:
    """`--changeTypes` is optional, validated, and forwarded (6.10, 8.3)."""

    def test_the_default_is_none(self):
        assert _parse([]).changeTypes is None

    def test_the_raw_values_are_collected(self):
        assert _parse(["--changeTypes", "delete", "create"]).changeTypes == ["delete", "create"]

    def test_an_omitted_selection_forwards_none_to_the_service(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan_file])

        assert run.exit_code == 0
        assert run.generate_graph.kwargs["change_types"] is None

    def test_a_selection_reaches_the_service_in_canonical_order(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan_file, "--changeTypes", "delete", "create"])

        assert run.exit_code == 0
        assert run.generate_graph.kwargs["change_types"] == ["create", "delete"]
        assert run.logged("Change type filter accepted: create delete")

    def test_the_full_selection_is_accepted(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan_file, "--changeTypes", *CHANGE_CATEGORIES])

        assert run.exit_code == 0
        assert run.generate_graph.kwargs["change_types"] == list(CHANGE_CATEGORIES)

    @pytest.mark.parametrize("value", ["destroy", "Delete", "no-op", "", "all"])
    def test_an_invalid_value_reports_the_accepted_values_and_exits(self, tmp_path, value):
        plan_file = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan_file, "--changeTypes", value])

        assert run.exit_code == 1
        assert run.errors == [f"Invalid --changeTypes value '{value}'. {ACCEPTED_VALUES_MESSAGE}"]
        assert not run.generated

    def test_one_invalid_value_among_valid_ones_still_exits(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan_file, "--changeTypes", "delete", "destroy"])

        assert run.exit_code == 1
        assert ACCEPTED_VALUES_MESSAGE in run.errors[0]
        assert not run.generated

    def test_a_selection_outside_plan_json_mode_warns_and_is_ignored(self, tmp_path):
        source_dir = tmp_path / "tf-root"
        source_dir.mkdir()
        (source_dir / "main.tf").write_text("# empty root\n", encoding="utf-8")

        run = _run_cli(["--terraformRootDirs", str(source_dir), "--changeTypes", "delete"])

        assert run.exit_code == 0
        assert run.generate_graph.kwargs["change_types"] is None
        assert any("--changeTypes applies to Terraform plan JSON input only" in w for w in run.warnings)

    def test_no_warning_is_emitted_in_plan_json_mode(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan_file, "--changeTypes", "delete"])

        assert not any("--changeTypes" in warning for warning in run.warnings)


class TestTerraformInputMutualExclusion:
    """Plan JSON and Terraform source cannot be selected together (1.5)."""

    MESSAGE = "Choose exactly one Terraform input: plan JSON or source directories"
    GENERIC = "choose exactly one local input mode"

    def test_the_message_is_reported_and_the_exit_code_is_non_zero(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())
        source_dir = tmp_path / "tf-root"
        source_dir.mkdir()

        run = _run_cli(["--terraformJsonFiles", plan_file, "--terraformRootDirs", str(source_dir)])

        assert run.exit_code == 1
        assert run.errors == [self.MESSAGE]
        assert not run.generated

    def test_the_specific_message_wins_over_the_generic_one(self, tmp_path):
        # All three local modes at once: the plan/source pair is checked first.
        plan_file = _write_plan(tmp_path, _diff_plan())
        source_dir = tmp_path / "tf-root"
        source_dir.mkdir()
        bicep_file = tmp_path / "main.bicep"
        bicep_file.write_text("// empty\n", encoding="utf-8")

        run = _run_cli(
            [
                "--terraformJsonFiles",
                plan_file,
                "--terraformRootDirs",
                str(source_dir),
                "--bicepFiles",
                str(bicep_file),
            ]
        )

        assert run.exit_code == 1
        assert run.errors == [self.MESSAGE]

    def test_the_generic_message_still_covers_bicep_plus_plan_json(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())
        bicep_file = tmp_path / "main.bicep"
        bicep_file.write_text("// empty\n", encoding="utf-8")

        run = _run_cli(["--terraformJsonFiles", plan_file, "--bicepFiles", str(bicep_file)])

        assert run.exit_code == 1
        assert self.GENERIC in run.errors[0]
        assert self.MESSAGE not in run.errors

    @pytest.mark.parametrize("mode", ["plan", "source"])
    def test_a_single_terraform_input_is_accepted(self, tmp_path, mode):
        plan_file = _write_plan(tmp_path, _diff_plan())
        source_dir = tmp_path / "tf-root"
        source_dir.mkdir()
        argv = ["--terraformJsonFiles", plan_file] if mode == "plan" else ["--terraformRootDirs", str(source_dir)]

        run = _run_cli(argv)

        assert run.exit_code == 0
        assert not run.logged(self.MESSAGE)
        assert run.generated


class TestMissingPlanPath:
    """A plan path that does not exist is reported before any generation (1.6)."""

    def test_the_missing_path_is_reported_and_the_exit_code_is_non_zero(self, tmp_path):
        absent = str(tmp_path / "absent.json")

        run = _run_cli(["--terraformJsonFiles", absent])

        assert run.exit_code == 1
        assert len(run.errors) == 1
        assert absent in run.errors[0]
        assert not run.generated

    def test_a_missing_path_among_present_ones_is_reported(self, tmp_path):
        present = _write_plan(tmp_path, _diff_plan(), "present.json")
        absent = str(tmp_path / "absent.json")

        run = _run_cli(["--terraformJsonFiles", present, absent])

        assert run.exit_code == 1
        assert absent in run.errors[0]
        assert present not in run.errors[0]
        assert not run.generated

    def test_a_missing_scope_metadata_file_is_reported(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())
        absent = str(tmp_path / "scope.json")

        run = _run_cli(["--terraformJsonFiles", plan_file, "--scopeMetadataFiles", absent])

        assert run.exit_code == 1
        assert absent in run.errors[0]
        assert not run.generated

    def test_an_existing_plan_path_reaches_the_service(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan_file])

        assert run.exit_code == 0
        assert run.generate_graph.kwargs["terraform_json_files"] == [plan_file]


class TestOutputPathPattern:
    """Plan_Diff_Mode writes the PNG to the legacy output path pattern (8.5)."""

    PATTERN = re.compile(r"azure_resources_\d{8}_\d{6}[/\\]azure_resources_\d{8}_\d{6}\.png$")

    @staticmethod
    def _generate(work_dir: str, template: Dict[str, Any], change_types: Optional[List[str]] = None):
        """Run one terraform-json generation and return `(png_path, render_calls)`."""
        from test_plan_diff_graph_plumbing import RG, SUB, TENANT

        os.makedirs(work_dir, exist_ok=True)
        plan_path = os.path.join(work_dir, "plan.json")
        with open(plan_path, "w", encoding="utf-8") as handle:
            json.dump({"format_version": "1.0"}, handle)
        built_path = os.path.join(work_dir, "template.json")
        with open(built_path, "w", encoding="utf-8") as handle:
            json.dump(template, handle)

        render_calls: List[Tuple[Optional[str], Optional[str]]] = []

        def mock_render(self, filename=None, format=None, *args, **kwargs):
            render_calls.append((filename, format))
            if filename:
                with open(f"{filename}.png", "w", encoding="utf-8") as handle:
                    handle.write("")
            return filename

        def mock_unflatten(self, *args, **kwargs):
            return self

        with (
            patch("core.graph_generator.build_terraform_template", return_value=built_path),
            patch("core.graph_generator.get_private_dns_zones_without_vnets", return_value=[]),
            patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", return_value=[]),
            patch("core.graph_generator.get_bastion_host_name", return_value=None),
            patch("graphviz.Digraph.render", mock_render),
            patch("graphviz.Digraph.unflatten", mock_unflatten),
            patch("subprocess.run", return_value=MagicMock()),
        ):
            from core.graph_generator import generate_resource_graph

            previous_dir = os.getcwd()
            os.chdir(work_dir)
            try:
                png_path = generate_resource_graph(
                    tenants=[TENANT],
                    subscriptions=[SUB],
                    resource_groups=[RG],
                    subnet_optimization=[False],
                    direction="TB",
                    tenant_minlen="LR",
                    max_subnet_in_line=4,
                    rankDebug="invis",
                    peOptimization=[True],
                    privateDnsZonesOptimization=False,
                    resourcesEdgeLength=1,
                    resourceGroupsEdgeLengthListBySubscription=[4],
                    crossPeOptimization=[False],
                    discoverResourceGroups=None,
                    exportDrawio=False,
                    use_local_template=True,
                    local_template_mode="terraform-json",
                    terraform_json_files=[plan_path],
                    change_types=change_types,
                )
            finally:
                os.chdir(previous_dir)

        return png_path, render_calls

    def test_a_plan_diff_run_uses_the_legacy_pattern(self, tmp_path):
        from test_plan_diff_graph_plumbing import plan_template

        png_path, render_calls = self._generate(
            str(tmp_path / "diff"),
            plan_template({"planstorage": "delete"}),
            change_types=["delete"],
        )

        assert self.PATTERN.search(png_path)
        assert os.path.isabs(png_path)
        rendered_stem, rendered_format = render_calls[-1]
        assert rendered_format == "png"
        # The renderer is handed the same relative stem the returned absolute path ends with.
        assert png_path.endswith(f"{rendered_stem}.png")

    def test_the_pattern_is_the_same_as_a_legacy_run(self, tmp_path):
        from test_plan_diff_graph_plumbing import plan_template

        legacy_png, _ = self._generate(str(tmp_path / "legacy"), plan_template())
        diff_png, _ = self._generate(str(tmp_path / "diff"), plan_template({"planstorage": "create"}))

        assert self.PATTERN.search(legacy_png)
        assert self.PATTERN.search(diff_png)
        # Same folder-plus-file shape, only the timestamp differs.
        assert re.sub(r"\d{8}_\d{6}", "T", os.path.basename(os.path.dirname(diff_png))) == re.sub(
            r"\d{8}_\d{6}", "T", os.path.basename(os.path.dirname(legacy_png))
        )
        assert re.sub(r"\d{8}_\d{6}", "T", os.path.basename(diff_png)) == re.sub(
            r"\d{8}_\d{6}", "T", os.path.basename(legacy_png)
        )

    def test_the_cli_reports_the_path_returned_by_the_service(self, tmp_path):
        plan_file = _write_plan(tmp_path, _diff_plan())
        expected = os.path.join("azure_resources_20250607_101112", "azure_resources_20250607_101112.png")

        run = _run_cli(["--terraformJsonFiles", plan_file], png_path=expected)

        assert run.exit_code == 0
        assert self.PATTERN.search(expected)
        assert run.logged(expected)
