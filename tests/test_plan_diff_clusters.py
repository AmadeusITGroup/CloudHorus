"""Change decoration of the VNet and subnet container clusters.

A VNet and a subnet carry a Change_Category like any other resource, and the
Legend counts them, but they render as Graphviz clusters rather than nodes, so
they never reach ``add_node_in_subgraph``. This module covers the cluster path:

* :func:`utils.change_style.cluster_style_attributes` - the cluster equivalent of
  ``node_style_attributes`` (border colour, background tint, border width);
* :func:`core.graph_generator.resolve_subnet_change_category` - the compound
  ``"<vnet>/<subnet>"`` name lookup the render pass needs, since it only holds the
  bare subnet name;
* a real generation run, asserting the emitted ``cluster_vnet``/``cluster_subnet``
  attributes and the Flag_Token in their labels for every Change_Category;
* Legacy_Mode and all-unchanged parity: the cluster attributes must stay
  byte-identical to the pre-feature output.

Requirements covered: 5.1, 5.2, 5.3, 5.4, 5.5, 5.9.
"""

import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.graph_generator import (  # noqa: E402
    SUBNET_RENDERER_TYPE,
    apply_cluster_change_style,
    resolve_subnet_change_category,
)
from test_plan_diff_graph_plumbing import (  # noqa: E402
    SUBNET,
    VNET,
    plan_template,
    run_terraform_json_generation,
)
from utils.change_style import (  # noqa: E402
    CHANGE_STYLES,
    CLUSTER_DECORATION_KEYS,
    CLUSTER_PENWIDTH,
    cluster_style_attributes,
    decorate_cluster_label,
    resolve_style,
)

#: Colour, tint and Flag_Token of every decorated Change_Category.
CATEGORY_STYLES = [
    ("create", "#107C10", "#DBEBDB", "+"),
    ("update", "#0078D4", "#D9EBF9", "~"),
    ("replace", "#D13438", "#F8E1E1", "±"),
    ("delete", "#D13438", "#F8E1E1", "-"),
]

#: Legacy cluster backgrounds, which a styleless category must leave untouched.
LEGACY_VNET_BGCOLOR = "bgcolor=lightblue"
LEGACY_SUBNET_BGCOLOR = "bgcolor=whitesmoke"


# ─── cluster_style_attributes ────────────────────────────────────────────────


@pytest.mark.parametrize("category,color,tint,_flag", CATEGORY_STYLES)
def test_cluster_style_attributes_carry_the_colour_tokens_of_the_category(category, color, tint, _flag):
    attributes = cluster_style_attributes(CHANGE_STYLES[category])
    assert attributes == {"color": color, "bgcolor": tint, "penwidth": CLUSTER_PENWIDTH}


def test_cluster_style_attributes_produce_exactly_the_declared_keys():
    """The declared key tuple is what callers merge over the legacy attributes."""
    for category in ("create", "update", "replace", "delete"):
        assert tuple(cluster_style_attributes(CHANGE_STYLES[category])) == CLUSTER_DECORATION_KEYS


def test_cluster_style_attributes_never_touch_the_cluster_style_or_label():
    """A cluster keeps its dashed outline and its own label (Requirement 5.6)."""
    for category in ("create", "update", "replace", "delete"):
        attributes = cluster_style_attributes(CHANGE_STYLES[category])
        assert "style" not in attributes
        assert "label" not in attributes


@pytest.mark.parametrize("category", [None, "unchanged", "forget"])
def test_cluster_style_attributes_are_empty_for_a_styleless_category(category):
    assert cluster_style_attributes(resolve_style(category)) == {}


def test_cluster_penwidth_is_thicker_than_the_node_penwidth():
    from utils.change_style import NODE_PENWIDTH

    assert float(CLUSTER_PENWIDTH) > float(NODE_PENWIDTH)


# ─── decorate_cluster_label ──────────────────────────────────────────────────

