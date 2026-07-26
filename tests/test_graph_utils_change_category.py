"""Unit tests for the optional ``change_category`` on ``add_node_in_subgraph``.

Covers Requirements 4.5, 4.6, 5.5, 5.6 and 8.6 for both the top-level
``utils.graph_utils`` helper and the mirrored ``cloudhorus.utils.graph_utils``
helper.

The change decoration is drawn on the whole node, so a decorated node adds the
``NODE_DECORATION_KEYS`` attributes and switches ``shape`` from ``none`` to
``box``. The icon and the geometry stay byte-identical to Legacy_Mode.
"""

import pytest

import cloudhorus.utils.graph_utils as mirror_graph_utils
import utils.graph_utils as graph_utils
from utils.change_style import CHANGE_STYLES, NODE_DECORATION_KEYS, NODE_PENWIDTH, node_style_attributes

#: Icon and geometry attributes that must never be influenced by a
#: Change_Category, so a decorated node shows the same icon in the same box.
#: ``shape`` is not one of them any more: the decoration draws the border and
#: the background on the node, which needs a drawn shape (``box``) instead of
#: Legacy_Mode's ``none``.
ICON_AND_GEOMETRY_ATTRIBUTES = (
    "image",
    "imagescale",
    "imagepos",
    "width",
    "height",
    "margin",
    "fontsize",
    "group",
    "labelloc",
)

DECORATED_CATEGORIES = ("create", "update", "replace", "delete")
UNDECORATED_CATEGORIES = (None, "unchanged", "bogus", "CREATE", "")


class FakeSubgraph:
    """Capture the attribute dict handed to Graphviz."""

    def __init__(self):
        self.calls = []

    def node(self, node_id, **attributes):
        self.calls.append((node_id, attributes))

    @property
    def attributes(self):
        assert len(self.calls) == 1, f"expected exactly one node, got {len(self.calls)}"
        return self.calls[0][1]


def build(module, change_category=..., group="grp-1"):
    """Add one node and return its attribute dict."""
    subgraph = FakeSubgraph()
    args = ("node-1", "app-web", "/icons/web.png", "Microsoft.Web/sites")
    if change_category is ...:
        module.add_node_in_subgraph(subgraph, *args, group)
    else:
        module.add_node_in_subgraph(subgraph, *args, group, change_category)
    return subgraph.attributes


MODULES = pytest.mark.parametrize(
    "module",
    [graph_utils, mirror_graph_utils],
    ids=["utils", "cloudhorus.utils"],
)


@MODULES
def test_legacy_call_without_change_category_is_unchanged(module):
    """A call that omits the new parameter keeps the legacy attribute dict."""
    legacy = build(module)

    assert legacy["shape"] == "none"
    assert legacy["image"] == "/icons/web.png"
    assert legacy["label"] == (
        "<<TABLE border='0' cellborder='0' cellspacing='0'>"
        "<TR><TD>app-web</TD></TR><TR><TD>Web/sites</TD></TR></TABLE>>"
    )


@MODULES
@pytest.mark.parametrize("category", UNDECORATED_CATEGORIES)
def test_undecorated_categories_match_legacy_attributes(module, category):
    """None, unchanged, and unknown categories produce identical attributes."""
    assert build(module, change_category=category) == build(module)


@MODULES
@pytest.mark.parametrize("category", DECORATED_CATEGORIES)
def test_decorated_label_carries_colour_and_flag(module, category):
    """Each decorated category injects its coloured Flag_Token in the label."""
    style = CHANGE_STYLES[category]
    label = build(module, change_category=category)["label"]

    assert f"<FONT COLOR='{style.color}'><B>{style.flag}</B></FONT>" in label
    assert "app-web" in label and "Web/sites" in label
    # The border and the background are node attributes now, not label markup.
    assert "border='1'" not in label
    assert f"color='{style.color}'" not in label
    assert style.tint not in label


@MODULES
@pytest.mark.parametrize("category", DECORATED_CATEGORIES)
def test_decorated_node_carries_the_border_and_the_tint(module, category):
    """The whole node is decorated: coloured border, tinted fill, drawn box."""
    style = CHANGE_STYLES[category]
    decorated = build(module, change_category=category)

    assert decorated["color"] == style.color
    assert decorated["fillcolor"] == style.tint
    assert decorated["penwidth"] == NODE_PENWIDTH
    assert decorated["shape"] == "box"
    assert "filled" in decorated["style"].split(",")
    assert {key: decorated[key] for key in NODE_DECORATION_KEYS} == node_style_attributes(style)


@MODULES
@pytest.mark.parametrize("category", DECORATED_CATEGORIES)
def test_only_the_label_and_the_decoration_keys_change(module, category):
    """Decoration touches the label and the decoration keys, nothing else."""
    legacy = build(module)
    decorated = build(module, change_category=category)

    # No attribute disappears; the only new keys are the decoration ones.
    assert set(legacy) <= set(decorated)
    assert set(decorated) - set(legacy) <= set(NODE_DECORATION_KEYS)
    assert decorated["label"] != legacy["label"]

    # Every icon and geometry attribute is byte-identical to Legacy_Mode.
    for name in ICON_AND_GEOMETRY_ATTRIBUTES:
        if name in legacy:
            assert decorated[name] == legacy[name], name

    # And nothing outside the label and the decoration keys differs at all.
    untouched = {"label", *NODE_DECORATION_KEYS}
    assert {k: v for k, v in decorated.items() if k not in untouched} == {
        k: v for k, v in legacy.items() if k not in untouched
    }


@MODULES
def test_change_category_accepted_as_keyword(module):
    """The new parameter is usable by keyword, after ``group``."""
    subgraph = FakeSubgraph()
    module.add_node_in_subgraph(
        subgraph,
        "node-1",
        "app-web",
        "/icons/web.png",
        "Microsoft.Web/sites",
        change_category="delete",
    )
    assert CHANGE_STYLES["delete"].flag in subgraph.attributes["label"]
