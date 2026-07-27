"""Parity tests for the Inspector-disabled path.

Feature: interactive-resource-inspector

Property 15 lives here (task 5.2): with Inspector_Mode off, the Renderer_Template
and the artifact path set of a run are the ones the release preceding this feature
produces. Property 16 joins it (task 7.7): with Inspector_Mode on and any one step
of the Inspector pipeline made to raise, the run still returns the PNG path, the
PNG is still on disk, the failure is a warning, and only the affected Inspector
artifact is missing. Property 13 closes the module (task 7.8): the PNG bytes, the
Graphviz DOT source and the Change_Summary sidecar of an Inspector_Mode run are
the bytes of the same run with Inspector_Mode off, and the enabled run reaches
them through exactly one dual-format layout pass.

Task 14.2 adds the Draw.io export parity check at the bottom of the module:
enabling Inspector_Mode must not change what the export carries (Requirement 1.8).
That check runs the real `dot` binary and the real `graphviz2drawio` converter, so
it is skipped rather than failing when either is unavailable, and it stays outside
the property suite — one worked example is the useful shape there.

The pre-Inspector serializer is pinned below as `pre_inspector_renderer_template`,
copied verbatim from the revision preceding this feature — that is the plan-diff
release, so `changeCategory` is part of the pinned reference and `inspectorValues`
is not. Comparing the current output against that pinned copy is what makes
"equal to the release preceding this feature" checkable inside the suite, the same
discipline `tests/test_plan_diff_legacy_parity.py` already uses.

Graphviz layout is faked out through the `graphviz.Digraph.render` mock the rest of
the suite uses for Property 15, so the artifact half of the property costs a
pipeline pass rather than a layout pass and the example count stays high. The
Draw.io check and Property 13 are the exceptions: they need the real layout, and
the Draw.io check needs the real `unflatten` too, for the reasons their own
sections document. Both are skipped per test rather than per module, so the
faked-layout properties still run on a machine that has no Graphviz binaries.
"""

import contextlib
import copy
import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterator, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource
from core.graph_generator import DOT_BINARY
from core.inspector import (
    INSPECTOR_INDEX_SUFFIX,
    INSPECTOR_RECORDS_SUFFIX,
    INTERACTION_LAYER_SUFFIX,
    InspectorCollector,
)
from core.plan_diff import CHANGE_CATEGORIES
from core.terraform_builder import TerraformTemplateBuilder
from strategies.plan_json import plan_documents
from test_inspector_render import CHANGE_SUMMARY_SUFFIX, run_generation
from test_plan_diff_graph_plumbing import VNET, plan_template, run_terraform_json_generation
from test_plan_diff_reporting import captured_logs

#: The Change_Category set the pre-existing `--changeTypes` filter accepts.
_CATEGORIES = list(CHANGE_CATEGORIES)

#: Files the generation harness writes as its inputs rather than as artifacts.
_HARNESS_INPUTS = re.compile(r"^(plan|template)-\d+\.json$")

#: The run folder and the artifacts inside it carry a per-run timestamp.
_TIMESTAMP = re.compile(r"\d{8}_\d{6}")


# ─── Pinned pre-Inspector serializer ──────────────────────────────────────────


def pre_inspector_renderer_resource(resource: LocalTemplateResource) -> Dict[str, Any]:
    """The `to_renderer_resource` body of the revision preceding this feature."""
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
    if resource.change_category is not None:
        emitted["changeCategory"] = resource.change_category
    return emitted


def pre_inspector_renderer_template(document: LocalTemplateDocument) -> Dict[str, Any]:
    """The `to_renderer_template` body of the revision preceding this feature."""
    template = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "resources": [pre_inspector_renderer_resource(resource) for resource in document.resources],
    }
    if document.metadata:
        template["metadata"] = document.metadata
    return template


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _explode(*_args: Any, **_kwargs: Any) -> None:
    """Stand-in for an Inspector helper the disabled path must never reach."""
    raise AssertionError("the Inspector-disabled path called an Inspector helper")


def _forbidden_inspector_helpers():
    """Patch context making every builder Inspector entry point fatal when called."""
    return (
        patch.object(TerraformTemplateBuilder, "_inspector_values_for", _explode),
        patch.object(TerraformTemplateBuilder, "_attach_inspector_values", _explode),
    )


def _artifact_paths(root: str) -> set:
    """The timestamp-normalized artifact path set a run left under `root`."""
    paths = set()
    for directory, _subdirectories, files in os.walk(root):
        for name in files:
            if directory == root and _HARNESS_INPUTS.match(name):
                continue
            relative = os.path.relpath(os.path.join(directory, name), root)
            paths.add(_TIMESTAMP.sub("T", relative.replace(os.sep, "/")))
    return paths


def _run_pipeline(template: Dict[str, Any], flags: Dict[str, Any], inspector: Optional[bool]):
    """One faked-layout generation pass; returns the artifact set and builder calls."""
    work_dir = tempfile.mkdtemp(prefix="cloudhorus_inspector_parity_")
    try:
        _source, _analyzer, calls = run_terraform_json_generation(
            [template],
            change_types=flags["change_types"],
            pe_optimization=flags["pe_optimization"],
            work_dir=work_dir,
            interactive_inspector=inspector,
        )
        return _artifact_paths(work_dir), calls
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ─── Property 15: Disabled mode leaves the pre-feature contract untouched ─────
# Feature: interactive-resource-inspector, Property 15: Disabled mode leaves the
# pre-feature contract untouched — for any Renderer_Template document and any
# combination of the existing generation flags, the template produced with
# `inspector_values` unset is key-for-key and value-for-value equal to the
# template the code path preceding this feature produces, the resource entries
# carry no `inspectorValues` key, and the artifact path set of a run with
# Inspector_Mode disabled equals the artifact path set of the pre-feature run for
# the same arguments.


