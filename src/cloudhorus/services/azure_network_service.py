"""Azure Network Service for managing network resources.

This module provides operations for interacting with Azure network resources
including VNets, subnets, private endpoints, DNS zones, and Bastion hosts.
"""

from typing import Any, Dict, List, Optional, cast

from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError
from azure.core.pipeline.policies import RetryPolicy
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient

from cloudhorus.services.base import BaseService


class AzureNetworkService(BaseService):
    """Service for Azure network resource operations.

    This service provides methods for querying and analyzing Azure network
    resources, with support for both live Azure queries and Bicep template analysis.

    Attributes:
        resource_clients: Cache of ResourceManagementClient instances by subscription
        network_clients: Cache of NetworkManagementClient instances by subscription
        template_registry: Optional template registry service for template-based queries
    """

    def __init__(self, credential, template_registry=None):
        """Initialize the Azure Network Service.

        Args:
            credential: Azure credential object for authentication
            template_registry: Optional TemplateRegistryService for template-based analysis
        """
        super().__init__()
        self._credential = credential
        self._template_registry = template_registry
        self._resource_clients = {}
        self._network_clients = {}

    def validate(self) -> bool:
        """Validate the service is properly configured.

        Returns:
            True if service is valid
        """
        try:
            self.logger.info("AzureNetworkService validated successfully")
            return True
        except Exception as e:
            self.logger.error(f"AzureNetworkService validation failed: {e}")
            return False

    def _get_resource_client(self, subscription_id: str) -> ResourceManagementClient:
        """Get or create a resource management client for a subscription.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            ResourceManagementClient for the specified subscription
        """
        if subscription_id not in self._resource_clients:
            self._resource_clients[subscription_id] = ResourceManagementClient(
                self._credential, subscription_id, retry_policy=RetryPolicy()
            )
        return cast(ResourceManagementClient, self._resource_clients[subscription_id])

    def _get_network_client(self, subscription_id: str) -> NetworkManagementClient:
        """Get or create a network management client for a subscription.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            NetworkManagementClient for the specified subscription
        """
        if subscription_id not in self._network_clients:
            self._network_clients[subscription_id] = NetworkManagementClient(
                self._credential, subscription_id, retry_policy=RetryPolicy()
            )
        return cast(NetworkManagementClient, self._network_clients[subscription_id])

    def get_pe_subnet_name(self, pe_name: str, resource_group: str, subscription_id: str) -> Optional[str]:
        """Get the subnet name for a private endpoint.

        Args:
            pe_name: Name of the private endpoint
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            Subnet name if found, None otherwise

        Example:
            >>> service.get_pe_subnet_name("pe-storage", "rg-prod", "sub-...")
            "snet-private-endpoints"
        """
        try:
            network_client = self._get_network_client(subscription_id)
            pe = network_client.private_endpoints.get(resource_group, pe_name)
            if pe.subnet and pe.subnet.id:
                # Extract subnet name from the subnet ID
                return str(pe.subnet.id.split("/")[-1])
            return None
        except ResourceNotFoundError:
            self.logger.debug(f"Private endpoint {pe_name} not found in RG {resource_group} — may belong to another RG")
            return None
        except Exception as e:
            self.logger.debug(f"Could not get subnet for private endpoint {pe_name}: {e}")
            return None

    def get_private_dns_zones(
        self,
        resource_group: str,
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Get private DNS zones in a resource group.

        Supports both live Azure queries and Bicep template analysis.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template instead of Azure
            template_data: The ARM template data (when use_local_template=True)

        Returns:
            List of private DNS zones with their properties

        Example:
            >>> service.get_private_dns_zones("rg-prod", "sub-...", False)
            [
                {
                    'id': '/subscriptions/.../privateDnsZones/privatelink.blob.core.windows.net',
                    'name': 'privatelink.blob.core.windows.net',
                    'type': 'Microsoft.Network/privateDnsZones',
                    'location': 'global'
                }
            ]
        """
        if use_local_template:
            # Check if we have multiple templates registered
            if self._template_registry and self._template_registry.is_using_multiple_templates():
                # Get template data for this specific resource group
                rg_template_data = self._template_registry.get_template_data_for_resource_group(resource_group)
                if rg_template_data:
                    return self._get_private_dns_zones_from_template(rg_template_data, resource_group)
                else:
                    self.logger.warning(f"No template data found for resource group '{resource_group}'")
                    return []
            elif template_data:
                # Single template mode with provided template data
                return self._get_private_dns_zones_from_template(template_data, resource_group)
            else:
                self.logger.warning("use_local_template=True but no template data available")
                return []
        else:
            return self._get_private_dns_zones_from_azure(resource_group, subscription_id)

    def _get_private_dns_zones_from_template(
        self, template_data: Dict[str, Any], resource_group: str
    ) -> List[Dict[str, Any]]:
        """Extract private DNS zones from ARM/Bicep template data.

        Args:
            template_data: The ARM template data
            resource_group: Name of the resource group (for context)

        Returns:
            List of private DNS zones
        """
        try:
            resources = template_data.get("resources", [])
            dns_zones = []

            for resource in resources:
                resource_type = resource.get("type", "")

                if resource_type == "Microsoft.Network/privateDnsZones":
                    dns_zones.append(
                        {
                            "id": f"[resourceId('Microsoft.Network/privateDnsZones', '{resource.get('name', '')}')]",
                            "name": resource.get("name", ""),
                            "type": resource_type,
                            "location": resource.get("location", "global"),
                        }
                    )

            return dns_zones

        except Exception as e:
            self.logger.error(f"Failed to get private DNS zones from template: {e}")
            return []

    def _get_private_dns_zones_from_azure(self, resource_group: str, subscription_id: str) -> List[Dict[str, Any]]:
        """Query private DNS zones from Azure.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            List of private DNS zones
        """
        try:
            resource_client = self._get_resource_client(subscription_id)

            # Filter for private DNS zone resources
            filter_str = "resourceType eq 'Microsoft.Network/privateDnsZones'"
            zones = resource_client.resources.list_by_resource_group(
                resource_group_name=resource_group, filter=filter_str
            )

            result = []
            for zone in zones:
                result.append({"id": zone.id, "name": zone.name, "type": zone.type, "location": zone.location})
            return result

        except ResourceNotFoundError:
            return []
        except ClientAuthenticationError as auth_error:
            if any(term in str(auth_error) for term in ["Unauthorized", "Forbidden", "401", "403"]):
                self.logger.warning(
                    f"Permission issue when listing private DNS zones in '{resource_group}': "
                    f"You may not have sufficient permissions"
                )
            else:
                self.logger.error(
                    f"Authentication error when listing private DNS zones in {resource_group}: " f"{auth_error}"
                )
            return []
        except Exception as e:
            error_str = str(e).lower()
            if any(
                term in error_str for term in ["unauthorized", "forbidden", "permission", "access denied", "401", "403"]
            ):
                self.logger.warning(f"Permission issue when listing private DNS zones in '{resource_group}'")
            elif "resourcegroupnotfound" in error_str or "could not be found" in error_str:
                self.logger.warning(f"Resource group '{resource_group}' could not be found")
            else:
                self.logger.error(f"Failed to list private DNS zones in {resource_group}: {e}")
            return []

    def get_private_dns_zones_without_vnets(
        self,
        resource_group: str,
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Get private DNS zones in resource groups that have no VNets.

        This method returns DNS zone names only if the resource group
        contains no virtual networks.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template
            template_data: The ARM template data (when use_local_template=True)

        Returns:
            List of DNS zone names if no VNets exist, empty list otherwise

        Example:
            >>> service.get_private_dns_zones_without_vnets("rg-dns-only", "sub-...")
            ["privatelink.blob.core.windows.net", "privatelink.vault.azure.net"]
        """
        if use_local_template:
            if self._template_registry and self._template_registry.is_using_multiple_templates():
                rg_template_data = self._template_registry.get_template_data_for_resource_group(resource_group)
                if rg_template_data:
                    return self._get_private_dns_zones_without_vnets_from_template(rg_template_data, resource_group)
                else:
                    self.logger.warning(f"No template data found for resource group '{resource_group}'")
                    return []
            elif template_data:
                return self._get_private_dns_zones_without_vnets_from_template(template_data, resource_group)
            else:
                self.logger.warning("use_local_template=True but no template data available")
                return []
        else:
            return self._get_private_dns_zones_without_vnets_from_azure(resource_group, subscription_id)

    def _get_private_dns_zones_without_vnets_from_template(
        self, template_data: Dict[str, Any], resource_group: str
    ) -> List[str]:
        """Analyze template to find DNS zones in RGs with no VNets.

        Args:
            template_data: The ARM template data
            resource_group: Name of the resource group (for logging)

        Returns:
            List of DNS zone names if no VNets, empty list otherwise
        """
        try:
            resources = template_data.get("resources", [])

            # Check for VNets and DNS zones
            vnets = []
            dns_zones = []

            for resource in resources:
                resource_type = resource.get("type", "")
                resource_name = resource.get("name", "")

                if resource_type == "Microsoft.Network/virtualNetworks":
                    vnets.append(resource_name)
                elif resource_type == "Microsoft.Network/privateDnsZones":
                    dns_zones.append(resource_name)

            # If VNets exist, return empty list
            if vnets:
                self.logger.debug(f"Template contains {len(vnets)} VNet(s). Skipping DNS zone lookup.")
                return []

            # No VNets found, return DNS zone names if any
            if dns_zones:
                self.logger.info(f"Found {len(dns_zones)} private DNS zone(s) with no VNets: {dns_zones}")
                return dns_zones
            else:
                self.logger.debug(f"No private DNS zones found in template for '{resource_group}'")
                return []

        except Exception as e:
            self.logger.error(f"Failed to analyze template for DNS zones without VNets: {e}")
            return []

    def _get_private_dns_zones_without_vnets_from_azure(self, resource_group: str, subscription_id: str) -> List[str]:
        """Query Azure for DNS zones in RGs with no VNets.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            List of DNS zone names if no VNets, empty list otherwise
        """
        try:
            resource_client = self._get_resource_client(subscription_id)

            # Check for VNets in the resource group
            vnet_filter = "resourceType eq 'Microsoft.Network/virtualNetworks'"
            vnets = list(
                resource_client.resources.list_by_resource_group(resource_group_name=resource_group, filter=vnet_filter)
            )

            # If VNets exist, return empty list
            if vnets:
                self.logger.debug(
                    f"Resource group '{resource_group}' contains {len(vnets)} VNet(s). " f"Skipping DNS zone lookup."
                )
                return []

            # No VNets found, check for private DNS zones
            dns_zones = self._get_private_dns_zones_from_azure(resource_group, subscription_id)

            if dns_zones:
                zone_names = [zone["name"] for zone in dns_zones]
                return zone_names
            else:
                return []

        except ResourceNotFoundError:
            self.logger.warning(f"Resource group '{resource_group}' not found")
            return []
        except ClientAuthenticationError as auth_error:
            if any(term in str(auth_error) for term in ["Unauthorized", "Forbidden", "401", "403"]):
                self.logger.warning(f"Permission issue when checking resource group '{resource_group}'")
            else:
                self.logger.error(
                    f"Authentication error when checking resource group {resource_group}: " f"{auth_error}"
                )
            return []
        except Exception as e:
            error_str = str(e).lower()
            if any(
                term in error_str for term in ["unauthorized", "forbidden", "permission", "access denied", "401", "403"]
            ):
                self.logger.warning(f"Permission issue when checking resource group '{resource_group}'")
            elif "resourcegroupnotfound" in error_str or "could not be found" in error_str:
                self.logger.warning(f"Resource group '{resource_group}' could not be found")
            else:
                self.logger.error(f"Failed to check DNS zones without VNets in {resource_group}: {e}")
            return []

    def is_vnet_linked_to_private_dns_zone(
        self,
        vnet_name: str,
        resource_groups: List[str],
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """Get list of private DNS zone names that a VNet is linked to.

        Args:
            vnet_name: Name of the virtual network
            resource_groups: List of resource group names to search
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template
            template_data: The ARM template data (when use_local_template=True)

        Returns:
            List of DNS zone names the VNet is linked to

        Example:
            >>> service.is_vnet_linked_to_private_dns_zone(
            ...     "vnet-prod", ["rg-prod", "rg-shared"], "sub-..."
            ... )
            ["privatelink.blob.core.windows.net", "privatelink.vault.azure.net"]
        """
        if use_local_template:
            if self._template_registry and self._template_registry.is_using_multiple_templates():
                # Collect linked zones from all templates for specified resource groups
                all_linked_zones = []
                for rg in resource_groups:
                    rg_template_data = self._template_registry.get_template_data_for_resource_group(rg)
                    if rg_template_data:
                        linked_zones = self._get_vnet_linked_dns_zones_from_template(rg_template_data, vnet_name, [rg])
                        all_linked_zones.extend(linked_zones)
                    else:
                        self.logger.debug(f"No template data found for resource group '{rg}'")

                # Remove duplicates while preserving order
                seen = set()
                unique_zones = []
                for zone in all_linked_zones:
                    if zone not in seen:
                        seen.add(zone)
                        unique_zones.append(zone)

                return unique_zones
            elif template_data:
                return self._get_vnet_linked_dns_zones_from_template(template_data, vnet_name, resource_groups)
            else:
                self.logger.warning("use_local_template=True but no template data available")
                return []
        else:
            return self._get_vnet_linked_dns_zones_from_azure(vnet_name, resource_groups, subscription_id)

    def _get_vnet_linked_dns_zones_from_template(
        self, template_data: Dict[str, Any], vnet_name: str, resource_groups: List[str]
    ) -> List[str]:
        """Analyze template to find DNS zones linked to a VNet.

        Args:
            template_data: The ARM template data
            vnet_name: Name of the virtual network
            resource_groups: List of resource group names (for context)

        Returns:
            List of DNS zone names linked to the VNet
        """
        try:
            resources = template_data.get("resources", [])
            linked_zones = []

            # First, find all private DNS zones
            dns_zones = []
            for resource in resources:
                if resource.get("type", "") == "Microsoft.Network/privateDnsZones":
                    dns_zones.append(resource.get("name", ""))

            # Then, find virtual network links referencing our VNet
            for resource in resources:
                resource_type = resource.get("type", "")

                if resource_type == "Microsoft.Network/privateDnsZones/virtualNetworkLinks":
                    properties = resource.get("properties", {})
                    virtual_network = properties.get("virtualNetwork", {})
                    vnet_reference = virtual_network.get("id", "")

                    # Extract VNet name from various possible formats
                    referenced_vnet_name = None

                    if isinstance(vnet_reference, str):
                        if vnet_reference == vnet_name:
                            referenced_vnet_name = vnet_name
                        elif "resourceId(" in vnet_reference or "[" in vnet_reference:
                            if ("'" + vnet_name + "'") in vnet_reference or ('"' + vnet_name + '"') in vnet_reference:
                                referenced_vnet_name = vnet_name
                        elif "/" in vnet_reference:
                            referenced_vnet_name = vnet_reference.split("/")[-1]

                    # If this link references our VNet, find which DNS zone it belongs to
                    if referenced_vnet_name == vnet_name:
                        resource_name = resource.get("name", "")
                        if "/" in resource_name:
                            # Handle nested format: "zone_name/link_name"
                            zone_name = resource_name.split("/")[0]
                            if zone_name in dns_zones and zone_name not in linked_zones:
                                linked_zones.append(zone_name)
                        else:
                            # Handle dependency-based linking
                            depends_on = resource.get("dependsOn", [])
                            for dependency in depends_on:
                                if isinstance(dependency, str) and "privateDnsZones" in dependency:
                                    for zone_name in dns_zones:
                                        if zone_name in dependency and zone_name not in linked_zones:
                                            linked_zones.append(zone_name)

            if linked_zones:
                self.logger.info(f"VNet '{vnet_name}' is linked to private DNS zones: {linked_zones}")
            else:
                self.logger.debug(f"VNet '{vnet_name}' is not linked to any private DNS zones in template")

            return linked_zones

        except Exception as e:
            self.logger.error(f"Failed to analyze template for VNet DNS zone links: {e}")
            return []

    def _get_vnet_linked_dns_zones_from_azure(
        self, vnet_name: str, resource_groups: List[str], subscription_id: str
    ) -> List[str]:
        """Query Azure for DNS zones linked to a VNet.

        Args:
            vnet_name: Name of the virtual network
            resource_groups: List of resource group names to search
            subscription_id: Azure subscription ID

        Returns:
            List of DNS zone names linked to the VNet
        """
        try:
            resource_client = self._get_resource_client(subscription_id)
            linked_zones = []

            # Get DNS zones from all resource groups
            for resource_group in resource_groups:
                dns_zones = self.get_private_dns_zones(resource_group, subscription_id, False)

                if not dns_zones:
                    continue

                for zone in dns_zones:
                    try:
                        # Filter for virtual network links
                        filter_str = "resourceType eq 'Microsoft.Network/privateDnsZones/virtualNetworkLinks'"

                        vnet_links = resource_client.resources.list_by_resource_group(
                            resource_group_name=resource_group, filter=filter_str
                        )

                        # Check if any links reference our VNet
                        for link in vnet_links:
                            try:
                                link_id = link.id
                                if link_id is None:
                                    continue
                                props = resource_client.resources.get_by_id(link_id, "2020-06-01").properties
                                if props and "virtualNetwork" in props:
                                    vnet_id = props["virtualNetwork"].get("id", "")
                                    linked_vnet_name = vnet_id.split("/")[-1]
                                    if linked_vnet_name == vnet_name:
                                        linked_zones.append(zone["name"])
                                        break
                            except Exception as link_error:
                                self.logger.debug(f"Error checking VNet link {link.id}: {link_error}")
                                continue
                    except Exception as zone_error:
                        self.logger.debug(
                            f"Error checking zone {zone['name']} in resource group {resource_group}: " f"{zone_error}"
                        )
                        continue

            if linked_zones:
                self.logger.info(f"VNet '{vnet_name}' is linked to private DNS zones: {linked_zones}")
            else:
                self.logger.warning(f"VNet '{vnet_name}' is not linked to any private DNS zones")

            return linked_zones

        except Exception as e:
            self.logger.error(f"Error checking VNet links to private DNS zones: {e}")
            return []

    def get_bastion_host_name(
        self,
        vnet_name: str,
        resource_group: str,
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Get the name of Bastion Host linked to a Virtual Network.

        Args:
            vnet_name: Name of the virtual network
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template
            template_data: The ARM template data (when use_local_template=True)

        Returns:
            Bastion Host name if found, None otherwise

        Example:
            >>> service.get_bastion_host_name("vnet-prod", "rg-prod", "sub-...")
            "bastion-prod"
        """
        if use_local_template:
            if self._template_registry and self._template_registry.is_using_multiple_templates():
                rg_template_data = self._template_registry.get_template_data_for_resource_group(resource_group)
                if rg_template_data:
                    return self._get_bastion_host_name_from_template(rg_template_data, vnet_name, resource_group)
                else:
                    self.logger.warning(f"No template data found for resource group '{resource_group}'")
                    return None
            elif template_data:
                return self._get_bastion_host_name_from_template(template_data, vnet_name, resource_group)
            else:
                self.logger.warning("use_local_template=True but no template data available")
                return None
        else:
            return self._get_bastion_host_name_from_azure(vnet_name, resource_group, subscription_id)

    def _get_bastion_host_name_from_template(
        self, template_data: Dict[str, Any], vnet_name: str, resource_group: str
    ) -> Optional[str]:
        """Analyze template to find Bastion Host linked to a VNet.

        Args:
            template_data: The ARM template data
            vnet_name: Name of the virtual network
            resource_group: Name of the resource group (for logging)

        Returns:
            Bastion Host name if found, None otherwise
        """
        try:
            resources = template_data.get("resources", [])

            # Find Bastion Hosts in the template
            for resource in resources:
                resource_type = resource.get("type", "")

                if resource_type == "Microsoft.Network/bastionHosts":
                    bastion_name = resource.get("name", "")
                    properties = resource.get("properties", {})
                    ip_configurations = properties.get("ipConfigurations", [])

                    for ip_config in ip_configurations:
                        subnet_ref = ip_config.get("properties", {}).get("subnet", {}).get("id", "")

                        # Extract VNet name from subnet reference
                        referenced_vnet_name = None

                        if isinstance(subnet_ref, str):
                            if "resourceId(" in subnet_ref or "[" in subnet_ref:
                                if ("'" + vnet_name + "'") in subnet_ref or ('"' + vnet_name + '"') in subnet_ref:
                                    referenced_vnet_name = vnet_name
                            elif "/" in subnet_ref and "virtualNetworks" in subnet_ref:
                                parts = subnet_ref.split("/")
                                for i, part in enumerate(parts):
                                    if part == "virtualNetworks" and i + 1 < len(parts):
                                        referenced_vnet_name = parts[i + 1]
                                        break

                        if referenced_vnet_name == vnet_name:
                            self.logger.info(f"Found Bastion Host '{bastion_name}' for VNet '{vnet_name}' in template")
                            return str(bastion_name) if bastion_name is not None else None

            self.logger.debug(f"No Bastion Host found for VNet '{vnet_name}' in template")
            return None

        except Exception as e:
            self.logger.error(f"Failed to analyze template for Bastion Host: {e}")
            return None

    def _get_bastion_host_name_from_azure(
        self, vnet_name: str, resource_group: str, subscription_id: str
    ) -> Optional[str]:
        """Query Azure for Bastion Host linked to a VNet.

        Args:
            vnet_name: Name of the virtual network
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            Bastion Host name if found, None otherwise
        """
        try:
            network_client = self._get_network_client(subscription_id)
            bastions = network_client.bastion_hosts.list_by_resource_group(resource_group)

            for bastion in bastions:
                if bastion.virtual_network and bastion.virtual_network.id:
                    bastion_vnet_name = bastion.virtual_network.id.split("/")[-1]
                    if bastion_vnet_name == vnet_name:
                        self.logger.info(f"Found Bastion Host '{bastion.name}' for VNet '{vnet_name}'")
                        return str(bastion.name) if bastion.name is not None else None

            return None

        except Exception as e:
            self.logger.error(f"Failed to list bastion hosts for VNet {vnet_name}: {e}")
            return None
