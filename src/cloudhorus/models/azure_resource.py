"""Azure resource models."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ResourceType(Enum):
    """Common Azure resource types."""

    VIRTUAL_NETWORK = "Microsoft.Network/virtualNetworks"
    SUBNET = "Microsoft.Network/virtualNetworks/subnets"
    NETWORK_SECURITY_GROUP = "Microsoft.Network/networkSecurityGroups"
    ROUTE_TABLE = "Microsoft.Network/routeTables"
    PRIVATE_ENDPOINT = "Microsoft.Network/privateEndpoints"
    PRIVATE_DNS_ZONE = "Microsoft.Network/privateDnsZones"
    WEB_APP = "Microsoft.Web/sites"
    FUNCTION_APP = "Microsoft.Web/sites"
    STORAGE_ACCOUNT = "Microsoft.Storage/storageAccounts"
    KEY_VAULT = "Microsoft.KeyVault/vaults"
    SQL_SERVER = "Microsoft.Sql/servers"
    COSMOS_DB = "Microsoft.DocumentDB/databaseAccounts"
    BASTION_HOST = "Microsoft.Network/bastionHosts"
    MANAGED_IDENTITY = "Microsoft.ManagedIdentity/userAssignedIdentities"


@dataclass
class AzureResource:
    """Represents an Azure resource with its properties and dependencies."""

    resource_id: str
    name: str
    resource_type: str
    resource_group: str
    subscription_id: str
    tenant_id: str
    location: Optional[str] = None
    properties: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    tags: Dict[str, str] = field(default_factory=dict)

    @property
    def short_type(self) -> str:
        """Get the short type name (last part after /)."""
        if "/" in self.resource_type:
            return self.resource_type.split("/")[-1]
        return self.resource_type

    @property
    def provider(self) -> str:
        """Get the resource provider (e.g., Microsoft.Network)."""
        if "/" in self.resource_type:
            return self.resource_type.split("/")[0]
        return self.resource_type

    def has_dependency(self, resource_id: str) -> bool:
        """Check if this resource depends on another resource."""
        return resource_id in self.dependencies

    def add_dependency(self, resource_id: str) -> None:
        """Add a dependency to this resource."""
        if resource_id not in self.dependencies:
            self.dependencies.append(resource_id)


@dataclass
class VirtualNetwork(AzureResource):
    """Specialized model for Virtual Network resources."""

    address_space: List[str] = field(default_factory=list)
    subnets: List[str] = field(default_factory=list)
    peerings: List[str] = field(default_factory=list)

    def add_subnet(self, subnet_id: str) -> None:
        """Add a subnet to this VNet."""
        if subnet_id not in self.subnets:
            self.subnets.append(subnet_id)

    def add_peering(self, peering_id: str) -> None:
        """Add a peering to this VNet."""
        if peering_id not in self.peerings:
            self.peerings.append(peering_id)


@dataclass
class Subnet(AzureResource):
    """Specialized model for Subnet resources."""

    address_prefix: Optional[str] = None
    network_security_group: Optional[str] = None
    route_table: Optional[str] = None
    service_endpoints: List[str] = field(default_factory=list)
    delegations: List[str] = field(default_factory=list)


@dataclass
class PrivateEndpoint(AzureResource):
    """Specialized model for Private Endpoint resources."""

    subnet_id: Optional[str] = None
    private_link_service_id: Optional[str] = None
    group_ids: List[str] = field(default_factory=list)
