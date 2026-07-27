"""The Inspector render branch and the Inspector_Payload write.

Tasks 7.3 and 7.4 of the interactive-resource-inspector spec:

* Inspector_Mode off keeps `dot.render(output_filename, format="png")` as the only
  render call, so the headless pipeline path is unchanged by construction;
* Inspector_Mode on saves the DOT source and drives one `dot` invocation carrying
  `-Kdot -Tpng -o <png> -Tsvg -o <svg> <source>` as a fixed argument vector with
  every path a separate element, then post-processes the SVG through
  `write_svg_with_embedded_icons`;
* every failure of that chain — no `dot` on `PATH`, a non-zero exit, a missing
  output, a discarded layer — is a warning followed by the disabled-mode render
  call, so the PNG is produced either way;
* the Inspector_Payload is written beside the Change_Summary sidecar, only in
  Inspector_Mode, wrapped so a failure is a warning and the run still returns the
  PNG path, and the sidecar's name and content are untouched.

Requirements covered: 1.3, 1.6, 1.9, 1.11, 1.12, 3.1, 3.6, 3.7, 3.8, 12.8.
"""

import json
import logging
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.graph_generator import (  # noqa: E402
    DOT_BINARY,
    DOT_LAYOUT_FLAG,
    render_with_interaction_layer,
)
from core.inspector import (  # noqa: E402
    INSPECTOR_INDEX_SUFFIX,
    INTERACTION_LAYER_SUFFIX,
    InspectorPayload,
)
from test_plan_diff_graph_plumbing import (  # noqa: E402
    RG,
    SUB,
    TENANT,
    plan_template,
)
from test_plan_diff_reporting import captured_logs  # noqa: E402

CHANGE_SUMMARY_SUFFIX = ".change-summary.json"

#: The shape Graphviz writes for an icon: an absolute href Requirement 3.7 forbids
#: from surviving into the shipped layer.
SVG_WITH_ICON = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
    '<g id="node1" class="node"><title>storage-rg</title>\n'
    '<image xlink:href="{icon}" width="108px" height="108px" '
    'preserveAspectRatio="xMinYMin meet" x="10" y="-20"/>\n'
    "</g>\n</svg>\n"
)

#: The same layer without an icon, which the rewrite returns untouched. Used where
#: the assertion is about the render branch rather than about icon embedding.
SVG_WITHOUT_ICON = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">\n'
    '<g id="node1" class="node"><title>storage-rg</title></g>\n'
    "</svg>\n"
)


class _FakeDot:
    """The minimum of the Graphviz surface the render branch touches."""

    def __init__(self, source: str = "digraph G { a }") -> None:
        self.source = source
        self.saved: List[Optional[str]] = []
        self.rendered: List[Any] = []

    def save(self, filename=None, *args, **kwargs):
        self.saved.append(filename)
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(self.source)
        return filename

    def render(self, filename=None, format=None, *args, **kwargs):
        self.rendered.append((filename, format, args, kwargs))
        with open(f"{filename}.{format}", "wb") as handle:
            handle.write(b"png-bytes")
        return f"{filename}.{format}"


def dot_stub(
    *,
    error: Optional[BaseException] = None,
    write_png: bool = True,
    write_svg: bool = True,
    svg_text: str = SVG_WITH_ICON.format(icon="/absolute/icons/Storage.png"),
):
    """A `subprocess.run` stand-in that emits the files its argument vector names.

    Returns `(run, calls)`. `calls` records every invocation, which is what makes
    "exactly one invocation carrying both formats" assertable without `dot`.
    """
    calls: List[Dict[str, Any]] = []

    def run(argv, *args, **kwargs):
        calls.append({"argv": argv, "args": args, "kwargs": kwargs})
        if error is not None:
            raise error
        targets = [argv[index + 1] for index, item in enumerate(argv) if item == "-o"]
        for target in targets:
            if target.endswith(".png") and write_png:
                with open(target, "wb") as handle:
                    handle.write(b"png-bytes")
            elif target.endswith(".svg") and write_svg:
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write(svg_text)
        return MagicMock(returncode=0, args=argv)

    return run, calls


# ─── 7.3 the dual-format invocation ──────────────────────────────────────────


