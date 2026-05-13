"""Graph Generator Service for orchestrating Azure resource visualization.

This module coordinates the generation of infrastructure diagrams from Azure
resources, managing the overall flow of template processing, dependency analysis,
and graph construction.

IMPORTANT: This service preserves the EXACT logic from the original graph_generator.py
"""

import json
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from tqdm import tqdm

from cloudhorus.models.configuration import VisualizationConfig
from cloudhorus.services.base import BaseService
from core.azure_cli import (
    export_resource_group_template,
    get_bastion_host_name,
    get_pe_subnet,
    get_private_dns_zones_without_vnets,
    get_resource_group_location,
    get_subscription_name,
    is_resource_group_in_subscription,
    is_resource_group_not_in_all_subscriptions,
    is_subscription_in_tenant,
    is_vnet_linked_to_private_dns_zone,
    login_to_tenant,
)
from core.bicep_builder import build_bicep_template
from core.graph_generator import create_resource_group_edges, create_subnet_edges, parse_dependency_string
from core.resource_processor import get_cross_resource_group_dependencies, get_subnet_implicit_dependencies
from utils.geticons import get_icon
from utils.graph_utils import add_node_in_subgraph, should_skip, should_skip_dependency


class GraphGeneratorService(BaseService):
    """Service for orchestrating resource graph generation.

    This service uses the EXACT SAME LOGIC as the original graph_generator.py function,
    just organized into a class structure for better maintainability.
    """

    def __init__(
        self,
        config: VisualizationConfig,
        azure_resource_service=None,
        template_registry=None,
        network_service=None,
        bicep_service=None,
        bicep_processor=None,
        analysis_service=None,
        graph_builder=None,
    ):
        """Initialize the Graph Generator Service."""
        super().__init__()
        self.config = config
        # Note: Some services may be None, which is okay - we use direct function calls
        # from the original code to maintain exact behavior

    def validate(self) -> bool:
        """Validate the service is properly configured."""
        self.logger.info("GraphGeneratorService validated successfully")
        return True

    def generate_graph(
        self,
        tenants: List[str],
        subscriptions: List[str],
        resource_groups: List[str],
        use_bicep_templates: bool = False,
        bicep_files: Optional[List[str]] = None,
        parameters_files: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Generate Azure resource graph - delegates to original logic."""
        # Import here to avoid circular dependency
        from core.graph_generator import generate_resource_graph

        # Extract optimization settings (one per subscription)
        subnet_optimization = [opt.subnet_optimization for opt in self.config.optimizations]
        pe_optimization = [opt.pe_optimization for opt in self.config.optimizations]
        cross_pe_optimization = [opt.cross_pe_optimization for opt in self.config.optimizations]

        # privateDnsZonesOptimization: use first subscription's value (or all same)
        private_dns_zones_opt = (
            self.config.optimizations[0].private_dns_zones_optimization if self.config.optimizations else True
        )

        # Call the original function with exact same parameters
        png_path = generate_resource_graph(
            tenants=tenants,
            subscriptions=subscriptions,
            resource_groups=resource_groups,
            subnet_optimization=subnet_optimization,
            direction=self.config.layout.edge_direction.value,
            tenant_minlen=self.config.layout.tenant_minlen,
            max_subnet_in_line=self.config.layout.max_subnet_per_line,
            rankDebug=self.config.layout.rank_debug.value,
            peOptimization=pe_optimization,
            privateDnsZonesOptimization=private_dns_zones_opt,
            resourcesEdgeLength=self.config.layout.resources_edge_length,
            resourceGroupsEdgeLengthListBySubscription=self.config.rg_edge_lengths,
            crossPeOptimization=cross_pe_optimization,
            discoverResourceGroups=self.config.discover_resource_groups,
            exportDrawio=self.config.export_drawio,
            use_local_template=use_bicep_templates,
            bicep_files=bicep_files,
            parameters_files=parameters_files,
        )

        # Return the actual PNG path from the generator
        return cast(Optional[str], png_path)
