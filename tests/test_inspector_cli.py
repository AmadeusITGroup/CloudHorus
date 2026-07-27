"""CLI and configuration surface of the Interactive Resource Inspector.

Feature: interactive-resource-inspector

Task 9.3 owns Property 17: `--interactiveInspector` value validation is total over
strings, and the option string, arity and default of every argument accepted
before this feature are unchanged.

Task 9.4 owns the example tests around it: the value reaching
`VisualizationConfig.interactive_inspector` and the service layer (2.1), the
argparse inventory snapshot (2.2), the parser default (1.2), the headless exit
codes of a successful and a failing run (1.7), the Interaction_Layer landing
beside the PNG in the run folder (3.6), exactly one `.inspector.jsonl` and one
`.inspector-index.json` per run (12.8), a run with no interactive display still
writing every artifact (1.12), the Plan_File read count unchanged by Inspector_Mode
(6.10), and the Azure-facing call count unchanged (10.5).

The pipeline guarantee is asserted alongside: with the flag absent the run
behaves as it did before the feature — same argparse inventory, same defaults,
same PNG output path pattern, and no Inspector artifact in the run folder.

The parser/`main()` harness (`_build_parser`, `_argument_inventory`, `_parse`,
`_run_cli`) is the one `tests/test_plan_diff_cli.py` already uses, imported rather
than duplicated, so a change to the CLI surface fails in one place.

Requirements: 1.2, 1.7, 1.12, 2.1, 2.2, 2.3, 3.6, 6.10, 10.5, 12.8
"""

import builtins
import json
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import main  # noqa: E402  (src/main.py, on sys.path through tests/conftest.py)
from cloudhorus.models.configuration import OptimizationConfig, VisualizationConfig  # noqa: E402
from conftest import DotAnalyzer  # noqa: E402
from core.graph_generator import DOT_BINARY  # noqa: E402
from core.inspector import (  # noqa: E402
    INSPECTOR_INDEX_SUFFIX,
    INSPECTOR_RECORDS_SUFFIX,
    INTERACTION_LAYER_SUFFIX,
)
from core.terraform_builder import TerraformTemplateBuilder  # noqa: E402
from test_inspector_parity import _blocking_subprocess_run  # noqa: E402
from test_plan_diff_cli import (  # noqa: E402
    LEGACY_ARGUMENTS,
    LEGACY_CHOICES,
    _argument_inventory,
    _build_parser,
    _diff_plan,
    _parse,
    _run_cli,
    _write_plan,
)
from test_plan_diff_graph_plumbing import RG, SUB, TENANT, plan_template  # noqa: E402

#: The argparse inventory as it stood before this feature: option string -> (nargs, default).
#: `--changeTypes` shipped with the plan-diff feature, so it belongs to the pre-existing
#: set here; `--interactiveInspector` is this feature's one addition (Requirement 2.2).
PRE_INSPECTOR_ARGUMENTS: Dict[str, Tuple[Any, Any]] = {**LEGACY_ARGUMENTS, "--changeTypes": ("+", None)}

#: The output path pattern the release preceding this feature writes (Requirement 1.4).
PNG_PATTERN = re.compile(r"azure_resources_\d{8}_\d{6}[/\\]azure_resources_\d{8}_\d{6}\.png$")

INVALID_VALUE_MESSAGE = "Invalid --interactiveInspector value '{value}'. Accepted values: True False"

#: An Interaction_Layer the icon-embedding pass accepts as it stands: well-formed,
#: namespaced, and carrying no `<image>`, so nothing has to be hoisted.
FAKE_SVG = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'width="800pt" height="600pt" viewBox="0 0 800 600">\n'
    '<g class="graph"><title>CloudHorus</title>\n'
    f'<g class="node"><title>planstorage-{RG}</title></g>\n'
    f'<g class="cluster"><title>cluster_vnetplan-vnet</title></g>\n'
    "</g></svg>\n"
)


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


@pytest.fixture(scope="module")
def plan_file(tmp_path_factory) -> str:
    """One plan JSON on disk for the whole module, so `@given` needs no per-example file."""
    return _write_plan(tmp_path_factory.mktemp("inspector-cli"), _diff_plan())


def _config(**kwargs) -> VisualizationConfig:
    return VisualizationConfig(
        tenants=["tenant-1"],
        subscriptions=["sub-1"],
        resource_groups=["rg-1"],
        optimizations=[OptimizationConfig()],
        **kwargs,
    )


def _run_cli_with_config(argv: List[str], png_path: Optional[str] = None):
    """Run the CLI, capturing the `VisualizationConfig` `main()` builds.

    Returns `(run, configs)`, where `configs` holds the real dataclass instances —
    the recorder forwards to the real class rather than replacing it, so
    `__post_init__` still runs and defaults still apply.
    """
    configs: List[VisualizationConfig] = []
    real_class = main.VisualizationConfig

    def recorder(*args, **kwargs):
        config = real_class(*args, **kwargs)
        configs.append(config)
        return config

    with patch.object(main, "VisualizationConfig", recorder):
        run = _run_cli(argv) if png_path is None else _run_cli(argv, png_path=png_path)
    return run, configs


# ─── Generation harness: the run folder with the layout engine faked out ──────


class _AzureCallCounter:
    """Delegating proxy over the `az_sdk` module that counts every call it serves."""

    def __init__(self, target: Any) -> None:
        self._target = target
        self.calls: List[str] = []

    def __getattr__(self, name: str) -> Any:
        attribute = getattr(self._target, name)
        if not callable(attribute):
            return attribute

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return attribute(*args, **kwargs)

        return counted