def test_one_invocation_carries_both_formats(tmp_path):
    """Requirement 3.1: one layout pass produces the PNG and the Interaction_Layer."""
    output_filename = os.path.join(str(tmp_path), "azure_resources_x")
    dot = _FakeDot()
    run, calls = dot_stub()

    with (
        patch("subprocess.run", run),
        patch("core.graph_generator.write_svg_with_embedded_icons", side_effect=lambda path: path) as rewrite,
    ):
        layer = render_with_interaction_layer(dot, output_filename)

    png_path = f"{output_filename}.png"
    svg_path = f"{output_filename}{INTERACTION_LAYER_SUFFIX}"

    assert dot.saved == [output_filename]
    assert len(calls) == 1
    assert calls[0]["argv"] == [
        DOT_BINARY,
        DOT_LAYOUT_FLAG,
        "-Tpng",
        "-o",
        png_path,
        "-Tsvg",
        "-o",
        svg_path,
        output_filename,
    ]
    assert calls[0]["kwargs"]["check"] is True
    assert rewrite.call_args.args == (svg_path,)
    assert layer == svg_path
    assert os.path.exists(png_path) and os.path.exists(svg_path)
    # The disabled-mode call is not made on the success path: one layout pass only.
    assert dot.rendered == []


def test_the_argument_vector_is_a_list_and_never_a_shell_string(tmp_path):
    """A resource name that reaches a filename must not be able to inject a command."""
    output_filename = os.path.join(str(tmp_path), "azure_resources_$(touch pwned); rm -rf")
    dot = _FakeDot()
    run, calls = dot_stub()

    with (
        patch("subprocess.run", run),
        patch("core.graph_generator.write_svg_with_embedded_icons", side_effect=lambda path: path),
    ):
        render_with_interaction_layer(dot, output_filename)

    argv = calls[0]["argv"]
    assert isinstance(argv, list)
    assert all(isinstance(element, str) for element in argv)
    assert calls[0]["kwargs"].get("shell") in (None, False)
    # Every path travels as its own element, unquoted and unsplit.
    assert argv[-1] == output_filename
    assert f"{output_filename}.png" in argv
    assert not os.path.exists(os.path.join(str(tmp_path), "pwned"))


def test_the_layer_carries_no_absolute_icon_path(tmp_path):
    """Requirement 3.7: the real rewrite embeds the icon, absolute path and all."""
    output_filename = os.path.join(str(tmp_path), "azure_resources_x")
    icon_path = os.path.join(str(tmp_path), "Storage.png")
    with open(icon_path, "wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\nfake")

    run, _ = dot_stub(svg_text=SVG_WITH_ICON.format(icon=icon_path))
    with patch("subprocess.run", run):
        layer = render_with_interaction_layer(_FakeDot(), output_filename)

    assert layer == f"{output_filename}{INTERACTION_LAYER_SUFFIX}"
    text = open(layer, encoding="utf-8").read()
    assert icon_path not in text
    assert "data:image/png;base64," in text
    assert "<use" in text
    # Identity survives the rewrite: the Inspector_Key lookup reads these titles.
    assert "<title>storage-rg</title>" in text


@pytest.mark.parametrize(
    "stub_kwargs",
    [
        {"error": FileNotFoundError(2, "No such file or directory: 'dot'")},
        {"error": subprocess.CalledProcessError(1, ["dot"])},
        {"write_png": False},
        {"write_svg": False},
    ],
    ids=["no-dot-binary", "non-zero-exit", "no-png-produced", "no-svg-produced"],
)
def test_a_failed_invocation_falls_back_to_the_library_render(tmp_path, stub_kwargs):
    """Requirements 1.9, 3.8: the PNG is produced either way."""
    output_filename = os.path.join(str(tmp_path), "azure_resources_x")
    dot = _FakeDot()
    run, _ = dot_stub(**stub_kwargs)

    with patch("subprocess.run", run), captured_logs() as logs:
        layer = render_with_interaction_layer(dot, output_filename)

    assert layer is None
    assert dot.rendered == [(output_filename, "png", (), {})]
    assert os.path.exists(f"{output_filename}.png")
    assert not os.path.exists(f"{output_filename}{INTERACTION_LAYER_SUFFIX}")
    assert any("Interaction_Layer" in message for message in logs.messages(logging.WARNING))


