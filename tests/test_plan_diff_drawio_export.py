"""Draw.io export of a Plan_Diff_Mode diagram.

Task 11.2 of the terraform-plan-diff-visualization spec, covering:

* Requirement 8.7 - the export converter meets the node decoration Change_Style
  introduces (``shape``, ``style``, ``color``, ``fillcolor``, ``penwidth``) and
  still completes, writing the ``.drawio`` file with that decoration converted;
* Requirement 10.5 - values the plan marks sensitive are absent from that file;
* Requirement 8.6 - a resource node keeps in Draw.io what it gets without
  Plan_Diff_Mode (see ``test_plan_diff_drawio_export_keeps_container_assignment``).

This module deliberately sits outside the property suite: it exercises
``graphviz2drawio`` and the real ``dot`` layout binary, not CloudHorus logic, so
one worked example is the useful shape and Hypothesis would only make it slow.
Both fixtures run the real chain through
:func:`test_plan_diff_integration.run_plan_diff_generation` with
``export_drawio=True``; only the PNG render call is faked, so the DOT source the
converter consumes is the real one.

Sensitive values are traced with marker tokens rather than by searching for
plausible secrets: every leaf the plan flags as sensitive is a unique
``zzsensitiveleaf<n>`` token, so one substring search decides Requirement 10.5.
Note that a CloudHorus diagram carries no resource attribute values at all -
node labels hold name, short type and Flag_Token - so the marker search is a
regression guard on that surface. The control assertion in
:func:`test_plan_diff_drawio_export_excludes_sensitive_values` shows the markers
are real values that redaction removes rather than values that never travel.
"""

import copy
import glob
import html
import json
import os
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("pygraphviz", reason="the Draw.io converter needs pygraphviz")
pytest.importorskip("graphviz2drawio", reason="the Draw.io export needs graphviz2drawio")

from core.plan_diff import ChangeExtractor  # noqa: E402
from core.terraform_builder import TerraformTemplateBuilder  # noqa: E402
from test_plan_diff_integration import (  # noqa: E402
    SUBNET,
    VNET,
    _change_entry,
    _planned_resource,
    plan_file,
    run_plan_diff_generation,
)

#: Prefix of every injected sensitive leaf. Lower-case alphanumeric, so a
#: mangled leak is still a leak the substring search finds.
MARKER_PREFIX = "zzsensitiveleaf"

#: Value keys the markers are hidden in. ``tags`` is one of the keys resource
#: normalization forwards into the Renderer_Template, so a marker hidden there
#: does travel towards the diagram unless redaction removes it first.
SENSITIVE_KEYS: Tuple[str, ...] = ("tags", "administrator_login_password")

#: An extra leaf whose plan action is a no-op, so the export holds one
#: undecorated resource node next to the decorated ones.
UNCHANGED_LEAF = "keepstorage"

#: Colour, Flag_Token and background tint of every resource node the export must
#: carry, keyed by the resource name. ``None`` marks the styleless category.
EXPECTED_DECORATION: Dict[str, Optional[Tuple[str, str, str]]] = {
    "newstorage": ("#107C10", "+", "#DBEBDB"),  # create
    "api-web": ("#0078D4", "~", "#D9EBF9"),  # update
    "legacystorage": ("#D13438", "-", "#F8E1E1"),  # delete
    "pe-legacy": ("#D13438", "-", "#F8E1E1"),  # delete
    UNCHANGED_LEAF: None,  # unchanged
}

#: Every change colour, used to prove the undecorated node carries none of them.
CHANGE_COLOURS: Tuple[str, ...] = ("#107C10", "#0078D4", "#D13438")

#: Every change tint, used to prove the undecorated node carries no change fill.
CHANGE_TINTS: Tuple[str, ...] = ("#DBEBDB", "#D9EBF9", "#F8E1E1")


# ─── Fixture plan ────────────────────────────────────────────────────────────


