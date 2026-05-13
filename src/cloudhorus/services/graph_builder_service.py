"""Graph Builder Service for constructing Graphviz diagrams.

This module provides operations for building Graphviz graph structures,
including nodes, edges, clusters, and styling.
"""

from typing import Any, Dict, Optional

from graphviz import Digraph

from cloudhorus.models.configuration import VisualizationConfig
from cloudhorus.services.base import BaseService
from cloudhorus.utils.icon_manager import IconManager
from utils.geticons import get_icon


class GraphBuilderService(BaseService):
    """Service for building Graphviz graph structures.

    This service handles:
    - Graph creation and configuration
    - Node addition with icons and styling
    - Edge creation with constraints
    - Cluster (subgraph) management
    - Graph layout optimization

    Attributes:
        icon_manager: Manager for resource icons
    """

    def __init__(self):
        """Initialize the Graph Builder Service."""
        super().__init__()
        self.icon_manager = IconManager()

    def validate(self) -> bool:
        """Validate the service is properly configured.

        Returns:
            True if service is valid
        """
        self.logger.info("GraphBuilderService validated successfully")
        return True

    def create_graph(self, config: VisualizationConfig) -> Digraph:
        """Create a new Graphviz Digraph with configuration.

        Args:
            config: Visualization configuration

        Returns:
            Configured Digraph instance
        """
        dot = Digraph(comment="Azure Resources")

        # Apply graph-level attributes (matching original graph_generator.py line 1357)
        dot.attr(
            splines="ortho",
            nodesep="0.1",
            ratio="auto",
            ranksep="2",
            rankdir=config.layout.edge_direction.value,
            fontsize="40",
            compound="true",
            concentrate="true",
        )
        dot.attr("node", shape="none", labelloc="b")
        dot.attr("edge", minlen="2")

        self.logger.info(f"Created graph with direction: {config.layout.edge_direction.value}")
        return dot

    def add_tenant_cluster(self, graph: Digraph, tenant_id: str, tenant_idx: int):
        """Add a tenant cluster to the graph.

        Args:
            graph: Graph to add cluster to
            tenant_id: Tenant ID
            tenant_idx: Index of tenant for naming
        """
        cluster_name = f"cluster_tenant_{tenant_idx}"

        with graph.subgraph(name=cluster_name) as tenant_cluster:
            tenant_cluster.attr(
                label=f"Tenant: {tenant_id[:8]}...",
                style="filled",
                fillcolor="lightcyan",
                fontsize="14",
                fontname="Arial Bold",
            )

        self.logger.debug(f"Added tenant cluster: {cluster_name}")

    def add_subscription_cluster(
        self, graph: Digraph, subscription_id: str, subscription_name: Optional[str], sub_idx: int
    ):
        """Add a subscription cluster to the graph.

        Args:
            graph: Graph to add cluster to
            subscription_id: Subscription ID
            subscription_name: Subscription display name
            sub_idx: Index of subscription
        """
        cluster_name = f"cluster_subscription_{sub_idx}"
        label = subscription_name or subscription_id[:8]

        with graph.subgraph(name=cluster_name) as sub_cluster:
            sub_cluster.attr(
                label=f"Subscription: {label}", style="filled", fillcolor="ivory1", fontsize="12", fontname="Arial"
            )

        self.logger.debug(f"Added subscription cluster: {cluster_name}")

    def add_resource_group_cluster(self, graph: Digraph, resource_group: str, rg_idx: int):
        """Add a resource group cluster to the graph.

        Args:
            graph: Graph to add cluster to
            resource_group: Resource group name
            rg_idx: Index of resource group
        """
        cluster_name = f"cluster_rg_{rg_idx}"

        with graph.subgraph(name=cluster_name) as rg_cluster:
            rg_cluster.attr(
                label=f"Resource Group: {resource_group}",
                style="filled",
                fillcolor="ghostwhite",
                fontsize="10",
                fontname="Arial",
            )

        self.logger.debug(f"Added resource group cluster: {cluster_name}")

    def add_resource_node(self, graph: Digraph, resource: Dict[str, Any], resource_group: str, subscription_id: str):
        """Add a resource node to the graph.

        Args:
            graph: Graph to add node to
            resource: Resource dictionary from template
            resource_group: Parent resource group
            subscription_id: Parent subscription ID
        """
        resource_type = resource.get("type", "")
        resource_name = resource.get("name", "")

        # Get icon for resource type using original get_icon() function
        icon_path = get_icon(resource_type)

        # Create node ID
        node_id = f"{resource_name}_{resource_group}"

        # Add node with icon
        graph.node(
            node_id,
            label=f'<<TABLE border="0" cellborder="0" cellspacing="0">' f"<TR><TD>{resource_name}</TD></TR></TABLE>>",
            image=icon_path,
            shape="none",
            imagepos="tc",
            labelloc="b",
        )

        self.logger.debug(f"Added resource node: {resource_name} ({resource_type})")

    def add_edge(
        self,
        graph: Digraph,
        source_id: str,
        target_id: str,
        minlen: int = 1,
        style: str = "solid",
        color: str = "black",
    ):
        """Add an edge between two nodes.

        Args:
            graph: Graph to add edge to
            source_id: Source node ID
            target_id: Target node ID
            minlen: Minimum edge length (for layout)
            style: Edge style (solid, dashed, dotted)
            color: Edge color
        """
        graph.edge(source_id, target_id, minlen=str(minlen), style=style, color=color)

        self.logger.debug(f"Added edge: {source_id} -> {target_id} (minlen={minlen})")

    def add_vnet_cluster(self, graph: Digraph, vnet_name: str, vnet_idx: int):
        """Add a VNet cluster to the graph.

        Args:
            graph: Graph to add cluster to
            vnet_name: VNet name
            vnet_idx: Index for naming
        """
        cluster_name = f"cluster_vnet_{vnet_idx}"

        with graph.subgraph(name=cluster_name) as vnet_cluster:
            vnet_cluster.attr(label=f"VNet: {vnet_name}", style="filled", fillcolor="lightblue", fontsize="10")

        self.logger.debug(f"Added VNet cluster: {cluster_name}")

    def add_subnet_node(self, graph: Digraph, subnet_name: str, vnet_name: str, subnet_idx: int):
        """Add a subnet node to the graph.

        Args:
            graph: Graph to add node to
            subnet_name: Subnet name
            vnet_name: Parent VNet name
            subnet_idx: Index for ID
        """
        node_id = f"subnet_{vnet_name}_{subnet_idx}"

        graph.node(node_id, label=subnet_name, shape="box", style="filled", fillcolor="lightyellow")

        self.logger.debug(f"Added subnet node: {subnet_name}")

    def get_node_id(self, resource_name: str, resource_group: str) -> str:
        """Generate a consistent node ID for a resource.

        Args:
            resource_name: Resource name
            resource_group: Resource group name

        Returns:
            Generated node ID
        """
        return f"{resource_name}_{resource_group}"

    def set_graph_layout_attributes(self, graph: Digraph, config: VisualizationConfig):
        """Apply layout configuration to graph.

        Args:
            graph: Graph to configure
            config: Visualization configuration
        """
        # Edge length for resources
        if config.layout.resources_edge_length:
            graph.attr("edge", minlen=str(config.layout.resources_edge_length))

        # Rank debugging
        if config.layout.rank_debug:
            graph.attr(ranksep="2.0")

        self.logger.debug("Applied layout attributes to graph")
