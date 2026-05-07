"""Azure Resource Service for managing subscriptions and resource groups.

This module provides operations for interacting with Azure subscriptions,
resource groups, and ARM template exports using the Azure SDK.
"""

import json
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, cast

from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError
from azure.core.pipeline.policies import RetryPolicy
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.models import ExportTemplateRequest
from azure.mgmt.subscription import SubscriptionClient

from cloudhorus.services.base import BaseService


class AzureResourceService(BaseService):
    """Service for Azure subscription and resource group operations.

    Attributes:
        subscription_client: Client for subscription operations
        resource_clients: Cache of ResourceManagementClient instances by subscription
    """

    def __init__(self, credential):
        """Initialize the Azure Resource Service.

        Args:
            credential: Azure credential object for authentication
        """
        super().__init__()
        self._credential = credential
        self._subscription_client = None
        self._resource_clients = {}  # Cache clients by subscription_id

    def validate(self) -> bool:
        """Validate the service is properly configured.

        Returns:
            True if service is valid and can connect to Azure
        """
        try:
            client = self._get_subscription_client()
            # Try to list subscriptions as a validation test
            list(client.subscriptions.list())
            self.logger.info("AzureResourceService validated successfully")
            return True
        except Exception as e:
            self.logger.error(f"AzureResourceService validation failed: {e}")
            return False

    def _get_subscription_client(self) -> SubscriptionClient:
        """Get or create the subscription client.

        Returns:
            Configured SubscriptionClient instance
        """
        if self._subscription_client is None:
            self._subscription_client = SubscriptionClient(self._credential)
        return cast(SubscriptionClient, self._subscription_client)

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

    def get_subscription_name(self, subscription_id: str) -> Optional[str]:
        """Get subscription display name from subscription ID.

        Args:
            subscription_id: Azure subscription ID (GUID)

        Returns:
            Subscription display name if found, None otherwise

        Example:
            >>> service.get_subscription_name("b32d2aa3-1234-5678-9abc-def012345678")
            "My Production Subscription"
        """
        try:
            client = self._get_subscription_client()
            subscription = client.subscriptions.get(subscription_id)
            return str(subscription.display_name) if subscription.display_name is not None else None
        except ResourceNotFoundError:
            self.logger.error(f"Subscription {subscription_id} not found")
            return None
        except ClientAuthenticationError as auth_error:
            error_str = str(auth_error).lower()
            if any(
                term in error_str for term in ["invalidauthenticationtokentenant", "tenant", "directory", "aadsts50020"]
            ):
                self.logger.warning(f"Subscription {subscription_id} appears to be in a different tenant")
            else:
                self.logger.error(f"Authentication error getting subscription {subscription_id}: {auth_error}")
            return None
        except Exception as e:
            error_str = str(e).lower()
            if any(term in error_str for term in ["tenant", "directory", "aadsts", "token"]):
                self.logger.warning(
                    f"Possible tenant-related issue when accessing subscription {subscription_id}: {e}. "
                    f"You may need to switch tenants or reauthenticate."
                )
            else:
                self.logger.error(f"Failed to get subscription name for {subscription_id}: {e}")
            return None

    def get_resource_group_location(self, resource_group_name: str, subscription_id: str) -> Optional[str]:
        """Get the Azure region location of a resource group.

        Args:
            resource_group_name: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            Azure region (e.g., "eastus", "westeurope") if found, None otherwise

        Example:
            >>> service.get_resource_group_location("rg-production", "b32d2aa3-...")
            "eastus"
        """
        try:
            client = self._get_resource_client(subscription_id)
            resource_group = client.resource_groups.get(resource_group_name)
            return str(resource_group.location) if resource_group.location is not None else None
        except ResourceNotFoundError:
            self.logger.error(f"Resource group {resource_group_name} not found")
            return None
        except Exception as e:
            self.logger.error(f"Failed to get location for resource group {resource_group_name}: {e}")
            return None

    def export_resource_group_template(self, subscription_id: str, resource_group_name: str) -> Optional[str]:
        """Export a resource group as an ARM template JSON file.

        This method exports all resources in a resource group to an ARM template.
        The template is saved to a file named '{resource_group_name}-template.json'.

        Args:
            subscription_id: Azure subscription ID
            resource_group_name: Name of the resource group to export

        Returns:
            Path to the exported template file if successful, None otherwise

        Example:
            >>> service.export_resource_group_template("b32d2aa3-...", "rg-production")
            "rg-production-template.json"
        """
        output_file = f"{resource_group_name}-template.json"

        try:
            # Use ResourceManagementClient's export_template method
            client = self._get_resource_client(subscription_id)

            export_params = ExportTemplateRequest(
                resources=["*"],
                options="SkipAllParameterization",
            )

            export_result = client.resource_groups.begin_export_template(
                resource_group_name=resource_group_name,
                parameters=export_params,
            ).result()

            # Write template to file
            with open(output_file, "w", encoding="utf-8") as file:
                file.write(json.dumps(export_result.template, indent=2))

            self.logger.info(f"Successfully exported resource group template to {output_file}")
            return output_file

        except AttributeError as e:
            # Fallback to Azure CLI if SDK method not available
            self.logger.warning(f"SDK method not available, falling back to CLI: {e}")
            return self._export_via_cli(subscription_id, resource_group_name, output_file)

        except Exception as e:
            self.logger.error(f"Failed to export resource group template: {e}")
            return None

    def _export_via_cli(self, subscription_id: str, resource_group_name: str, output_file: str) -> Optional[str]:
        """Fallback method to export template using Azure CLI.

        Args:
            subscription_id: Azure subscription ID
            resource_group_name: Name of the resource group
            output_file: Path where template should be saved

        Returns:
            Path to exported file if successful, None otherwise
        """
        try:
            cmd = [
                "az",
                "group",
                "export",
                "--subscription",
                subscription_id,
                "--name",
                resource_group_name,
                "--skip-all-params",
                "--output",
                "json",
            ]

            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # Write result to file
            with open(output_file, "w", encoding="utf-8") as file:
                file.write(result.stdout)

            self.logger.info(f"Successfully exported resource group template using CLI to {output_file}")
            return output_file

        except subprocess.CalledProcessError as cli_error:
            self.logger.error(f"CLI fallback failed: {cli_error.stderr}")
            return None

    def is_resource_group_in_subscription(self, resource_group: str, subscription_id: str) -> bool:
        """Check if a resource group exists in a specific subscription.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            True if the resource group exists in the subscription, False otherwise

        Example:
            >>> service.is_resource_group_in_subscription("rg-production", "b32d2aa3-...")
            True
        """
        try:
            client = self._get_resource_client(subscription_id)
            exists = client.resource_groups.check_existence(resource_group)

            if exists:
                subscription_name = self.get_subscription_name(subscription_id)
                self.logger.info(f"Resource group {resource_group} found in subscription {subscription_name}")

            return bool(exists)

        except ClientAuthenticationError as auth_error:
            if any(term in str(auth_error) for term in ["Unauthorized", "Forbidden", "401", "403"]):
                subscription_name = self.get_subscription_name(subscription_id) or subscription_id
                self.logger.warning(
                    f"Permission issue when checking resource group {resource_group} "
                    f"in subscription {subscription_name}: {auth_error}"
                )
            else:
                self.logger.error(
                    f"Authentication error when checking resource group {resource_group} "
                    f"in subscription {subscription_id}: {auth_error}"
                )
            return False

        except Exception as e:
            error_str = str(e).lower()
            if any(
                term in error_str for term in ["unauthorized", "forbidden", "permission", "access denied", "401", "403"]
            ):
                subscription_name = self.get_subscription_name(subscription_id) or subscription_id
                self.logger.warning(
                    f"Permission issue when checking resource group {resource_group} "
                    f"in subscription {subscription_name}: {e}"
                )
            else:
                self.logger.error(
                    f"Error checking resource group {resource_group} " f"in subscription {subscription_id}: {e}"
                )
            return False

    def is_resource_group_not_in_all_subscriptions(self, resource_group: str, subscriptions: List[str]) -> bool:
        """Check if a resource group does NOT exist in any of the given subscriptions.

        Args:
            resource_group: Name of the resource group
            subscriptions: List of Azure subscription IDs to check

        Returns:
            True if resource group is not found in any subscription, False if found in at least one

        Example:
            >>> service.is_resource_group_not_in_all_subscriptions(
            ...     "rg-orphan",
            ...     ["sub1-...", "sub2-...", "sub3-..."]
            ... )
            True
        """
        try:
            for subscription_id in subscriptions:
                if self.is_resource_group_in_subscription(resource_group, subscription_id):
                    return False
            return True
        except Exception as e:
            self.logger.error(f"Error checking resource group in subscriptions: {e}")
            return False

    def list_resource_groups(self, subscription_id: str) -> List[str]:
        """List all resource groups in a subscription.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            List of resource group names

        Example:
            >>> service.list_resource_groups("b32d2aa3-...")
            ["rg-production", "rg-staging", "rg-dev"]
        """
        try:
            client = self._get_resource_client(subscription_id)
            resource_groups = client.resource_groups.list()
            return [rg.name for rg in resource_groups if rg.name is not None]
        except Exception as e:
            self.logger.error(f"Failed to list resource groups: {e}")
            return []
