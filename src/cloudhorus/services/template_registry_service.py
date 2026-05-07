"""Template Registry Service for managing Bicep template mappings.

This module provides operations for registering and managing multiple Bicep
templates with their associated resource groups, subscriptions, and tenants.
"""

from typing import Any, Dict, List, Optional, cast

from azure.mgmt.subscription import SubscriptionClient

from cloudhorus.services.base import BaseService


class TemplateRegistryService(BaseService):
    """Service for managing Bicep template mappings across Azure resources.

    This service maintains the relationships between Bicep templates and their
    corresponding resource groups, subscriptions, and tenants. It provides
    fast lookup capabilities for template-driven infrastructure analysis.

    Attributes:
        templates: List of ARM template data (compiled from Bicep)
        resource_groups: Corresponding resource groups for each template
        subscriptions: Corresponding subscriptions for each template
        tenants: Corresponding tenants for each template
        rg_to_subscription: Direct mapping from RG name to subscription ID
        subscription_to_tenant: Direct mapping from subscription ID to tenant ID
        template_index_map: Quick lookup to find template index by RG name
    """

    def __init__(self, credential=None):
        """Initialize the Template Registry Service.

        Args:
            credential: Optional Azure credential for tenant discovery
        """
        super().__init__()
        self._credential = credential
        self._subscription_client = None
        self._initialize_mappings()

    def _initialize_mappings(self):
        """Initialize empty template mapping storage structures."""
        self._mappings = {
            "templates": [],
            "resource_groups": [],
            "subscriptions": [],
            "tenants": [],
            "rg_to_subscription": {},
            "subscription_to_tenant": {},
            "template_index_map": {},
        }

    def validate(self) -> bool:
        """Validate the service is properly configured.

        Returns:
            True if service is valid (always True for registry)
        """
        self.logger.info("TemplateRegistryService validated successfully")
        return True

    def register_multiple_templates(
        self,
        templates_data: List[Dict[str, Any]],
        resource_groups: List[str],
        subscriptions: List[str],
        tenants: Optional[List[str]] = None,
    ) -> bool:
        """Register multiple Bicep templates with their Azure resource mappings.

        This method establishes the relationships between compiled Bicep templates
        and their target deployment locations (resource groups, subscriptions, tenants).

        Args:
            templates_data: List of ARM template data (compiled from Bicep files)
            resource_groups: List of resource group names (index-aligned with templates)
            subscriptions: List of subscription IDs (index-aligned with templates)
            tenants: Optional list of tenant IDs (index-aligned with templates)

        Returns:
            True if registration successful, False otherwise

        Raises:
            ValueError: If list lengths don't match

        Example:
            >>> service.register_multiple_templates(
            ...     templates_data=[template1, template2],
            ...     resource_groups=["rg-prod", "rg-dev"],
            ...     subscriptions=["sub1-...", "sub2-..."],
            ...     tenants=["tenant1-...", "tenant2-..."]
            ... )
            True
        """
        try:
            # Validate input lengths match
            if not (len(templates_data) == len(resource_groups) == len(subscriptions)):
                raise ValueError("Templates, resource groups, and subscriptions lists must have the same length")

            if tenants and len(tenants) != len(templates_data):
                raise ValueError("If provided, tenants list must have the same length as templates")

            # If no tenants provided, try to discover them from subscriptions
            if not tenants:
                self.logger.info("No tenants provided, attempting to discover from subscriptions")
                tenants = []
                for subscription_id in subscriptions:
                    tenant_id = self._discover_tenant_for_subscription(subscription_id)
                    tenants.append(tenant_id or "")

            # Clear existing mappings
            self._initialize_mappings()

            # Store the mappings
            self._mappings["templates"] = templates_data
            self._mappings["resource_groups"] = resource_groups
            self._mappings["subscriptions"] = subscriptions
            self._mappings["tenants"] = tenants

            # Build quick lookup mappings
            for i, (rg, sub, tenant) in enumerate(zip(resource_groups, subscriptions, tenants)):
                self._mappings["rg_to_subscription"][rg] = sub
                self._mappings["subscription_to_tenant"][sub] = tenant
                self._mappings["template_index_map"][rg] = i

            self.logger.info(f"Successfully registered {len(templates_data)} Bicep templates with their mappings")
            return True

        except Exception as e:
            self.logger.error(f"Failed to register multiple Bicep templates: {e}")
            return False

    def _discover_tenant_for_subscription(self, subscription_id: str) -> Optional[str]:
        """Discover the tenant ID for a given subscription using Azure SDK.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            Tenant ID if found, None otherwise
        """
        try:
            if self._credential and self._subscription_client is None:
                self._subscription_client = SubscriptionClient(self._credential)

            if self._subscription_client:
                subscription = self._subscription_client.subscriptions.get(subscription_id)
                # In azure-mgmt-subscription v3, Subscription may not have tenant_id
                tid = getattr(subscription, "tenant_id", None)
                if tid:
                    return str(tid)
                self.logger.warning(
                    f"Subscription model lacks tenant_id; cannot auto-discover tenant for {subscription_id}"
                )
                return None
            else:
                self.logger.warning(f"No credential provided for tenant discovery for subscription {subscription_id}")
                return None

        except Exception as e:
            self.logger.warning(f"Could not discover tenant for subscription {subscription_id}: {e}")
            return None

    def get_template_data_for_resource_group(self, resource_group: str) -> Optional[Dict[str, Any]]:
        """Retrieve template data for a specific resource group.

        Args:
            resource_group: Name of the resource group

        Returns:
            ARM template data dictionary if found, None otherwise

        Example:
            >>> service.get_template_data_for_resource_group("rg-production")
            {'$schema': '...', 'resources': [...], ...}
        """
        try:
            if resource_group in self._mappings["template_index_map"]:
                index = self._mappings["template_index_map"][resource_group]
                return cast(Optional[Dict[str, Any]], self._mappings["templates"][index])
            return None
        except Exception as e:
            self.logger.error(f"Error getting template data for resource group {resource_group}: {e}")
            return None

    def get_subscription_for_resource_group(self, resource_group: str) -> Optional[str]:
        """Get the subscription ID associated with a resource group.

        Args:
            resource_group: Name of the resource group

        Returns:
            Subscription ID if found, None otherwise

        Example:
            >>> service.get_subscription_for_resource_group("rg-production")
            "b32d2aa3-1234-5678-9abc-def012345678"
        """
        return cast(Optional[str], self._mappings["rg_to_subscription"].get(resource_group))

    def get_tenant_for_subscription(self, subscription_id: str) -> Optional[str]:
        """Get the tenant ID associated with a subscription.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            Tenant ID if found, None otherwise

        Example:
            >>> service.get_tenant_for_subscription("b32d2aa3-...")
            "7d7761c0-1234-5678-9abc-def012345678"
        """
        return cast(Optional[str], self._mappings["subscription_to_tenant"].get(subscription_id))

    def get_all_registered_resource_groups(self) -> List[str]:
        """Get all registered resource groups.

        Returns:
            List of all registered resource group names

        Example:
            >>> service.get_all_registered_resource_groups()
            ["rg-production", "rg-staging", "rg-dev"]
        """
        return list(self._mappings["resource_groups"])

    def get_all_registered_subscriptions(self) -> List[str]:
        """Get all unique registered subscriptions.

        Returns:
            List of unique subscription IDs

        Example:
            >>> service.get_all_registered_subscriptions()
            ["b32d2aa3-...", "f0f45244-..."]
        """
        return list(set(self._mappings["subscriptions"]))

    def get_all_registered_tenants(self) -> List[str]:
        """Get all unique registered tenants (excluding None values).

        Returns:
            List of unique tenant IDs

        Example:
            >>> service.get_all_registered_tenants()
            ["7d7761c0-...", "8e8872d1-..."]
        """
        return list(set(filter(None, self._mappings["tenants"])))

    def is_using_multiple_templates(self) -> bool:
        """Check if multiple Bicep templates are currently registered.

        Returns:
            True if at least one template is registered, False otherwise

        Example:
            >>> service.is_using_multiple_templates()
            True
        """
        return len(self._mappings["templates"]) > 0

    def get_template_count(self) -> int:
        """Get the number of registered templates.

        Returns:
            Count of registered templates

        Example:
            >>> service.get_template_count()
            3
        """
        return len(self._mappings["templates"])

    def is_resource_group_registered(self, resource_group: str) -> bool:
        """Check if a resource group is registered in the template mappings.

        Args:
            resource_group: Name of the resource group

        Returns:
            True if resource group is registered, False otherwise

        Example:
            >>> service.is_resource_group_registered("rg-production")
            True
        """
        return resource_group in self._mappings["template_index_map"]

    def clear_registrations(self):
        """Clear all registered template mappings.

        This is useful when switching between different sets of templates
        or cleaning up before a new registration.
        """
        self._initialize_mappings()
        self.logger.info("Cleared all template registrations")

    def get_registration_summary(self) -> Dict[str, Any]:
        """Get a summary of all registered templates and mappings.

        Returns:
            Dictionary containing counts and statistics about registered templates

        Example:
            >>> service.get_registration_summary()
            {
                'total_templates': 3,
                'total_resource_groups': 3,
                'unique_subscriptions': 2,
                'unique_tenants': 1,
                'resource_groups': ['rg-prod', 'rg-staging', 'rg-dev']
            }
        """
        return {
            "total_templates": len(self._mappings["templates"]),
            "total_resource_groups": len(self._mappings["resource_groups"]),
            "unique_subscriptions": len(set(self._mappings["subscriptions"])),
            "unique_tenants": len(set(filter(None, self._mappings["tenants"]))),
            "resource_groups": self._mappings["resource_groups"].copy(),
            "subscriptions": list(set(self._mappings["subscriptions"])),
            "tenants": list(set(filter(None, self._mappings["tenants"]))),
        }