CLUSTER_LABEL = (
    "<<TABLE border='0' cellborder='0' cellspacing='0' cellpadding='0'>"
    "<TR><TD align='center' rowspan='2'><img src='/icons/subnets.png' scale='true'/></TD>"
    "<TD align='left'>snet-data</TD></TR>"
    "<TR><TD align='left'>CIDR: 10.0.1.0/24</TD></TR></TABLE>>"
)


def test_decorate_cluster_label_puts_the_flag_in_the_naming_cell():
    """Graphviz refuses a cell holding both an image and text, so the icon cell
    is skipped and the Flag_Token lands in the cell naming the container."""
    decorated = decorate_cluster_label(CLUSTER_LABEL, CHANGE_STYLES["create"])

    assert "<FONT COLOR='#107C10'><B>+</B></FONT> snet-data" in decorated
    assert "<FONT COLOR='#107C10'><B>+</B></FONT> <img" not in decorated
    # Every existing cell survives, the table structure included.
    assert decorated.count("<TD") == CLUSTER_LABEL.count("<TD")
    assert "<img src='/icons/subnets.png' scale='true'/>" in decorated
    assert "CIDR: 10.0.1.0/24" in decorated


@pytest.mark.parametrize("category", [None, "unchanged", "forget"])
def test_decorate_cluster_label_is_a_no_op_for_a_styleless_category(category):
    assert decorate_cluster_label(CLUSTER_LABEL, resolve_style(category)) == CLUSTER_LABEL


def test_decorate_cluster_label_falls_back_when_every_cell_holds_an_image():
    label = "<<TABLE><TR><TD><img src='/icons/subnets.png'/></TD></TR></TABLE>>"
    decorated = decorate_cluster_label(label, CHANGE_STYLES["delete"])
    assert "<B>-</B>" in decorated


# ─── the compound subnet name lookup ─────────────────────────────────────────


def test_subnet_category_is_resolved_from_the_compound_renderer_name():
    """The Renderer_Template names a subnet `"<vnet>/<subnet>"` (Requirement 4.1)."""
    index = {("vnet-hub/snet-data", SUBNET_RENDERER_TYPE): "create"}
    assert resolve_subnet_change_category(index, "vnet-hub", "snet-data") == "create"


def test_subnet_category_falls_back_to_the_bare_subnet_name():
    index = {("snet-data", SUBNET_RENDERER_TYPE): "delete"}
    assert resolve_subnet_change_category(index, "vnet-hub", "snet-data") == "delete"


def test_the_compound_name_wins_over_the_bare_name():
    """Two virtual networks may hold subnets of the same name."""
    index = {
        ("vnet-hub/snet-data", SUBNET_RENDERER_TYPE): "create",
        ("snet-data", SUBNET_RENDERER_TYPE): "delete",
    }
    assert resolve_subnet_change_category(index, "vnet-hub", "snet-data") == "create"


def test_a_subnet_of_another_vnet_is_not_matched():
    index = {("vnet-spoke/snet-data", SUBNET_RENDERER_TYPE): "create"}
    assert resolve_subnet_change_category(index, "vnet-hub", "snet-data") is None


@pytest.mark.parametrize(
    "index,vnet,subnet",
    [
        ({}, "vnet-hub", "snet-data"),
        ({("vnet-hub/snet-data", SUBNET_RENDERER_TYPE): "create"}, "vnet-hub", ""),
        ({("vnet-hub/snet-data", "Microsoft.Network/virtualNetworks"): "create"}, "vnet-hub", "snet-data"),
    ],
)
def test_subnet_category_is_none_when_nothing_matches(index, vnet, subnet):
    assert resolve_subnet_change_category(index, vnet, subnet) is None


def test_subnet_category_uses_the_bare_name_when_the_vnet_is_unknown():
    index = {("snet-data", SUBNET_RENDERER_TYPE): "update"}
    assert resolve_subnet_change_category(index, "", "snet-data") == "update"


# ─── apply_cluster_change_style ──────────────────────────────────────────────

BASE_ATTRIBUTES = {"style": "dashed", "fontsize": "30", "color": "black", "bgcolor": "whitesmoke"}
BASE_LABEL = "<<TABLE border='0'><TR><TD align='left'>snet-data</TD></TR></TABLE>>"


