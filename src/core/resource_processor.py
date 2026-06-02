import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from utils.graph_utils import should_skip
from utils.logger import SingletonLogger

from .azure_cli import (
    export_resource_group_template,
    get_pe_subnet,
    get_template_data_for_resource_group,
    is_resource_group_in_subscription,
)

logger = SingletonLogger().get_logger()


@dataclass
class ResourceProperties:
    """Data class to hold resource properties for type safety"""

    resource_type: str
    resource_name: str
    properties: Dict


def extract_subnet_name_from_id(subnet_id: str) -> Optional[str]:
    """
    Extract ONLY actual subnet names that exist in the template.
    NO generation, NO mapping, NO pattern matching.

    Args:
        subnet_id: The subnet ID string from template

    Returns:
        Optional[str]: The literal subnet name if found, None otherwise
    """
    if not subnet_id or not isinstance(subnet_id, str):
        return None

    subnet_id = subnet_id.strip()

    # Case 1: Full resource path - get the actual subnet name at the end
    if "/subnets/" in subnet_id:
        return subnet_id.split("/subnets/")[-1].split("/")[0]

    # Case 2: resourceId function - get the actual third parameter
    if subnet_id.startswith("[resourceId(") and subnet_id.endswith(")]"):
        try:
            # Remove brackets and function name
            inner = subnet_id[12:-2]  # Remove '[resourceId(' and ')]'
            params = [p.strip().strip("'\"") for p in inner.split(",")]
            if len(params) >= 3:
                return params[2] if params[2] else None
        except:
            pass

    # Case 3: Simple subnet name - ONLY if it looks like a real subnet name
    if (
        len(subnet_id) < 50
        and "/" not in subnet_id
        and "[" not in subnet_id
        and "reference(" not in subnet_id
        and "outputs." not in subnet_id
        and "deployment" not in subnet_id.lower()
        and not subnet_id.startswith("some-")  # Avoid test patterns
        and subnet_id.replace("-", "").replace("_", "").isalnum()
    ):  # Only real names
        return subnet_id

    # For all other cases not explicitly handled above (i.e., when the subnet_id does not match known patterns for full resource paths, resourceId functions, or simple valid subnet names),
    # we deliberately avoid guessing or inferring the subnet name. This is to prevent incorrect extraction and potential misconfiguration.
    # Instead, we return None to signal that the subnet name could not be reliably determined.
    return None


