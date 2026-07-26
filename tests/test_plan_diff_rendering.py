"""Property-based tests for plan diff node rendering.

Feature: terraform-plan-diff-visualization

This module holds the rendering properties of the design. Properties 10, 11, 12
and 20 are implemented here, one section each; the remaining rendering property
has its own task and its own section seam at the bottom of the file:

- Property 21: Unchanged plans render byte-identical DOT
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import cloudhorus.utils.change_style as mirror_change_style
import cloudhorus.utils.graph_utils as mirror_graph_utils
import utils.change_style as change_style
import utils.graph_utils as graph_utils

# ─── Property 10: Node attributes outside the decoration keys are never modified ──
#
# The change decoration moved from the label to the whole node, so the property
# is no longer "only the label changes". What still holds, and is asserted here,
# is that only the label and the ``NODE_DECORATION_KEYS`` may differ from
# Legacy_Mode, that every icon and geometry attribute is byte-identical, and
# that an undecorated category still produces the byte-identical dict.

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from core.plan_diff import CHANGE_CATEGORIES  # noqa: E402
from strategies.plan_json import resource_names  # noqa: E402

#: Icon and geometry attributes that must be byte-identical between Legacy_Mode
#: and Plan_Diff_Mode whatever the Change_Category is: a decorated node shows
#: the same icon, at the same scale, in the same box, in the same group
#: (Requirements 4.5, 4.6, 5.5, 5.6, 8.6).
#:
#: ``shape`` is deliberately absent. The change decoration is drawn on the whole
#: node rather than inside the label, which needs a drawn shape (``box``) where
#: Legacy_Mode uses ``none``; ``shape`` is therefore one of the decoration keys
#: below, and the icon-and-geometry set is what parity is asserted on.
ICON_AND_GEOMETRY_ATTRIBUTES: Tuple[str, ...] = (
    "image",
    "imagescale",
    "imagepos",
    "labelloc",
    "width",
    "height",
    "margin",
    "fontsize",
    "group",
)

#: The only node attributes a Change_Category may add or change, straight from
#: the module that defines them.
DECORATION_KEYS: Tuple[str, ...] = change_style.NODE_DECORATION_KEYS

#: Categories the Change_Style table decorates.
DECORATED_CATEGORIES: Tuple[str, ...] = ("create", "update", "replace", "delete")

#: The two renderer modules that must stay in step (design section 5).
RENDER_MODULES = (
    (graph_utils, change_style),
    (mirror_graph_utils, mirror_change_style),
)


class FakeSubgraph:
    """Capture the exact attribute dict handed to Graphviz."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Dict[str, Any]]] = []

    def node(self, node_id: str, **attributes: Any) -> None:
        self.calls.append((node_id, attributes))

    @property
    def attributes(self) -> Dict[str, Any]:
        assert len(self.calls) == 1, f"expected exactly one node, got {len(self.calls)}"
        return self.calls[0][1]


@contextmanager
def _quiet_style_warnings():
    """Silence the out-of-set category warning and forget what was reported."""
    change_style.reset_style_warnings()
    mirror_change_style.reset_style_warnings()
    with patch.object(change_style, "logger"), patch.object(mirror_change_style, "logger"):
        yield
    change_style.reset_style_warnings()
    mirror_change_style.reset_style_warnings()


def _node_attributes(module, node: Dict[str, Any], change_category: Any = ...) -> Dict[str, Any]:
    """Render one node and return its attribute dict.

    ``change_category is ...`` renders through the Legacy_Mode call shape, which
    omits the new parameter entirely.
    """
    subgraph = FakeSubgraph()
    positional = (
        subgraph,
        node["node_id"],
        node["label"],
        node["image_path"],
        node["resource_type"],
        node["group"],
    )
    if change_category is ...:
        module.add_node_in_subgraph(*positional)
    else:
        module.add_node_in_subgraph(*positional, change_category=change_category)
    return subgraph.attributes


def _without_label(attributes: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in attributes.items() if key != "label"}