@pytest.mark.parametrize("category,color,tint,flag", CATEGORY_STYLES)
def test_apply_cluster_change_style_overrides_the_legacy_colours(category, color, tint, flag):
    label, attributes = apply_cluster_change_style(BASE_LABEL, dict(BASE_ATTRIBUTES), category)

    assert attributes["color"] == color
    assert attributes["bgcolor"] == tint
    assert attributes["penwidth"] == CLUSTER_PENWIDTH
    # The dashed outline and the font size survive untouched.
    assert attributes["style"] == "dashed"
    assert attributes["fontsize"] == "30"
    # The Flag_Token lands in the first cell of the label (Requirement 5.9).
    assert f"<FONT COLOR='{color}'><B>{flag}</B></FONT> snet-data" in label


@pytest.mark.parametrize("category", [None, "unchanged", "forget"])
def test_apply_cluster_change_style_is_a_no_op_for_a_styleless_category(category):
    label, attributes = apply_cluster_change_style(BASE_LABEL, dict(BASE_ATTRIBUTES), category)
    assert label == BASE_LABEL
    assert attributes == BASE_ATTRIBUTES


def test_apply_cluster_change_style_does_not_mutate_the_attributes_it_is_given():
    given = dict(BASE_ATTRIBUTES)
    apply_cluster_change_style(BASE_LABEL, given, "create")
    assert given == BASE_ATTRIBUTES


# ─── a real generation run ───────────────────────────────────────────────────


def cluster_attributes(source: str, cluster_name: str) -> str:
    """Return the attribute line of the first `cluster_name` subgraph.

    Graphviz writes the cluster attributes as bare assignments on the line that
    follows the `subgraph` header.
    """
    match = re.search(rf'subgraph "{re.escape(cluster_name)}" \{{\n(?P<attrs>[^\n]*)\n', source)
    assert match is not None, f"cluster {cluster_name!r} not found in DOT source"
    return match.group("attrs")


def cluster_template(
    vnet_category: Optional[str] = None,
    subnet_category: Optional[str] = None,
    compound_subnet_name: bool = True,
) -> Dict[str, Any]:
    """The plumbing fixture plus a standalone subnet resource entry.

    The Terraform builder emits a subnet twice: nested under its virtual network's
    `properties.subnets` (which is what the render pass walks) and as a resource
    entry of its own named `"<vnet>/<subnet>"` (which is what carries the
    Change_Category into `change_index`). Both are reproduced here.

    The subnet entry is present whatever the categories are, so the Legacy_Mode
    baseline and the decorated runs describe the same resources and a DOT
    comparison between them is about the decoration alone.
    """
    categories = {}
    if vnet_category is not None:
        categories[VNET] = vnet_category
    template = plan_template(categories)

    subnet_resource: Dict[str, Any] = {
        "type": SUBNET_RENDERER_TYPE,
        "apiVersion": "2023-04-01",
        "name": f"{VNET}/{SUBNET}" if compound_subnet_name else SUBNET,
        "location": "westeurope",
        "properties": {"addressPrefix": "10.0.1.0/24"},
    }
    if subnet_category is not None:
        subnet_resource["changeCategory"] = subnet_category
    template["resources"].append(subnet_resource)

    if vnet_category is None and subnet_category is None:
        # Legacy_Mode: no `changeCategory` anywhere and no change metadata.
        template.pop("metadata", None)
        return template

    counts = {category: 0 for category in ("create", "update", "replace", "delete", "unchanged")}
    for category in (vnet_category, subnet_category):
        if category:
            counts[category] = counts.get(category, 0) + 1
    template["metadata"] = {"changeCounts": counts, "changesNotDisplayed": []}
    return template