def get_subnet_implicit_dependencies(
    resource_groups: List[str],
    subscription_id: str,
    CategoryDepth: int,
    peOptimization: bool,
    subnet_implicit_dependencies: Dict[str, str],
    use_local_template: bool,
    bicep_files: Optional[List[str]] = None,
    parameters_files: Optional[List[str]] = None,
    subscriptions: Optional[List[str]] = None,
    dependencies: Optional[Dict] = None,
    add_to_dependencies_dict: bool = True,
    discoverResourceGroups: Optional[List[str]] = None,
    original_rg_count: Optional[int] = None,
    cross_rg_ghost_resources: Optional[set] = None,
) -> Dict[str, str]:
    """
    Extract subnet implicit dependencies from all Azure resources in the Resources groups to avoid ORDER impact.

    This function analyzes Azure resources to identify implicit subnet dependencies,
    particularly for Web Apps and Private Endpoints. It handles:
    - Web Apps (Microsoft.Web/sites) virtual network integration
    - Private Endpoints subnet associations

    Args:
        resource_groups: List of resource group names to process
        subscription_id: Azure subscription ID to filter resources
        CategoryDepth: Depth of resource type hierarchy to consider
        peOptimization: Flag to optimize Private Endpoint subnet handling
        subnet_implicit_dependencies: Existing dictionary of subnet dependencies
        use_local_template: If True, use local Bicep template instead of Azure export
        bicep_files: List of paths to Bicep template files (required when use_local_template=True)
        parameters_files: List of paths to parameters files (required when use_local_template=True)
        subscriptions: List of subscription IDs (required for Bicep template mapping)
        dependencies: Optional dependencies dictionary to add implicit dependencies when both resources are in same RG
        add_to_dependencies_dict: If True and dependencies provided, add implicit dependencies to dependencies dict
                                when both resource and subnet are in same resource group, otherwise use subnet_implicit_dependencies
        discoverResourceGroups: List of RG names for which discovery is enabled. None or empty = disabled.

    Returns:
        Updated dictionary mapping resource names to their dependent subnet names

    Example:
        {
            'myWebApp': 'integration-subnet',
            'myPrivateEndpoint': 'pe-subnet'
        }
    """
    try:
        resource_name = "unknown"  # Initialize to prevent UnboundLocalError
        # Snapshot only the ORIGINAL RGs (user-specified) so discovered RGs
        # from previous subscription iterations don't get re-exported here.
        rg_limit = original_rg_count if original_rg_count is not None else len(resource_groups)
        original_rgs = list(resource_groups[:rg_limit])
        for rg_index, resourceGroup in enumerate(original_rgs):
            template: Optional[Dict[str, Any]] = None
            if use_local_template:
                template = get_template_data_for_resource_group(resourceGroup)
                if template is None:
                    # Legacy fallback: build Bicep template when the template registry has not been primed yet.
                    if not bicep_files or not parameters_files or not subscriptions:
                        logger.warning(f"Local template mode enabled but no registered template found for {resourceGroup}")
                        continue

                    try:
                        if rg_index < len(bicep_files):
                            bicep_file = bicep_files[rg_index]
                            parameters_file = parameters_files[rg_index]
                        else:
                            bicep_file = bicep_files[-1]
                            parameters_file = parameters_files[-1]

                        logger.info(
                            f"Building Bicep template for subnet dependencies: {bicep_file} with parameters: {parameters_file}"
                        )
                        from .bicep_builder import build_bicep_template

                        output_file = build_bicep_template(bicep_file, parameters_file)
                        if not output_file:
                            logger.error(f"Failed to build Bicep template for resource group {resourceGroup}")
                            continue
                        logger.info(f"Built Bicep template to {output_file} for subnet dependency analysis")
                    except Exception as e:
                        logger.error(f"Error building Bicep template for {resourceGroup}: {e}")
                        continue
            else:
                # Azure mode: Export from Azure Resource Manager
                if is_resource_group_in_subscription(resourceGroup, subscription_id, use_local_template):
                    # Export the resource group template
                    output_file = export_resource_group_template(subscription_id, resourceGroup)
                    logger.info(f"Exported template for resource group {resourceGroup} to {output_file}")
                    if output_file is None:
                        logger.error(f"Failed to export template for resource group {resourceGroup} — skipping")
                        continue
                else:
                    logger.debug(f"Skipping resource group {resourceGroup} - not in subscription {subscription_id}")
                    continue

            # Initialize and parse the template variable inside the loop
            try:
                if template is None:
                    with open(output_file, "r") as file:
                        template = json.load(file)
                logger.info(
                    f'Processing resources in {"local template" if use_local_template else f"resource group {resourceGroup}"} for subnet dependencies'
                )
            except (json.JSONDecodeError, FileNotFoundError) as e:
                logger.error(f"Failed to load template file {output_file}: {e}")
                continue

            # Extract resources and dependencies
            resources = template.get("resources", [])
            for resource in resources:
                # Get the Azure resource type
                resource_type = resource["type"]
                if should_skip(resource_type):
                    continue
                resource_type_parts = resource_type.split("/")
                if (
                    len(resource_type_parts) <= (CategoryDepth + 1)
                    or resource_type == "Microsoft.Network/virtualNetworks"
                    or resource_type == "Microsoft.Network/virtualNetworks/subnets"
                ):
                    if resource_type == "Microsoft.Network/virtualNetworks/subnets":
                        resource_name = resource["name"].split("/")[-1]
                    elif peOptimization and resource_type == "Microsoft.Network/privateEndpoints":
                        if not use_local_template:
                            # Azure mode: Use get_pe_subnet which requires Azure credentials
                            resource_name = (
                                "privateEndpoints"
                                + "-"
                                + (get_pe_subnet(resource["name"], resourceGroup, subscription_id) or "unknown")
                            )
                        else:
                            # Bicep mode: Extract PE name from template without Azure API calls
                            pe_name = resource["name"]
                            # Try to extract subnet reference from PE properties for better naming
                            pe_properties = resource.get("properties", {})
                            pe_subnet_id = pe_properties.get("subnet", {}).get("id")
                            if pe_subnet_id:
                                # Extract subnet name from the subnet ID reference
                                extracted_subnet = extract_subnet_name_from_id(pe_subnet_id)
                                if extracted_subnet:
                                    resource_name = f"privateEndpoints-{extracted_subnet}"
                                else:
                                    resource_name = f"privateEndpoints-{pe_name}"
                            else:
                                resource_name = f"privateEndpoints-{pe_name}"
                    else:
                        resource_name = resource["name"]
                else:
                    continue

                # Check explicit subnet dependencies from 'dependsOn' to determine
                # if this resource has a VNet/subnet dependency.  When the subnet is
                # in the SAME resource group the main graph_generator loop already
                # handles placement, so we skip here.  When the subnet is in a
                # DIFFERENT RG we create a subnet_implicit_dependencies entry so a
                # VNet-integration edge is drawn.
                has_explicit_subnet_dep = False
                explicit_subnet_name_from_dep = None
                if "dependsOn" in resource:
                    for dependency in resource.get("dependsOn", []):
                        if (
                            "Microsoft.Network/virtualNetworks/subnets" in dependency
                            or "Microsoft.Network/virtualNetworks" in dependency
                        ):
                            has_explicit_subnet_dep = True
                            # Try to extract the subnet name from the dependsOn string
                            explicit_subnet_name_from_dep = extract_subnet_name_from_id(dependency)
                            break

                if has_explicit_subnet_dep:
                    # Determine which RG the subnet lives in from the dependsOn string.
                    # dependsOn can be either a full resource path (/subscriptions/...)
                    # or an ARM expression ([resourceId(...)]). We can only parse RG
                    # from full paths; ARM expressions fall through to resource_handlers.
                    dep_subnet_rg = None
                    dep_str = resource.get("dependsOn", [""])[0] if resource.get("dependsOn") else ""
                    if dep_str.startswith("/subscriptions/") and "/resourceGroups/" in dep_str:
                        parts = dep_str.split("/")
                        if len(parts) > 4 and parts[3] == "resourceGroups":
                            dep_subnet_rg = parts[4]

                    if dep_subnet_rg and dep_subnet_rg != resourceGroup and explicit_subnet_name_from_dep:
                        # Cross-RG: subnet is in a different RG → VNet integration edge
                        subnet_implicit_dependencies[resource_name + "-" + resourceGroup] = (
                            explicit_subnet_name_from_dep
                        )
                        if cross_rg_ghost_resources is not None:
                            cross_rg_ghost_resources.add((resource_name, resource_type, dep_subnet_rg))
                        logger.debug(
                            f"Added cross-RG subnet_implicit_dependency from dependsOn - {resource_name} ({resourceGroup}) -> {explicit_subnet_name_from_dep} ({dep_subnet_rg})"
                        )
                        continue
                    elif dep_subnet_rg and dep_subnet_rg == resourceGroup:
                        # Same RG — the graph_generator main loop handles placement
                        continue
                    # If we couldn't determine the subnet RG from dependsOn (ARM expression
                    # format like [resourceId(...)]), fall through to resource_handlers which
                    # uses properties.subnet.id (full resource paths) for reliable RG detection.

                properties = resource.get("properties", {})
                subnet_id: Optional[str] = None

                # Resource type mapping with concise handlers
                resource_handlers = {
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
                    "Microsoft.Sql/managedInstances": lambda p: p.get("subnetId") if p.get("subnetId") else None,
                    "Microsoft.Cache/Redis": lambda p: p.get("subnetId") if "subnetId" in p else None,
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

                # Get subnet ID using the appropriate handler
                if resource_type in resource_handlers:
                    subnet_id = resource_handlers[resource_type](properties)

                    if subnet_id:
                        # Handle complex ARM template references for subnet IDs
                        subnet_name = extract_subnet_name_from_id(subnet_id)
                        if subnet_name:
                            # Check if we should add to dependencies dict when both resources are in same RG
                            if add_to_dependencies_dict and dependencies is not None:
                                # Extract resource group from subnet ID to compare with current resource group
                                subnet_rg = None
                                logger.debug(
                                    f"Processing subnet dependency - Resource: {resource_name}, Current RG: {resourceGroup}, Subnet ID: {subnet_id}"
                                )

                                # For Bicep mode, check if both resources are in the same template context
                                if use_local_template:
                                    # In Bicep mode, if subnet_id contains a resource group reference, extract it
                                    if subnet_id.startswith("/subscriptions/") and "/resourceGroups/" in subnet_id:
                                        parts = subnet_id.split("/")
                                        if len(parts) > 4 and parts[3] == "resourceGroups":
                                            subnet_rg = parts[4]
                                            logger.debug(
                                                f"Extracted subnet RG from resource ID: {subnet_rg} (current RG: {resourceGroup})"
                                            )
                                            # Use the actual extracted RG — in multi-template Bicep mode
                                            # the subnet can be in a different RG than the current resource.
                                    else:
                                        # For simple subnet names or complex references in Bicep mode, assume same RG
                                        subnet_rg = resourceGroup
                                        logger.debug(
                                            f"Bicep mode: Simple subnet reference, treating as same RG: {subnet_rg}"
                                        )
                                else:
                                    # Azure mode: Use standard resource group extraction
                                    if subnet_id.startswith("/subscriptions/") and "/resourceGroups/" in subnet_id:
                                        parts = subnet_id.split("/")
                                        if len(parts) > 4 and parts[3] == "resourceGroups":
                                            subnet_rg = parts[4]
                                            logger.debug(
                                                f"Azure mode: Extracted subnet RG from resource ID: {subnet_rg}"
                                            )
                                    elif "[" not in subnet_id and "]" not in subnet_id:
                                        # For simple subnet names without full resource path, assume same RG
                                        subnet_rg = resourceGroup
                                        logger.debug(
                                            f"Azure mode: Simple subnet name detected, assuming same RG: {subnet_rg}"
                                        )
                                    else:
                                        # ARM expression format (e.g. [resourceId(...)]) — without explicit
                                        # subscriptionId/resourceGroupName args, ARM defaults to current scope.
                                        subnet_rg = resourceGroup
                                        logger.debug(
                                            f"Azure mode: ARM expression subnet ID, assuming same RG: {subnet_rg}"
                                        )

                                logger.debug(
                                    f"Resource group comparison - Subnet RG: '{subnet_rg}' vs Current RG: '{resourceGroup}'"
                                )

                                # Check if subnet is in the same resource group as the current resource
                                if subnet_rg == resourceGroup:
                                    # Add to dependencies dict since both resource and subnet are in same RG
                                    resource_key = (resource_name, resource_type, resourceGroup)
                                    if resource_key not in dependencies:
                                        dependencies[resource_key] = []
                                    dependencies[resource_key].append(
                                        (subnet_name, "Microsoft.Network/virtualNetworks/subnets", resourceGroup)
                                    )
                                    logger.debug(
                                        f"Added to dependencies dict - {resource_name} -> {subnet_name} (same RG: {resourceGroup})"
                                    )
                                elif subnet_rg in resource_groups:
                                    # Add to subnet_implicit_dependencies since subnet is in different RG in the allowed list
                                    subnet_implicit_dependencies[resource_name + "-" + resourceGroup] = subnet_name
                                    if cross_rg_ghost_resources is not None:
                                        cross_rg_ghost_resources.add((resource_name, resource_type, subnet_rg))
                                    logger.debug(
                                        f"Added to subnet_implicit_dependencies - {resource_name}: {subnet_id} -> {subnet_name} (cross-RG: {subnet_rg} != {resourceGroup})"
                                    )
                                elif discoverResourceGroups and resourceGroup in discoverResourceGroups and subnet_rg:
                                    # Discovery mode: Add the new resource group to the list
                                    if subnet_rg not in resource_groups:
                                        resource_groups.append(subnet_rg)
                                        logger.info(
                                            f"🔍 Discovered new resource group: {subnet_rg} (subnet dependency from {resource_name})"
                                        )
                                    # Add to subnet_implicit_dependencies
                                    subnet_implicit_dependencies[resource_name + "-" + resourceGroup] = subnet_name
                                    if cross_rg_ghost_resources is not None:
                                        cross_rg_ghost_resources.add((resource_name, resource_type, subnet_rg))
                                    logger.debug(
                                        f"Added to subnet_implicit_dependencies - {resource_name}: {subnet_id} -> {subnet_name} (discovered RG: {subnet_rg})"
                                    )
                            else:
                                # Default behavior: add to subnet_implicit_dependencies
                                subnet_implicit_dependencies[resource_name + "-" + resourceGroup] = subnet_name
                                logger.debug(
                                    f"Added subnet dependency for {resource_name}: {subnet_id} -> {subnet_name}"
                                )
        return subnet_implicit_dependencies

    except Exception as e:
        # Provide more context about where the error occurred
        context = f"resource '{resource_name}'" if resource_name != "unknown" else "during subnet dependency processing"
        logger.error(f"Error processing subnet dependencies for {context}: {str(e)}")
        # Log additional debug information
        logger.debug(f"Exception occurred in get_subnet_implicit_dependencies", exc_info=True)
        return subnet_implicit_dependencies


def get_cross_resource_group_dependencies(
    resource: Dict,
    resource_name: str,
    resource_groups: List[str],
    cross_resource_group_dependencies: Dict[str, Any],
    subscription_id: Optional[str] = None,
    resource_group: Optional[str] = None,
    discoverResourceGroups: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Extract cross-resource group dependencies from Azure resources.

    This function analyzes Private Endpoints to identify dependencies on resources
    in other resource groups. It processes:
    - Private Link Service connections (automatic)
    - Manual Private Link Service connections
    - Cross-resource group service references

    Args:
        resource: Dictionary containing resource configuration from ARM template
        resource_name: Name of the resource being processed
        resource_groups: List of valid resource group names to check against
        cross_resource_group_dependencies: Existing dictionary of dependencies
        subscription_id: Current subscription ID for subscription comparison
        resource_group: Current resource group being processed
        discoverResourceGroups: List of RG names for which discovery is enabled. None or empty = disabled.

    Returns:
        Updated dictionary mapping resource names to their dependencies with minlen values:
        {
            'resource1': {
                'targets': ['target1', 'target2'],
                'minlens': [0, 1],
                'target_subscriptions': ['sub1', 'sub2']
            }
        }
    """
    try:
        # Only process Private Endpoints
        if resource.get("type") != "Microsoft.Network/privateEndpoints":
            return cross_resource_group_dependencies

        properties = resource.get("properties", {})

        # Process both types of connections
        connection_types = [
            properties.get("privateLinkServiceConnections", []),
            properties.get("manualPrivateLinkServiceConnections", []),
        ]

        for connections in connection_types:
            for connection in connections:
                connection_props = connection.get("properties", {})
                service_id = connection_props.get("privateLinkServiceId")

                # Process only literal resource IDs (not ARM template functions)
                if service_id and "resourceId(" not in service_id:
                    # Skip if it contains ARM template functions
                    if "[" in service_id or "]" in service_id or "concat(" in service_id:
                        continue

                    # Azure resource ID format:
                    # /subscriptions/{sub-id}/resourceGroups/{rg-name}/providers/{provider}/{resource-type}/{resource-name}
                    parts = service_id.split("/")
                    if len(parts) < 5:  # Make sure we have enough parts
                        continue

                    # Extract subscription ID from the resource ID
                    target_subscription_id = parts[2] if len(parts) > 2 else None
                    resource_group_service_name = parts[4] if len(parts) > 4 else None

                    # Check if target resource group is in allowed list or discovery mode
                    if resource_group_service_name not in resource_groups:
                        if (
                            discoverResourceGroups
                            and resource_group in discoverResourceGroups
                            and resource_group_service_name
                        ):
                            # Discovery mode: Add the new resource group to the list
                            # Only add if not already present (avoid duplicates)
                            if resource_group_service_name not in resource_groups:
                                resource_groups.append(resource_group_service_name)
                                logger.info(
                                    f"🔍 Discovered new resource group: {resource_group_service_name} (PE dependency from {resource_name})"
                                )
                        else:
                            # Skip if target resource group is not in allowed list and discovery is off
                            continue  # Skip this connection but process others

                    # Extract the target resource name
                    private_link_service_name = parts[-1]

                    # Initialize the dictionary entry if it doesn't exist
                    if resource_name not in cross_resource_group_dependencies:
                        cross_resource_group_dependencies[resource_name] = {
                            "targets": [],
                            "minlens": [],
                            "target_subscriptions": [],
                            "target_resource_groups": [],  # Changed to list to support multiple targets in different RGs
                            "target_resource_types": [],  # Resource types extracted from privateLinkServiceId path
                            "source_resource_group": "",
                        }

                    # Check if the target is already in the list
                    if private_link_service_name not in cross_resource_group_dependencies[resource_name]["targets"]:
                        # Determine minlen value based on subscription comparison
                        minlen = (
                            0
                            if (
                                subscription_id and target_subscription_id and subscription_id != target_subscription_id
                            )
                            else 1
                        )

                        # Add the target and its minlen value
                        cross_resource_group_dependencies[resource_name]["targets"].append(private_link_service_name)
                        cross_resource_group_dependencies[resource_name]["minlens"].append(minlen)
                        cross_resource_group_dependencies[resource_name]["target_subscriptions"].append(
                            target_subscription_id
                        )
                        cross_resource_group_dependencies[resource_name]["target_resource_groups"].append(
                            resource_group_service_name
                        )  # Append to list
                        # Extract resource type from the privateLinkServiceId path
                        # Format: /subscriptions/{sub}/resourceGroups/{rg}/providers/{provider}/{type}/{name}
                        target_resource_type = (
                            parts[6] + "/" + parts[7] if len(parts) > 7 else "Microsoft.Resources/resources"
                        )
                        cross_resource_group_dependencies[resource_name]["target_resource_types"].append(
                            target_resource_type
                        )
                        cross_resource_group_dependencies[resource_name]["source_resource_group"] = resource_group

                        connection_type = (
                            "automatic"
                            if connection in properties.get("privateLinkServiceConnections", [])
                            else "manual"
                        )
                        same_sub_text = "different subscription" if minlen == 0 else "same subscription"
                        logger.debug(
                            f"Added cross-resource dependency ({connection_type}, {same_sub_text}): {resource_name} -> {private_link_service_name} with minlen={minlen}"
                        )

        return cross_resource_group_dependencies

    except Exception as e:
        logger.error(f"Error processing cross-resource dependencies for {resource_name}: {str(e)}")
        return cross_resource_group_dependencies