def _fake_dot_invocation(calls: List[List[str]]):
    """A `subprocess.run` double that writes the outputs the real `dot` would write.

    The dual-format invocation names its targets after `-o`, so the double honours
    exactly those: an empty PNG and a minimal, well-formed Interaction_Layer.
    """

    def fake_run(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and any(str(token) == "-o" for token in command):
            tokens = [str(token) for token in command]
            calls.append(tokens)
            for index, token in enumerate(tokens):
                if token != "-o" or index + 1 >= len(tokens):
                    continue
                target = tokens[index + 1]
                if target.endswith(INTERACTION_LAYER_SUFFIX):
                    with open(target, "w", encoding="utf-8") as handle:
                        handle.write(FAKE_SVG)
                else:
                    with open(target, "wb") as handle:
                        handle.write(b"")
        return MagicMock(returncode=0)

    return fake_run


def _run_generation(
    work_dir: str,
    interactive_inspector: Optional[bool] = None,
    categories: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Run one terraform-json generation with Graphviz layout faked out.

    Returns the PNG path, the run folder, the DOT source, the recorded `dot`
    invocations, the builder call kwargs and the Azure-facing call counts.
    """
    os.makedirs(work_dir, exist_ok=True)
    plan_path = os.path.join(work_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump({"format_version": "1.0"}, handle)
    built_path = os.path.join(work_dir, "template.json")
    with open(built_path, "w", encoding="utf-8") as handle:
        json.dump(plan_template(categories), handle)

    builder_calls: List[Dict[str, Any]] = []
    dot_invocations: List[List[str]] = []
    captured: Dict[str, str] = {}

    def fake_build(terraform_json_file, *args, **kwargs):
        builder_calls.append({"path": terraform_json_file, "args": args, "kwargs": kwargs})
        return built_path

    def mock_render(self, filename=None, format=None, *args, **kwargs):
        captured["source"] = self.source
        if filename:
            with open(f"{filename}.png", "wb") as handle:
                handle.write(b"")
        return filename

    def mock_unflatten(self, *args, **kwargs):
        return self

    import core.graph_generator as graph_generator

    azure = _AzureCallCounter(graph_generator.az_sdk)
    kwargs: Dict[str, Any] = {}
    if interactive_inspector is not None:
        kwargs["interactive_inspector"] = interactive_inspector

    with (
        patch("core.graph_generator.build_terraform_template", side_effect=fake_build),
        patch("core.graph_generator.get_private_dns_zones_without_vnets", return_value=[]),
        patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", return_value=[]),
        patch("core.graph_generator.get_bastion_host_name", return_value=None),
        patch("core.graph_generator.az_sdk", azure),
        patch("core.graph_generator.export_resource_group_template") as export_template,
        patch("core.graph_generator.get_subscription_name") as subscription_name,
        patch("graphviz.Digraph.render", mock_render),
        patch("graphviz.Digraph.unflatten", mock_unflatten),
        patch("subprocess.run", side_effect=_fake_dot_invocation(dot_invocations)),
    ):
        previous_dir = os.getcwd()
        os.chdir(work_dir)
        try:
            png_path = graph_generator.generate_resource_graph(
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
                **kwargs,
            )
        finally:
            os.chdir(previous_dir)

        azure_calls = Counter(azure.calls)
        azure_calls["export_resource_group_template"] = export_template.call_count
        azure_calls["get_subscription_name"] = subscription_name.call_count

    return {
        "png_path": png_path,
        "run_folder": os.path.dirname(png_path),
        "source": captured.get("source", ""),
        "dot_invocations": dot_invocations,
        "builder_calls": builder_calls,
        "azure_calls": azure_calls,
    }


def _artifacts(run_folder: str, suffix: str) -> List[str]:
    """Every file of `run_folder` carrying `suffix`, sorted."""
    return sorted(name for name in os.listdir(run_folder) if name.endswith(suffix))


# ─── Property 17: CLI value validation is total ───────────────────────────────


def _inspector_values() -> st.SearchStrategy[str]:
    """Strings supplied as the value of `--interactiveInspector`.

    The accepted values come first in every letter case that matters, then the
    values `str_to_bool` treats as true or false but this argument must reject
    (Requirement 2.3 is stricter than `--exportDrawio` on purpose), then arbitrary
    text — including text with leading dashes and inner whitespace, which is why
    the value is passed in the `--flag=value` form.
    """
    return st.one_of(
        st.sampled_from(("True", "true", "TRUE", "tRuE", "False", "false", "FALSE", "fAlSe")),
        st.sampled_from(("yes", "no", "1", "0", "t", "y", "", " true", "true ", "True\n", "-x", "--True")),
        st.text(max_size=12),
    )


# Feature: interactive-resource-inspector, Property 17: For any string supplied as
# the value of `--interactiveInspector`, CloudHorus enables Inspector_Mode when the
# value case-folds to `true`, leaves it disabled when the value case-folds to
# `false`, and otherwise reports the accepted values and terminates with a non-zero
# exit code; and the option-string, arity and default of every CLI argument accepted
# before this feature are unchanged.
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(value=_inspector_values())
def test_property_cli_value_validation_is_total(plan_file, value):
    """Property 17: CLI value validation is total.

    Three outcomes, no fourth: enabled, disabled, or refused with the accepted
    values named and a non-zero exit before any generation work starts. The
    validation is case-insensitive and exact — `yes`, `1` and `true ` are refused,
    unlike `--exportDrawio`, whose lenient `str_to_bool` behaviour this feature
    leaves untouched. The inventory clause rides along on every example, so no
    generated value can be shown to change the CLI surface either.

    **Validates: Requirements 2.2, 2.3**
    """
    run = _run_cli(["--terraformJsonFiles", plan_file, f"--interactiveInspector={value}"])

    folded = value.lower()
    if folded == "true":
        assert run.exit_code == 0
        assert run.generate_graph.kwargs["interactive_inspector"] is True
    elif folded == "false":
        assert run.exit_code == 0
        assert run.generate_graph.kwargs["interactive_inspector"] is False
    else:
        assert run.exit_code != 0
        assert run.errors == [INVALID_VALUE_MESSAGE.format(value=value)]
        assert not run.generated

    # The option string, arity and default of every pre-existing argument, unchanged.
    inventory = _argument_inventory()
    assert {name: inventory[name] for name in PRE_INSPECTOR_ARGUMENTS} == PRE_INSPECTOR_ARGUMENTS
    assert set(inventory) - set(PRE_INSPECTOR_ARGUMENTS) == {"--interactiveInspector"}


# ─── The argparse surface (Requirements 2.2, 1.2) ─────────────────────────────


class TestArgparseSurface:
    """The one added argument, and nothing else touched (2.2, 1.2)."""

    def test_no_pre_existing_argument_changed_or_disappeared(self):
        inventory = _argument_inventory()

        assert {name: inventory[name] for name in PRE_INSPECTOR_ARGUMENTS} == PRE_INSPECTOR_ARGUMENTS
        assert set(PRE_INSPECTOR_ARGUMENTS) <= set(inventory)

    def test_interactive_inspector_is_the_only_addition(self):
        assert set(_argument_inventory()) - set(PRE_INSPECTOR_ARGUMENTS) == {"--interactiveInspector"}

    def test_the_default_is_the_string_false(self):
        """Requirement 1.2: Inspector_Mode is off unless the Operator asks for it."""
        assert _argument_inventory()["--interactiveInspector"] == (None, "False")
        assert _parse([]).interactiveInspector == "False"

    def test_the_argument_shape_matches_export_drawio(self):
        """Requirement 2.2: `type=str`, `default="False"`, no `choices`, no arity."""
        actions = {
            action.option_strings[0]: action
            for action in _build_parser()._actions
            if action.option_strings and action.dest != "help"
        }
        inspector, drawio = actions["--interactiveInspector"], actions["--exportDrawio"]

        assert (inspector.type, inspector.default, inspector.nargs) == (str, "False", None)
        assert (inspector.type, inspector.default, inspector.nargs) == (drawio.type, drawio.default, drawio.nargs)
        assert inspector.choices is None
        assert inspector.dest == "interactiveInspector"

    def test_constrained_arguments_keep_their_accepted_values(self):
        choices = {
            action.option_strings[0]: action.choices
            for action in _build_parser()._actions
            if action.option_strings and action.dest != "help"
        }

        assert {name: choices[name] for name in LEGACY_CHOICES} == LEGACY_CHOICES

    def test_export_drawio_keeps_its_lenient_conversion(self):
        """Requirement 2.2: the strict check is this argument's, not a change to another."""
        assert main.str_to_bool("yes") is True
        assert main.str_to_bool("1") is True
        assert main.str_to_bool("nonsense") is False


# ─── The value reaching the configuration and the service (2.1, 2.8) ──────────


class TestConfigurationForwarding:
    """`--interactiveInspector True` reaches `VisualizationConfig` and the service (2.1)."""

    def test_true_reaches_the_configuration_and_the_service(self, tmp_path):
        run, configs = _run_cli_with_config(
            ["--terraformJsonFiles", _write_plan(tmp_path, _diff_plan()), "--interactiveInspector", "True"]
        )

        assert run.exit_code == 0
        assert [config.interactive_inspector for config in configs] == [True]
        assert run.generate_graph.kwargs["interactive_inspector"] is True

    def test_false_reaches_the_configuration_and_the_service(self, tmp_path):
        run, configs = _run_cli_with_config(
            ["--terraformJsonFiles", _write_plan(tmp_path, _diff_plan()), "--interactiveInspector", "False"]
        )

        assert run.exit_code == 0
        assert [config.interactive_inspector for config in configs] == [False]
        assert run.generate_graph.kwargs["interactive_inspector"] is False

    def test_an_absent_flag_is_the_pre_feature_run(self, tmp_path):
        """Requirement 1.2: the flag off the command line is Inspector_Mode disabled."""
        run, configs = _run_cli_with_config(["--terraformJsonFiles", _write_plan(tmp_path, _diff_plan())])

        assert run.exit_code == 0
        assert [config.interactive_inspector for config in configs] == [False]
        assert run.generate_graph.kwargs["interactive_inspector"] is False

    @pytest.mark.parametrize("mode", ["terraform-json", "terraform-source", "bicep"])
    def test_the_toggle_is_independent_of_the_input_mode(self, tmp_path, mode):
        """Requirement 2.8: the input mode and Inspector_Mode are separate choices."""
        if mode == "terraform-json":
            argv = ["--terraformJsonFiles", _write_plan(tmp_path, _diff_plan())]
        elif mode == "terraform-source":
            root = tmp_path / "tf-root"
            root.mkdir()
            (root / "main.tf").write_text("# empty root\n", encoding="utf-8")
            argv = ["--terraformRootDirs", str(root)]
        else:
            bicep = tmp_path / "main.bicep"
            bicep.write_text("// empty\n", encoding="utf-8")
            params = tmp_path / "main.params.json"
            params.write_text(json.dumps({"parameters": {}}), encoding="utf-8")
            argv = ["--bicepFiles", str(bicep), "--parametersFiles", str(params)]

        run, configs = _run_cli_with_config([*argv, "--interactiveInspector", "true"])

        assert run.exit_code == 0
        assert [config.interactive_inspector for config in configs] == [True]
        assert run.generate_graph.kwargs["interactive_inspector"] is True


# ─── Headless exit codes (Requirement 1.7) ────────────────────────────────────


class TestHeadlessExitCodes:
    """A headless run returns the exit code the pre-feature release returns (1.7)."""

    def test_a_successful_run_exits_zero_with_the_inspector_on_and_off(self, tmp_path):
        plan = _write_plan(tmp_path, _diff_plan())

        disabled = _run_cli(["--terraformJsonFiles", plan])
        enabled = _run_cli(["--terraformJsonFiles", plan, "--interactiveInspector", "True"])

        assert disabled.exit_code == 0
        assert enabled.exit_code == disabled.exit_code
        assert disabled.generated and enabled.generated

    def test_a_failing_generation_exits_non_zero_with_the_inspector_on_and_off(self, tmp_path):
        plan = _write_plan(tmp_path, _diff_plan())

        disabled = _run_cli(["--terraformJsonFiles", plan], png_path=None)
        enabled = _run_cli(["--terraformJsonFiles", plan, "--interactiveInspector", "True"], png_path=None)

        assert disabled.exit_code == 1
        assert enabled.exit_code == disabled.exit_code
        assert any("Graph generation failed" in message for message in enabled.errors)

    def test_an_invalid_value_exits_before_any_generation_work(self, tmp_path):
        plan = _write_plan(tmp_path, _diff_plan())

        run = _run_cli(["--terraformJsonFiles", plan, "--interactiveInspector", "Yes"])

        assert run.exit_code == 1
        assert run.errors == [INVALID_VALUE_MESSAGE.format(value="Yes")]
        assert not run.generated


# ─── The run folder (Requirements 3.6, 12.8, 1.4, 1.12) ───────────────────────


class TestRunArtifacts:
    """What an Inspector_Mode run leaves in the folder it already creates."""

    def test_the_interaction_layer_lands_beside_the_png(self, tmp_path):
        """Requirement 3.6: the layer is written into the run folder of the PNG."""
        run = _run_generation(str(tmp_path / "enabled"), interactive_inspector=True)

        stem = os.path.splitext(os.path.basename(run["png_path"]))[0]
        assert _artifacts(run["run_folder"], ".png") == [f"{stem}.png"]
        assert _artifacts(run["run_folder"], INTERACTION_LAYER_SUFFIX) == [f"{stem}{INTERACTION_LAYER_SUFFIX}"]
        assert os.path.dirname(run["png_path"]) == run["run_folder"]

    def test_exactly_one_payload_and_one_index_per_run(self, tmp_path):
        """Requirement 12.8: one JSONL, one index, both named after the diagram."""
        run = _run_generation(str(tmp_path / "enabled"), interactive_inspector=True)

        stem = os.path.splitext(os.path.basename(run["png_path"]))[0]
        assert _artifacts(run["run_folder"], INSPECTOR_RECORDS_SUFFIX) == [f"{stem}{INSPECTOR_RECORDS_SUFFIX}"]
        assert _artifacts(run["run_folder"], INSPECTOR_INDEX_SUFFIX) == [f"{stem}{INSPECTOR_INDEX_SUFFIX}"]

        index_path = os.path.join(run["run_folder"], f"{stem}{INSPECTOR_INDEX_SUFFIX}")
        with open(index_path, "r", encoding="utf-8") as handle:
            index = json.load(handle)
        with open(os.path.join(run["run_folder"], f"{stem}{INSPECTOR_RECORDS_SUFFIX}"), "rb") as handle:
            lines = [line for line in handle.read().split(b"\n") if line]

        assert index["recordCount"] == len(lines) == len(index["keys"])
        assert index["diagram"] == f"{stem}.png"

    def test_a_disabled_run_writes_no_inspector_artifact(self, tmp_path):
        """Requirement 1.4: the flag off leaves the pre-feature artifact set."""
        run = _run_generation(str(tmp_path / "disabled"), interactive_inspector=False)

        for suffix in (INTERACTION_LAYER_SUFFIX, INSPECTOR_RECORDS_SUFFIX, INSPECTOR_INDEX_SUFFIX):
            assert _artifacts(run["run_folder"], suffix) == []
        assert run["dot_invocations"] == []

    def test_the_png_path_pattern_is_the_pre_feature_pattern(self, tmp_path):
        """Requirement 1.4: same folder-plus-file shape either way, only the timestamp differs."""
        disabled = _run_generation(str(tmp_path / "disabled"), interactive_inspector=False)
        enabled = _run_generation(str(tmp_path / "enabled"), interactive_inspector=True)
        omitted = _run_generation(str(tmp_path / "omitted"))

        for run in (disabled, enabled, omitted):
            assert PNG_PATTERN.search(run["png_path"])
            assert os.path.isabs(run["png_path"])
            assert os.path.exists(run["png_path"])

        def shape(path: str) -> str:
            return re.sub(r"\d{8}_\d{6}", "T", os.path.join(os.path.basename(os.path.dirname(path)), os.path.basename(path)))

        assert shape(enabled["png_path"]) == shape(disabled["png_path"]) == shape(omitted["png_path"])

    def test_one_dual_format_layout_pass_produces_both_outputs(self, tmp_path):
        """Requirement 3.1 at this level: one invocation carrying both `-Tpng` and `-Tsvg`."""
        run = _run_generation(str(tmp_path / "enabled"), interactive_inspector=True)

        assert len(run["dot_invocations"]) == 1
        command = run["dot_invocations"][0]
        assert "-Tpng" in command and "-Tsvg" in command
        # A fixed argument vector, every path its own element: no shell string.
        assert all(isinstance(token, str) for token in command)

    def test_a_run_without_an_interactive_display_writes_every_artifact(self, tmp_path, monkeypatch):
        """Requirement 1.12: no display, and still the PNG plus every Inspector artifact."""
        monkeypatch.delenv("DISPLAY", raising=False)
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        monkeypatch.setenv("CLOUDHORUS_NON_INTERACTIVE", "true")

        run = _run_generation(str(tmp_path / "headless"), interactive_inspector=True)

        stem = os.path.splitext(os.path.basename(run["png_path"]))[0]
        for suffix in (".png", INTERACTION_LAYER_SUFFIX, INSPECTOR_RECORDS_SUFFIX, INSPECTOR_INDEX_SUFFIX):
            assert os.path.exists(os.path.join(run["run_folder"], f"{stem}{suffix}"))

    def test_the_builder_is_asked_for_inspector_values_only_when_enabled(self, tmp_path):
        """Requirement 1.5: the disabled run passes the pre-feature builder arguments."""
        enabled = _run_generation(str(tmp_path / "enabled"), interactive_inspector=True)
        disabled = _run_generation(str(tmp_path / "disabled"), interactive_inspector=False)

        assert [call["kwargs"].get("collect_inspector_values") for call in enabled["builder_calls"]] == [True]
        assert all("collect_inspector_values" not in call["kwargs"] for call in disabled["builder_calls"])


# ─── No extra input reads (Requirements 6.10, 10.5) ───────────────────────────


class TestNoAdditionalReads:
    """Inspector_Mode reads the inputs the run already reads, and nothing more."""

    @staticmethod
    def _plan_open_count(plan_path: str, output_path: str, collect: bool) -> int:
        """Build the template for real, counting how often the Plan_File is opened."""
        real_open = builtins.open
        opens: List[str] = []

        def spy(file, *args, **kwargs):
            try:
                if os.path.abspath(str(file)) == os.path.abspath(plan_path):
                    opens.append(str(file))
            except (TypeError, ValueError):  # pragma: no cover - a file descriptor
                pass
            return real_open(file, *args, **kwargs)

        with patch("builtins.open", spy):
            assert (
                TerraformTemplateBuilder().build_terraform_template(
                    plan_path, output_path, None, collect
                )
                is not None
            )
        return len(opens)

    def test_the_plan_file_is_opened_the_same_number_of_times(self, tmp_path):
        """Requirement 6.10: the after snapshot comes from data the run already holds."""
        plan_path = _write_plan(tmp_path, _diff_plan())

        without = self._plan_open_count(plan_path, str(tmp_path / "off.json"), False)
        with_inspector = self._plan_open_count(plan_path, str(tmp_path / "on.json"), True)

        assert without == 1
        assert with_inspector == without

    def test_the_azure_facing_call_count_is_unchanged(self, tmp_path):
        """Requirement 10.5: Inspector_Mode issues no additional Azure request.

        The run goes through the local-template path, which is the one the suite can
        drive without an Azure tenant; the assertion is the one Requirement 10.5
        makes — enabling the Inspector adds no call to any Azure-facing entry point
        of the pipeline, because a record is built from the resource dict already in
        scope.
        """
        disabled = _run_generation(str(tmp_path / "disabled"), interactive_inspector=False)
        enabled = _run_generation(str(tmp_path / "enabled"), interactive_inspector=True)

        assert enabled["azure_calls"] == disabled["azure_calls"]
        assert enabled["azure_calls"]["export_resource_group_template"] == 0
        assert enabled["azure_calls"]["get_subscription_name"] == 0


# ─── Task 14.3: the end-to-end CLI run ────────────────────────────────────────
#
# Everything above drives `main()` with the generator service replaced, or the
# pipeline with Graphviz layout faked out. This section runs the whole thing: the
# real CLI over a sample Plan_File, the real builder, the real `dot` layout and the
# real dual-format invocation, so the artifacts under assertion are the ones a
# pipeline would find on disk. The only thing replaced is the platform command a
# finished run issues to open the PNG in a desktop viewer.
#
# The pipeline guarantee is asserted as a pair of runs over one input:
#
# * with the flag off, the run folder holds exactly the pre-feature artifact set —
#   the DOT source, the PNG and the Change_Summary sidecar — at the pre-feature PNG
#   path (Requirements 1.4, 1.7, 1.11);
# * with the flag on, the same folder additionally holds the Interaction_Layer and
#   the two Inspector artifacts, and nothing else changes (Requirements 3.6, 12.8);
# * every Inspector_Key of the index is the `<title>` of an element the layer draws,
#   and every drawn resource node and virtual-network/subnet cluster has an index
#   entry (Requirements 3.2, 3.3, 3.4, 3.5, 4.1).
#
# Then the sample-plan regression anchor over `samples/terraform-modular/generated`
# pins the index key set and the attribute rows of one record, so a change in what
# the payload describes has to be an explicit edit here.
#
# Requirements: 1.11, 3.6, 4.1, 12.8

#: The sample plans the anchor runs over.
_SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")
LANDING_ZONE_PLAN = os.path.join(_SAMPLES, "terraform-plan-diff", "landing-zone.plan.json")
MODULAR_PLANS = [
    os.path.join(_SAMPLES, "terraform-modular", "generated", "network.plan.json"),
    os.path.join(_SAMPLES, "terraform-modular", "generated", "app.plan.json"),
]
MODULAR_SCOPES = [
    os.path.join(_SAMPLES, "terraform-modular", "generated", "network.scope.json"),
    os.path.join(_SAMPLES, "terraform-modular", "generated", "app.scope.json"),
]

#: The artifact suffixes the release preceding this feature writes for a
#: Plan_Diff_Mode run: the DOT source `dot.render` saves, the PNG, and the sidecar.
PRE_FEATURE_SUFFIXES = frozenset({"", ".change-summary.json", ".png"})

#: The three artifacts Inspector_Mode adds.
INSPECTOR_SUFFIXES = frozenset({INTERACTION_LAYER_SUFFIX, INSPECTOR_RECORDS_SUFFIX, INSPECTOR_INDEX_SUFFIX})

#: Container `<title>` prefixes that name a scope grouping rather than a resource.
#: Requirement 3.3 scopes the activatable containers to virtual networks and
#: subnets, so the tenant, subscription and resource-group containers, the layout
#: parent and the Legend are outside the Inspector's element set by design.
STRUCTURAL_CLUSTER_PREFIXES = (
    "cluster_parent",
    "cluster_tenant",
    "cluster_subscription",
    "cluster_resource_group",
    "cluster_change_legend",
)

#: Nodes the Diagram draws that describe no resource: the Legend block.
NON_RESOURCE_NODES = frozenset({"change_legend"})

#: Nodes the private-DNS-zone rendering path draws that the Inspector once left
#: uncollected. The coverage extension instruments every `add_node_in_subgraph` site,
#: so both now carry an Inspector_Record and the set is empty: Requirement 3.2 reads
#: as covering every resource the Graph_Pipeline draws as a node, and it now does.
#: Kept as an empty pin rather than deleted, so a regression that reintroduces a
#: drawn-but-undescribed node fails here with the node named.
UNCOLLECTED_SAMPLE_NODES = frozenset()

#: The Inspector_Key set of the modular sample run, pinned as the regression anchor.
#: The two private-DNS-zone entries are the coverage extension: the aggregated
#: `PrivateDNSZones-<vnet>` node, whose source is synthesized from the VNet's zone
#: list, and the standalone zone node drawn for a zone with no VNet link.
MODULAR_INDEX_KEYS = {
    "api-web-rg-platform-app": "node",
    "app-plan-rg-platform-app": "node",
    "privateEndpoints-app-rg-platform-app": "node",
    "PrivateDNSZones-core-vnet": "node",
    "privatelink.azurewebsites.net": "node",
    "cluster_vnetcore-vnet": "virtualNetwork",
    "cluster_subnetapp": "subnet",
}

#: The Attribute_Entry list of one modular sample record, pinned in full.
MODULAR_WEB_APP_ATTRIBUTES = [
    {"path": "location", "state": "unchanged", "before": "westeurope", "after": "westeurope"},
    {"path": "name", "state": "unchanged", "before": "api-web", "after": "api-web"},
    {
        "path": "virtual_network_subnet_id",
        "state": "unchanged",
        "before": (
            "/subscriptions/sub-platform-001/resourceGroups/rg-platform-network/providers/"
            "Microsoft.Network/virtualNetworks/core-vnet/subnets/app"
        ),
        "after": (
            "/subscriptions/sub-platform-001/resourceGroups/rg-platform-network/providers/"
            "Microsoft.Network/virtualNetworks/core-vnet/subnets/app"
        ),
    },
]

_SVG_NS = "{http://www.w3.org/2000/svg}"

requires_real_layout = pytest.mark.skipif(
    shutil.which(DOT_BINARY) is None or shutil.which("unflatten") is None,
    reason="the end-to-end CLI run needs the real dot and unflatten binaries",
)


class EndToEndRun:
    """One real CLI run and the artifacts its run folder holds."""

    def __init__(self, work_dir: str, exit_code: int) -> None:
        self.work_dir = work_dir
        self.exit_code = exit_code
        folders = sorted(name for name in os.listdir(work_dir) if name.startswith("azure_resources_"))
        assert folders, f"the run wrote no output folder under {work_dir}"
        self.stem = folders[-1]
        self.folder = os.path.join(work_dir, self.stem)

    def path(self, suffix: str = "") -> str:
        return os.path.join(self.folder, f"{self.stem}{suffix}")

    @property
    def png_path(self) -> str:
        return self.path(".png")

    @property
    def suffixes(self) -> set:
        """The artifact suffixes of the run folder, the timestamped stem removed."""
        return {name.replace(self.stem, "") for name in os.listdir(self.folder)}

    def text(self, suffix: str) -> str:
        with open(self.path(suffix), "r", encoding="utf-8") as handle:
            return handle.read()

    @property
    def analyzer(self):
        """A `DotAnalyzer` over the DOT source the render pass saved."""
        return DotAnalyzer(self.text(""))

    @property
    def index(self) -> Dict[str, Any]:
        return json.loads(self.text(INSPECTOR_INDEX_SUFFIX))

    def record(self, key: str) -> Dict[str, Any]:
        """Read one Inspector_Record the way the bridge reads it: seek and bounded read."""
        entry = self.index["keys"][key]
        with open(self.path(INSPECTOR_RECORDS_SUFFIX), "rb") as handle:
            handle.seek(entry["offset"])
            raw = handle.read(entry["length"])
        return json.loads(raw.decode("utf-8"))

    def layer_titles(self) -> Dict[str, set]:
        """The `<title>` text of the Interaction_Layer, grouped by element class.

        These are the elements the WebUI hit-tests, so they are the definition of
        "drawn": an invisible layout helper carries no `<g class="node">` at all.
        """
        root = ET.parse(self.path(INTERACTION_LAYER_SUFFIX)).getroot()
        titles: Dict[str, set] = {}
        for element in root.iter(f"{_SVG_NS}g"):
            title = element.find(f"{_SVG_NS}title")
            if title is None or not title.text:
                continue
            titles.setdefault(element.get("class") or "", set()).add(title.text)
        return titles


def _run_cli_end_to_end(
    work_dir: str,
    plans: List[str],
    interactive_inspector: Optional[bool],
    scopes: Optional[List[str]] = None,
) -> EndToEndRun:
    """Run `main()` over `plans` for real, in `work_dir`, and return the run's artifacts."""
    os.makedirs(work_dir, exist_ok=True)
    argv = ["cloudhorus", "--terraformJsonFiles", *plans]
    if scopes:
        argv += ["--scopeMetadataFiles", *scopes]
    argv += ["--nonInteractive", "true"]
    if interactive_inspector is not None:
        argv += ["--interactiveInspector", "True" if interactive_inspector else "False"]

    exit_code = 0
    previous_dir = os.getcwd()
    os.chdir(work_dir)
    try:
        with patch.object(sys, "argv", argv), patch("subprocess.run", _blocking_subprocess_run()):
            try:
                main.main()
            except SystemExit as signal:
                exit_code = signal.code or 0
    finally:
        os.chdir(previous_dir)

    return EndToEndRun(work_dir, exit_code)


@pytest.fixture(scope="module")
def end_to_end_runs(tmp_path_factory):
    """The landing-zone sample plan run twice: with the flag off, then with it on."""
    root = tmp_path_factory.mktemp("inspector-e2e")
    disabled = _run_cli_end_to_end(str(root / "off"), [LANDING_ZONE_PLAN], False)
    enabled = _run_cli_end_to_end(str(root / "on"), [LANDING_ZONE_PLAN], True)
    return disabled, enabled


@pytest.fixture(scope="module")
def sample_anchor_runs(tmp_path_factory):
    """The modular sample plans run twice, as the regression anchor."""
    root = tmp_path_factory.mktemp("inspector-samples")
    disabled = _run_cli_end_to_end(str(root / "off"), MODULAR_PLANS, False, MODULAR_SCOPES)
    enabled = _run_cli_end_to_end(str(root / "on"), MODULAR_PLANS, True, MODULAR_SCOPES)
    return disabled, enabled


@requires_real_layout
class TestEndToEndPipelineGuarantee:
    """One real CLI run per branch over the landing-zone sample plan."""

    def test_the_flag_off_writes_exactly_the_pre_feature_artifact_set(self, end_to_end_runs):
        """Requirements 1.4, 1.7: the pre-feature artifacts, at the pre-feature path."""
        disabled, _enabled = end_to_end_runs

        assert disabled.exit_code == 0
        assert disabled.suffixes == set(PRE_FEATURE_SUFFIXES)
        assert PNG_PATTERN.search(disabled.png_path)
        assert os.path.getsize(disabled.png_path) > 0

    def test_the_flag_on_adds_the_layer_and_the_payload_at_the_same_png_path(self, end_to_end_runs):
        """Requirements 3.6, 12.8, 1.11: three artifacts added, nothing else moved."""
        disabled, enabled = end_to_end_runs

        assert enabled.exit_code == 0
        assert enabled.suffixes == set(PRE_FEATURE_SUFFIXES | INSPECTOR_SUFFIXES)
        assert enabled.suffixes - disabled.suffixes == set(INSPECTOR_SUFFIXES)
        assert disabled.suffixes - enabled.suffixes == set()

        def shape(path: str) -> str:
            return re.sub(
                r"\d{8}_\d{6}",
                "T",
                os.path.join(os.path.basename(os.path.dirname(path)), os.path.basename(path)),
            )

        assert shape(enabled.png_path) == shape(disabled.png_path)
        assert PNG_PATTERN.search(enabled.png_path)
        assert os.path.getsize(enabled.png_path) > 0

        # Requirement 1.11: the sidecar keeps its name and its bytes.
        assert enabled.text(".change-summary.json") == disabled.text(".change-summary.json")

        # Exactly one payload and one index, named after the diagram (Requirement 12.8).
        index = enabled.index
        assert index["diagram"] == f"{enabled.stem}.png"
        assert index["records"] == f"{enabled.stem}{INSPECTOR_RECORDS_SUFFIX}"
        with open(enabled.path(INSPECTOR_RECORDS_SUFFIX), "rb") as handle:
            lines = [line for line in handle.read().split(b"\n") if line]
        assert index["recordCount"] == len(index["keys"]) == len(lines)

    def test_every_index_key_is_the_title_of_a_drawn_element(self, end_to_end_runs):
        """Requirements 3.4, 3.5, 4.1: the keys the WebUI looks up are the drawn titles."""
        _disabled, enabled = end_to_end_runs

        titles = enabled.layer_titles()
        drawn_nodes = titles.get("node", set())
        drawn_clusters = titles.get("cluster", set())
        assert drawn_nodes and drawn_clusters

        index = enabled.index
        node_keys = {key for key, entry in index["keys"].items() if entry["kind"] == "node"}
        cluster_keys = set(index["keys"]) - node_keys

        # Soundness: no record describes something the Diagram does not draw.
        assert node_keys <= drawn_nodes
        assert cluster_keys <= drawn_clusters
        # And the DOT the layout consumed carries the same identifiers.
        analyzer = enabled.analyzer
        for key in node_keys:
            assert analyzer.has_node(key), key
        for key in cluster_keys:
            assert analyzer.has_subgraph(key), key

        # Coverage: every drawn resource node and every VNet/subnet container has one.
        assert drawn_nodes - NON_RESOURCE_NODES == node_keys
        structural = {title for title in drawn_clusters if title.startswith(STRUCTURAL_CLUSTER_PREFIXES)}
        assert drawn_clusters - structural == cluster_keys
        assert {entry["kind"] for entry in index["keys"].values()} <= {"node", "virtualNetwork", "subnet"}

    def test_a_record_of_the_run_carries_its_identity_and_attribute_rows(self, end_to_end_runs):
        """Requirement 4.4: the record behind a drawn element describes that resource."""
        _disabled, enabled = end_to_end_runs

        index = enabled.index
        key = "aks-platform-cloudhorus-rg-1"
        assert key in index["keys"]

        record = enabled.record(key)
        assert record["key"] == key
        assert record["kind"] == "node"
        assert record["name"] == "aks-platform"
        assert record["resourceGroup"] == "cloudhorus-rg-1"
        # The plan replaces this resource, so the record carries the marker (4.9).
        assert record["changeCategory"] == "replace"
        assert record["replacement"] is True
        assert record["attributes"], "a record of a described resource must carry rows"
        assert all(entry["state"] in {"added", "removed", "changed", "unchanged"} for entry in record["attributes"])
        paths = [entry["path"] for entry in record["attributes"]]
        assert paths == sorted(paths)


@requires_real_layout
class TestSamplePlanAnchor:
    """The modular sample plans, pinned so a change in the payload is an explicit edit."""

    def test_the_index_key_set_is_the_pinned_set(self, sample_anchor_runs):
        """Requirement 4.1 as a regression anchor over the shipped sample plans."""
        _disabled, enabled = sample_anchor_runs

        index = enabled.index
        assert {key: entry["kind"] for key, entry in index["keys"].items()} == MODULAR_INDEX_KEYS
        assert index["recordCount"] == len(MODULAR_INDEX_KEYS)

        # What the anchor now pins is the absence of the gap: every node the layer
        # draws, the Legend aside, carries an Inspector_Record. A node that is drawn
        # but not described would be activatable with an empty panel, which is the
        # regression `UNCOLLECTED_SAMPLE_NODES` used to record and now forbids.
        drawn_nodes = enabled.layer_titles().get("node", set())
        undescribed = drawn_nodes - set(index["keys"]) - NON_RESOURCE_NODES
        assert undescribed == UNCOLLECTED_SAMPLE_NODES, f"drawn but not described: {sorted(undescribed)}"

        # Every record the anchor pins carries rows, so no key above buys its
        # membership with an empty panel (Requirement 3.2).
        for key in index["keys"]:
            assert enabled.record(key)["attributes"], f"{key} carries an empty panel"

    def test_one_record_carries_the_pinned_attribute_rows(self, sample_anchor_runs):
        """Requirements 5.2, 5.3, 5.4: the rows, their paths and their order, pinned."""
        _disabled, enabled = sample_anchor_runs

        record = enabled.record("api-web-rg-platform-app")

        assert record["name"] == "api-web"
        assert record["resourceType"] == "Microsoft.Web/sites"
        assert record["resourceGroup"] == "rg-platform-app"
        # Legacy_Mode input: no Change_Record, so no Change_Category and every row
        # `unchanged` (Requirements 6.9, 10.2).
        assert record["changeCategory"] is None
        assert record["attributes"] == MODULAR_WEB_APP_ATTRIBUTES
        assert record["omittedAttributes"] == 0
        assert record["truncations"] == []

    def test_the_artifact_sets_differ_only_by_the_inspector_artifacts(self, sample_anchor_runs):
        """Requirement 1.11 on a Legacy_Mode input: nothing else is added or renamed.

        These sample plans carry no `resource_changes`, so the run is Legacy_Mode and
        writes no Change_Summary sidecar. The sidecar assertion that matters here is
        therefore that Inspector_Mode does not introduce one, and that the only
        difference between the two runs is the three Inspector artifacts.
        """
        disabled, enabled = sample_anchor_runs

        assert disabled.suffixes == {"", ".png"}
        assert enabled.suffixes == {"", ".png"} | set(INSPECTOR_SUFFIXES)
        assert ".change-summary.json" not in enabled.suffixes
        assert enabled.text("") == disabled.text(""), "the DOT source changed with the Inspector on"