@pytest.mark.parametrize("category,color,tint,flag", CATEGORY_STYLES)
def test_vnet_cluster_carries_the_change_category(category, color, tint, flag, tmp_path):
    """Requirements 5.1-5.4, 5.9 for the VNet container."""
    source, _, _ = run_terraform_json_generation(
        [cluster_template(vnet_category=category)],
        work_dir=str(tmp_path),
    )
    attributes = cluster_attributes(source, f"cluster_vnet{VNET}")

    assert f'color="{color}"' in attributes
    assert f'bgcolor="{tint}"' in attributes
    assert f"penwidth={CLUSTER_PENWIDTH}" in attributes
    # The cluster keeps its dashed outline, its font size and its layout keys.
    assert "style=dashed" in attributes
    assert "fontsize=40" in attributes
    assert "rankdir=TB" in attributes and "ranksep=1.0" in attributes
    # The Flag_Token sits in the cell naming the VNet, not in the icon cell:
    # Graphviz rejects a table cell holding both an image and text.
    assert f"<FONT COLOR='{color}'><B>{flag}</B></FONT> Name :{VNET}" in attributes
    assert f"<FONT COLOR='{color}'><B>{flag}</B></FONT> <img" not in attributes
    assert "Virtual-Networks.png" in attributes


@pytest.mark.parametrize("category,color,tint,flag", CATEGORY_STYLES)
def test_subnet_cluster_carries_the_change_category(category, color, tint, flag, tmp_path):
    """Requirements 5.1-5.4, 5.9 for the subnet container."""
    source, _, _ = run_terraform_json_generation(
        [cluster_template(subnet_category=category)],
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    attributes = cluster_attributes(source, f"cluster_subnet{SUBNET}")

    assert f'color="{color}"' in attributes
    assert f'bgcolor="{tint}"' in attributes
    assert f"penwidth={CLUSTER_PENWIDTH}" in attributes
    assert "style=dashed" in attributes
    assert "fontsize=30" in attributes
    assert f"<FONT COLOR='{color}'><B>{flag}</B></FONT> {SUBNET}" in attributes
    assert f"<FONT COLOR='{color}'><B>{flag}</B></FONT> <img" not in attributes
    assert "subnets.png" in attributes
    assert "CIDR: 10.0.1.0/24" in attributes


def test_every_reopening_of_a_subnet_cluster_carries_the_same_decoration(tmp_path):
    """The render pass opens `cluster_subnet<name>` from four different places."""
    source, _, _ = run_terraform_json_generation(
        [cluster_template(subnet_category="create")],
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    blocks = re.findall(rf'subgraph "cluster_subnet{re.escape(SUBNET)}" \{{\n([^\n]*)\n', source)
    assert len(blocks) >= 2, "the fixture must re-open the subnet cluster"
    for attributes in blocks:
        assert 'color="#107C10"' in attributes
        assert 'bgcolor="#DBEBDB"' in attributes
        assert f"penwidth={CLUSTER_PENWIDTH}" in attributes


def test_a_bare_subnet_resource_name_is_still_decorated(tmp_path):
    """A template naming its subnets without the VNet takes the fallback path."""
    source, _, _ = run_terraform_json_generation(
        [cluster_template(subnet_category="delete", compound_subnet_name=False)],
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    attributes = cluster_attributes(source, f"cluster_subnet{SUBNET}")
    assert 'color="#D13438"' in attributes
    assert 'bgcolor="#F8E1E1"' in attributes


def test_the_vnet_and_its_subnet_are_decorated_independently(tmp_path):
    """A `update` VNet holding a `create` subnet shows both states."""
    source, _, _ = run_terraform_json_generation(
        [cluster_template(vnet_category="update", subnet_category="create")],
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    vnet = cluster_attributes(source, f"cluster_vnet{VNET}")
    subnet = cluster_attributes(source, f"cluster_subnet{SUBNET}")

    assert 'color="#0078D4"' in vnet and 'bgcolor="#D9EBF9"' in vnet
    assert 'color="#107C10"' in subnet and 'bgcolor="#DBEBDB"' in subnet


def test_an_undecorated_subnet_keeps_its_legacy_colours(tmp_path):
    """A decorated VNet must not bleed onto its `unchanged` subnet."""
    source, _, _ = run_terraform_json_generation(
        [cluster_template(vnet_category="update", subnet_category="unchanged")],
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    subnet = cluster_attributes(source, f"cluster_subnet{SUBNET}")

    assert LEGACY_SUBNET_BGCOLOR in subnet
    assert "color=black" in subnet
    assert "penwidth" not in subnet
    for colour in ("#0078D4", "#107C10", "#D13438"):
        assert colour not in subnet


# ─── Legacy parity ───────────────────────────────────────────────────────────


def test_a_legacy_template_leaves_the_cluster_attributes_untouched(tmp_path):
    source, _, _ = run_terraform_json_generation(
        [cluster_template()],
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    vnet = cluster_attributes(source, f"cluster_vnet{VNET}")
    subnet = cluster_attributes(source, f"cluster_subnet{SUBNET}")

    assert LEGACY_VNET_BGCOLOR in vnet and "color=black" in vnet and "penwidth" not in vnet
    assert LEGACY_SUBNET_BGCOLOR in subnet and "color=black" in subnet and "penwidth" not in subnet


def test_an_all_unchanged_plan_renders_byte_identical_dot(tmp_path):
    """`unchanged` containers take the Legacy_Mode path (Requirement 5.5)."""
    legacy_source, _, _ = run_terraform_json_generation(
        [cluster_template()],
        pass_change_types=False,
        work_dir=str(tmp_path / "legacy"),
    )
    unchanged_source, _, _ = run_terraform_json_generation(
        [cluster_template(vnet_category="unchanged", subnet_category="unchanged")],
        change_types=None,
        work_dir=str(tmp_path / "unchanged"),
    )
    assert unchanged_source == legacy_source


def test_an_out_of_set_category_renders_byte_identical_dot(tmp_path):
    """Rendering continues with Legacy_Mode cluster styling (Requirement 4.6)."""
    legacy_source, _, _ = run_terraform_json_generation(
        [cluster_template()],
        pass_change_types=False,
        work_dir=str(tmp_path / "legacy"),
    )
    odd_source, _, _ = run_terraform_json_generation(
        [cluster_template(vnet_category="forget", subnet_category="forget")],
        work_dir=str(tmp_path / "odd"),
    )
    assert odd_source == legacy_source


def test_the_decorated_cluster_labels_are_valid_graphviz_markup(tmp_path):
    """The real `dot` binary lays out the decorated DOT without an error.

    Graphviz refuses an HTML table cell that holds both an image and text — it
    fails the whole render rather than dropping the label — and a cluster label
    opens with the container icon. So this renders the DOT of a decorated run
    through the real binary rather than asserting on markup shape alone.
    """
    dot_binary = shutil.which("dot")
    if dot_binary is None:  # pragma: no cover - environment without Graphviz
        pytest.skip("the Graphviz `dot` binary is not installed")

    source, _, _ = run_terraform_json_generation(
        [cluster_template(vnet_category="update", subnet_category="create")],
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    assert "<B>~</B>" in source and "<B>+</B>" in source

    result = subprocess.run(
        [dot_binary, "-Tsvg", "-o", os.path.join(str(tmp_path), "decorated.svg")],
        input=source.encode("utf-8"),
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"syntax error" not in result.stderr


def test_the_rank_control_nodes_of_a_decorated_cluster_are_unchanged(tmp_path):
    """The invisible rank-control nodes must not pick up any decoration."""
    legacy_source, _, _ = run_terraform_json_generation(
        [cluster_template()],
        pass_change_types=False,
        work_dir=str(tmp_path / "legacy"),
    )
    decorated_source, _, _ = run_terraform_json_generation(
        [cluster_template(vnet_category="update", subnet_category="create")],
        pe_optimization=False,
        work_dir=str(tmp_path / "decorated"),
    )

    invisible: List[str] = re.findall(r'"[^"\n]*invis[^"\n]*" \[[^\]]*\]', legacy_source)
    assert invisible, "the fixture must emit rank-control nodes"
    for statement in invisible:
        assert statement in decorated_source, statement
    assert f'"{SUBNET}" [label="" height=1.5' in decorated_source
