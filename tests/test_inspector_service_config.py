"""Tests for `interactive_inspector` plumbing in the configuration and the service layer.

Covers Requirement 1.2 (Inspector_Mode defaults to disabled), Requirement 2.1
(`--interactiveInspector True` enables it for the run) and Requirement 2.8
(Inspector_Mode is independent of the input mode).
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cloudhorus.models.configuration import OptimizationConfig, VisualizationConfig  # noqa: E402
from cloudhorus.services.graph_generator_service import GraphGeneratorService  # noqa: E402

TARGET = "core.graph_generator.generate_resource_graph"


def _config(**kwargs) -> VisualizationConfig:
    return VisualizationConfig(
        tenants=["tenant-1"],
        subscriptions=["sub-1"],
        resource_groups=["rg-1"],
        optimizations=[OptimizationConfig()],
        **kwargs,
    )


# ─── VisualizationConfig ─────────────────────────────────────────────────────


def test_interactive_inspector_defaults_to_false():
    """Inspector_Mode is off unless the Operator asks for it (Requirement 1.2)."""
    assert _config().interactive_inspector is False


def test_interactive_inspector_accepts_a_supplied_value():
    assert _config(interactive_inspector=True).interactive_inspector is True


def test_legacy_positional_construction_is_unaffected():
    """The new field is trailing, so positional construction keeps its meaning."""
    config = VisualizationConfig(["tenant-1"], ["sub-1"], ["rg-1"])
    assert config.tenants == ["tenant-1"]
    assert config.subscriptions == ["sub-1"]
    assert config.resource_groups == ["rg-1"]
    assert config.change_types is None
    assert config.interactive_inspector is False


def test_legacy_keyword_construction_is_unaffected():
    """Pre-existing __post_init__ validation is untouched by the new field."""
    config = VisualizationConfig(subscriptions=["sub-1", "sub-2"])
    assert len(config.optimizations) == 2
    assert config.rg_edge_lengths == [4, 4]
    assert config.interactive_inspector is False


# ─── GraphGeneratorService.generate_graph ────────────────────────────────────


def test_generate_graph_forwards_interactive_inspector_when_enabled():
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        png_path = service.generate_graph(
            tenants=["tenant-1"],
            subscriptions=["sub-1"],
            resource_groups=["rg-1"],
            use_bicep_templates=True,
            local_template_mode="terraform-json",
            terraform_json_files=["plan.json"],
            interactive_inspector=True,
        )

    assert png_path == "/tmp/out.png"
    assert mock_generate.call_args.kwargs["interactive_inspector"] is True


def test_generate_graph_omits_interactive_inspector_when_disabled():
    """Legacy call sites produce the exact same argument list as before the feature."""
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        png_path = service.generate_graph(
            tenants=["tenant-1"],
            subscriptions=["sub-1"],
            resource_groups=["rg-1"],
        )

    assert png_path == "/tmp/out.png"
    kwargs = mock_generate.call_args.kwargs
    assert "interactive_inspector" not in kwargs
    assert "change_types" not in kwargs
    assert kwargs["use_local_template"] is False


def test_generate_graph_omits_interactive_inspector_when_explicitly_false():
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        service.generate_graph(
            tenants=["tenant-1"],
            subscriptions=["sub-1"],
            resource_groups=["rg-1"],
            interactive_inspector=False,
        )

    assert "interactive_inspector" not in mock_generate.call_args.kwargs


def test_generate_graph_accepts_interactive_inspector_positionally_last():
    """The parameter is trailing, so it is the last positional argument."""
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        service.generate_graph(
            ["tenant-1"],
            ["sub-1"],
            ["rg-1"],
            True,
            "terraform-json",
            None,
            None,
            ["plan.json"],
            None,
            None,
            ["create", "update"],
            True,
        )

    kwargs = mock_generate.call_args.kwargs
    assert kwargs["change_types"] == ["create", "update"]
    assert kwargs["interactive_inspector"] is True


def test_generate_graph_forwards_inspector_independently_of_change_types():
    """Inspector_Mode is independent of the input mode (Requirement 2.8)."""
    service = GraphGeneratorService(config=_config())

    with patch(TARGET, return_value="/tmp/out.png") as mock_generate:
        service.generate_graph(
            tenants=["tenant-1"],
            subscriptions=["sub-1"],
            resource_groups=["rg-1"],
            interactive_inspector=True,
        )

    kwargs = mock_generate.call_args.kwargs
    assert kwargs["interactive_inspector"] is True
    assert "change_types" not in kwargs

# ─── `--interactiveInspector` on the CLI (task 9.2) ──────────────────────────
#
# Requirement 2.2 (optional argument defaulted to `False`), Requirement 2.3 (a value
# outside `{true, false}` reports the accepted values and exits non-zero) and
# Requirement 2.1 (`True` reaches `VisualizationConfig.interactive_inspector`).

import json  # noqa: E402

import pytest  # noqa: E402

import main  # noqa: E402  (src/main.py, on sys.path through tests/conftest.py)

FAKE_PNG = os.path.join("azure_resources_20250101_120000", "azure_resources_20250101_120000.png")


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


@pytest.fixture
def plan_file(tmp_path) -> str:
    """A Terraform plan JSON path: main.py only checks that the file exists."""
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"format_version": "1.2", "planned_values": {"root_module": {"resources": []}}}))
    return str(path)


class CliRun:
    """The observable outcome of one `main.main()` invocation."""

    def __init__(self, exit_code, logger, service_class):
        self.exit_code = exit_code
        self.errors = [str(call.args[0]) for call in logger.error.call_args_list]
        self.generated = service_class.return_value.generate_graph.called
        self.config = service_class.call_args.kwargs["config"] if service_class.called else None


def _run_cli(argv) -> CliRun:
    """Run the real `main.main()` with only the generator service replaced by a double."""
    with (
        patch.object(sys, "argv", ["cloudhorus", *argv, "--nonInteractive", "true"]),
        patch.object(main, "logger") as logger,
        patch.object(main, "GraphGeneratorService") as service_class,
    ):
        service_class.return_value.validate.return_value = True
        service_class.return_value.generate_graph.return_value = FAKE_PNG

        exit_code = 0
        try:
            main.main()
        except SystemExit as signal:
            exit_code = signal.code

        return CliRun(exit_code, logger, service_class)


def test_the_parser_default_is_the_string_false():
    with patch.object(sys, "argv", ["cloudhorus"]):
        assert main.parse_arguments().interactiveInspector == "False"


@pytest.mark.parametrize(
    "value,expected",
    [("True", True), ("true", True), ("TRUE", True), ("False", False), ("false", False), ("FALSE", False)],
)
def test_accepted_values_enable_or_disable_inspector_mode(plan_file, value, expected):
    run = _run_cli(["--terraformJsonFiles", plan_file, "--interactiveInspector", value])

    assert run.exit_code == 0
    assert run.errors == []
    assert run.config.interactive_inspector is expected


def test_the_flag_reaches_the_visualization_config(plan_file):
    """Requirement 2.1: the enabled run carries Inspector_Mode in its configuration."""
    run = _run_cli(["--terraformJsonFiles", plan_file, "--interactiveInspector", "True"])

    assert run.config.interactive_inspector is True
    assert run.generated


def test_the_flag_is_absent_by_default(plan_file):
    run = _run_cli(["--terraformJsonFiles", plan_file])

    assert run.exit_code == 0
    assert run.config.interactive_inspector is False


@pytest.mark.parametrize("value", ["yes", "1", "", "Truthy", "no-op", "0"])
def test_an_invalid_value_reports_the_accepted_values_and_exits(plan_file, value):
    run = _run_cli(["--terraformJsonFiles", plan_file, "--interactiveInspector", value])

    assert run.exit_code == 1
    assert run.errors == [f"Invalid --interactiveInspector value '{value}'. Accepted values: True False"]
    assert not run.generated
