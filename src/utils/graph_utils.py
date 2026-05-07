import re

from graphviz import Digraph

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


def add_node_in_subgraph(subgraph, node_id, label, image_path, resource_type, group=""):
    if resource_type == "Microsoft.ManagedIdentity/userAssignedIdentities":
        resource_type = resource_type.split("/")[-1]
    else:
        resource_type = resource_type.split(".")[-1]
    node_label = f"<<TABLE border='0' cellborder='0' cellspacing='0'><TR><TD>{label}</TD></TR><TR><TD>{resource_type}</TD></TR></TABLE>>"
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
    subgraph.node(node_id, **node_attributes)