def drawio_plan() -> Tuple[Dict[str, Any], List[str]]:
    """Return the export fixture plan and the sensitive markers it hides.

    Built on the integration fixture, which already spans every Change_Category
    around a VNet/subnet container hierarchy, plus one no-op leaf. Every value
    key in :data:`SENSITIVE_KEYS` holds a fresh marker and is flagged in the
    matching sensitivity mask, on both the planned resources and the change
    objects the deleted resources are reconstructed from.
    """
    plan = copy.deepcopy(plan_file())
    unchanged_values: Dict[str, Any] = {"name": UNCHANGED_LEAF, "location": "westeurope"}
    plan["planned_values"]["root_module"]["resources"].append(
        _planned_resource(
            "azurerm_storage_account.keep", "azurerm_storage_account", "keep", copy.deepcopy(unchanged_values)
        )
    )
    plan["resource_changes"].append(
        _change_entry(
            "azurerm_storage_account.keep",
            "azurerm_storage_account",
            "keep",
            ["no-op"],
            copy.deepcopy(unchanged_values),
            copy.deepcopy(unchanged_values),
        )
    )

    markers: List[str] = []

    def _mark() -> str:
        marker = f"{MARKER_PREFIX}{len(markers):04d}"
        markers.append(marker)
        return marker

    def _hide(values: Dict[str, Any]) -> Dict[str, bool]:
        values["tags"] = {"secret": _mark()}
        values["administrator_login_password"] = _mark()
        return {key: True for key in SENSITIVE_KEYS}

    for entry in plan["resource_changes"]:
        change = entry["change"]
        for phase in ("before", "after"):
            if isinstance(change.get(phase), dict):
                change[f"{phase}_sensitive"] = _hide(change[phase])
    for entry in plan["planned_values"]["root_module"]["resources"]:
        entry["sensitive_values"] = _hide(entry["values"])

    return plan, markers