def _comparable(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise the one pre-existing difference between the two renderers.

    ``cloudhorus.utils.graph_utils`` omits ``group`` when it is empty, where
    ``utils.graph_utils`` emits ``group=""``. Both mean "no layout group", and
    neither depends on the Change_Category, so an empty ``group`` is dropped
    before the two modules are compared attribute for attribute.
    """
    return {key: value for key, value in attributes.items() if not (key == "group" and value == "")}


def _without_decoration(attributes: Dict[str, Any]) -> Dict[str, Any]:
    """Drop the label and every key the change decoration is allowed to own."""
    return {
        key: value
        for key, value in attributes.items()
        if key != "label" and key not in DECORATION_KEYS
    }


# ─── Strategies ───────────────────────────────────────────────────────────────

#: Renderer resource types reaching ``add_node_in_subgraph``, including the
#: userAssignedIdentities special case of the display-type shortening.
RENDERER_TYPES: Tuple[str, ...] = (
    "Microsoft.Web/sites",
    "Microsoft.Network/virtualNetworks",
    "Microsoft.Network/virtualNetworks/subnets",
    "Microsoft.Storage/storageAccounts",
    "Microsoft.ContainerService/managedClusters",
    "Microsoft.Network/privateEndpoints",
    "Microsoft.ManagedIdentity/userAssignedIdentities",
)

IMAGE_PATHS: Tuple[str, ...] = (
    "/icons/web.png",
    "/icons/vnet.png",
    "icons/storage account.png",
    "",
)


@st.composite
def render_nodes(draw: st.DrawFn) -> Dict[str, Any]:
    """A node-rendering call: id, display label, icon path, type and group."""
    return {
        "node_id": draw(resource_names()) + "-rg",
        "label": draw(resource_names()),
        "image_path": draw(st.sampled_from(IMAGE_PATHS)),
        "resource_type": draw(st.sampled_from(RENDERER_TYPES)),
        "group": draw(st.one_of(st.just(""), st.sampled_from(["grp-1", "vnet-core"]))),
    }


def out_of_set_categories() -> st.SearchStrategy[Any]:
    """``changeCategory`` values outside the Change_Category set (Requirement 4.6).

    Includes near-misses (wrong case, trailing space, Terraform action names),
    the empty string, and values that are not strings at all, so the styling
    lookup is exercised on both the KeyError and the unhashable path.
    """
    return st.one_of(
        st.sampled_from(["CREATE", "Delete", "replace ", "no-op", "read", "modified", ""]),
        st.text(max_size=8).filter(lambda value: value not in CHANGE_CATEGORIES),
        st.integers(min_value=-5, max_value=5),
        st.booleans(),
        st.just(["delete"]),
        st.just({"category": "delete"}),
    )


def undecorated_categories() -> st.SearchStrategy[Any]:
    """Every value that must leave the whole attribute dict at Legacy_Mode."""
    return st.one_of(st.none(), st.just("unchanged"), out_of_set_categories())


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(node=render_nodes(), category=undecorated_categories())
def test_property_undecorated_categories_keep_the_legacy_attribute_dict(node, category):
    """Property 10: Node attributes outside the label are never modified.

    For the absent Change_Category, the ``unchanged`` category, and any value
    outside the Change_Category set, the produced attribute dict — ``label``
    included — is equal to the Legacy_Mode one, in both renderer modules.

    **Validates: Requirements 4.5, 4.6, 5.5, 5.6, 8.6**
    """
    for module, _styles in RENDER_MODULES:
        with _quiet_style_warnings():
            legacy = _node_attributes(module, node)
            actual = _node_attributes(module, node, change_category=category)

        assert actual == legacy, module.__name__


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(node=render_nodes(), category=st.sampled_from(DECORATED_CATEGORIES))
def test_property_decoration_touches_only_the_decoration_keys(node, category):
    """Property 10: Node attributes outside the decoration keys are never modified.

    For a decorated Change_Category, the only attributes that may appear or
    change are the label and the decoration keys (``shape``, ``style``,
    ``color``, ``fillcolor``, ``penwidth``). Every icon and geometry attribute —
    ``image``, ``imagescale``, ``imagepos``, ``width``, ``height``, ``margin``,
    ``fontsize``, ``labelloc``, ``group`` — is byte-identical to Legacy_Mode, no
    attribute disappears, and the decoration keys carry exactly what the
    Change_Style table says they should.

    **Validates: Requirements 4.5, 4.6, 5.5, 5.6, 8.6**
    """
    for module, styles in RENDER_MODULES:
        with _quiet_style_warnings():
            legacy = _node_attributes(module, node)
            decorated = _node_attributes(module, node, change_category=category)
            style = styles.resolve_style(category)

        # Nothing disappears, and the only new keys are the decoration ones.
        assert set(legacy) <= set(decorated), module.__name__
        assert set(decorated) - set(legacy) <= set(DECORATION_KEYS), module.__name__
        # Every icon and geometry attribute is byte-identical, name by name.
        for name in ICON_AND_GEOMETRY_ATTRIBUTES:
            if name in legacy:
                assert decorated[name] == legacy[name], f"{module.__name__}:{name}"
        # And nothing outside the label and the decoration keys differs at all.
        assert _without_decoration(decorated) == _without_decoration(legacy), module.__name__
        # The decoration keys hold the whole-node decoration of that category.
        assert {key: decorated[key] for key in DECORATION_KEYS} == styles.node_style_attributes(
            style
        ), module.__name__
        # The label carries the change state too, as the Flag_Token.
        assert decorated["label"] != legacy["label"], module.__name__


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(node=render_nodes(), category=st.one_of(undecorated_categories(), st.sampled_from(DECORATED_CATEGORIES)))
def test_property_style_output_is_exactly_the_two_style_helpers(node, category):
    """Property 10: Node attributes outside the decoration keys are never modified.

    The whole styling output of a node is reproducible from the Legacy_Mode
    output plus the two Change_Style helpers: the emitted attribute dict equals
    the Legacy_Mode dict with ``decorate_label`` applied to its label and
    ``node_style_attributes`` merged in — nothing else, for every category,
    decorated or not.

    **Validates: Requirements 4.5, 4.6, 5.5, 5.6, 8.6**
    """
    for module, styles in RENDER_MODULES:
        with _quiet_style_warnings():
            legacy = _node_attributes(module, node)
            actual = _node_attributes(module, node, change_category=category)
            style = styles.resolve_style(category)

        expected = dict(legacy)
        if style is not None:
            expected["label"] = styles.decorate_label(legacy["label"], style)
            expected.update(styles.node_style_attributes(style))

        assert actual == expected, module.__name__


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(node=render_nodes(), category=st.sampled_from(CHANGE_CATEGORIES))
def test_property_both_renderer_modules_emit_the_same_node(node, category):
    """Property 10: Node attributes outside the decoration keys are never modified.

    The mirrored helper in ``cloudhorus.utils.graph_utils`` reacts to a
    Change_Category exactly like ``utils.graph_utils``: both modules emit the
    same attribute dict, decoration keys and label included, and each module's
    own icon and geometry attributes stay at its Legacy_Mode values.

    **Validates: Requirements 4.5, 4.6, 5.5, 5.6, 8.6**
    """
    with _quiet_style_warnings():
        primary_legacy = _node_attributes(graph_utils, node)
        mirror_legacy = _node_attributes(mirror_graph_utils, node)
        primary = _node_attributes(graph_utils, node, change_category=category)
        mirror = _node_attributes(mirror_graph_utils, node, change_category=category)

    # The two modules are indistinguishable, before and after decoration. The
    # one pre-existing divergence, unrelated to the Change_Category: the
    # mirrored builder omits `group` entirely when it is empty, where
    # `utils.graph_utils` emits `group=""`.
    assert _comparable(primary_legacy) == _comparable(mirror_legacy)
    assert _comparable(primary) == _comparable(mirror)

    for name in ICON_AND_GEOMETRY_ATTRIBUTES:
        if name in primary_legacy:
            assert primary[name] == primary_legacy[name], name
        if name in mirror_legacy:
            assert mirror[name] == mirror_legacy[name], name


# ─── Property 11: Change styling maps categories to colour and flag ───────────
#
# The colour token now reaches the output through the node ``color``/``fillcolor``
# attributes and through the Flag_Token's font colour; the Flag_Token itself is
# still label text, which is what keeps Requirement 5.9 (monochrome print) true.

#: The Change_Style table as designed: category -> (colour token, Flag_Token)
#: (Requirements 5.1, 5.2, 5.3, 5.4).
EXPECTED_STYLES: Dict[str, Tuple[str, str]] = {
    "create": ("#107C10", "+"),
    "update": ("#0078D4", "~"),
    "replace": ("#D13438", "±"),
    "delete": ("#D13438", "-"),
}

#: Background tint of each decorated category (Requirements 5.1, 5.2, 5.3, 5.4).
EXPECTED_TINTS: Dict[str, str] = {
    "create": "#DBEBDB",
    "update": "#D9EBF9",
    "replace": "#F8E1E1",
    "delete": "#F8E1E1",
}

#: Every colour token of the table, used to catch a category borrowing another
#: category's colour.
ALL_COLOURS: Tuple[str, ...] = tuple({color for color, _flag in EXPECTED_STYLES.values()})

_TAG_RE = re.compile(r"<[^>]*>")
_COLOUR_ATTRIBUTE_RE = re.compile(r"\s*(?:BG)?COLOR\s*=\s*(['\"])[^'\"]*\1", re.IGNORECASE)


def _label_text(label_html: str) -> str:
    """Return the visible text of an HTML-like Graphviz label.

    Everything inside a tag — attributes included, so every colour token
    disappears — is removed, which leaves exactly what a monochrome print
    shows (Requirement 5.9).
    """
    inner = label_html
    if inner.startswith("<<") and inner.endswith(">>"):
        # A Graphviz HTML label is delimited by one angle bracket on each side.
        inner = inner[1:-1]
    return _TAG_RE.sub("", inner)


def _without_colour_information(label_html: str) -> str:
    """Drop every ``COLOR``/``BGCOLOR`` attribute from a label."""
    return _COLOUR_ATTRIBUTE_RE.sub("", label_html)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(node=render_nodes(), category=st.sampled_from(DECORATED_CATEGORIES))
def test_property_node_carries_the_designed_colour_and_flag_token(node, category):
    """Property 11: Change styling maps categories to colour and flag.

    For each decorated Change_Category the Change_Style table holds the designed
    colour token, Flag_Token and tint; the colour token reaches the output twice
    over — as the node border colour and as the Flag_Token's font colour — the
    tint reaches it as the node fill, no foreign category's colour appears
    anywhere in the emitted node, and the Flag_Token is present as label *text*:
    the visible text of the decorated label is the Flag_Token followed by the
    Legacy_Mode text.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.9**
    """
    expected_colour, expected_flag = EXPECTED_STYLES[category]
    expected_tint = EXPECTED_TINTS[category]

    for module, styles in RENDER_MODULES:
        with _quiet_style_warnings():
            style = styles.resolve_style(category)
            legacy = _node_attributes(module, node)
            decorated = _node_attributes(module, node, change_category=category)

        # The table maps the category to the designed colour, flag and tint.
        assert style is not None, module.__name__
        assert (style.color, style.flag, style.tint) == (
            expected_colour,
            expected_flag,
            expected_tint,
        ), module.__name__

        label = decorated["label"]
        # The colour token reaches the node border and the Flag_Token font, and
        # the tint reaches the node fill.
        assert decorated["color"] == expected_colour, module.__name__
        assert decorated["fillcolor"] == expected_tint, module.__name__
        assert expected_colour in label, module.__name__

        # Only that category's colour, anywhere in the emitted node.
        rendered = "".join(str(value) for value in decorated.values())
        for other_colour in ALL_COLOURS:
            if other_colour != expected_colour:
                assert other_colour not in rendered, f"{module.__name__}:{other_colour}"
        assert expected_colour not in "".join(str(value) for value in legacy.values()), module.__name__

        # The Flag_Token is label text, not only a colour attribute.
        assert _label_text(decorated["label"]) == expected_flag + " " + _label_text(legacy["label"]), module.__name__


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(node=render_nodes(), category=st.sampled_from(DECORATED_CATEGORIES))
def test_property_flag_token_survives_colour_removal(node, category):
    """Property 11: Change styling maps categories to colour and flag.

    Stripping every trace of colour from the emitted node — the label's colour
    attributes *and* the node's own ``color``/``fillcolor``, which is what a
    monochrome print leaves — keeps the Flag_Token in place and keeps the visible
    text unchanged, so the Change_Category stays readable without colour
    (Requirement 5.9).

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.9**
    """
    expected_colour, expected_flag = EXPECTED_STYLES[category]
    expected_tint = EXPECTED_TINTS[category]

    for module, _styles in RENDER_MODULES:
        with _quiet_style_warnings():
            legacy = _node_attributes(module, node)
            decorated = _node_attributes(module, node, change_category=category)

        # Every colour the decoration emits is dropped: the label attributes and
        # the node border and fill.
        monochrome = dict(decorated)
        monochrome.pop("color", None)
        monochrome.pop("fillcolor", None)
        monochrome["label"] = _without_colour_information(decorated["label"])

        remaining = "".join(str(value) for value in monochrome.values())
        assert expected_colour not in remaining, module.__name__
        assert expected_tint not in remaining, module.__name__

        # The Change_Category is still readable: the Flag_Token is label text.
        assert _label_text(monochrome["label"]) == expected_flag + " " + _label_text(
            legacy["label"]
        ), module.__name__


# ─── Property 12: Legend presence and content follow the Change_Model ─────────

import shutil  # noqa: E402
import tempfile  # noqa: E402

from test_plan_diff_graph_plumbing import (  # noqa: E402
    RG,
    VNET,
    plan_template,
    run_terraform_json_generation,
)
from test_plan_diff_legend import LEGEND_CLUSTER  # noqa: E402
from test_plan_diff_legend import legend as legend_cluster_body  # noqa: E402

#: The Legend row of each Change_Category: colour token, Flag_Token, display
#: label. ``unchanged`` is styleless, so it carries no colour and no flag
#: (Requirements 5.1, 5.2, 5.3, 5.4, 5.7).
LEGEND_ROWS: Dict[str, Tuple[Any, Any, str, Any]] = {
    "create": ("#107C10", "+", "Create", "#DBEBDB"),
    "update": ("#0078D4", "~", "Update", "#D9EBF9"),
    "replace": ("#D13438", "±", "Replace", "#F8E1E1"),
    "delete": ("#D13438", "-", "Delete", "#F8E1E1"),
    "unchanged": (None, None, "Unchanged", None),
}

#: The three fixture resources that can carry a Change_Category: an RG-level
#: resource, a subnet-placed resource, and a container.
CHANGE_SLOTS: Tuple[str, ...] = ("storage", "endpoint", "vnet")

_COUNT_CELL_RE = re.compile(r"<TD>(\d+)</TD>")


def change_model_slots() -> st.SearchStrategy[Dict[str, str]]:
    """One template's Change_Model: fixture slot -> Change_Category."""
    return st.dictionaries(
        keys=st.sampled_from(CHANGE_SLOTS),
        values=st.sampled_from(CHANGE_CATEGORIES),
        min_size=1,
        max_size=len(CHANGE_SLOTS),
    )


def change_model_runs() -> st.SearchStrategy[List[Dict[str, str]]]:
    """A whole run: one Change_Model per registered template."""
    return st.lists(change_model_slots(), min_size=1, max_size=2)


@contextmanager
def _generation_workspace():
    """A throwaway directory for one generation run."""
    path = tempfile.mkdtemp(prefix="cloudhorus_legend_property_")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _slot_names(suffix: str) -> Dict[str, str]:
    """Resource names the fixture template gives each slot for `suffix`."""
    return {
        "storage": "planstorage" + suffix.replace("-", ""),
        "endpoint": "pe-storage" + suffix,
        "vnet": VNET + suffix,
    }


def _render_change_model(run: List[Dict[str, str]], **kwargs: Any) -> str:
    """Render a run of Change_Models and return the DOT source."""
    single = len(run) == 1
    templates = []
    for index, slots in enumerate(run):
        suffix = "" if single else f"-{index}"
        names = _slot_names(suffix)
        templates.append(
            plan_template(
                {names[slot]: category for slot, category in slots.items()},
                suffix=suffix,
                resource_group=RG if single else f"{RG}-{index}",
                **kwargs,
            )
        )

    with _generation_workspace() as work_dir:
        source, _analyzer, _calls = run_terraform_json_generation(
            templates,
            work_dir=work_dir,
            **({"pass_change_types": False} if kwargs.get("with_metadata") is False else {}),
        )
    return source


def _expected_counts(run: List[Dict[str, str]]) -> Dict[str, int]:
    """Per-category record counts of the whole run."""
    counts = {category: 0 for category in CHANGE_CATEGORIES}
    for slots in run:
        for category in slots.values():
            counts[category] += 1
    return counts


@settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(run=change_model_runs())
def test_property_legend_appears_exactly_for_a_changed_change_model(run):
    """Property 12: Legend presence and content follow the Change_Model.

    The Diagram carries a Legend exactly when at least one Change_Record holds
    a Change_Category other than `unchanged`; an all-`unchanged` Change_Model
    renders no Legend at all.

    **Validates: Requirements 5.7, 5.8**
    """
    counts = _expected_counts(run)
    expect_legend = any(count > 0 for category, count in counts.items() if category != "unchanged")

    source = _render_change_model(run)

    assert (LEGEND_CLUSTER in source) is expect_legend, counts
    assert ("Change Legend" in source) is expect_legend, counts


@settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(run=change_model_runs())
def test_property_legend_lists_exactly_the_present_categories(run):
    """Property 12: Legend presence and content follow the Change_Model.

    When present, the Legend holds one row per Change_Category present in the
    Change_Model, each carrying that category's colour token, Flag_Token and
    record count, and no row for an absent category. The row counts sum to the
    number of Change_Records of the run.

    **Validates: Requirements 5.7, 5.8**
    """
    counts = _expected_counts(run)
    present = {category for category, count in counts.items() if count > 0}
    if not (present - {"unchanged"}):
        return  # no Legend to inspect; presence is asserted by the property above

    block = legend_cluster_body(_render_change_model(run))

    for category, (colour, flag, label, tint) in LEGEND_ROWS.items():
        if category not in present:
            assert label not in block, category
            continue
        count = counts[category]
        if colour is None:
            # The styleless category: display label plus count, no swatch.
            assert f"<TD>{label}</TD><TD>{count}</TD>" in block, category
        else:
            # The swatch mirrors a decorated node: tinted fill, coloured border.
            assert f"BGCOLOR='{tint}' COLOR='{colour}' BORDER='1'" in block, category
            assert f"<FONT COLOR='{colour}'><B>{flag}</B></FONT> {label}</TD><TD>{count}</TD>" in block, category

    # Every Change_Record of the run is counted in exactly one Legend row.
    assert sum(int(value) for value in _COUNT_CELL_RE.findall(block)) == sum(counts.values()), counts


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(run=change_model_runs())
def test_property_legacy_runs_never_render_a_legend(run):
    """Property 12: Legend presence and content follow the Change_Model.

    A Legacy_Mode run carries no Change_Model, so whatever categories the
    resources would have had, no Legend is emitted (Requirement 5.8).

    **Validates: Requirements 5.7, 5.8**
    """
    source = _render_change_model(run, with_metadata=False)

    assert LEGEND_CLUSTER not in source
    assert "Change Legend" not in source


# ─── Property 20: Sensitive values never reach an output surface ──────────────

import glob  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402

from core.plan_diff import (  # noqa: E402
    ChangeExtractor,
    build_change_summary,
    format_change_summary,
)
from core.terraform_builder import TerraformTemplateBuilder  # noqa: E402
from strategies.plan_json import (  # noqa: E402
    actions_for_category,
    azurerm_resource_values,
    sensitive_masks,
)
from test_plan_diff_integration import RG as PLAN_RG  # noqa: E402
from test_plan_diff_integration import run_plan_diff_generation  # noqa: E402

#: Every generated sensitive leaf is replaced by a token starting with this
#: prefix, so a single substring search over an output surface decides the
#: property. The token is lower-case alphanumeric, which survives any name
#: sanitisation the pipeline applies: a mangled leak is still a leak we see.
MARKER_PREFIX = "zzsensitiveleaf"

#: Attributes the fixture always marks sensitive, so no generated example can
#: satisfy the property vacuously. ``tags`` is there on purpose: it is one of the
#: value keys normalization forwards into the Renderer_Template, so a marker
#: hidden in it does reach the diagram pipeline unless redaction removes it.
GUARANTEED_SENSITIVE_KEYS: Tuple[str, ...] = ("admin_password", "tags")

PLAN_PROVIDER = "registry.terraform.io/hashicorp/azurerm"

#: The resources of the generated plan: Terraform type, Terraform resource name,
#: the renderer type the builder maps it to, and whether it renders as a node
#: whose label can be inspected (a virtual network renders as a cluster).
#: ``azurerm_key_vault`` has no renderer mapping, which drives the
#: `unmapped-type` branch of the Change_Summary.
SENSITIVE_PLAN_SLOTS: Tuple[Tuple[str, str, str, bool], ...] = (
    ("azurerm_storage_account", "planstorage", "Microsoft.Storage/storageAccounts", True),
    ("azurerm_virtual_network", "plannet", "Microsoft.Network/virtualNetworks", False),
    ("azurerm_private_endpoint", "planpe", "Microsoft.Network/privateEndpoints", True),
    ("azurerm_key_vault", "plankv", "Terraform.Azurerm/key_vault", True),
)

#: Flag_Token of each Change_Category, `None` for the styleless one.
CATEGORY_FLAGS: Dict[str, Any] = {
    "create": "+",
    "update": "~",
    "replace": "±",
    "delete": "-",
    "unchanged": None,
}


def _inject_markers(node: Any, mask: Any, markers: List[str]) -> Any:
    """Return `node` with every leaf the mask flags replaced by a fresh marker.

    The walk mirrors `_redact_sensitive`: dictionaries are matched by key, lists
    by index, and a truthy scalar mask flags the whole subtree beneath it. Only
    flagged positions receive a marker, so any marker reaching an output surface
    is a value the plan declared sensitive.
    """
    if isinstance(mask, dict) and isinstance(node, dict):
        return {
            key: _inject_markers(child, mask[key], markers) if key in mask else child
            for key, child in node.items()
        }
    if isinstance(mask, list) and isinstance(node, list):
        return [
            _inject_markers(item, mask[index], markers) if index < len(mask) else item
            for index, item in enumerate(node)
        ]
    if isinstance(mask, (dict, list)):
        # Shape mismatch: the mask flags nothing here, exactly as redaction reads it.
        return node
    if not mask:
        return node
    marker = f"{MARKER_PREFIX}{len(markers):04d}"
    markers.append(marker)
    return marker


@st.composite
def sensitive_plans(draw: st.DrawFn) -> Tuple[Dict[str, Any], List[str]]:
    """Draw a Plan_File whose sensitive leaves are all traceable markers.

    Each resource draws a ``(value_tree, mask)`` pair from
    :func:`strategies.plan_json.sensitive_masks`, then every leaf the mask flags
    is replaced by a marker token. The resource ``name`` is deliberately kept
    out of the mask so the diagram keeps stable node identities; every other
    attribute, nested blocks included, is fair game.

    Returns the plan document and the list of markers it hides.
    """
    markers: List[str] = []
    planned: List[Dict[str, Any]] = []
    changes: List[Dict[str, Any]] = []

    for terraform_type, name, _renderer_type, _renders_as_node in SENSITIVE_PLAN_SLOTS:
        category = draw(st.sampled_from(CHANGE_CATEGORIES))
        tree, mask = draw(
            sensitive_masks(values=azurerm_resource_values(terraform_type=terraform_type, resource_name=name))
        )
        if not isinstance(mask, dict):
            # A whole-resource mask would redact `values` down to a bare string;
            # flag every top-level key instead, which redacts every subtree.
            mask = {key: True for key in tree}
        mask.pop("name", None)
        for key in GUARANTEED_SENSITIVE_KEYS:
            tree.setdefault(key, {"env": "prod"} if key == "tags" else "unset")
            mask[key] = True

        values = _inject_markers(tree, mask, markers)
        address = f"{terraform_type}.{name}"
        change: Dict[str, Any] = {"actions": draw(actions_for_category(category))}

        if category == "delete":
            # A destroyed resource lives only in `change.before`.
            change["before"] = values
            change["before_sensitive"] = mask
        else:
            change["after"] = values
            change["after_sensitive"] = mask
            if category != "create":
                change["before"] = values
                change["before_sensitive"] = mask
            planned_entry: Dict[str, Any] = {
                "address": address,
                "mode": "managed",
                "type": terraform_type,
                "name": name,
                "provider_name": PLAN_PROVIDER,
                "values": values,
            }
            if draw(st.booleans()):
                # The planned resource's own `sensitive_values` is the fallback
                # mask when the change object carries no `after_sensitive`.
                del change["after_sensitive"]
                planned_entry["sensitive_values"] = mask
            planned.append(planned_entry)

        changes.append(
            {
                "address": address,
                "mode": "managed",
                "type": terraform_type,
                "name": name,
                "provider_name": PLAN_PROVIDER,
                "change": change,
            }
        )

    plan = {
        "format_version": "1.0",
        "terraform_version": "1.9.5",
        "planned_values": {"root_module": {"resources": planned}},
        "resource_changes": changes,
    }
    return plan, markers


def _leaks(markers: List[str], *surfaces: str) -> List[str]:
    """Return every marker found in any of the given output surfaces."""
    return [marker for marker in markers if any(marker in surface for surface in surfaces)]


@contextmanager
def _captured_log_records():
    """Collect every log record CloudHorus writes while the block runs."""
    records: List[logging.LogRecord] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Collector()
    logger = logging.getLogger("SingletonLogger")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def _log_text(records: List[logging.LogRecord]) -> str:
    """Flatten log records into one searchable string, arguments included."""
    parts: List[str] = []
    for record in records:
        try:
            parts.append(record.getMessage())
        except Exception:  # pragma: no cover - a broken format string is not a leak
            parts.append(str(record.msg))
        parts.append(repr(record.args))
    return "\n".join(parts)


def _sidecar_text(work_dir: str) -> str:
    """Return the concatenated content of every Change_Summary sidecar written."""
    paths = glob.glob(os.path.join(work_dir, "**", f"*{'.change-summary.json'}"), recursive=True)
    contents = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as handle:
            contents.append(handle.read())
    return "\n".join(contents)


def _resource_label_text(source: str, node_id: str) -> Any:
    """Return the visible text of a node's label, or `None` when it is absent."""
    match = re.search(rf'"{re.escape(node_id)}" \[label=(<<TABLE.*?>>)', source, re.DOTALL)
    if match is None:
        return None
    return _label_text(match.group(1))


def _display_type(renderer_type: str) -> str:
    """Mirror the display-type shortening `add_node_in_subgraph` applies."""
    if renderer_type == "Microsoft.ManagedIdentity/userAssignedIdentities":
        return renderer_type.split("/")[-1]
    return renderer_type.split(".")[-1]


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(plan_and_markers=sensitive_plans())
def test_property_sensitive_values_never_reach_the_dot_source_or_the_logs(plan_and_markers):
    """Property 20: Sensitive values never reach an output surface.

    A whole Plan_Diff_Mode run is driven from a plan whose sensitive leaves are
    traceable markers. No marker appears in the Graphviz DOT source that feeds
    the Draw.io export, in any log record the run writes, or in the
    Change_Summary sidecar; and every resource node label carries exactly the
    resource name, the resource type and the Flag_Token of its Change_Category.

    **Validates: Requirements 10.2, 10.3, 10.4, 10.5**
    """
    plan, markers = plan_and_markers
    assert markers, "the fixture must hide at least one sensitive value"

    with _generation_workspace() as work_dir:
        with _captured_log_records() as records:
            source, _analyzer = run_plan_diff_generation(plan, None, work_dir)
        sidecar = _sidecar_text(work_dir)

    assert source, "the run produced no DOT source"
    logs = _log_text(records)

    # Requirement 10.5: the DOT source is what the Draw.io export is built from.
    assert _leaks(markers, source) == [], "sensitive value in the DOT source"
    # Requirement 10.4.
    assert _leaks(markers, logs) == [], "sensitive value in a log record"
    # Requirement 10.3.
    assert _leaks(markers, sidecar) == [], "sensitive value in the Change_Summary sidecar"

    # Requirement 10.2: a node label holds nothing but name, type and Flag_Token.
    model = ChangeExtractor().extract(plan["resource_changes"])
    inspected = 0
    for terraform_type, name, renderer_type, renders_as_node in SENSITIVE_PLAN_SLOTS:
        if not renders_as_node:
            continue
        label = _resource_label_text(source, f"{name}-{PLAN_RG}")
        if label is None:
            continue  # the resource reached no node; nothing to restrict
        flag = CATEGORY_FLAGS[model.category_for(f"{terraform_type}.{name}") or "unchanged"]
        expected = f"{name}{_display_type(renderer_type)}"
        assert label == (expected if flag is None else f"{flag} {expected}"), name
        inspected += 1
    assert inspected, "no resource node label was inspected"


def _strip_sensitivity_declarations(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of the plan with every sensitivity mask removed.

    Nothing can be redacted in that copy, so it is the control that shows the
    marker search is live: the same values then do travel into the payload the
    diagram is built from.
    """
    control = json.loads(json.dumps(plan))
    for entry in control["resource_changes"]:
        entry["change"].pop("before_sensitive", None)
        entry["change"].pop("after_sensitive", None)
    for entry in control["planned_values"]["root_module"]["resources"]:
        entry.pop("sensitive_values", None)
    return control


def _renderer_payload(plan: Dict[str, Any]) -> Tuple[Any, str]:
    """Build a plan and return `(document, renderer template as JSON text)`."""
    model = ChangeExtractor().extract(plan["resource_changes"])
    document = TerraformTemplateBuilder().build_document_from_json(plan, change_model=model)
    return document, json.dumps(document.to_renderer_template(), ensure_ascii=False, default=str)


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(plan_and_markers=sensitive_plans())
def test_property_sensitive_values_never_reach_the_change_summary(plan_and_markers):
    """Property 20: Sensitive values never reach an output surface.

    The Change_Summary of a plan full of sensitive values — its payload, its
    console lines, and the reported undisplayed changes — carries addresses,
    Terraform types, categories and reasons only, and the Renderer_Template the
    DOT source and the Draw.io export are built from carries no sensitive value
    either. The control, the same plan with its sensitivity declarations
    stripped, does carry the values, which is what makes the property non-vacuous.

    **Validates: Requirements 10.2, 10.3, 10.4, 10.5**
    """
    plan, markers = plan_and_markers
    document, template = _renderer_payload(plan)

    model = ChangeExtractor().extract(plan["resource_changes"])
    summary = build_change_summary(
        model,
        document,
        unmapped=[record.terraform_type for record in model.records.values()][:1],
        skipped=None,
    )
    payload = json.dumps(summary.to_payload(), ensure_ascii=False)
    lines = "\n".join(format_change_summary(summary))

    # Requirement 10.3.
    assert _leaks(markers, payload, lines) == [], "sensitive value in the Change_Summary"
    # The document metadata the run-level summary is rebuilt from is equally clean.
    assert _leaks(markers, json.dumps(document.metadata, ensure_ascii=False, default=str)) == []
    # Requirements 10.2, 10.5: nothing sensitive enters the rendering payload.
    assert _leaks(markers, template) == [], "sensitive value in the Renderer_Template"

    # The control leaks, so the assertions above are about redaction, not about
    # values that never travel this far.
    _control_document, control_template = _renderer_payload(_strip_sensitivity_declarations(plan))
    assert _leaks(markers, control_template), "the control must carry the values redaction removes"


# ─── Property 21: Unchanged plans render byte-identical DOT ───────────────────
# Task 7.11 implements this property here.

from strategies.plan_json import plan_documents  # noqa: E402

#: Every colour token the Change_Style table can emit; none may appear in the
#: DOT source of an all-`unchanged` run.
STYLE_COLOURS: Tuple[str, ...] = ("#107C10", "#0078D4", "#D13438")


def _legacy_twin(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Return the same plan without its `resource_changes` array.

    Plan_Diff_Mode is activated by the presence of that array, so the twin is
    exactly "the same resources in Terraform JSON mode without Plan_Diff_Mode":
    identical `planned_values` and `configuration`, no change information.
    """
    twin = json.loads(json.dumps(plan))
    twin.pop("resource_changes", None)
    return twin


def _render_plan_source(plan: Dict[str, Any]) -> str:
    """Render one plan through the real pipeline in a throwaway workspace."""
    with _generation_workspace() as work_dir:
        source, _analyzer = run_plan_diff_generation(plan, None, work_dir)
    return source


@settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(plan=plan_documents(categories=["unchanged"], min_resources=1, max_resources=4))
def test_property_all_unchanged_plans_render_the_legacy_dot_source(plan):
    """Property 21: Unchanged plans render byte-identical DOT.

    A Plan_Diff_Mode run whose change entries all resolve to `unchanged` is
    driven end to end, then the same resources are rendered again in Terraform
    JSON mode without Plan_Diff_Mode — the identical document with its
    `resource_changes` array removed. Both runs produce byte-identical DOT
    source, and the Plan_Diff_Mode source carries no Change_Style colour and no
    Legend.

    **Validates: Requirements 12.6**
    """
    model = ChangeExtractor().extract(plan["resource_changes"])
    # Non-vacuity: the plan really does carry change entries, all `unchanged`.
    assert model.records, "the generated plan carries no Change_Record"
    assert {record.category for record in model.records.values()} == {"unchanged"}

    diff_source = _render_plan_source(plan)
    legacy_source = _render_plan_source(_legacy_twin(plan))

    assert diff_source, "the Plan_Diff_Mode run produced no DOT source"
    assert diff_source == legacy_source

    for colour in STYLE_COLOURS:
        assert colour not in diff_source, colour
    assert LEGEND_CLUSTER not in diff_source