@st.composite
def _parity_cases(draw) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A plan document plus one combination of the pre-existing generation flags.

    The document drives the Renderer_Template half. The generation half runs over
    the fixed `plan_template` fixture the plan-diff suite already uses, with its
    Change_Categories and the pre-existing flags drawn per example: a generated
    template can name resource groups the local-template mapping cannot resolve,
    which sends the pipeline down the live Azure path, and this property is about
    the artifacts a local run writes.
    """
    plan = draw(
        plan_documents(
            max_resources=3,
            with_resource_changes=draw(st.booleans()),
            with_configuration=draw(st.booleans()),
        )
    )
    flags = {
        "categories": draw(
            st.dictionaries(
                st.sampled_from(["planstorage", "pe-storage", VNET]),
                st.sampled_from(_CATEGORIES),
                max_size=3,
            )
        ),
        "change_types": draw(
            st.one_of(st.none(), st.lists(st.sampled_from(_CATEGORIES), min_size=1, max_size=3, unique=True))
        ),
        "pe_optimization": draw(st.booleans()),
    }
    return plan, flags


@settings(
    max_examples=int(os.environ.get("CH_PARITY_EXAMPLES", "100")),
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(case=_parity_cases())
def test_property_15_disabled_mode_leaves_the_pre_feature_contract_untouched(case) -> None:
    """Property 15: Disabled mode leaves the pre-feature contract untouched.

    The Renderer_Template half is asserted against the pinned pre-Inspector
    serializer for the pre-feature call shape and for an explicit `False`, with
    every builder Inspector entry point patched to raise so reaching one is a
    failure rather than a silent no-op. The artifact half compares the path set of
    a run made with the pre-feature argument list against the path set of a run
    made with `interactive_inspector=False`.

    **Validates: Requirements 1.3, 1.4, 1.5**
    """
    plan, flags = case
    change_types = flags["change_types"]

    values_patch, attach_patch = _forbidden_inspector_helpers()
    with values_patch, attach_patch:
        # The pre-feature call shape: no keyword at all.
        pre_feature = TerraformTemplateBuilder()._build_plan_document(plan, change_types)
        # The same run with the keyword supplied explicitly off.
        disabled = TerraformTemplateBuilder()._build_plan_document(plan, change_types, False)

        pre_feature_template = pre_feature.to_renderer_template()
        disabled_template = disabled.to_renderer_template()

    # Key for key and value for value against the pinned pre-Inspector serializer.
    for document, template in ((pre_feature, pre_feature_template), (disabled, disabled_template)):
        expected = pre_inspector_renderer_template(document)
        assert template == expected
        assert list(template) == list(expected)
        for produced, reference in zip(template["resources"], expected["resources"]):
            assert list(produced) == list(reference)

    # The two call shapes are the same code path, down to the serialized bytes.
    assert json.dumps(disabled_template, sort_keys=True) == json.dumps(
        pre_feature_template, sort_keys=True
    )

    # No `inspectorValues` key anywhere in the document or in the template.
    assert all(resource.inspector_values is None for resource in disabled.resources)
    assert "inspectorValues" not in json.dumps(disabled_template)
    resources: List[Dict[str, Any]] = disabled_template["resources"]
    assert all("inspectorValues" not in resource for resource in resources)

    # The artifact path set of a disabled run equals the pre-feature run's set.
    pipeline_template = plan_template(flags["categories"])
    pre_feature_artifacts, pre_feature_calls = _run_pipeline(pipeline_template, flags, None)
    disabled_artifacts, disabled_calls = _run_pipeline(pipeline_template, flags, False)

    assert disabled_artifacts == pre_feature_artifacts
    # Nothing the Inspector writes is in that set, and the PNG still is.
    assert not any(
        path.endswith((".svg", ".inspector.jsonl", ".inspector-index.json"))
        for path in disabled_artifacts
    )
    assert any(path.endswith(".png") for path in disabled_artifacts)
    # The builder is called with the pre-feature argument list on both runs.
    for calls in (pre_feature_calls, disabled_calls):
        assert calls
        assert all("collect_inspector_values" not in call["kwargs"] for call in calls)


# ─── Property 16: Inspector failures never cost the diagram ───────────────────
# Feature: interactive-resource-inspector, Property 16: Inspector failures never
# cost the diagram — for any step of the Inspector pipeline — collector
# construction, record building, the dual-format `dot` invocation, icon embedding,
# payload writing — made to raise, the run logs a warning, omits the affected
# Inspector artifact, writes the PNG artifact at the unchanged output path, and
# returns that path.
#
# Needs no `dot`: the layout is faked out through the same `run_generation` harness
# task 7.3 uses, whose `subprocess.run` stand-in writes the files the argument
# vector names. The four injection sites are the four places the implementation
# guards, and each one is patched to raise a marker exception whose text the
# warning assertion looks for, so "a warning was logged" is a statement about *this*
# failure rather than about any warning the run happens to emit.


class _InjectedFailure(RuntimeError):
    """The exception the injected Inspector step raises."""


#: The Inspector pipeline steps the property injects a failure into, mapped to the
#: Inspector artifact a failure there is allowed to cost the run.
_FAILURE_SITES: Dict[str, str] = {
    "build_payload": "payload",
    "write_inspector_payload": "payload",
    "embed_svg_icons": "layer",
    "dot_invocation": "layer",
}


@contextlib.contextmanager
def _injected_inspector_failure(site: str, marker: str) -> Iterator[Dict[str, Any]]:
    """Patch one Inspector step to raise; yield the `run_generation` keywords to use.

    `build_payload` and `embed_svg_icons` are patched where the implementation looks
    them up. The payload write and the dual-format invocation are injected through
    the harness's own seams, so the patch the harness installs stays in place.

    The `dot` stand-in raises only for the layout invocation and returns a success
    for everything else, so the platform auto-open command a finished run issues is
    not collateral damage of this injection.
    """

    def explode(*_args: Any, **_kwargs: Any) -> None:
        raise _InjectedFailure(marker)

    if site == "build_payload":
        with patch.object(InspectorCollector, "build_payload", explode):
            yield {}
    elif site == "write_inspector_payload":
        yield {"payload_writer": explode}
    elif site == "embed_svg_icons":
        # `write_svg_with_embedded_icons` resolves this name in `core.inspector`,
        # turning the raise into the discarded layer the render branch falls back on.
        with patch("core.inspector.embed_svg_icons", explode):
            yield {}
    elif site == "dot_invocation":

        def run(argv, *_args: Any, **_kwargs: Any):
            first = os.path.basename(str(argv[0])) if isinstance(argv, (list, tuple)) and argv else ""
            if first == DOT_BINARY:
                raise _InjectedFailure(marker)
            return MagicMock(returncode=0, args=argv)

        yield {"dot_run": run}
    else:  # pragma: no cover - a site added to the table without a patch
        raise AssertionError(f"no failure injection defined for {site!r}")


@settings(
    max_examples=int(os.environ.get("CH_INSPECTOR_FAILURE_EXAMPLES", "100")),
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(
    site=st.sampled_from(sorted(_FAILURE_SITES)),
    categories=st.dictionaries(
        st.sampled_from(["planstorage", "pe-storage", VNET]),
        st.sampled_from(_CATEGORIES),
        max_size=3,
    ),
    with_metadata=st.booleans(),
)
def test_property_16_inspector_failures_never_cost_the_diagram(site, categories, with_metadata) -> None:
    """Property 16: Inspector failures never cost the diagram.

    One Inspector_Mode run per example with `site` patched to raise. The run must
    return the PNG path under the run folder, that PNG must exist, the injected
    failure must appear in a warning, and the Change_Summary sidecar must still be
    there — the run completed. Only the artifact the failed step produces is
    missing: a payload failure leaves the Interaction_Layer alone, and a layer
    failure leaves the payload write to happen.

    **Validates: Requirements 1.9, 3.8**
    """
    marker = f"injected Inspector failure at {site}"
    work_dir = tempfile.mkdtemp(prefix="cloudhorus_inspector_failure_")
    try:
        with _injected_inspector_failure(site, marker) as run_kwargs, captured_logs() as logs:
            result = run_generation(
                plan_template(categories, with_metadata=with_metadata),
                work_dir=work_dir,
                interactive_inspector=True,
                **run_kwargs,
            )

        png_path = result["png_path"]
        stem = os.path.basename(png_path)[: -len(".png")]

        # The PNG is at the unchanged output path, and it is really on disk.
        assert png_path == os.path.abspath(os.path.join(result["output_dir"], f"{stem}.png"))
        assert os.path.exists(png_path)
        assert f"{stem}.png" in result["files"]

        # The failure was logged at warning level, and it is this failure.
        assert any(marker in message for message in logs.messages(logging.WARNING))

        # The run completed: the DOT source is there, and so is the Change_Summary
        # sidecar for the inputs that produce one (a template carrying
        # Change_Categories and the counts metadata, which is the condition
        # `plan_template` itself applies).
        assert stem in result["files"]
        if categories and with_metadata:
            assert f"{stem}{CHANGE_SUMMARY_SUFFIX}" in result["files"]

        layer_written = f"{stem}{INTERACTION_LAYER_SUFFIX}" in result["files"]
        if _FAILURE_SITES[site] == "layer":
            # The affected artifact is omitted, and the disabled-mode render call is
            # what produced the PNG instead.
            assert not layer_written
            assert result["renders"] == [
                (os.path.join(os.path.basename(result["output_dir"]), stem), "png")
            ]
        else:
            # A payload failure costs the payload only.
            assert layer_written
            # `build_payload` raising means the writer is never reached; the writer
            # raising means it was reached exactly once and wrote nothing.
            assert len(result["payloads"]) == (0 if site == "build_payload" else 1)

        # Whichever step failed, no Inspector payload file was left behind, and the
        # run raised nothing into the caller.
        for suffix in (INSPECTOR_RECORDS_SUFFIX, INSPECTOR_INDEX_SUFFIX):
            assert f"{stem}{suffix}" not in result["files"]
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ─── Task 14.2: the Draw.io export is unchanged by Inspector_Mode ─────────────
#
# Requirement 1.8: a run that exports Draw.io writes the same Draw.io file with
# Inspector_Mode on as it does with Inspector_Mode off. Two runs over the same
# input are compared, both exporting, one with the Inspector on.
#
# Why this needs the real binaries, and how far the byte compare reaches
# ----------------------------------------------------------------------
# The `.dot` file the export feeds to the converter is `dot.source` *after*
# `unflatten`, which pretty-prints one attribute per line. The rest of the suite
# stubs `Digraph.unflatten` and `subprocess.run`, so a comparison made through
# that harness says nothing about production — the same blind spot let the
# icon-and-decoration repair in `fix_drawio_hierarchy` silently do nothing on real
# exports twice already (see the DOT-form tests in
# `tests/test_plan_diff_drawio_export.py`). Both runs here therefore use the real
# `dot` layout, the real `unflatten` and the real converter; the only stubs are the
# Azure-facing lookups the local-template path cannot make and the platform
# auto-open command at the end of a run.
#
# `graphviz2drawio.convert` is not reproducible, for two separate reasons, and only
# one of them has been removed.
#
# The one that is gone was the layout. The converter re-laid the graph out through
# pygraphviz, and that path is unstable: the same `.dot` text put one subnet
# container at x=2276, 1828, 2047 and 2495 across four calls, and the containers
# swapped sides. `apply_authoritative_geometry` now reads the layout from
# `dot -Tdot` and writes it onto the cells after conversion, so every box is a
# function of the DOT alone — and the DOT is byte-identical with Inspector_Mode on
# and off. Geometry is therefore comparable exactly, and is compared exactly.
#
# The one that remains is the serialisation. The converter still numbers the
# `clustN` and `nodeN` cells in an order that varies between conversions of one
# unchanged file, and the attribute escaping varies with it: two exports of the same
# input first diverge at byte 490, an `&` against a `"`, with byte-identical DOT on
# both sides. A whole-file byte compare therefore still measures the converter
# rather than CloudHorus, and would fail for reasons Inspector_Mode has nothing to
# do with. (One pair of runs did come out byte-identical while this was being
# investigated, which is what the numbering order makes possible, and is exactly why
# a single measurement is not evidence of stability here.)
#
# So the criterion is discharged on every axis that is decidable:
#
# * the converter *input* — the `.dot` bytes the run writes — is byte-identical,
#   and is the unflattened form production feeds;
# * every cell's *geometry* is identical, keyed by label rather than by the
#   unstable cell id;
# * the export *structure* — the cell inventory, and per resource the shape, the
#   embedded icon, the full style and the container it sits in — is identical;
# * no value the plan marks sensitive appears in either export.
#
# The Inspector artifacts of the enabled run are asserted to exist, so the parity
# above is parity against a run that really took the Inspector branch.

#: Commands a finished run may issue to open the PNG in a desktop viewer. Blocked
#: rather than executed, so the benchmark of this test is the pipeline and not a
#: window manager.
_AUTO_OPEN_COMMANDS = frozenset(
    {"wslpath", "powershell.exe", "pwsh.exe", "cmd.exe", "explorer.exe", "xdg-open", "open", "start"}
)

_DOT_AVAILABLE = shutil.which(DOT_BINARY) is not None
_UNFLATTEN_AVAILABLE = shutil.which("unflatten") is not None


def _converter_available() -> bool:
    """Whether the Draw.io converter and its Graphviz binding are importable."""
    try:
        import graphviz2drawio  # noqa: F401
        import pygraphviz  # noqa: F401
    except Exception:  # noqa: BLE001 - an unimportable converter is a skip, not a failure
        return False
    return True


requires_real_export = pytest.mark.skipif(
    not (_DOT_AVAILABLE and _UNFLATTEN_AVAILABLE and _converter_available()),
    reason="the Draw.io export parity check needs the real dot and unflatten binaries plus graphviz2drawio",
)

#: A node statement as `unflatten` writes it: the attribute list spread over lines.
#: Used to prove the exported DOT is the production form rather than the stubbed
#: single-line form.
_PRETTY_PRINTED_NODE = re.compile(r'^[ \t]*"[^"\n]+"[ \t]*\[[^\]\n]*,[ \t]*\n[ \t]*[A-Za-z_]+=', re.MULTILINE)


class _Export:
    """One real generation run that exported Draw.io, plus the artifacts it wrote."""

    def __init__(self, work_dir: str) -> None:
        self.work_dir = work_dir
        folders = sorted(
            name for name in os.listdir(work_dir) if name.startswith("azure_resources_")
        )
        assert folders, f"no run folder under {work_dir}"
        self.stem = folders[-1]
        self.folder = os.path.join(work_dir, self.stem)

    def path(self, suffix: str) -> str:
        return os.path.join(self.folder, f"{self.stem}{suffix}")

    def exists(self, suffix: str) -> bool:
        return os.path.exists(self.path(suffix))

    def read_bytes(self, suffix: str) -> bytes:
        with open(self.path(suffix), "rb") as handle:
            return handle.read()

    def read_text(self, suffix: str) -> str:
        return self.read_bytes(suffix).decode("utf-8")

    @property
    def files(self) -> List[str]:
        return sorted(os.listdir(self.folder))

    @property
    def cells(self) -> Dict[str, Dict[str, str]]:
        root = ET.fromstring(self.read_text(".drawio"))
        assert root.tag == "mxGraphModel"
        return {cell.get("id", ""): dict(cell.attrib) for cell in root.iter("mxCell")}


def _blocking_subprocess_run():
    """A `subprocess.run` wrapper that runs everything except the auto-open commands."""
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        first = ""
        if isinstance(command, (list, tuple)) and command:
            first = os.path.basename(str(command[0]))
        elif isinstance(command, str):
            first = os.path.basename(command.split(" ")[0])
        if first in _AUTO_OPEN_COMMANDS:
            return MagicMock(returncode=0, stdout="", stderr="")
        return real_run(command, *args, **kwargs)

    return run


def _real_export_run(plan: Dict[str, Any], work_dir: str, interactive_inspector: bool) -> _Export:
    """Run one real generation over `plan` with `--exportDrawio` and return its artifacts.

    Real Graphviz layout, real `unflatten`, real Draw.io converter. Only the three
    Azure-facing lookups the local-template path cannot serve and the auto-open
    command are replaced.
    """
    from test_plan_diff_integration import RG, SUB, TENANT

    os.makedirs(work_dir, exist_ok=True)
    plan_path = os.path.join(work_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump(plan, handle)

    with (
        patch("core.graph_generator.get_private_dns_zones_without_vnets", return_value=[]),
        patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", return_value=[]),
        patch("core.graph_generator.get_bastion_host_name", return_value=None),
        patch("subprocess.run", _blocking_subprocess_run()),
    ):
        from core.graph_generator import generate_resource_graph

        previous_dir = os.getcwd()
        os.chdir(work_dir)
        try:
            generate_resource_graph(
                tenants=[TENANT],
                subscriptions=[SUB],
                resource_groups=[RG],
                subnet_optimization=[False],
                direction="TB",
                tenant_minlen="LR",
                max_subnet_in_line=4,
                rankDebug="invis",
                peOptimization=[False],
                privateDnsZonesOptimization=False,
                resourcesEdgeLength=1,
                resourceGroupsEdgeLengthListBySubscription=[4],
                crossPeOptimization=[False],
                discoverResourceGroups=None,
                exportDrawio=True,
                use_local_template=True,
                local_template_mode="terraform-json",
                terraform_json_files=[plan_path],
                interactive_inspector=interactive_inspector,
            )
        finally:
            os.chdir(previous_dir)

    return _Export(work_dir)


@pytest.fixture(scope="module")
def drawio_parity():
    """The same input exported twice: once with Inspector_Mode off, once with it on."""
    from test_plan_diff_drawio_export import drawio_plan

    plan, generated_markers = drawio_plan()
    assert generated_markers, "the fixture must hide at least one sensitive value"

    root = tempfile.mkdtemp(prefix="cloudhorus_inspector_drawio_")
    try:
        disabled = _real_export_run(plan, os.path.join(root, "off"), interactive_inspector=False)
        enabled = _real_export_run(plan, os.path.join(root, "on"), interactive_inspector=True)
        yield disabled, enabled, generated_markers
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _plain_text(cell: Dict[str, str]) -> str:
    """Return the visible text of a cell value, markup removed."""
    return re.sub(r"<[^>]*>", "", html.unescape(cell.get("value", ""))).strip()


def _style(cell: Dict[str, str]) -> Dict[str, str]:
    """Return the cell style as a key/value mapping."""
    style: Dict[str, str] = {}
    for part in cell.get("style", "").split(";"):
        if not part:
            continue
        key, _, value = part.partition("=")
        style[key] = value
    return style


def _resource_cell(cells: Dict[str, Dict[str, str]], name: str) -> Dict[str, str]:
    """Return the single node cell whose label names `name`."""
    matches = [
        cell for cell_id, cell in cells.items() if cell_id.startswith("node") and name in _plain_text(cell)
    ]
    assert len(matches) == 1, f"expected one Draw.io node for {name!r}, found {len(matches)}"
    return matches[0]


def _container_label(cells: Dict[str, Dict[str, str]], cell: Dict[str, str]) -> str:
    """Return the visible label of the container a cell sits in.

    The parent *id* is not comparable across two conversions: the converter numbers
    the `clustN` cells in an order that varies between runs of the same input. The
    parent's label text is stable and is what "sits in the same container" means.
    """
    parent = cells.get(cell.get("parent", ""), {})
    return _plain_text(parent)


def _cell_kinds(cells: Dict[str, Dict[str, str]]) -> Dict[str, int]:
    """Count the cells of the export by id prefix."""
    counts: Dict[str, int] = {}
    for cell_id in cells:
        prefix = re.sub(r"\d+$", "", cell_id) or "root"
        counts[prefix] = counts.get(prefix, 0) + 1
    return counts


@requires_real_export
def test_inspector_mode_leaves_the_draw_io_converter_input_byte_identical(drawio_parity) -> None:
    """Requirement 1.8: the export reads the same DOT with Inspector_Mode on and off.

    The `.dot` file is what CloudHorus hands the converter, and it is written from
    `dot.source` after the real `unflatten`. Byte equality here is the strongest
    statement available about the export input, and the pretty-printed shape
    assertion is what proves the comparison is about the production form rather
    than the single-line form the stubbed harness produces.
    """
    disabled, enabled, _markers = drawio_parity

    disabled_dot = disabled.read_bytes(".dot")
    enabled_dot = enabled.read_bytes(".dot")

    assert disabled_dot == enabled_dot, "Inspector_Mode changed the DOT the Draw.io export reads"
    assert _PRETTY_PRINTED_NODE.search(enabled_dot.decode("utf-8")), (
        "the exported DOT is not the unflattened form, so this comparison would not "
        "speak about production"
    )

    # The enabled run really took the Inspector branch, so the parity above is not
    # parity between two disabled runs.
    assert enabled.exists(INTERACTION_LAYER_SUFFIX)
    assert enabled.exists(INSPECTOR_RECORDS_SUFFIX)
    assert enabled.exists(INSPECTOR_INDEX_SUFFIX)
    for suffix in (INTERACTION_LAYER_SUFFIX, INSPECTOR_RECORDS_SUFFIX, INSPECTOR_INDEX_SUFFIX):
        assert not disabled.exists(suffix)

    # And both runs wrote the pre-feature export artifacts under the same names.
    def suffixes(export: _Export) -> set:
        return {name.replace(export.stem, "") for name in export.files}

    assert {".dot", ".drawio", ".png"} <= suffixes(disabled)
    assert suffixes(enabled) - suffixes(disabled) == {
        INTERACTION_LAYER_SUFFIX,
        INSPECTOR_RECORDS_SUFFIX,
        INSPECTOR_INDEX_SUFFIX,
    }
    assert suffixes(disabled) - suffixes(enabled) == set()


@requires_real_export
def test_the_draw_io_geometry_is_identical_with_inspector_mode_on_and_off(drawio_parity) -> None:
    """Requirement 1.8 on the axis that is now decidable: every cell box is equal.

    Geometry used to be the part of the export that moved for reasons unrelated to
    Inspector_Mode, because the converter re-laid the graph out through pygraphviz
    and that path is not reproducible. `apply_authoritative_geometry` now writes the
    `dot -Tdot` layout onto the cells, so the boxes are a function of the DOT alone
    — and the DOT is byte-identical either way, which the test above asserts.

    Cells are compared by their own id, and the geometry is keyed by the cell's
    label rather than by that id, because the converter still numbers the `clustN`
    and `nodeN` cells in an order that varies between conversions of one unchanged
    file. That remaining instability is what keeps a whole-file byte compare out of
    reach; see the module comment.
    """
    disabled, enabled, _markers = drawio_parity

    def boxes(export: _Export) -> Dict[str, Tuple[str, str, str, str]]:
        root = ET.fromstring(export.read_text(".drawio"))
        found: Dict[str, Tuple[str, str, str, str]] = {}
        for cell in root.iter("mxCell"):
            geometry = cell.find("mxGeometry")
            if geometry is None:
                continue
            label = re.sub(r"<[^>]*>", " ", cell.get("value") or "").strip()
            if not label:
                continue
            found[" ".join(label.split())] = (
                geometry.get("x", ""),
                geometry.get("y", ""),
                geometry.get("width", ""),
                geometry.get("height", ""),
            )
        return found

    disabled_boxes = boxes(disabled)
    enabled_boxes = boxes(enabled)

    # Control: real cells are being compared, and the boxes carry real coordinates.
    assert len(disabled_boxes) >= 5, f"only {len(disabled_boxes)} labelled cells found"
    assert any(box[2] and box[3] for box in disabled_boxes.values())

    assert set(enabled_boxes) == set(disabled_boxes)
    for label, box in sorted(disabled_boxes.items()):
        assert enabled_boxes[label] == box, f"Inspector_Mode moved or resized {label!r}"


@requires_real_export
def test_inspector_mode_leaves_the_draw_io_shapes_icons_and_containers_unchanged(drawio_parity) -> None:
    """Requirement 1.8: the exported diagram carries the same cells either way.

    The comparison is the one `tests/test_plan_diff_drawio_export.py` makes for
    Requirement 8.6 of the plan-diff feature, applied to the Inspector toggle: the
    cell inventory, and per resource the shape family, the embedded icon, the whole
    style string and the container it sits in. Nothing is allowed to differ here —
    unlike the plan-diff comparison, which permits the decoration keys, the
    Inspector adds no decoration at all.
    """
    from test_plan_diff_drawio_export import EXPECTED_DECORATION

    disabled, enabled, _markers = drawio_parity
    disabled_cells = disabled.cells
    enabled_cells = enabled.cells

    assert _cell_kinds(enabled_cells) == _cell_kinds(disabled_cells)

    for name in EXPECTED_DECORATION:
        disabled_cell = _resource_cell(disabled_cells, name)
        enabled_cell = _resource_cell(enabled_cells, name)

        assert _style(enabled_cell) == _style(disabled_cell), f"{name} changed style"
        assert _style(enabled_cell).get("shape") == _style(disabled_cell).get("shape"), f"{name} changed shape"
        assert _style(enabled_cell).get("image") == _style(disabled_cell).get("image"), f"{name} changed icon"
        assert _plain_text(enabled_cell) == _plain_text(disabled_cell), f"{name} changed label"
        assert _container_label(enabled_cells, enabled_cell) == _container_label(
            disabled_cells, disabled_cell
        ), f"{name} changed container"

    def container_labels(cells: Dict[str, Dict[str, str]]) -> List[str]:
        return sorted(
            _plain_text(cell)
            for cell_id, cell in cells.items()
            if cell_id.startswith("clust") and _plain_text(cell)
        )

    assert container_labels(enabled_cells) == container_labels(disabled_cells)


@requires_real_export
def test_inspector_mode_adds_no_sensitive_value_to_the_export(drawio_parity) -> None:
    """No value the plan marks sensitive reaches either export, or the added artifacts.

    The fixture hides a unique `zzsensitiveleaf<n>` token in every leaf it flags as
    sensitive, so one substring search decides the question. The tokens searched for
    are the ones the plan on disk actually holds, which is what makes this an
    assertion about redaction rather than about values that never travel: the
    fixture shares one values dict between a change's before and after phase, so
    some of the tokens it generates are overwritten before the plan is written.
    """
    disabled, enabled, generated = drawio_parity

    # Control: search for the tokens the run really reads, and nothing else.
    with open(os.path.join(enabled.work_dir, "plan.json"), "r", encoding="utf-8") as handle:
        plan_text = handle.read()
    markers = [marker for marker in generated if marker in plan_text]
    assert markers, "the fixture must hide at least one value the run reads"

    surfaces = {
        "disabled .drawio": disabled.read_text(".drawio"),
        "disabled .dot": disabled.read_text(".dot"),
        "enabled .drawio": enabled.read_text(".drawio"),
        "enabled .dot": enabled.read_text(".dot"),
        "Interaction_Layer": enabled.read_text(INTERACTION_LAYER_SUFFIX),
        "Inspector_Payload": enabled.read_text(INSPECTOR_RECORDS_SUFFIX),
        "Inspector_Index": enabled.read_text(INSPECTOR_INDEX_SUFFIX),
    }

    for label, text in surfaces.items():
        leaked = [marker for marker in markers if marker in text]
        assert leaked == [], f"sensitive value in the {label}: {leaked[:3]}"


# ─── Property 13: Headless output parity ──────────────────────────────────────
# Feature: interactive-resource-inspector, Property 13: Headless output parity —
# for any resource set, a run with Inspector_Mode enabled produces Graphviz DOT
# source byte-identical to the DOT source of the same run with Inspector_Mode
# disabled, and a PNG artifact byte-identical to that run's PNG at the same output
# path; the Change_Summary sidecar bytes are identical across the two runs as well.
#
# Why this one needs the real binary
# ----------------------------------
# The claim is about bytes the layout engine produces, so faking the layout out
# would assert nothing: the `patch("graphviz.Digraph.render", mock_render)`
# convention the rest of the suite follows writes an empty PNG, and two empty
# files are equal for reasons Graphviz has nothing to do with. Both runs here
# therefore drive the real `dot`; the only stubs are the three Azure-facing lookups
# the local-template path cannot make and the platform auto-open command a finished
# run issues. The skip is per test through `requires_real_dot` rather than
# module-wide, so the faked-layout properties above keep running where `dot` is
# absent.
#
# `max_examples` is 5 with `deadline=None`, as the design's testing strategy
# prescribes: each example pays for two real layout passes, and the cheap parity
# claims stay at full strength in Property 15.
#
# The evidence this rests on is the design spike: on `dot` 2.43 the dual-format
# invocation's PNG carries the same md5 as the Graphviz library render of the same
# source. That measurement is what makes the assertion expected to hold; this test
# is what keeps it holding.

requires_real_dot = pytest.mark.skipif(
    not _DOT_AVAILABLE, reason="headless output parity compares bytes the real dot binary produces"
)

#: The leaf resources of the plan-diff integration fixture the generator may drop,
#: so the property runs over a varying resource set rather than one fixed diagram.
#: The VNet and the subnet are never dropped: they are the container hierarchy the
#: remaining resources are placed into.
_PARITY_LEAVES: Tuple[str, ...] = (
    "azurerm_storage_account.new",
    "azurerm_linux_web_app.api",
    "azurerm_storage_account.legacy",
    "azurerm_private_endpoint.legacy",
)


@st.composite
def _headless_parity_runs(draw) -> Dict[str, Any]:
    """A plan plus the generation flags to run it twice with.

    The plan is the plan-diff integration fixture — every Change_Category around a
    VNet/subnet hierarchy, including two deletes that exist only in
    `resource_changes` — with a drawn subset of its leaves removed. Keeping the
    fixture as the base is deliberate: a freely generated plan can name resource
    groups the local-template mapping cannot resolve, which sends the pipeline down
    the live Azure path, and this property is about the bytes a local run writes.

    `change_types` always retains `update`, the VNet's category, so the filter
    never empties the diagram and the comparison stays about a real drawing.
    """
    from test_plan_diff_integration import plan_file

    plan = copy.deepcopy(plan_file())
    dropped = draw(st.sets(st.sampled_from(_PARITY_LEAVES), max_size=len(_PARITY_LEAVES) - 1))

    plan["planned_values"]["root_module"]["resources"] = [
        entry
        for entry in plan["planned_values"]["root_module"]["resources"]
        if entry["address"] not in dropped
    ]
    plan["resource_changes"] = [
        entry for entry in plan["resource_changes"] if entry["address"] not in dropped
    ]

    change_types = draw(
        st.one_of(
            st.none(),
            st.lists(st.sampled_from(_CATEGORIES), min_size=1, max_size=3, unique=True).map(
                lambda drawn: sorted(set(drawn) | {"update"})
            ),
        )
    )
    return {
        "plan": plan,
        "change_types": change_types,
        "direction": draw(st.sampled_from(["TB", "LR"])),
        "pe_optimization": draw(st.booleans()),
    }


def _counting_subprocess_run(invocations: List[List[str]]):
    """A `subprocess.run` spy that records every argument vector and calls through.

    The auto-open command a finished run issues is answered with a stand-in rather
    than executed, so the test does not open a desktop viewer, and it is recorded
    like everything else so the assertion about the layout invocations is made over
    the whole call log rather than over a pre-filtered one.
    """
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        argv = [str(part) for part in command] if isinstance(command, (list, tuple)) else [str(command)]
        invocations.append(argv)
        first = os.path.basename(argv[0].split(" ")[0]) if argv else ""
        if first in _AUTO_OPEN_COMMANDS:
            return MagicMock(returncode=0, stdout="", stderr="")
        return real_run(command, *args, **kwargs)

    return run


def _dual_format_invocations(invocations: List[List[str]]) -> List[List[str]]:
    """The recorded invocations that ask one layout pass for both formats."""
    return [argv for argv in invocations if "-Tpng" in argv and "-Tsvg" in argv]


def _real_headless_run(case: Dict[str, Any], work_dir: str, interactive_inspector: bool):
    """Run one real headless generation and return its artifacts plus the call log.

    Real Graphviz layout, no Draw.io export — this property is about the PNG, the
    DOT source and the Change_Summary sidecar, and the export has its own parity
    check further up the module.
    """
    from test_plan_diff_integration import RG, SUB, TENANT

    os.makedirs(work_dir, exist_ok=True)
    plan_path = os.path.join(work_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump(case["plan"], handle)

    invocations: List[List[str]] = []
    with (
        patch("core.graph_generator.get_private_dns_zones_without_vnets", return_value=[]),
        patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", return_value=[]),
        patch("core.graph_generator.get_bastion_host_name", return_value=None),
        patch("subprocess.run", _counting_subprocess_run(invocations)),
    ):
        from core.graph_generator import generate_resource_graph

        previous_dir = os.getcwd()
        os.chdir(work_dir)
        try:
            generate_resource_graph(
                tenants=[TENANT],
                subscriptions=[SUB],
                resource_groups=[RG],
                subnet_optimization=[False],
                direction=case["direction"],
                tenant_minlen="LR",
                max_subnet_in_line=4,
                rankDebug="invis",
                peOptimization=[case["pe_optimization"]],
                privateDnsZonesOptimization=False,
                resourcesEdgeLength=1,
                resourceGroupsEdgeLengthListBySubscription=[4],
                crossPeOptimization=[False],
                discoverResourceGroups=None,
                exportDrawio=False,
                use_local_template=True,
                local_template_mode="terraform-json",
                terraform_json_files=[plan_path],
                change_types=case["change_types"],
                interactive_inspector=interactive_inspector,
            )
        finally:
            os.chdir(previous_dir)

    return _Export(work_dir), invocations


@requires_real_dot
@settings(
    max_examples=int(os.environ.get("CH_PARITY_PNG_EXAMPLES", "5")),
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(case=_headless_parity_runs())
def test_property_13_headless_output_parity(case) -> None:
    """Property 13: Headless output parity.

    The same input is generated twice into two temp folders, once with
    Inspector_Mode off and once with it on, both through the real layout engine.
    Three byte comparisons follow: the PNG through `hashlib.md5`, the Graphviz DOT
    source, and the Change_Summary sidecar. The enabled run must additionally have
    produced the Interaction_Layer, the Inspector records and the index — so the
    parity is parity against a run that really took the Inspector branch — and its
    call log must hold exactly one invocation carrying both `-Tpng` and `-Tsvg`,
    which is the one-layout-pass claim of Requirement 3.1. The disabled run must
    hold none: it goes through `dot.render`, which asks for the PNG alone.

    The DOT source compared is the extension-less file both branches write —
    `dot.render` writes it before rendering, `dot.save` writes it in the enabled
    branch — so the comparison covers the input the layout engine reads, not only
    the raster it emits.

    **Validates: Requirements 1.6, 1.11, 3.1, 14.13**
    """
    root = tempfile.mkdtemp(prefix="cloudhorus_inspector_png_parity_")
    try:
        disabled, disabled_calls = _real_headless_run(case, os.path.join(root, "off"), False)
        enabled, enabled_calls = _real_headless_run(case, os.path.join(root, "on"), True)

        # The enabled run took the Inspector branch, and the disabled run did not.
        for suffix in (INTERACTION_LAYER_SUFFIX, INSPECTOR_RECORDS_SUFFIX, INSPECTOR_INDEX_SUFFIX):
            assert enabled.exists(suffix), f"the enabled run wrote no {suffix}"
            assert not disabled.exists(suffix), f"the disabled run wrote a {suffix}"

        # Requirement 3.1: one layout pass produced both formats, and it happened once.
        dual = _dual_format_invocations(enabled_calls)
        assert len(dual) == 1, f"expected one dual-format layout pass, recorded {len(dual)}"
        assert os.path.basename(dual[0][0]) == DOT_BINARY
        assert _dual_format_invocations(disabled_calls) == []

        # Requirement 1.6: the PNG is at the same relative path and byte-identical.
        assert disabled.exists(".png") and enabled.exists(".png")
        disabled_png = disabled.read_bytes(".png")
        enabled_png = enabled.read_bytes(".png")
        assert hashlib.md5(enabled_png).hexdigest() == hashlib.md5(disabled_png).hexdigest(), (
            "Inspector_Mode changed the PNG bytes"
        )
        assert enabled_png == disabled_png
        # Control: a real raster on both sides, so the equality above is not the
        # equality of two empty files a faked layout would have produced.
        assert disabled_png.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(disabled_png) > 1024

        # The DOT source the engine read is the same source either way.
        disabled_source = disabled.read_bytes("")
        assert enabled.read_bytes("") == disabled_source, "Inspector_Mode changed the DOT source"
        assert b"digraph" in disabled_source and b"subgraph" in disabled_source

        # Requirement 1.11: the Change_Summary sidecar is untouched by this feature.
        assert disabled.exists(CHANGE_SUMMARY_SUFFIX), "the fixture must produce a Change_Summary sidecar"
        assert enabled.read_bytes(CHANGE_SUMMARY_SUFFIX) == disabled.read_bytes(CHANGE_SUMMARY_SUFFIX)

        # The enabled run adds artifacts and removes none.
        def suffixes(export: _Export) -> set:
            return {name.replace(export.stem, "") for name in export.files}

        assert suffixes(enabled) - suffixes(disabled) == {
            INTERACTION_LAYER_SUFFIX,
            INSPECTOR_RECORDS_SUFFIX,
            INSPECTOR_INDEX_SUFFIX,
        }
        assert suffixes(disabled) - suffixes(enabled) == set()
    finally:
        shutil.rmtree(root, ignore_errors=True)