def test_a_discarded_layer_falls_back_to_the_library_render(tmp_path):
    """An unreadable icon or malformed SVG costs the layer, never the diagram."""
    output_filename = os.path.join(str(tmp_path), "azure_resources_x")
    dot = _FakeDot()
    run, _ = dot_stub()

    with (
        patch("subprocess.run", run),
        patch("core.graph_generator.write_svg_with_embedded_icons", return_value=None),
        captured_logs() as logs,
    ):
        layer = render_with_interaction_layer(dot, output_filename)

    assert layer is None
    assert dot.rendered == [(output_filename, "png", (), {})]
    assert os.path.exists(f"{output_filename}.png")
    assert any("discarded" in message for message in logs.messages(logging.WARNING))


# ─── 7.3 / 7.4 through a generation run ──────────────────────────────────────


def run_generation(
    template: Dict[str, Any],
    work_dir: str,
    interactive_inspector: Optional[bool] = None,
    dot_run: Optional[Any] = None,
    payload_writer: Optional[Any] = None,
):
    """Run a terraform-json generation pass and return the run's observations.

    Layout is faked out — `graphviz.Digraph.render` writes an empty PNG and
    records the call — so the assertions are about which render path the branch
    takes and which artifacts the run writes, not about Graphviz itself.

    Returns a dict with the returned PNG path, the recorded `render` calls, the
    recorded `dot` invocations, the `write_inspector_payload` calls and the files
    the run's output folder holds.
    """
    os.makedirs(work_dir, exist_ok=True)
    plan_path = os.path.join(work_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump({"format_version": "1.0"}, handle)
    built_path = os.path.join(work_dir, "template.json")
    with open(built_path, "w", encoding="utf-8") as handle:
        json.dump(template, handle)

    renders: List[Any] = []

    def mock_render(self, filename=None, format=None, *args, **kwargs):
        renders.append((filename, format))
        # The real render writes the DOT source beside the raster, which is what
        # `dot.save` writes on the Inspector_Mode branch, so both branches produce
        # the same artifact set apart from the Interaction_Layer.
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(self.source)
        with open(f"{filename}.{format}", "wb") as handle:
            handle.write(b"")
        return filename

    def mock_unflatten(self, *args, **kwargs):
        return self

    run, calls = dot_stub(svg_text=SVG_WITHOUT_ICON) if dot_run is None else (dot_run, [])
    payloads: List[Dict[str, Any]] = []

    def record_payload(payload, output_filename):
        payloads.append({"payload": payload, "output_filename": output_filename})
        if payload_writer is not None:
            return payload_writer(payload, output_filename)
        return f"{output_filename}{INSPECTOR_INDEX_SUFFIX}"

    kwargs: Dict[str, Any] = {}
    if interactive_inspector is not None:
        kwargs["interactive_inspector"] = interactive_inspector

    with (
        patch("core.graph_generator.build_terraform_template", return_value=built_path),
        patch("core.graph_generator.get_private_dns_zones_without_vnets", return_value=[]),
        patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", return_value=[]),
        patch("core.graph_generator.get_bastion_host_name", return_value=None),
        patch("core.graph_generator.write_inspector_payload", side_effect=record_payload),
        patch("graphviz.Digraph.render", mock_render),
        patch("graphviz.Digraph.unflatten", mock_unflatten),
        patch("subprocess.run", run),
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
                **kwargs,
            )
        finally:
            os.chdir(previous_dir)

    output_dir = os.path.dirname(png_path)
    # `subprocess.run` is patched process-wide, so the auto-open calls the run
    # makes at the end land in the same list. Only the layout invocations matter.
    dot_calls = [call for call in calls if call["argv"] and call["argv"][0] == DOT_BINARY]
    return {
        "png_path": png_path,
        "renders": renders,
        "dot_calls": dot_calls,
        "payloads": payloads,
        "files": sorted(os.listdir(output_dir)),
        "output_dir": output_dir,
    }


@pytest.mark.parametrize("interactive_inspector", [None, False])
def test_disabled_mode_renders_through_the_library_only(tmp_path, interactive_inspector):
    """Requirement 1.3: the pre-feature render call is the only call."""
    result = run_generation(
        plan_template({"planstorage": "create"}),
        work_dir=str(tmp_path),
        interactive_inspector=interactive_inspector,
    )

    stem = os.path.basename(result["png_path"])[: -len(".png")]
    assert result["renders"] == [(os.path.join(os.path.basename(result["output_dir"]), stem), "png")]
    assert result["dot_calls"] == []
    assert result["payloads"] == []
    assert set(result["files"]) == {stem, f"{stem}{CHANGE_SUMMARY_SUFFIX}", f"{stem}.png"}


def test_enabled_mode_takes_the_dual_format_branch(tmp_path):
    """Requirements 3.1, 3.6: one invocation, both artifacts, in the run folder."""
    result = run_generation(
        plan_template({"planstorage": "create"}),
        work_dir=str(tmp_path),
        interactive_inspector=True,
    )

    stem = os.path.basename(result["png_path"])[: -len(".png")]
    assert result["renders"] == []
    assert len(result["dot_calls"]) == 1
    argv = result["dot_calls"][0]["argv"]
    assert "-Tpng" in argv and "-Tsvg" in argv
    assert os.path.basename(argv[argv.index("-Tpng") + 2]) == f"{stem}.png"
    assert set(result["files"]) == {
        stem,
        f"{stem}{CHANGE_SUMMARY_SUFFIX}",
        f"{stem}.png",
        f"{stem}{INTERACTION_LAYER_SUFFIX}",
    }


# ─── 7.4 the payload beside the sidecar ──────────────────────────────────────


def test_enabled_mode_writes_the_payload_from_the_run_collector(tmp_path):
    """Requirements 3.6, 12.8: the payload is derived from the diagram path."""
    result = run_generation(
        plan_template({"planstorage": "create", "pe-storage": "delete"}),
        work_dir=str(tmp_path),
        interactive_inspector=True,
    )

    assert len(result["payloads"]) == 1
    written = result["payloads"][0]
    stem = os.path.basename(result["png_path"])[: -len(".png")]
    assert os.path.basename(written["output_filename"]) == stem
    payload = written["payload"]
    assert isinstance(payload, InspectorPayload)
    keys = {record.key for record in payload.records}
    assert f"planstorage-{RG}" in keys
    assert any(key.startswith("cluster_vnet") for key in keys)


def test_the_payload_write_never_costs_the_run_its_png(tmp_path):
    """Requirement 1.9: a raising payload write is a warning, the PNG still returns."""

    def explode(payload, output_filename):
        raise RuntimeError("payload write blew up")

    with captured_logs() as logs:
        result = run_generation(
            plan_template({"planstorage": "create"}),
            work_dir=str(tmp_path),
            interactive_inspector=True,
            payload_writer=explode,
        )

    stem = os.path.basename(result["png_path"])[: -len(".png")]
    assert result["png_path"] == os.path.abspath(os.path.join(result["output_dir"], f"{stem}.png"))
    assert os.path.exists(result["png_path"])
    assert any("payload write blew up" in message for message in logs.messages(logging.WARNING))
    # The Interaction_Layer is untouched by the payload failure.
    assert f"{stem}{INTERACTION_LAYER_SUFFIX}" in result["files"]


def test_the_change_summary_sidecar_is_untouched_by_the_inspector(tmp_path):
    """Requirement 1.11: same sidecar name, same sidecar bytes, with and without."""
    template = plan_template({"planstorage": "create", "pe-storage": "delete"})
    disabled = run_generation(template, work_dir=str(tmp_path / "off"), interactive_inspector=False)
    enabled = run_generation(template, work_dir=str(tmp_path / "on"), interactive_inspector=True)

    def sidecar(result):
        stem = os.path.basename(result["png_path"])[: -len(".png")]
        path = os.path.join(result["output_dir"], f"{stem}{CHANGE_SUMMARY_SUFFIX}")
        assert os.path.basename(path) in result["files"]
        return open(path, encoding="utf-8").read()

    assert sidecar(disabled) == sidecar(enabled)

    # The Interaction_Layer is the only artifact Inspector_Mode adds here, since
    # the payload writer is faked out: no existing artifact is renamed or dropped.
    def suffixes(result):
        stem = os.path.basename(result["png_path"])[: -len(".png")]
        return {name.replace(stem, "") for name in result["files"]}

    assert suffixes(enabled) - suffixes(disabled) == {INTERACTION_LAYER_SUFFIX}
    assert suffixes(disabled) - suffixes(enabled) == set()
