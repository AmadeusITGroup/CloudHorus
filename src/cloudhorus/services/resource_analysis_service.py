"""Resource Analysis Service for dependency tracking and relationship mapping.

This module provides operations for analyzing Azure resource dependencies,
including implicit subnet dependencies and cross-resource-group relationships.
"""

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from cloudhorus.services.base import BaseService


class ResourceAnalysisService(BaseService):
    """Service for analyzing resource dependencies and relationships.

    This service handles:
    - Subnet implicit dependencies (Web Apps, Private Endpoints, etc.)
    - Cross-resource-group dependencies
    - Resource relationship mapping
    - Dependency graph construction

    Attributes:
        resource_handlers: Mapping of resource types to subnet extraction logic
    """

    def __init__(self):
        """Initialize the Resource Analysis Service."""
        super().__init__()
        self._initialize_resource_handlers()

    def validate(self) -> bool:
        """Validate the service is properly configured.

        Returns:
            True if service is valid
        """
        self.logger.info("ResourceAnalysisService validated successfully")
        return True

    def _initialize_resource_handlers(self):
        """Initialize resource type handlers for subnet extraction."""
        self.resource_handlers = {
            "Microsoft.Network/applicationGateways": lambda p: (
                p.get("gatewayIPConfigurations", [{}])[0].get("properties", {}).get("subnet", {}).get("id")
                if p.get("gatewayIPConfigurations")
                else None
            ),
            "Microsoft.Network/bastionHosts": lambda p: (
                p.get("ipConfigurations", [{}])[0].get("properties", {}).get("subnet", {}).get("id")
                if p.get("ipConfigurations")
                else None
            ),
            "Microsoft.Network/azureFirewalls": lambda p: (
                p.get("ipConfigurations", [{}])[0].get("properties", {}).get("subnet", {}).get("id")
                if p.get("ipConfigurations")
                else None
            ),
            "Microsoft.Network/virtualNetworkGateways": lambda p: (
                p.get("ipConfigurations", [{}])[0].get("properties", {}).get("subnet", {}).get("id")
                if p.get("ipConfigurations")
                else None
            ),
            "Microsoft.Network/routeServers": lambda p: (
                p.get("ipConfigurations", [{}])[0].get("properties", {}).get("subnet", {}).get("id")
                if p.get("ipConfigurations")
                else None
            ),
            "Microsoft.Network/privateEndpoints": lambda p: (
                p.get("subnet", {}).get("id") if p.get("subnet") else None
            ),
            "Microsoft.Web/sites": lambda p: (
                p.get("virtualNetworkSubnetId") if "virtualNetworkSubnetId" in p else None
            ),
            "Microsoft.Web/hostingEnvironments": lambda p: (
                p.get("virtualNetwork", {}).get("id") if p.get("virtualNetwork") else None
            ),
            "Microsoft.ContainerService/managedClusters": lambda p: (
                p.get("agentPoolProfiles", [{}])[0].get("vnetSubnetID") if p.get("agentPoolProfiles") else None
            ),
            "Microsoft.DBforMySQL/flexibleServers": lambda p: (
                p.get("network", {}).get("delegatedSubnetResourceId") if p.get("network") else None
            ),
            "Microsoft.DBforPostgreSQL/flexibleServers": lambda p: (
                p.get("network", {}).get("delegatedSubnetResourceId") if p.get("network") else None
            ),
            "Microsoft.Sql/managedInstances": lambda p: (p.get("subnetId") if p.get("subnetId") else None),
            "Microsoft.Cache/Redis": lambda p: (p.get("subnetId") if "subnetId" in p else None),
            "Microsoft.NetApp/netAppAccounts/capacityPools/volumes": lambda p: (
                p.get("subnetId") if "subnetId" in p else None
            ),
            "Microsoft.HDInsight/clusters": lambda p: (
                p.get("computeProfile", {}).get("roles", [{}])[0].get("virtualNetworkProfile", {}).get("subnet")
                if p.get("computeProfile", {}).get("roles")
                else None
            ),
            "Microsoft.ApiManagement/service": lambda p: (
                p.get("virtualNetworkConfiguration", {}).get("subnetResourceId")
                if p.get("virtualNetworkConfiguration")
                else None
            ),
            "Microsoft.LabServices/labs": lambda p: (
                p.get("networkProfile", {}).get("subnetId") if p.get("networkProfile") else None
            ),
            "Microsoft.ContainerInstance/containerGroups": lambda p: (
                p.get("subnetIds", [None])[0] if p.get("subnetIds") else None
            ),
            "Microsoft.Kusto/clusters": lambda p: (
                p.get("virtualNetworkConfiguration", {}).get("subnetId")
                if p.get("virtualNetworkConfiguration")
                else None
            ),
        }

    def analyze_template_dependencies(
        self, template_path: str, resource_group: str
    ) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
        """Analyze a template for resource dependencies.

        Args:
            template_path: Path to the ARM template JSON file
            resource_group: Name of the resource group

        Returns:
            Tuple of (subnet_dependencies, explicit_dependencies)
        """
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template = json.load(f)

            resources = template.get("resources", [])
            subnet_deps = {}
            explicit_deps = {}

            for resource in resources:
                resource_type = resource.get("type", "")
                resource_name = resource.get("name", "")

                # Extract subnet dependencies
                subnet_dep = self._extract_subnet_dependency(resource, resource_group)
                if subnet_dep:
                    subnet_deps[resource_name] = subnet_dep

                # Extract explicit dependencies
                depends_on = resource.get("dependsOn", [])
                if depends_on:
                    explicit_deps[resource_name] = depends_on

            return subnet_deps, explicit_deps

        except Exception as e:
            self.logger.error(f"Failed to analyze template dependencies: {e}")
            return {}, {}

    def _extract_subnet_dependency(self, resource: Dict[str, Any], resource_group: str) -> Optional[str]:
        """Extract subnet dependency from a resource.

        Args:
            resource: Resource dictionary from template
            resource_group: Name of the resource group

        Returns:
            Subnet name if found, None otherwise
        """
        resource_type = resource.get("type", "")
        properties = resource.get("properties", {})

        # Check if resource type has a handler
        if resource_type not in self.resource_handlers:
            return None

        # Get subnet ID using handler
        subnet_id = self.resource_handlers[resource_type](properties)

        if not subnet_id:
            return None

        # Extract subnet name from ID
        from cloudhorus.services.subnet_resolver_service import SubnetResolverService

        resolver = SubnetResolverService()
        result = resolver.extract_subnet_name_from_id(subnet_id)
        return str(result) if result is not None else None

    def get_cross_resource_group_dependencies(
        self, resource: Dict[str, Any], resource_name: str, resource_group: str, subscription_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Extract cross-resource-group dependencies from a Private Endpoint.

        Args:
            resource: Resource dictionary from template
            resource_name: Name of the resource
            resource_group: Source resource group
            subscription_id: Current subscription ID

        Returns:
            Dictionary with targets, minlens, and metadata
        """
        # Only process Private Endpoints
        if resource.get("type") != "Microsoft.Network/privateEndpoints":
            return {}

        properties = resource.get("properties", {})
        targets: List[str] = []
        minlens: List[int] = []
        target_subscriptions: List[Optional[str]] = []
        target_resource_groups: List[Optional[str]] = []

        # Process both connection types
        connection_types = [
            properties.get("privateLinkServiceConnections", []),
            properties.get("manualPrivateLinkServiceConnections", []),
        ]

        for connections in connection_types:
            for connection in connections:
                connection_props = connection.get("properties", {})
                service_id = connection_props.get("privateLinkServiceId")

                # Skip ARM template functions
                if not service_id or "resourceId(" in service_id:
                    continue
                if "[" in service_id or "]" in service_id or "concat(" in service_id:
                    continue

                # Parse resource ID
                parts = service_id.split("/")
                if len(parts) < 5:
                    continue

                target_subscription_id = parts[2] if len(parts) > 2 else None
                target_rg = parts[4] if len(parts) > 4 else None
                target_resource = parts[-1]

                # Add to results
                if target_resource not in targets:
                    minlen = (
                        0
                        if (subscription_id and target_subscription_id and subscription_id != target_subscription_id)
                        else 1
                    )

                    targets.append(target_resource)
                    minlens.append(minlen)
                    target_subscriptions.append(target_subscription_id)
                    target_resource_groups.append(target_rg)

                    connection_type = (
                        "automatic" if connection in properties.get("privateLinkServiceConnections", []) else "manual"
                    )
                    same_sub = "different subscription" if minlen == 0 else "same subscription"

                    self.logger.debug(
                        f"Cross-RG dependency ({connection_type}, {same_sub}): "
                        f"{resource_name} -> {target_resource} (minlen={minlen})"
                    )

        result: Dict[str, Any] = {
            "targets": targets,
            "minlens": minlens,
            "target_subscriptions": target_subscriptions,
            "target_resource_groups": target_resource_groups,
            "source_resource_group": resource_group,
        }
        return result if targets else {}

    def build_dependency_graph(
        self, resources: List[Dict[str, Any]], resource_group: str
    ) -> Dict[Tuple[str, str, str], List[Tuple[str, str, str]]]:
        """Build a dependency graph from resources.

        Args:
            resources: List of resource dictionaries
            resource_group: Name of the resource group

        Returns:
            Dictionary mapping (name, type, rg) to list of dependencies
        """
        dependency_graph = {}

        for resource in resources:
            resource_name = resource.get("name", "")
            resource_type = resource.get("type", "")
            resource_key = (resource_name, resource_type, resource_group)

            dependencies = []

            # Add explicit dependencies
            for dep in resource.get("dependsOn", []):
                dep_info = self._parse_dependency(dep, resource_group)
                if dep_info:
                    dependencies.append(dep_info)

            # Add subnet dependency if exists
            subnet_dep = self._extract_subnet_dependency(resource, resource_group)
            if subnet_dep:
                dependencies.append((subnet_dep, "Microsoft.Network/virtualNetworks/subnets", resource_group))

            if dependencies:
                dependency_graph[resource_key] = dependencies

        return dependency_graph

    def _parse_dependency(self, dependency: str, resource_group: str) -> Optional[Tuple[str, str, str]]:
        """Parse a dependency reference to extract resource info.

        Args:
            dependency: Dependency string from ARM template
            resource_group: Default resource group

        Returns:
            Tuple of (name, type, rg) if parseable, None otherwise
        """
        try:
            # Handle resource ID format
            if dependency.startswith("[") and dependency.endswith("]"):
                # Remove brackets
                dependency = dependency[1:-1]

            # Handle resourceId function
            if "resourceId(" in dependency:
                # Extract resource type and name from resourceId
                match = re.search(r"'([^']+)'.*'([^']+)'", dependency)
                if match:
                    resource_type = match.group(1)
                    resource_name = match.group(2)
                    return (resource_name, resource_type, resource_group)

            # Handle full resource paths
            if "/" in dependency:
                parts = dependency.split("/")
                if "providers" in parts:
                    provider_idx = parts.index("providers")
                    if provider_idx + 2 < len(parts):
                        resource_type = f"{parts[provider_idx + 1]}/{parts[provider_idx + 2]}"
                        resource_name = parts[-1]

                        # Extract resource group if present
                        if "resourceGroups" in parts:
                            rg_idx = parts.index("resourceGroups")
                            if rg_idx + 1 < len(parts):
                                resource_group = parts[rg_idx + 1]

                        return (resource_name, resource_type, resource_group)

            return None

        except Exception as e:
            self.logger.debug(f"Failed to parse dependency '{dependency}': {e}")
            return None
