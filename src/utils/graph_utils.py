import re

from graphviz import Digraph

from .change_style import decorate_label, node_style_attributes, resolve_style
from .skip_patterns import SKIP_DEPENDENCY_RESOURCE_PATTERNS, SKIP_RESOURCE_PATTERNS


def should_skip(resource_type):
    for pattern in SKIP_RESOURCE_PATTERNS:
        if re.match(pattern, resource_type):
            return True
    return False


def should_skip_dependency(resource_type):
    for pattern in SKIP_DEPENDENCY_RESOURCE_PATTERNS:
        if re.match(pattern, resource_type):
            return True
    return False


def add_node_in_subgraph(subgraph, node_id, label, image_path, resource_type, group="", change_category=None):
    """Add a resource node to a subgraph.

    ``change_category`` is a trailing optional Change_Category. When it is
    ``None``, ``"unchanged"``, or an unknown value, the node attributes are
    byte-identical to the Legacy_Mode output. Otherwise the label gains the
    Flag_Token and the node gains a coloured border plus a light tinted
    background covering the whole node, icon included. The icon and the geometry
    (``image``, ``imagescale``, ``imagepos``, ``width``, ``height``, ``margin``,
    ``fontsize``, ``labelloc``, ``group``) are left untouched
    (Requirements 4.5, 4.6, 5.5, 5.6).
    """
    if resource_type == "Microsoft.ManagedIdentity/userAssignedIdentities":
        resource_type = resource_type.split("/")[-1]
    else:
        resource_type = resource_type.split(".")[-1]
    node_label = f"<<TABLE border='0' cellborder='0' cellspacing='0'><TR><TD>{label}</TD></TR><TR><TD>{resource_type}</TD></TR></TABLE>>"
    style = resolve_style(change_category)
    if style is not None:
        node_label = decorate_label(node_label, style)
    node_attributes = {
        "label": node_label,
        "image": image_path,
        "shape": "none",
        "labelloc": "b",  # Label at bottom
        "imagescale": "false",
        "width": "1.8",  # Slightly reduced width for tighter layout
        "height": "1.8",  # Slightly reduced height
        "imagepos": "tc",  # Image at top center
        "fontsize": "10",
        "margin": "0.05,0.02",  # Tighter margins (horizontal, vertical) - reduced from 0.01,0.01
        "group": group,
    }
    if style is not None:
        # Border and background over the whole node; the icon draws on top of the fill.
        node_attributes.update(node_style_attributes(style))
    subgraph.node(node_id, **node_attributes)