def legacy_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return the same plan without its change records, so no diff activates."""
    legacy = copy.deepcopy(plan)
    legacy.pop("resource_changes", None)
    return legacy


# ─── Export runs ─────────────────────────────────────────────────────────────


class Export:
    """One generation run plus the artifacts it wrote."""

    def __init__(self, work_dir: str, dot_source: str) -> None:
        self.work_dir = work_dir
        self.dot_source = dot_source

    @property
    def drawio_path(self) -> str:
        return _artifact(self.work_dir, ".drawio")

    @property
    def dot_path(self) -> str:
        return _artifact(self.work_dir, ".dot")

    @property
    def xml_text(self) -> str:
        with open(self.drawio_path, "r", encoding="utf-8") as handle:
            return handle.read()

    @property
    def cells(self) -> Dict[str, Dict[str, str]]:
        return _cells(self.xml_text)


def _artifact(work_dir: str, suffix: str) -> str:
    """Return the single artifact with `suffix` the run wrote below `work_dir`."""
    matches = glob.glob(os.path.join(work_dir, "**", f"*{suffix}"), recursive=True)
    assert len(matches) == 1, f"expected exactly one {suffix} file, found {matches}"
    return matches[0]


def _cells(xml_text: str) -> Dict[str, Dict[str, str]]:
    """Parse the Draw.io XML and return every `mxCell` by id.

    Parsing rather than substring matching, so a malformed export fails here
    instead of silently passing the content assertions.
    """
    root = ET.fromstring(xml_text)
    return {cell.get("id", ""): dict(cell.attrib) for cell in root.iter("mxCell")}


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
    matches = [cell for cell_id, cell in cells.items() if cell_id.startswith("node") and name in _plain_text(cell)]
    assert len(matches) == 1, f"expected one Draw.io node for {name!r}, found {len(matches)}"
    return matches[0]


def _container_cell(cells: Dict[str, Dict[str, str]], name: str) -> Dict[str, str]:
    """Return the single container cell whose label names `name`."""
    matches = [cell for cell_id, cell in cells.items() if cell_id.startswith("clust") and name in _plain_text(cell)]
    assert len(matches) == 1, f"expected one Draw.io container for {name!r}, found {len(matches)}"
    return matches[0]


def _cluster_labels(cells: Dict[str, Dict[str, str]]) -> List[str]:
    """Return the visible text of every container cell, sorted."""
    return sorted(
        _plain_text(cell) for cell_id, cell in cells.items() if cell_id.startswith("clust") and _plain_text(cell)
    )


#: Flag_Token a decorated container label opens with.
FLAG_TOKENS: Tuple[str, ...] = ("+", "~", "±", "-")


def _undecorated_labels(cells: Dict[str, Dict[str, str]]) -> List[str]:
    """Return every container label with its leading Flag_Token stripped."""
    labels = []
    for label in _cluster_labels(cells):
        for flag in FLAG_TOKENS:
            if label.startswith(f"{flag} "):
                label = label[len(flag) + 1 :]
                break
        labels.append(label)
    return sorted(labels)


def _leaks(markers: List[str], *surfaces: str) -> List[str]:
    """Return every marker found in any of the given surfaces."""
    return [marker for marker in markers if any(marker in surface for surface in surfaces)]


PLAN, MARKERS = drawio_plan()


@pytest.fixture(scope="module")
def plan_diff_export():
    """A Plan_Diff_Mode generation that exports Draw.io."""
    work_dir = tempfile.mkdtemp(prefix="cloudhorus_drawio_plan_diff_")
    try:
        source, _analyzer = run_plan_diff_generation(PLAN, None, work_dir, export_drawio=True)
        yield Export(work_dir, source)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def legacy_export():
    """The same resources exported without a plan diff, as the 8.6 baseline."""
    work_dir = tempfile.mkdtemp(prefix="cloudhorus_drawio_legacy_")
    try:
        source, _analyzer = run_plan_diff_generation(legacy_plan(PLAN), None, work_dir, export_drawio=True)
        yield Export(work_dir, source)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


# ─── Requirement 8.7: the export completes and writes the file ───────────────


def test_plan_diff_drawio_export_writes_a_non_empty_file(plan_diff_export):
    """The converter meets the Change_Style decoration and still writes the file.

    Requirement 8.7. A decorated node carries a drawn shape, a border colour, a
    background fill and a Flag_Token that no Legacy_Mode node has, so this
    asserts the export path survives them: the `.drawio` file exists, is
    non-empty, is well-formed Draw.io XML, and holds a node cell for every
    resource of the plan.
    """
    path = plan_diff_export.drawio_path
    assert os.path.isfile(path)
    assert os.path.getsize(path) > 0, "the Draw.io file is empty"

    root = ET.fromstring(plan_diff_export.xml_text)
    assert root.tag == "mxGraphModel"

    cells = plan_diff_export.cells
    for name in EXPECTED_DECORATION:
        assert _resource_cell(cells, name), name


def test_plan_diff_drawio_export_carries_the_change_decorated_labels(plan_diff_export):
    """Every changed resource reaches Draw.io with its colour and Flag_Token.

    Requirement 8.7: the attributes Change_Style introduces are not dropped on
    the way out, they are converted. The decoration now lives on the node — a
    coloured border and a tinted background — plus the coloured Flag_Token in the
    label, so all three are asserted. The undecorated resource is asserted too,
    so the test fails if decoration bleeds onto an `unchanged` resource.
    """
    cells = plan_diff_export.cells

    for name, decoration in EXPECTED_DECORATION.items():
        cell = _resource_cell(cells, name)
        text = _plain_text(cell)
        markup = html.unescape(cell.get("value", "")).lower()
        style = _style(cell)
        stroke = style.get("strokeColor", "").lower()
        fill = style.get("fillColor", "").lower()

        if decoration is None:
            assert text.startswith(name), text
            for colour in CHANGE_COLOURS:
                assert colour.lower() not in markup, f"{name} carries the change colour {colour}"
                assert colour.lower() not in stroke, f"{name} carries the change colour {colour}"
            for tint in CHANGE_TINTS:
                assert tint.lower() != fill, f"{name} carries the change tint {tint}"
            continue

        colour, flag, tint = decoration
        assert text.startswith(flag), f"{name} lost its Flag_Token: {text!r}"
        assert colour.lower() in markup, f"{name} lost the change colour in its label"
        assert stroke == colour.lower(), f"{name} lost the change colour on its border"
        assert fill == tint.lower(), f"{name} lost the change tint on its background"

    legend = [cell for cell_id, cell in cells.items() if "Change Legend" in _plain_text(cell)]
    assert len(legend) == 1, "the Legend did not reach the Draw.io file"


# ─── Requirement 10.5: no sensitive value in the Draw.io file ────────────────


def test_plan_diff_drawio_export_excludes_sensitive_values(plan_diff_export):
    """No value the plan marks sensitive appears in the exported artifacts.

    Requirement 10.5. The `.dot` file written next to the export is checked as
    well, since it is the input the converter reads and it ships beside the
    diagram. The control at the end builds the same plan with its sensitivity
    masks stripped and finds the markers in the rendering payload, which is what
    makes the two assertions above about redaction rather than about values that
    never travel this far.
    """
    assert MARKERS, "the fixture must hide at least one sensitive value"

    xml_text = plan_diff_export.xml_text
    with open(plan_diff_export.dot_path, "r", encoding="utf-8") as handle:
        dot_text = handle.read()

    assert _leaks(MARKERS, xml_text) == [], "sensitive value in the Draw.io file"
    assert _leaks(MARKERS, dot_text) == [], "sensitive value in the exported DOT file"
    assert _leaks(MARKERS, plan_diff_export.dot_source) == [], "sensitive value in the DOT source"

    control = copy.deepcopy(PLAN)
    for entry in control["resource_changes"]:
        entry["change"].pop("before_sensitive", None)
        entry["change"].pop("after_sensitive", None)
    for entry in control["planned_values"]["root_module"]["resources"]:
        entry.pop("sensitive_values", None)

    builder = TerraformTemplateBuilder()
    redacted = builder.build_document_from_json(PLAN, change_model=ChangeExtractor().extract(PLAN["resource_changes"]))
    unredacted = builder.build_document_from_json(
        control, change_model=ChangeExtractor().extract(control["resource_changes"])
    )
    redacted_payload = json.dumps(redacted.to_renderer_template(), ensure_ascii=False, default=str)
    unredacted_payload = json.dumps(unredacted.to_renderer_template(), ensure_ascii=False, default=str)

    assert _leaks(MARKERS, unredacted_payload), "the control must carry the values redaction removes"
    assert _leaks(MARKERS, redacted_payload) == [], "sensitive value in the rendering payload"


# ─── Requirement 8.6: Draw.io parity with a run without Plan_Diff_Mode ───────

#: Style keys that carry the Change_Style decoration itself, so they are the only
#: ones a Plan_Diff_Mode node cell is allowed to differ in. The decoration is
#: drawn on the whole node now, which is a border colour, a border width and a
#: background fill.
DECORATION_STYLE_KEYS: Tuple[str, ...] = ("strokeColor", "strokeWidth", "fillColor")


def test_plan_diff_drawio_export_keeps_shape_icon_and_container(plan_diff_export, legacy_export):
    """A resource node keeps its Draw.io shape, icon and container in Plan_Diff_Mode.

    Requirement 8.6. Both exports describe the same resources; the Plan_Diff_Mode
    one additionally decorates nodes and labels, reconstructs the deleted
    resources, and adds the Legend. For every resource that reaches both files,
    the node cell must agree on the shape family, on the embedded icon, and on
    where it sits in the container structure. Only the decoration keys may
    differ: the border colour, the border width and the background fill.
    """
    plan_diff_cells = plan_diff_export.cells
    legacy_cells = legacy_export.cells

    shared = sorted(
        name
        for name in EXPECTED_DECORATION
        if any(name in _plain_text(cell) for cell_id, cell in legacy_cells.items() if cell_id.startswith("node"))
    )
    assert shared, "the baseline export holds none of the resources under test"
    assert UNCHANGED_LEAF in shared and "api-web" in shared

    for name in shared:
        plan_diff_style = _style(_resource_cell(plan_diff_cells, name))
        legacy_style = _style(_resource_cell(legacy_cells, name))

        assert plan_diff_style.get("shape") == legacy_style.get("shape"), f"{name} changed shape"
        assert plan_diff_style.get("image") == legacy_style.get("image"), f"{name} changed icon"
        assert plan_diff_style.get("aspect") == legacy_style.get("aspect"), f"{name} changed aspect"

        comparable = {key: value for key, value in plan_diff_style.items() if key not in DECORATION_STYLE_KEYS}
        expected = {key: value for key, value in legacy_style.items() if key not in DECORATION_STYLE_KEYS}
        assert comparable == expected, f"{name} changed a non-decoration style key"

    # Container assignment: the same containers exist, and every node sits in the
    # same place of the container structure as it does without Plan_Diff_Mode.
    # A container carrying a Change_Category also carries its Flag_Token now, so
    # the labels are compared with that prefix removed.
    assert set(_cluster_labels(legacy_cells)).issubset(set(_undecorated_labels(plan_diff_cells)))
    for name in shared:
        assert _resource_cell(plan_diff_cells, name).get("parent") == _resource_cell(legacy_cells, name).get(
            "parent"
        ), f"{name} changed container"


def test_plan_diff_drawio_export_keeps_the_resource_icons_of_deleted_resources(plan_diff_export):
    """Resources that exist only in the diff still carry a Draw.io icon.

    Requirement 8.6 for the reconstructed deletes: they have no Legacy_Mode
    counterpart to compare against, since `planned_values` does not describe
    them, so the assertion is that they reach Draw.io as icon nodes like any
    other resource of their type.
    """
    cells = plan_diff_export.cells

    for name in ("legacystorage", "pe-legacy"):
        style = _style(_resource_cell(cells, name))
        assert style.get("shape") == "image", f"{name} is not an icon node"
        assert style.get("image", "").startswith("data:image/png,"), f"{name} carries no icon"


# ─── The DOT the converter actually reads is pretty-printed ──────────────────
#
# `run_plan_diff_generation` fakes `Digraph.unflatten`, so the DOT it captures
# holds one node statement per line. The real export writes `dot.source` after
# `unflatten`, which pretty-prints one attribute per line. Every helper that
# reads the DOT back therefore has to cope with a statement spanning lines —
# the icon-and-decoration repair silently did nothing in production until it
# did, which no test could see while `unflatten` was stubbed.

#: One node statement as `unflatten` writes it: attributes across several lines.
PRETTY_PRINTED_DOT = """digraph {
\tsubgraph "cluster_rg" {
\t\t"legacystorage-rg" [
\t\t\tlabel=<<TABLE border='0' cellborder='0' cellspacing='0'><TR><TD><FONT COLOR='#D13438'><B>-</B></FONT> legacystorage</TD></TR><TR><TD>Storage/storageAccounts</TD></TR></TABLE>>,
\t\t\timage="/icons/Storage-Accounts.png",
\t\t\tcolor="#D13438",
\t\t\tfillcolor="#F8E1E1",
\t\t\tpenwidth=2,
\t\t\tshape=box,
\t\t\tstyle="filled,rounded"];
\t\t"keepstorage-rg" [
\t\t\tlabel=<<TABLE border='0' cellborder='0' cellspacing='0'><TR><TD>keepstorage</TD></TR><TR><TD>Storage/storageAccounts</TD></TR></TABLE>>,
\t\t\timage="/icons/Storage-Accounts.png",
\t\t\tshape=none];
\t}
\t"legacystorage-rg" -> "keepstorage-rg" [color="#000000"];
}
"""


def test_pretty_printed_dot_node_statements_are_parsed():
    """A node statement spread over several lines is still read back.

    Both `_dot_node_icons` and `_dot_node_decorations` have to find it, otherwise
    the icon-and-decoration repair in `fix_drawio_hierarchy` never fires on a
    real export.
    """
    from core.graph_generator import _dot_node_decorations, _dot_node_icons

    icons = _dot_node_icons(PRETTY_PRINTED_DOT)
    decorations = _dot_node_decorations(PRETTY_PRINTED_DOT)

    assert icons == {
        "legacystorage": ["/icons/Storage-Accounts.png"],
        "keepstorage": ["/icons/Storage-Accounts.png"],
    }
    # Only the decorated node carries a decoration, and it carries all of it.
    assert decorations == {
        "legacystorage": {"strokeColor": "#D13438", "fillColor": "#F8E1E1", "strokeWidth": "2"}
    }


def test_edge_statements_are_not_mistaken_for_nodes():
    """`"a" -> "b" [attrs]` ends in the same shape as a node declaration.

    The edge colour must not be read as a node decoration, and the edge target
    must not be indexed as a node.
    """
    from core.graph_generator import _dot_node_decorations, _iter_dot_node_attributes

    dot = 'digraph {\n\t"a" -> "b" [color="#D13438",\n\t\tpenwidth=2];\n}\n'

    assert list(_iter_dot_node_attributes(dot)) == []
    assert _dot_node_decorations(dot) == {}


def test_single_line_dot_statements_are_still_parsed():
    """The in-memory `dot.source` form keeps working."""
    from core.graph_generator import _dot_node_decorations, _dot_node_icons

    dot = (
        "digraph {\n"
        "\t\"legacystorage-rg\" [label=<<TABLE border='0'><TR><TD>"
        "<FONT COLOR='#D13438'><B>-</B></FONT> legacystorage</TD></TR></TABLE>> "
        'image="/icons/Storage-Accounts.png" color="#D13438" fillcolor="#F8E1E1" penwidth=2]\n'
        "}\n"
    )

    assert _dot_node_icons(dot) == {"legacystorage": ["/icons/Storage-Accounts.png"]}
    assert _dot_node_decorations(dot)["legacystorage"]["strokeColor"] == "#D13438"


def test_helpers_survive_the_real_unflatten_of_the_exported_dot(plan_diff_export):
    """The repair helpers cope with the DOT `unflatten` actually produces.

    `run_plan_diff_generation` fakes `Digraph.unflatten`, so the `.dot` artifact
    it leaves behind is the single-line form. Production writes `dot.source`
    after a real `unflatten`, which pretty-prints one attribute per line — the
    form that silently defeated the icon-and-decoration repair. Here the real
    `unflatten` binary is run over the exported DOT, so the assertion is about
    what the converter reads in production rather than about the stubbed form.
    """
    import graphviz

    from core.graph_generator import _dot_node_decorations, _dot_node_icons

    with open(plan_diff_export.dot_path, "r", encoding="utf-8") as handle:
        exported = handle.read()

    dot_text = graphviz.unflatten(exported)

    # The real unflatten does spread an attribute list over several lines, which
    # is exactly what the single-line-anchored parser used to miss. It keeps the
    # first attribute on the line that opens the list and puts every following
    # one on its own line, so the shape to look for is a node statement whose
    # opening line ends on a comma. The leading anchor keeps edge statements
    # (`"a" -> "b" [attrs]`) out of the match.
    pretty_printed_node = re.compile(
        r'^[ \t]*"[^"\n]+"[ \t]*\[[^\]\n]*,[ \t]*\n[ \t]*[A-Za-z_]+=', re.MULTILINE
    )
    assert pretty_printed_node.search(dot_text), "unflatten did not pretty-print the DOT"

    # And the helpers recover every decorated resource from that form.
    icons = _dot_node_icons(dot_text)
    decorations = _dot_node_decorations(dot_text)
    for name, decoration in EXPECTED_DECORATION.items():
        assert name in icons, f"{name} has no icon in the exported DOT"
        if decoration is None:
            assert name not in decorations, f"{name} must carry no decoration"
        else:
            colour, _flag, tint = decoration
            assert decorations[name] == {
                "strokeColor": colour,
                "fillColor": tint,
                "strokeWidth": "2",
            }, name


# ─── The VNet and subnet clusters carry a decoration too ─────────────────────
#
# A VNet and a subnet render as Graphviz clusters, so their Change_Style lives in
# the cluster attributes rather than in a node statement, and the Draw.io
# container cell is rebuilt from a fixed style string. The fixture plan updates
# the VNet `core-vnet` and leaves the subnet `app` at `no-op`, so one decorated
# and one undecorated container reach the export.

#: Change_Style of the fixture's VNet cluster, as Draw.io style keys.
VNET_CLUSTER_DECORATION: Dict[str, str] = {
    "strokeColor": "#0078D4",
    "fillColor": "#D9EBF9",
    "fillOpacity": "100",
    "strokeWidth": "3",
}

#: One cluster as `unflatten` writes it: a `graph [ ... ]` block across lines.
PRETTY_PRINTED_CLUSTER_DOT = """digraph {
\tsubgraph "cluster_vnetcore-vnet" {
\t\tgraph [bgcolor="#D9EBF9",
\t\t\tcolor="#0078D4",
\t\t\tfontsize=40,
\t\t\tlabel=<<TABLE border='0'><TR><TD><img src="/icons/Virtual-Networks.png"/></TD><TD align='left'><FONT COLOR='#0078D4'><B>~</B></FONT> Name :core-vnet</TD></TR><TR><TD align='left'>CIDR: 10.20.0.0/16</TD></TR></TABLE>>,
\t\t\tpenwidth=3,
\t\t\tstyle=dashed
\t\t];
\t\tsubgraph "cluster_subnetapp" {
\t\t\tgraph [bgcolor=whitesmoke,
\t\t\t\tcolor=black,
\t\t\t\tfontsize=30,
\t\t\t\tstyle=dashed
\t\t\t];
\t\t\t"legacystorage-rg" [
\t\t\t\tcolor="#D13438",
\t\t\t\tfillcolor="#F8E1E1",
\t\t\t\tpenwidth=2];
\t\t}
\t}
}
"""


def test_cluster_decorations_are_read_from_both_dot_forms():
    """A cluster decoration is found in the pretty-printed and the single-line form.

    `unflatten` rewrites bare cluster attributes into a `graph [ ... ]` block, and
    the export reads the unflattened source, so both shapes have to parse. The
    decorated node nested in the undecorated subnet cluster is the trap: its
    `color` must not be read as its container's.
    """
    from core.graph_generator import _dot_cluster_decorations

    pretty = _dot_cluster_decorations(PRETTY_PRINTED_CLUSTER_DOT)
    assert pretty == {"cluster_vnetcore-vnet": VNET_CLUSTER_DECORATION}

    single_line = (
        "digraph {\n"
        '\tsubgraph "cluster_vnetcore-vnet" {\n'
        '\t\tbgcolor="#D9EBF9" color="#0078D4" fontsize=40 penwidth=3 style=dashed\n'
        '\t\tsubgraph "cluster_subnetapp" {\n'
        "\t\t\tbgcolor=whitesmoke color=black fontsize=30 style=dashed\n"
        '\t\t\t"legacystorage-rg" [color="#D13438" fillcolor="#F8E1E1" penwidth=2]\n'
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )
    assert _dot_cluster_decorations(single_line) == {"cluster_vnetcore-vnet": VNET_CLUSTER_DECORATION}


def test_cluster_cells_are_matched_by_label_text_not_by_position():
    """A cluster the render pass re-opens is several DOT blocks but one cell.

    `fix_drawio_hierarchy` numbers the clusters it finds in the DOT and matches
    them to the converter's `clustN` cells by that order, which does not line up
    once a cluster is re-opened — the container cells are therefore resolved by
    their label text instead.
    """
    from core.graph_generator import _dot_cluster_label_texts, _resolve_cluster_decoration

    texts = _dot_cluster_label_texts(PRETTY_PRINTED_CLUSTER_DOT)
    assert texts["cluster_vnetcore-vnet"] == "Name :core-vnet"

    decorations = {"cluster_vnetcore-vnet": VNET_CLUSTER_DECORATION}
    assert _resolve_cluster_decoration("~ Name :core-vnetCIDR: 10.20.0.0/16", decorations, texts) == (
        VNET_CLUSTER_DECORATION
    )
    # A container that is not the decorated one keeps its style.
    assert _resolve_cluster_decoration("Name: test-rg-plan-diff", decorations, texts) == {}
    assert _resolve_cluster_decoration("", decorations, texts) == {}


def test_two_containers_with_the_same_label_are_left_undecorated():
    """An ambiguous match yields no decoration rather than a guess."""
    from core.graph_generator import _resolve_cluster_decoration

    decorations = {
        "cluster_subnetapp": {"strokeColor": "#107C10"},
        "cluster_subnetapp2": {"strokeColor": "#D13438"},
    }
    texts = {"cluster_subnetapp": "app", "cluster_subnetapp2": "app"}
    assert _resolve_cluster_decoration("+ appCIDR: 10.0.0.0/24", decorations, texts) == {}


def test_cluster_decorations_survive_the_real_unflatten(plan_diff_export):
    """The exported DOT, unflattened by the real binary, still yields the decoration.

    The test harness stubs `Digraph.unflatten`, so this runs the real one over the
    exported `.dot` and asserts against that form — the same trap the node
    decoration repair fell into.
    """
    import graphviz

    from core.graph_generator import _dot_cluster_decorations

    with open(plan_diff_export.dot_path, "r", encoding="utf-8") as handle:
        exported = handle.read()

    dot_text = graphviz.unflatten(exported)
    decorations = _dot_cluster_decorations(dot_text)

    assert decorations.get(f"cluster_vnet{VNET}") == VNET_CLUSTER_DECORATION
    # The subnet is a no-op in the fixture plan, so it carries no decoration.
    assert f"cluster_subnet{SUBNET}" not in decorations
    # No unrelated container picked one up either.
    assert set(decorations) == {f"cluster_vnet{VNET}"}


def test_plan_diff_drawio_export_carries_the_cluster_decoration(plan_diff_export, legacy_export):
    """The VNet container reaches Draw.io with its change colour, the subnet without.

    Requirement 8.7 for containers: the cluster cell style is rebuilt from a fixed
    string by the converter post-processing, so the change colours have to be
    re-applied on top of it. The undecorated subnet container is asserted against
    the same run without Plan_Diff_Mode, so a bleed onto an `unchanged` container
    fails here.
    """
    vnet_cell = _container_cell(plan_diff_export.cells, VNET)
    style = _style(vnet_cell)

    for key, value in VNET_CLUSTER_DECORATION.items():
        assert style.get(key, "").lower() == value.lower(), f"the VNet container lost {key}"
    assert "~" in _plain_text(vnet_cell), "the VNet container lost its Flag_Token"

    subnet_style = _style(_container_cell(plan_diff_export.cells, SUBNET))
    legacy_subnet_style = _style(_container_cell(legacy_export.cells, SUBNET))
    assert subnet_style.get("strokeColor") == legacy_subnet_style.get("strokeColor")
    assert subnet_style.get("strokeWidth") == legacy_subnet_style.get("strokeWidth")
    for colour in CHANGE_COLOURS + CHANGE_TINTS:
        assert colour.lower() not in subnet_style.get("strokeColor", "").lower()
        assert colour.lower() != subnet_style.get("fillColor", "").lower()
