"""Graph visualization utilities."""

from typing import Any, Dict, Optional

from graphviz import Digraph

from .change_style import decorate_label, node_style_attributes, resolve_style


class GraphNodeBuilder:
    """Builder for Graphviz nodes with consistent styling."""

    def __init__(self):
        """Initialize the node builder with default attributes."""
        self.default_width = "1.8"
        self.default_height = "1.8"
        self.default_fontsize = "10"
        self.default_margin = "0.05,0.02"

    def create_node_label(self, label: str, resource_type: str, change_category: Optional[str] = None) -> str:
        """Create a formatted HTML label for a node.

        Args:
            label: The main label text
            resource_type: The resource type to display
            change_category: Optional Change_Category decorating the label only

        Returns:
            HTML formatted label string
        """
        # Format resource type for display
        if resource_type == "Microsoft.ManagedIdentity/userAssignedIdentities":
            display_type = resource_type.split("/")[-1]
        else:
            display_type = resource_type.split(".")[-1]

        node_label = (
            f"<<TABLE border='0' cellborder='0' cellspacing='0'>"
            f"<TR><TD>{label}</TD></TR>"
            f"<TR><TD>{display_type}</TD></TR>"
            f"</TABLE>>"
        )

        style = resolve_style(change_category)
        if style is not None:
            node_label = decorate_label(node_label, style)
        return node_label

    def get_node_attributes(
        self,
        label: str,
        image_path: str,
        resource_type: str,
        group: str = "",
        change_category: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, str]:
        """Get node attributes for Graphviz.

        Args:
            label: The node label text
            image_path: Path to the icon image
            resource_type: The Azure resource type
            group: Optional group identifier for layout
            change_category: Optional Change_Category decorating the label only
            **kwargs: Additional custom attributes

        Returns:
            Dictionary of Graphviz node attributes
        """
        node_label = self.create_node_label(label, resource_type, change_category)

        attributes = {
            "label": node_label,
            "image": image_path,
            "shape": "none",
            "labelloc": "b",
            "imagescale": "false",
            "width": kwargs.get("width", self.default_width),
            "height": kwargs.get("height", self.default_height),
            "imagepos": "tc",
            "fontsize": kwargs.get("fontsize", self.default_fontsize),
            "margin": kwargs.get("margin", self.default_margin),
        }

        if group:
            attributes["group"] = group

        # Border and background over the whole node; the icon draws on top of the fill.
        style = resolve_style(change_category)
        if style is not None:
            attributes.update(node_style_attributes(style))

        # Add any additional custom attributes
        for key, value in kwargs.items():
            if key not in attributes:
                attributes[key] = value

        return attributes

    def add_node_to_subgraph(
        self,
        subgraph: Digraph,
        node_id: str,
        label: str,
        image_path: str,
        resource_type: str,
        group: str = "",
        change_category: Optional[str] = None,
        **kwargs,
    ) -> None:
        """Add a node to a Graphviz subgraph.

        Args:
            subgraph: The Graphviz subgraph to add to
            node_id: Unique identifier for the node
            label: The node label text
            image_path: Path to the icon image
            resource_type: The Azure resource type
            group: Optional group identifier for layout
            change_category: Optional Change_Category decorating the label only
            **kwargs: Additional custom attributes
        """
        attributes = self.get_node_attributes(
            label, image_path, resource_type, group, change_category=change_category, **kwargs
        )
        subgraph.node(node_id, **attributes)


# Global node builder instance
_node_builder: Optional[GraphNodeBuilder] = None


def get_node_builder() -> GraphNodeBuilder:
    """Get the global node builder instance."""
    global _node_builder
    if _node_builder is None:
        _node_builder = GraphNodeBuilder()
    return _node_builder


def add_node_in_subgraph(
    subgraph: Digraph,
    node_id: str,
    label: str,
    image_path: str,
    resource_type: str,
    group: str = "",
    change_category: Optional[str] = None,
) -> None:
    """Add a node to a subgraph (backward compatibility).

    Args:
        subgraph: The Graphviz subgraph
        node_id: Unique node identifier
        label: Node label text
        image_path: Path to icon image
        resource_type: Azure resource type
        group: Optional group identifier
        change_category: Optional Change_Category. ``None``, ``"unchanged"``, and
            unknown values leave every attribute exactly as in Legacy_Mode;
            otherwise the label gains the Flag_Token and the node gains a
            coloured border plus a tinted background over its whole area
            (Requirements 4.5, 4.6, 5.5, 5.6).
    """
    builder = get_node_builder()
    builder.add_node_to_subgraph(
        subgraph, node_id, label, image_path, resource_type, group, change_category=change_category
    )
