import json
import os
import platform
import sys
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urlparse

from azure.core.exceptions import ClientAuthenticationError, ResourceNotFoundError
from azure.core.pipeline.policies import RetryPolicy

# Azure SDK imports
from azure.identity import ClientSecretCredential, DefaultAzureCredential, DeviceCodeCredential
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.mgmt.resource.resources.models import ExportTemplateRequest, ResourceGroup
from azure.mgmt.subscription import SubscriptionClient

from core.readonly_policy import ReadOnlyPolicy
from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()


class AzureUtility:
    """
    A cross-platform utility class for Azure operations using the Azure SDK for Python.

    This class provides methods to interact with Azure resources without relying on
    the Azure CLI, making it more cross-platform and avoiding shell dependencies.
    """

    AUTH_DEVICE_CODE = "device-code"
    AUTH_SERVICE_PRINCIPAL = "service-principal"
    AUTH_ENVIRONMENT = "environment"

    def __init__(self, auth_method: str = AUTH_DEVICE_CODE):
        """Initialize the Azure utility class.

        Args:
            auth_method: Authentication method:
                - 'device-code' (default): Interactive browser-based login.
                - 'service-principal': Non-interactive via AZURE_CLIENT_ID,
                  AZURE_TENANT_ID, and AZURE_CLIENT_SECRET env vars.
                - 'environment': Uses DefaultAzureCredential which auto-detects
                  pre-existing auth (az login, managed identity, env vars, etc.).
                  Ideal for CI/CD runners where authentication is already done.
        """
        self.logger = SingletonLogger().get_logger()
        self._auth_method = auth_method
        self._readonly_policy = ReadOnlyPolicy()
        self._credentials: Optional[Any] = None
        self._subscription_client: Optional[SubscriptionClient] = None
        self._resource_client: Optional[ResourceManagementClient] = None
        self._network_client: Optional[NetworkManagementClient] = None
        self._resource_client_subscription_id: Optional[str] = None
        self._network_client_subscription_id: Optional[str] = None
        self._current_tenant_id: Optional[str] = None
        self._exported_templates: Dict[Tuple[str, str], str] = {}  # (subscription_id, rg_name) -> output_file_path

        # ── Centralized API response caches ──
        # These caches persist for the lifetime of this AzureUtility instance,
        # eliminating redundant HTTP round-trips across resource_processor,
        # graph_generator, and internal helper methods.
        self._rg_in_subscription_cache: Dict[Tuple[str, str], bool] = {}  # (rg, sub) -> exists
        self._subscription_name_cache: Dict[str, Optional[str]] = {}  # sub_id -> name
        self._rg_location_cache: Dict[Tuple[str, str], Optional[str]] = {}  # (rg, sub) -> location
        self._pe_subnet_cache: Dict[Tuple[str, str, str], Optional[str]] = {}  # (pe, rg, sub) -> subnet
        self._dns_zones_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}  # (rg, sub) -> zones
        self._dns_zones_without_vnets_cache: Dict[Tuple[str, str], List[str]] = {}  # (rg, sub) -> zone_names
        self._vnet_dns_links_cache: Dict[Tuple[str, str], List[str]] = {}  # (vnet, sub) -> zone_names
        self._rg_has_vnets_cache: Dict[Tuple[str, str], bool] = {}  # (rg, sub) -> has_vnets

        # Initialize storage for multiple Bicep template mappings
        self._initialize_template_mappings()

    def _device_code_callback(self, verification_uri, user_code, expires_on):
        """Enhanced callback to display device code authentication information to user."""
        import os
        import sys
        from datetime import datetime, timezone

        # expires_on is an absolute datetime; compute remaining for console display
        remaining_init = int(max(0, (expires_on - datetime.now(timezone.utc)).total_seconds()))
        m, s = divmod(remaining_init, 60)
        expires_display = f"{m} min {s} sec" if m else f"{s} seconds"

        # Print the static authentication banner once to console
        auth_message = f"\n{'='*60}\n"
        auth_message += f"🚨 AZURE AUTHENTICATION REQUIRED 🚨\n"
        auth_message += f"{'='*60}\n"
        auth_message += f"To sign in, use a web browser to open the page:\n"
        auth_message += f"    {verification_uri}\n"
        auth_message += f"\n"
        auth_message += f"And enter the code:\n"
        auth_message += f"    {user_code}\n"
        auth_message += f"\n"
        auth_message += f"This code will expire in {expires_display}.\n"
        auth_message += f"{'='*60}\n"

        try:
            print(auth_message, flush=True)
        except Exception:
            pass

        # Write temp file for GUI with ISO timestamp so the frontend can do a live countdown
        try:
            expires_iso = expires_on.isoformat()
            temp_auth_file = os.path.join(os.getcwd(), "azure_auth_prompt.txt")
            with open(temp_auth_file, "w", encoding="utf-8") as f:
                f.write(f"AZURE AUTHENTICATION REQUIRED\n")
                f.write(f"URL: {verification_uri}\n")
                f.write(f"CODE: {user_code}\n")
                f.write(f"EXPIRES_ON: {expires_iso}\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass

    def _initialize_template_mappings(self):
        """Initialize template mappings storage."""
        self._template_mappings = {
            "templates": [],  # List of template data
            "resource_groups": [],  # Corresponding resource groups for each template
            "subscriptions": [],  # Corresponding subscriptions for each template
            "tenants": [],  # Corresponding tenants for each template
            "rg_to_subscription": {},  # Direct mapping from RG to subscription
            "subscription_to_tenant": {},  # Direct mapping from subscription to tenant
            "template_index_map": {},  # Map to quickly find template index by RG name
        }

    def _is_non_interactive(self) -> bool:
        """Check if running in non-interactive / CI-CD mode."""
        return os.environ.get("CLOUDHORUS_NON_INTERACTIVE", "").lower() in ("true", "1", "yes")

    def _get_credential(self):
        """
        Get the Azure credential object for authentication.

        Supports three flows controlled by ``self._auth_method``:
        - **device-code** (default): Interactive browser-based authentication.
        - **service-principal**: Non-interactive via AZURE_CLIENT_ID, AZURE_TENANT_ID,
          and AZURE_CLIENT_SECRET env vars.
        - **environment**: Uses DefaultAzureCredential which auto-detects
          pre-existing auth (az login, managed identity, env vars).  Ideal for
          CI/CD runners where the runner authenticates before CloudHorus runs.

        In non-interactive mode (CI/CD), device-code auth is rejected with a
        clear error to prevent pipelines from hanging.

        Returns:
            A credential object for Azure authentication.
        """
        if self._credentials is None:
            if self._auth_method == self.AUTH_SERVICE_PRINCIPAL:
                self._credentials = self._create_service_principal_credential()
            elif self._auth_method == self.AUTH_ENVIRONMENT:
                self._credentials = self._create_environment_credential()
            else:
                # Guard: fail-fast in CI/CD instead of blocking on device-code
                if self._is_non_interactive():
                    raise EnvironmentError(
                        "Non-interactive mode is enabled but authentication requires device-code flow. "
                        "Use --authMethod service-principal with AZURE_CLIENT_ID, AZURE_TENANT_ID, "
                        "and AZURE_CLIENT_SECRET env vars, or --authMethod environment to use "
                        "pre-existing credentials (az login, managed identity) for CI/CD pipelines."
                    )
                try:
                    self.logger.info("🦅 CloudHorus: Initializing Azure authentication via device code flow...")
                    self.logger.info("📱 Preparing interactive authentication (no az login needed)...")

                    self._credentials = DeviceCodeCredential(prompt_callback=self._device_code_callback, timeout=300)

                    self.logger.info("✅ Azure credential object prepared (authentication deferred to tenant login)")

                except Exception as login_error:
                    self.logger.error(f"❌ Device code authentication failed: {str(login_error)}")
                    self.logger.error("Please check your internet connection and try again")
                    raise

        return self._credentials

    def _create_service_principal_credential(self) -> ClientSecretCredential:
        """Create a ClientSecretCredential from environment variables.

        Reads:
            AZURE_TENANT_ID    — Required.
            AZURE_CLIENT_ID    — Required.
            AZURE_CLIENT_SECRET — Required. The client secret value.

        Returns:
            ClientSecretCredential

        Raises:
            EnvironmentError: If required variables are missing.
        """
        tenant_id = os.environ.get("AZURE_TENANT_ID", "").strip()
        client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("AZURE_CLIENT_SECRET", "").strip()

        if not tenant_id or not client_id:
            raise EnvironmentError(
                "Service-principal auth requires AZURE_TENANT_ID and AZURE_CLIENT_ID " "environment variables."
            )
        if not client_secret:
            raise EnvironmentError("Service-principal auth requires AZURE_CLIENT_SECRET environment variable.")

        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.logger.info(
            f"✅ Service Principal credential created for tenant {tenant_id[:8]}..., " f"client {client_id[:8]}..."
        )
        return credential

    def _create_environment_credential(self) -> DefaultAzureCredential:
        """Create a DefaultAzureCredential for CI/CD environments.

        Uses Azure's credential chain which auto-detects pre-existing authentication:
        - Environment variables (AZURE_CLIENT_ID/SECRET/TENANT_ID)
        - Managed Identity (Azure VMs, App Service, AKS, etc.)
        - Azure CLI (az login session)
        - Azure PowerShell (Connect-AzAccount session)

        This is the recommended approach for CI/CD runners where the
        authentication step is performed before CloudHorus runs.

        Returns:
            DefaultAzureCredential
        """
        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=True,
            exclude_developer_cli_credential=True,
        )
        self.logger.info(
            "✅ Environment credential initialized (auto-detecting: "
            "env vars → managed identity → az login → PowerShell)"
        )
        return credential

    def _get_subscription_client(self) -> SubscriptionClient:
        """Get the Azure Subscription client."""
        if self._subscription_client is None:
            self._subscription_client = SubscriptionClient(
                self._get_credential(),
                per_call_policies=[self._readonly_policy],
            )
        return cast(SubscriptionClient, self._subscription_client)

    def _get_resource_client(self, subscription_id: str) -> ResourceManagementClient:
        """Get the Azure Resource Management client for a specific subscription."""
        # Safety check: if we're in template mode and templates are registered, we should never need Azure clients
        if hasattr(self, "_template_mappings") and self.is_using_multiple_templates():
            self.logger.warning(
                f"WARNING: Attempting to create Azure client while in template mode. This may indicate a bug."
            )

        # Always create a new client if subscription changes to ensure we're using the correct subscription
        if self._resource_client is None or self._resource_client_subscription_id != subscription_id:
            self._resource_client = ResourceManagementClient(
                self._get_credential(),
                subscription_id,
                retry_policy=RetryPolicy(),
                per_call_policies=[self._readonly_policy],
            )
            self._resource_client_subscription_id = subscription_id
        return cast(ResourceManagementClient, self._resource_client)

    def _get_network_client(self, subscription_id: str) -> NetworkManagementClient:
        """Get the Azure Network Management client for a specific subscription."""
        # Always create a new client if subscription changes to ensure we're using the correct subscription
        if self._network_client is None or self._network_client_subscription_id != subscription_id:
            self._network_client = NetworkManagementClient(
                self._get_credential(),
                subscription_id,
                retry_policy=RetryPolicy(),
                per_call_policies=[self._readonly_policy],
            )
            self._network_client_subscription_id = subscription_id
        return cast(NetworkManagementClient, self._network_client)

    def login_interactively(self, tenant_id: Optional[str] = None) -> bool:
        """
        Perform login to Azure.

        For device-code flow: Interactive device-code login with tenant scoping.
        For service-principal / environment flow: Validates the pre-configured
        credential against the management plane (no user interaction).

        Args:
            tenant_id: Optional tenant ID to log in to a specific tenant

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # ── Non-interactive paths (SP + environment): just validate ──
            if self._auth_method in (self.AUTH_SERVICE_PRINCIPAL, self.AUTH_ENVIRONMENT):
                cred = self._get_credential()
                cred.get_token("https://management.azure.com/.default")
                sc = SubscriptionClient(cred, per_call_policies=[self._readonly_policy])
                tenant_info = None
                for t in sc.tenants.list():
                    if not tenant_id or t.tenant_id == tenant_id:
                        tenant_info = t
                        break
                if tenant_info:
                    display = getattr(tenant_info, "display_name", None) or tenant_id or "unknown"
                    auth_label = (
                        "Service Principal" if self._auth_method == self.AUTH_SERVICE_PRINCIPAL else "Environment"
                    )
                    self.logger.info(f"✅ {auth_label} authenticated to tenant: {display}")
                    self._current_tenant_id = tenant_id
                    self._subscription_client = sc
                    return True
                self.logger.error(f"{self._auth_method} credential cannot access the requested tenant")
                return False

            # ── Device-code path (original logic) ──
            # Force fresh credentials when tenant changes OR on first call
            # (the initial _get_credential() creates an un-scoped credential;
            #  we must replace it with a tenant-scoped one so the user
            #  authenticates as a MEMBER, not a guest.)
            if self._credentials is not None and tenant_id:
                current_tenant = getattr(self, "_current_tenant_id", None)
                if current_tenant is None or current_tenant != tenant_id:
                    if current_tenant:
                        self.logger.info(
                            f"Tenant changed from {current_tenant} to {tenant_id}, forcing re-authentication..."
                        )
                    else:
                        self.logger.info(f"First tenant login — scoping credential to tenant {tenant_id}...")
                    self._credentials = None
                    self._subscription_client = None
                    self._resource_client = None
                    self._network_client = None

            # If we already have credentials, try to reuse them
            if self._credentials is not None:
                self.logger.info("Reusing existing Azure credentials (already authenticated)")
                # Ensure subscription client is built
                if self._subscription_client is None:
                    self._subscription_client = SubscriptionClient(self._credentials)

                # Validate by checking tenant info
                tenant_info = None
                try:
                    for tenant in self._subscription_client.tenants.list():
                        if not tenant_id or tenant.tenant_id == tenant_id:
                            tenant_info = tenant
                            break
                except Exception:
                    # Token might not work for this tenant — fall through to re-auth
                    self.logger.info(f"Existing credentials cannot access tenant {tenant_id}, re-authenticating...")
                    self._credentials = None
                    self._subscription_client = None

                if tenant_info:
                    tenant_display = getattr(tenant_info, "display_name", None) or getattr(
                        tenant_info, "tenant_id", "unknown"
                    )
                    self.logger.info(f"Successfully logged in to tenant: {tenant_display}")
                    self._current_tenant_id = tenant_id
                    return True

            # Need fresh credentials — create device code credential
            # Guard: fail-fast in CI/CD instead of blocking on device-code
            if self._is_non_interactive():
                raise EnvironmentError(
                    "Non-interactive mode: device-code login required but not allowed. "
                    "Use --authMethod service-principal or --authMethod environment for CI/CD pipelines."
                )

            if tenant_id:
                self._credentials = DeviceCodeCredential(
                    tenant_id=tenant_id, prompt_callback=self._device_code_callback, timeout=300
                )
            else:
                self._credentials = DeviceCodeCredential(prompt_callback=self._device_code_callback, timeout=300)

            # Force token acquisition — blocks until the user completes the device code flow
            self._credentials.get_token("https://management.azure.com/.default")

            # Rebuild subscription client with the now-authenticated credential
            self._subscription_client = SubscriptionClient(self._credentials)

            # Validate by checking tenant info
            tenant_info = None
            for tenant in self._subscription_client.tenants.list():
                if not tenant_id or tenant.tenant_id == tenant_id:
                    tenant_info = tenant
                    break

            if tenant_info:
                tenant_display = getattr(tenant_info, "display_name", None) or getattr(
                    tenant_info, "tenant_id", "unknown"
                )
                self.logger.info(f"Successfully logged in to tenant: {tenant_display}")
                self._current_tenant_id = tenant_id
                return True

            self.logger.error("Login validation failed - could not find tenant information")
            return False

        except Exception as e:
            self.logger.error(f"Login failed: {str(e)}")
            return False

    def login_to_tenant(self, tenant_id: str) -> Optional[str]:
        """
        Login to Azure with specific tenant using an interactive approach.

        Args:
            tenant_id: The Azure tenant ID

        Returns:
            Optional[str]: The tenant name if login successful, None otherwise
        """
        try:
            # Attempt to login interactively to the specified tenant
            self.logger.info(f"Attempting to login to tenant {tenant_id} interactively...")
            if self.login_interactively(tenant_id):
                return self.get_tenant_name(tenant_id)
            return None

        except Exception as e:
            self.logger.error(f"Failed to login to tenant: {str(e)}")
            return None

    def get_tenant_name(self, tenant_id: str) -> Optional[str]:
        """
        Get the display name of an Azure tenant using its ID.

        Args:
            tenant_id: The Azure tenant ID

        Returns:
            Optional[str]: The tenant display name if found, None otherwise
        """
        try:
            subscription_client = self._get_subscription_client()
            for tenant in subscription_client.tenants.list():
                if tenant.tenant_id == tenant_id:
                    display_name = getattr(tenant, "display_name", None)
                    return str(display_name) if display_name else str(tenant.tenant_id)

            self.logger.warning(f"No tenant name found for ID {tenant_id}")
            return None

        except Exception as e:
            self.logger.error(f"Error getting tenant name: {str(e)}")
            return None

    def get_subscription_name(self, subscription_id: str) -> Optional[str]:
        """
        Get subscription name from subscription ID.
        Results are cached for the lifetime of this AzureUtility instance.

        Args:
            subscription_id: The Azure subscription ID

        Returns:
            Optional[str]: The subscription name if found, None otherwise
        """
        # Check cache first
        if subscription_id in self._subscription_name_cache:
            return self._subscription_name_cache[subscription_id]
        try:
            subscription_client = self._get_subscription_client()
            subscription = subscription_client.subscriptions.get(subscription_id)
            result = str(subscription.display_name) if subscription.display_name is not None else None
            self._subscription_name_cache[subscription_id] = result
            return result
        except ResourceNotFoundError:
            self.logger.error(f"Subscription {subscription_id} not found")
            self._subscription_name_cache[subscription_id] = None
            return None
        except ClientAuthenticationError as auth_error:
            error_str = str(auth_error).lower()
            # Check if this is a tenant-related authentication issue
            if any(
                term in error_str for term in ["invalidauthenticationtokentenant", "tenant", "directory", "aadsts50020"]
            ):
                self.logger.warning(f"Subscription {subscription_id} appears to be in a different tenant")
            else:
                self.logger.warning(f"Authentication error getting subscription {subscription_id}: {str(auth_error)}")
            self._subscription_name_cache[subscription_id] = None
            return None
        except Exception as e:
            # Check if the error message contains tenant-related terms
            error_str = str(e).lower()
            if any(term in error_str for term in ["tenant", "directory", "aadsts", "token"]):
                self.logger.warning(
                    f"Possible tenant-related issue when accessing subscription {subscription_id}: {str(e)}. "
                    f"You may need to switch tenants or reauthenticate."
                )
            else:
                self.logger.error(f"Failed to get subscription name for {subscription_id}: {str(e)}")
            self._subscription_name_cache[subscription_id] = None
            return None

    def get_resource_group_location(self, resource_group_name: str, subscription_id: str) -> Optional[str]:
        """
        Get the location of a resource group.
        Results are cached for the lifetime of this AzureUtility instance.

        Args:
            resource_group_name: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            Optional[str]: The resource group location if found, None otherwise
        """
        cache_key = (resource_group_name, subscription_id)
        if cache_key in self._rg_location_cache:
            return self._rg_location_cache[cache_key]
        try:
            resource_client = self._get_resource_client(subscription_id)
            resource_group = resource_client.resource_groups.get(resource_group_name)
            result = str(resource_group.location) if resource_group.location is not None else None
            self._rg_location_cache[cache_key] = result
            return result
        except ResourceNotFoundError:
            self.logger.warning(f"Resource group {resource_group_name} not found in subscription {subscription_id}")
            self._rg_location_cache[cache_key] = None
            return None
        except Exception as e:
            error_str = str(e).lower()
            if any(term in error_str for term in ["authorization", "forbidden", "permission"]):
                self.logger.warning(
                    f"No permission to get location for resource group {resource_group_name} "
                    f"— access restricted (this is expected for discovered RGs without RBAC)"
                )
            else:
                self.logger.error(f"Failed to get location for resource group {resource_group_name}: {str(e)}")
            self._rg_location_cache[cache_key] = None
            return None

    def export_resource_group_template(self, subscription_id: str, resource_group_name: str) -> Optional[str]:
        """
        Export a resource group as an ARM template.
        Falls back to resource-by-resource listing when the RG has >200 tracked resources.

        Args:
            subscription_id: Azure subscription ID
            resource_group_name: Name of the resource group

        Returns:
            Optional[str]: Path to the exported template file if successful, None otherwise
        """
        output_file = f"{resource_group_name}-template.json"

        # Return cached result if already exported this session
        cache_key = (subscription_id, resource_group_name)
        if cache_key in self._exported_templates:
            cached: str = self._exported_templates[cache_key]
            self.logger.info(f"Reusing cached template for {resource_group_name} → {cached}")
            return cached

        try:
            # Use the ResourceManagementClient directly instead of TemplateExportClient
            resource_client = self._get_resource_client(subscription_id)

            # Use the resources.export_template_at_subscription_scope method
            export_result = resource_client.resource_groups.begin_export_template(
                resource_group_name=resource_group_name,
                parameters=ExportTemplateRequest(
                    resources=["*"],
                    options="SkipAllParameterization",
                ),
            ).result()

            # Write the result to a file
            with open(output_file, "w") as file:
                file.write(json.dumps(export_result.template, indent=2))

            self.logger.info(f"Successfully exported resource group template to {output_file}")
            self._exported_templates[cache_key] = output_file
            return output_file

        except AttributeError as e:
            # Fallback to direct Azure CLI call if SDK method not available
            self.logger.warning(f"SDK method not available, falling back to CLI: {str(e)}")
            try:
                import subprocess

                # Use Azure CLI directly
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

                # Parse the result and write to file
                with open(output_file, "w", encoding="utf-8") as file:
                    file.write(result.stdout)

                self.logger.info(f"Successfully exported resource group template using CLI to {output_file}")
                self._exported_templates[cache_key] = output_file
                return output_file

            except subprocess.CalledProcessError as cli_error:
                self.logger.error(f"CLI fallback failed: {cli_error.stderr}")
                return None

        except Exception as e:
            error_msg = str(e)
            # Detect the 200-resource limit and fall back to resource-by-resource listing
            if "200" in error_msg and "tracked resources" in error_msg.lower():
                self.logger.warning(
                    f"Resource group {resource_group_name} exceeds 200 tracked resources. "
                    f"Falling back to individual resource listing..."
                )
                return self._build_template_from_resource_list(subscription_id, resource_group_name, output_file)
            self.logger.error(f"Failed to export resource group template: {error_msg}")
            return None

    def _build_template_from_resource_list(
        self, subscription_id: str, resource_group_name: str, output_file: str
    ) -> Optional[str]:
        """
        Build an ARM-template-like JSON by listing resources individually.
        Used as fallback when the RG has >200 tracked resources.
        Applies the same skip-pattern filtering as normal ARM template exports
        to ensure consistent graph rendering behaviour.
        """
        from utils.graph_utils import should_skip

        try:
            resource_client = self._get_resource_client(subscription_id)
            resources_list = []

            # Resource types that add no value to the architecture diagram
            # and should be excluded from the fallback template
            noisy_types = {
                "Microsoft.Network/networkInterfaces",
                "Microsoft.Network/publicIPAddresses",
                "Microsoft.Network/networkWatchers",
                "Microsoft.Network/networkWatchers/connectionMonitors",
                "Microsoft.Network/networkWatchers/flowLogs",
                "microsoft.insights/actiongroups",
                "microsoft.insights/activityLogAlerts",
                "microsoft.insights/components",
                "Microsoft.OperationalInsights/workspaces",
                "Microsoft.ManagedIdentity/userAssignedIdentities",
                "Microsoft.Portal/dashboards",
                "Microsoft.Compute/disks",
                "Microsoft.Compute/snapshots",
                "Microsoft.Compute/sshPublicKeys",
                "Microsoft.Compute/images",
            }

            skipped_count = 0
            for resource in resource_client.resources.list_by_resource_group(resource_group_name):
                # Apply the same skip patterns used by the graph generator
                if should_skip(resource.type):
                    skipped_count += 1
                    continue

                # Filter out noisy infrastructure resources that clutter the diagram
                if resource.type in noisy_types:
                    skipped_count += 1
                    continue

                resource_entry: Dict[str, Any] = {
                    "type": resource.type,
                    "name": resource.name,
                    "location": resource.location,
                    "properties": {},
                    "dependsOn": [],
                }

                # Fetch full resource details (with properties) for resource types we care about
                important_types = {
                    "Microsoft.Network/virtualNetworks",
                    "Microsoft.Network/virtualNetworks/subnets",
                    "Microsoft.Network/privateEndpoints",
                    "Microsoft.Network/azureFirewalls",
                    "Microsoft.Network/applicationGateways",
                    "Microsoft.Network/bastionHosts",
                    "Microsoft.Network/virtualNetworkGateways",
                    "Microsoft.Network/routeTables",
                    "Microsoft.Network/networkSecurityGroups",
                    "Microsoft.Network/routeServers",
                    "Microsoft.Web/sites",
                    "Microsoft.Web/hostingEnvironments",
                    "Microsoft.ContainerService/managedClusters",
                    "Microsoft.DBforMySQL/flexibleServers",
                    "Microsoft.DBforPostgreSQL/flexibleServers",
                    "Microsoft.Sql/managedInstances",
                    "Microsoft.Cache/Redis",
                    "Microsoft.ApiManagement/service",
                    "Microsoft.Network/privateDnsZones",
                }

                if resource.type in important_types:
                    try:
                        resource_id = resource.id
                        if resource_id is not None:
                            full = resource_client.resources.get_by_id(
                                resource_id, api_version=self._resolve_api_version(resource_client, resource.type)
                            )
                            if full.properties:
                                resource_entry["properties"] = dict(full.properties)
                    except Exception as detail_err:
                        self.logger.debug(f"Could not fetch details for {resource.name}: {detail_err}")

                    # Fallback for PEs: use NetworkManagementClient when generic
                    # get_by_id returns empty properties or throws an exception.
                    # This runs OUTSIDE the get_by_id try/except so it always
                    # executes regardless of whether get_by_id succeeded or failed.
                    if resource.type == "Microsoft.Network/privateEndpoints" and not resource_entry["properties"]:
                        try:
                            network_client = self._get_network_client(subscription_id)
                            pe = network_client.private_endpoints.get(resource_group_name, resource.name or "")
                            pe_props: Dict[str, Any] = {}
                            if pe.private_link_service_connections:
                                pe_props["privateLinkServiceConnections"] = [
                                    {
                                        "name": conn.name,
                                        "properties": {
                                            "privateLinkServiceId": conn.private_link_service_id,
                                            "groupIds": conn.group_ids or [],
                                        },
                                    }
                                    for conn in pe.private_link_service_connections
                                ]
                            if pe.manual_private_link_service_connections:
                                pe_props["manualPrivateLinkServiceConnections"] = [
                                    {
                                        "name": conn.name,
                                        "properties": {
                                            "privateLinkServiceId": conn.private_link_service_id,
                                            "groupIds": conn.group_ids or [],
                                        },
                                    }
                                    for conn in pe.manual_private_link_service_connections
                                ]
                            if pe.subnet:
                                pe_props["subnet"] = {"id": pe.subnet.id}
                            if pe.custom_dns_configs:
                                pe_props["customDnsConfigs"] = [
                                    {"fqdn": dns.fqdn, "ipAddresses": dns.ip_addresses} for dns in pe.custom_dns_configs
                                ]
                            if pe_props:
                                resource_entry["properties"] = pe_props
                                self.logger.debug(
                                    f"Retrieved PE details via NetworkManagementClient for {resource.name}"
                                )
                        except Exception as pe_err:
                            self.logger.debug(f"NetworkManagementClient fallback for PE {resource.name}: {pe_err}")

                    # Build dependsOn from properties references (ARM template format)
                    resource_entry["dependsOn"] = self._extract_dependencies_from_properties(
                        resource_entry["properties"], resource.type
                    )

                resources_list.append(resource_entry)

            template = {
                "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                "contentVersion": "1.0.0.0",
                "resources": resources_list,
            }

            with open(output_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(template, indent=2, default=str))

            self.logger.info(
                f"Built template from {len(resources_list)} listed resources "
                f"({skipped_count} skipped by filters) → {output_file}"
            )
            self._exported_templates[(subscription_id, resource_group_name)] = output_file
            return output_file

        except Exception as e:
            self.logger.error(f"Failed to build template from resource list: {e}")
            return None

    @staticmethod
    def _resolve_api_version(resource_client, resource_type: str) -> str:
        """Resolve the latest API version for a given resource type."""
        try:
            provider_ns = resource_type.split("/")[0]
            type_name = "/".join(resource_type.split("/")[1:])
            provider = resource_client.providers.get(provider_ns)
            for rt in provider.resource_types:
                if rt.resource_type.lower() == type_name.lower():
                    return str(rt.api_versions[0])  # latest
        except Exception:
            pass
        return "2023-07-01"  # safe fallback

    @staticmethod
    def _extract_dependencies_from_properties(properties: dict, resource_type: str) -> list:
        """Build a dependsOn list by scanning properties for resource ID references.

        Generates ARM template format [resourceId('type', 'name1', 'name2')] strings
        so that parse_dependency_string can correctly parse them.
        """
        deps: List[str] = []
        if not properties or not isinstance(properties, dict):
            return deps

        def _to_arm_resource_id(azure_resource_id: str) -> Optional[str]:
            """Convert a full Azure resource ID to ARM template [resourceId(...)] format.

            Example:
                /subscriptions/.../providers/Microsoft.Network/virtualNetworks/vnet1/subnets/subnet1
                → [resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet1', 'subnet1')]
            """
            if "/providers/" not in azure_resource_id:
                return None

            provider_path = azure_resource_id.split("/providers/")[-1]
            parts = provider_path.split("/")

            if len(parts) < 2:
                return None

            # Build resource type and name segments
            # Pattern: Namespace/TypeSegment/NameValue/TypeSegment/NameValue/...
            type_parts = [parts[0]]  # Namespace e.g. Microsoft.Network
            name_parts = []

            i = 1
            while i < len(parts):
                if i + 1 < len(parts):
                    type_parts.append(parts[i])  # type segment
                    name_parts.append(parts[i + 1])  # name value
                    i += 2
                else:
                    # Trailing type segment without a name — skip
                    break

            if not name_parts:
                return None

            res_type = "/".join(type_parts)
            names_str = ", ".join(f"'{n}'" for n in name_parts)
            return f"[resourceId('{res_type}', {names_str})]"

        def _scan(obj):
            if isinstance(obj, str) and "/Microsoft." in obj and "/subnets/" in obj:
                # Looks like a subnet resource ID — convert to ARM template format
                arm_dep = _to_arm_resource_id(obj)
                if arm_dep and arm_dep not in deps:
                    deps.append(arm_dep)
            elif isinstance(obj, dict):
                for v in obj.values():
                    _scan(v)
            elif isinstance(obj, list):
                for v in obj:
                    _scan(v)

        _scan(properties)
        return deps

    def get_pe_subnet_name(self, pe_name: str, resource_group: str, subscription_id: str) -> Optional[str]:
        """
        Get the private endpoint subnet name.
        Results are cached globally across all callers (resource_processor, graph_generator).

        Args:
            pe_name: Name of the private endpoint
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            Optional[str]: The subnet name if found, None otherwise
        """
        cache_key = (pe_name, resource_group, subscription_id)
        if cache_key in self._pe_subnet_cache:
            self.logger.debug(f"PE subnet cache hit: {pe_name} -> {self._pe_subnet_cache[cache_key]}")
            return self._pe_subnet_cache[cache_key]
        try:
            network_client = self._get_network_client(subscription_id)
            pe = network_client.private_endpoints.get(resource_group, pe_name)
            result: Optional[str] = None
            if pe.subnet and pe.subnet.id:
                # Extract subnet name from the subnet ID
                result = str(pe.subnet.id.split("/")[-1])
            self._pe_subnet_cache[cache_key] = result
            return result
        except ResourceNotFoundError:
            self.logger.debug(f"Private endpoint {pe_name} not found in RG {resource_group} — may belong to another RG")
            self._pe_subnet_cache[cache_key] = None
            return None
        except Exception as e:
            self.logger.debug(f"Could not get subnet for private endpoint {pe_name}: {str(e)}")
            self._pe_subnet_cache[cache_key] = None
            return None

    def get_private_dns_zones(
        self,
        resource_group: str,
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get private DNS zones in a resource group.
        Enhanced to handle multiple Bicep templates with registered mappings.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template data instead of Azure portal
            template_data: The ARM template data to analyze (when use_local_template=True)

        Returns:
            List[Dict[str, Any]]: List of private DNS zones with their properties
        """
        if use_local_template:
            # Check if we have multiple templates registered
            if self.is_using_multiple_templates():
                # Get template data for this specific resource group
                rg_template_data = self.get_template_data_for_resource_group(resource_group)
                if rg_template_data:
                    return self._get_private_dns_zones_from_template(rg_template_data, resource_group)
                else:
                    self.logger.warning(
                        f"No template data found for resource group '{resource_group}' in registered mappings"
                    )
                    return []
            elif template_data:
                # Single template mode with provided template data
                return self._get_private_dns_zones_from_template(template_data, resource_group)
            else:
                self.logger.warning(
                    "use_local_template=True but no template data provided and no multiple templates registered"
                )
                return []
        else:
            return self._get_private_dns_zones_from_azure(resource_group, subscription_id)

    def _get_private_dns_zones_from_template(
        self, template_data: Dict[str, Any], resource_group: str
    ) -> List[Dict[str, Any]]:
        """
        Get private DNS zones from Bicep template data.

        Args:
            template_data: The ARM template data
            resource_group: Name of the resource group (for consistency)

        Returns:
            List[Dict[str, Any]]: List of private DNS zones with their properties
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
            self.logger.error(f"Failed to get private DNS zones from template: {str(e)}")
            return []

    def _get_private_dns_zones_from_azure(self, resource_group: str, subscription_id: str) -> List[Dict[str, Any]]:
        """
        Get private DNS zones from Azure portal.
        Results are cached per (resource_group, subscription_id) pair.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            List[Dict[str, Any]]: List of private DNS zones with their properties
        """
        cache_key = (resource_group, subscription_id)
        if cache_key in self._dns_zones_cache:
            return self._dns_zones_cache[cache_key]
        try:
            # We'll use ARM resource client to query for private DNS zones
            # since they are resources with type 'Microsoft.Network/privateDnsZones'
            resource_client = self._get_resource_client(subscription_id)

            # Filter for private DNS zone resources
            filter_str = "resourceType eq 'Microsoft.Network/privateDnsZones'"
            zones = resource_client.resources.list_by_resource_group(
                resource_group_name=resource_group, filter=filter_str
            )

            result = []
            for zone in zones:
                result.append({"id": zone.id, "name": zone.name, "type": zone.type, "location": zone.location})
            self._dns_zones_cache[cache_key] = result
            return result
        except ResourceNotFoundError:
            # self.logger.warning(f"Resource group '{resource_group}' not in this tenant. Skipping private DNS zone lookup.")
            self._dns_zones_cache[cache_key] = []
            return []
        except ClientAuthenticationError as auth_error:
            # Handle authentication errors as warnings
            if (
                "Unauthorized" in str(auth_error)
                or "Forbidden" in str(auth_error)
                or "401" in str(auth_error)
                or "403" in str(auth_error)
            ):
                subscription_name = self.get_subscription_name(subscription_id) or subscription_id
                self.logger.warning(
                    f"Permission issue when listing private DNS zones in resource group '{resource_group}' in subscription {subscription_name}: "
                    f"You may not have sufficient permissions. Error: {str(auth_error)}"
                )
            else:
                self.logger.warning(
                    f"Authentication error when listing private DNS zones in {resource_group}: {str(auth_error)}"
                )
            self._dns_zones_cache[cache_key] = []
            return []
        except Exception as e:
            # Check if the error message contains authorization-related terms
            error_str = str(e).lower()
            if any(
                term in error_str
                for term in ["unauthorized", "forbidden", "permission", "access denied", "authorization", "401", "403"]
            ):
                subscription_name = self.get_subscription_name(subscription_id) or subscription_id
                self.logger.warning(
                    f"Permission issue when listing private DNS zones in resource group '{resource_group}' in subscription {subscription_name}: "
                    f"You may not have sufficient permissions. Error: {str(e)}"
                )
            elif "resourcegroupnotfound" in error_str or "could not be found" in error_str:
                self.logger.warning(
                    f"Resource group '{resource_group}' could not be found. Skipping private DNS zone lookup."
                )
            else:
                self.logger.error(f"Failed to list private DNS zones in {resource_group}: {str(e)}")
            self._dns_zones_cache[cache_key] = []
            return []

    def get_private_dns_zones_without_vnets(
        self,
        resource_group: str,
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Get private DNS zones in a resource group that has no VNets.
        Enhanced to handle multiple Bicep templates with registered mappings.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template data instead of Azure portal
            template_data: The ARM template data to analyze (when use_local_template=True)

        Returns:
            List[str]: List of private DNS zone names if resource group has no VNets but has DNS zones
        """
        if use_local_template:
            # Check if we have multiple templates registered
            if self.is_using_multiple_templates():
                # Get template data for this specific resource group
                rg_template_data = self.get_template_data_for_resource_group(resource_group)
                if rg_template_data:
                    return self._get_private_dns_zones_without_vnets_from_template(rg_template_data, resource_group)
                else:
                    self.logger.warning(
                        f"No template data found for resource group '{resource_group}' in registered mappings"
                    )
                    return []
            elif template_data:
                # Single template mode with provided template data
                return self._get_private_dns_zones_without_vnets_from_template(template_data, resource_group)
            else:
                self.logger.warning(
                    "use_local_template=True but no template data provided and no multiple templates registered"
                )
                return []
        else:
            return self._get_private_dns_zones_without_vnets_from_azure(resource_group, subscription_id)

    def _get_private_dns_zones_without_vnets_from_template(
        self, template_data: Dict[str, Any], resource_group: str
    ) -> List[str]:
        """
        Analyze Bicep template to find private DNS zones in resource groups that have no VNets.

        Args:
            template_data: The ARM template data
            resource_group: Name of the resource group (for logging purposes)

        Returns:
            List[str]: List of private DNS zone names if no VNets but has DNS zones
        """
        try:
            resources = template_data.get("resources", [])

            # Check if there are any VNets in the template
            vnets = []
            dns_zones = []

            for resource in resources:
                resource_type = resource.get("type", "")
                resource_name = resource.get("name", "")

                # Check for VNets
                if resource_type == "Microsoft.Network/virtualNetworks":
                    vnets.append(resource_name)

                # Check for private DNS zones
                elif resource_type == "Microsoft.Network/privateDnsZones":
                    dns_zones.append(resource_name)

            # If VNets exist in template, return empty list
            if vnets:
                self.logger.debug(f"Bicep template contains {len(vnets)} VNet(s). Skipping DNS zone lookup.")
                return []

            # No VNets found, return DNS zone names if any
            if dns_zones:
                self.logger.info(f"Found {len(dns_zones)} private DNS zone(s) in template with no VNets: {dns_zones}")
                return dns_zones
            else:
                self.logger.debug(f"No private DNS zones found in template for resource group '{resource_group}'")
                return []

        except Exception as e:
            self.logger.error(f"Failed to analyze template for DNS zones without VNets: {str(e)}")
            return []

    def _get_private_dns_zones_without_vnets_from_azure(self, resource_group: str, subscription_id: str) -> List[str]:
        """
        Get private DNS zones from Azure portal that are in resource groups with no VNets.
        Results are cached. Also caches the "has VNets" check to avoid a separate API call
        when the same RG is queried later.

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            List[str]: List of private DNS zone names if resource group has no VNets but has DNS zones
        """
        # Check result-level cache first
        result_cache_key = (resource_group, subscription_id)
        if result_cache_key in self._dns_zones_without_vnets_cache:
            return self._dns_zones_without_vnets_cache[result_cache_key]

        try:
            # Check the VNet existence cache first; only call Azure if unknown
            vnet_cache_key = (resource_group, subscription_id)
            if vnet_cache_key in self._rg_has_vnets_cache:
                has_vnets = self._rg_has_vnets_cache[vnet_cache_key]
            else:
                resource_client = self._get_resource_client(subscription_id)
                vnet_filter = "resourceType eq 'Microsoft.Network/virtualNetworks'"
                vnets = list(
                    resource_client.resources.list_by_resource_group(
                        resource_group_name=resource_group, filter=vnet_filter
                    )
                )
                has_vnets = len(vnets) > 0
                self._rg_has_vnets_cache[vnet_cache_key] = has_vnets

            # If VNets exist, return empty list
            if has_vnets:
                self.logger.debug(f"Resource group '{resource_group}' contains VNet(s). Skipping DNS zone lookup.")
                self._dns_zones_without_vnets_cache[result_cache_key] = []
                return []

            # No VNets found, check for private DNS zones (uses its own cache)
            dns_zones = self._get_private_dns_zones_from_azure(resource_group, subscription_id)

            if dns_zones:
                zone_names = [zone["name"] for zone in dns_zones]
                self._dns_zones_without_vnets_cache[result_cache_key] = zone_names
                return zone_names
            else:
                self._dns_zones_without_vnets_cache[result_cache_key] = []
                return []

        except ResourceNotFoundError:
            self.logger.warning(
                f"Resource group '{resource_group}' not found. Cannot check for DNS zones without VNets."
            )
            self._dns_zones_without_vnets_cache[result_cache_key] = []
            return []
        except ClientAuthenticationError as auth_error:
            if (
                "Unauthorized" in str(auth_error)
                or "Forbidden" in str(auth_error)
                or "401" in str(auth_error)
                or "403" in str(auth_error)
            ):
                subscription_name = self.get_subscription_name(subscription_id) or subscription_id
                self.logger.warning(
                    f"Permission issue when checking resource group '{resource_group}' in subscription {subscription_name}: "
                    f"You may not have sufficient permissions. Error: {str(auth_error)}"
                )
            else:
                self.logger.warning(
                    f"Authentication error when checking resource group {resource_group}: {str(auth_error)}"
                )
            self._dns_zones_without_vnets_cache[result_cache_key] = []
            return []
        except Exception as e:
            error_str = str(e).lower()
            if any(
                term in error_str
                for term in ["unauthorized", "forbidden", "permission", "access denied", "authorization", "401", "403"]
            ):
                subscription_name = self.get_subscription_name(subscription_id) or subscription_id
                self.logger.warning(
                    f"Permission issue when checking resource group '{resource_group}' in subscription {subscription_name}: "
                    f"You may not have sufficient permissions. Error: {str(e)}"
                )
            elif "resourcegroupnotfound" in error_str or "could not be found" in error_str:
                self.logger.warning(f"Resource group '{resource_group}' could not be found.")
            else:
                self.logger.error(f"Failed to check DNS zones without VNets in {resource_group}: {str(e)}")
            self._dns_zones_without_vnets_cache[result_cache_key] = []
            return []

    def is_vnet_linked_to_private_dns_zone(
        self,
        vnet_name: str,
        resource_groups: List[str],
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Get the list of private DNS zone names that a VNet is linked to.
        Enhanced to handle multiple Bicep templates with registered mappings.

        Args:
            vnet_name: Name of the virtual network
            resource_groups: List of resource group names to search in
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template data instead of Azure portal
            template_data: The ARM template data to analyze (when use_local_template=True)

        Returns:
            List[str]: List of private DNS zone names that the VNet is linked to
        """
        if use_local_template:
            # Check if we have multiple templates registered
            if self.is_using_multiple_templates():
                # Collect linked zones from all templates that contain the specified resource groups
                all_linked_zones = []
                for rg in resource_groups:
                    rg_template_data = self.get_template_data_for_resource_group(rg)
                    if rg_template_data:
                        linked_zones = self._get_vnet_linked_dns_zones_from_template(rg_template_data, vnet_name, [rg])
                        all_linked_zones.extend(linked_zones)
                    else:
                        self.logger.debug(f"No template data found for resource group '{rg}' in registered mappings")

                # Remove duplicates while preserving order
                seen = set()
                unique_zones = []
                for zone in all_linked_zones:
                    if zone not in seen:
                        seen.add(zone)
                        unique_zones.append(zone)

                return unique_zones
            elif template_data:
                # Single template mode with provided template data
                return self._get_vnet_linked_dns_zones_from_template(template_data, vnet_name, resource_groups)
            else:
                self.logger.warning(
                    "use_local_template=True but no template data provided and no multiple templates registered"
                )
                return []
        else:
            return self._get_vnet_linked_dns_zones_from_azure(vnet_name, resource_groups, subscription_id)

    def _get_vnet_linked_dns_zones_from_template(
        self, template_data: Dict[str, Any], vnet_name: str, resource_groups: List[str]
    ) -> List[str]:
        """
        Analyze Bicep template to find private DNS zones that a VNet is linked to.

        Args:
            template_data: The ARM template data
            vnet_name: Name of the virtual network
            resource_groups: List of resource group names (for logging purposes)

        Returns:
            List[str]: List of private DNS zone names that the VNet is linked to
        """
        try:
            resources = template_data.get("resources", [])
            linked_zones = []

            # First, find all private DNS zones in the template
            dns_zones = []
            for resource in resources:
                if resource.get("type", "") == "Microsoft.Network/privateDnsZones":
                    dns_zones.append(resource.get("name", ""))

            # Then, find all virtual network links and check if they reference our VNet
            for resource in resources:
                resource_type = resource.get("type", "")

                # Check for virtual network links
                if resource_type == "Microsoft.Network/privateDnsZones/virtualNetworkLinks":
                    properties = resource.get("properties", {})
                    virtual_network = properties.get("virtualNetwork", {})

                    # Handle different ways the VNet can be referenced in template
                    vnet_reference = virtual_network.get("id", "")

                    # Extract VNet name from various possible formats:
                    # - Direct name reference
                    # - ResourceId function calls
                    # - Full ARM resource ID paths
                    referenced_vnet_name = None

                    if isinstance(vnet_reference, str):
                        if vnet_reference == vnet_name:
                            # Direct name match
                            referenced_vnet_name = vnet_name
                        elif "resourceId(" in vnet_reference or "[" in vnet_reference:
                            # ARM function - try to extract VNet name
                            if ("'" + vnet_name + "'") in vnet_reference or ('"' + vnet_name + '"') in vnet_reference:
                                referenced_vnet_name = vnet_name
                        elif "/" in vnet_reference:
                            # Full resource ID path
                            referenced_vnet_name = vnet_reference.split("/")[-1]

                    # If this link references our VNet, find which DNS zone it belongs to
                    if referenced_vnet_name == vnet_name:
                        # Extract DNS zone name from the link's parent resource
                        # Format: zone_name/virtualNetworkLinks/link_name
                        resource_name = resource.get("name", "")
                        if "/" in resource_name:
                            # Handle nested resource format: "zone_name/link_name"
                            zone_name = resource_name.split("/")[0]
                            if zone_name in dns_zones and zone_name not in linked_zones:
                                linked_zones.append(zone_name)
                        else:
                            # Handle dependency-based linking by checking dependsOn
                            depends_on = resource.get("dependsOn", [])
                            for dependency in depends_on:
                                if isinstance(dependency, str) and "privateDnsZones" in dependency:
                                    # Extract zone name from dependency reference
                                    for zone_name in dns_zones:
                                        if zone_name in dependency and zone_name not in linked_zones:
                                            linked_zones.append(zone_name)

            if linked_zones:
                self.logger.info(f"VNet '{vnet_name}' is linked to private DNS zones in template: {linked_zones}")
            else:
                self.logger.debug(f"VNet '{vnet_name}' is not linked to any private DNS zones in template")

            return linked_zones

        except Exception as e:
            self.logger.error(f"Failed to analyze template for VNet DNS zone links: {str(e)}")
            return []

    def _get_vnet_linked_dns_zones_from_azure(
        self, vnet_name: str, resource_groups: List[str], subscription_id: str
    ) -> List[str]:
        """
        Get private DNS zones from Azure portal that a VNet is linked to.
        Results are cached per (vnet_name, subscription_id) pair so that
        repeated lookups for the same VNet across different code paths
        reuse the same result.

        Args:
            vnet_name: Name of the virtual network
            resource_groups: List of resource group names to search in
            subscription_id: Azure subscription ID

        Returns:
            List[str]: List of private DNS zone names that the VNet is linked to
        """
        # Check cache first
        vnet_cache_key = (vnet_name, subscription_id)
        if vnet_cache_key in self._vnet_dns_links_cache:
            return self._vnet_dns_links_cache[vnet_cache_key]

        try:
            # We'll use ARM resource client to query for private DNS zone virtual network links
            resource_client = self._get_resource_client(subscription_id)
            linked_zones: List[str] = []

            # Collect all VNet link resources across all RGs in one pass per RG,
            # then match zones — avoids per-zone API calls.
            for resource_group in resource_groups:
                # Reuse cached DNS zones list (populated by _get_private_dns_zones_from_azure)
                dns_zones = self.get_private_dns_zones(resource_group, subscription_id)

                # Skip this resource group if no DNS zones found
                if not dns_zones:
                    continue

                # Build a set of zone names for fast lookup
                zone_name_set = {zone["name"] for zone in dns_zones}

                try:
                    # Fetch ALL virtual network links for this RG in a single API call
                    filter_str = "resourceType eq 'Microsoft.Network/privateDnsZones/virtualNetworkLinks'"
                    vnet_links = list(
                        resource_client.resources.list_by_resource_group(
                            resource_group_name=resource_group, filter=filter_str
                        )
                    )

                    # Match links to our VNet, extracting the parent DNS zone name
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
                                    # Extract the DNS zone name from the link resource ID
                                    # Format: .../privateDnsZones/{zoneName}/virtualNetworkLinks/{linkName}
                                    if link_id and "/privateDnsZones/" in link_id:
                                        parts = link_id.split("/")
                                        for idx, part in enumerate(parts):
                                            if part == "privateDnsZones" and idx + 1 < len(parts):
                                                zone_from_id = parts[idx + 1]
                                                if zone_from_id in zone_name_set and zone_from_id not in linked_zones:
                                                    linked_zones.append(zone_from_id)
                                                break
                        except Exception as link_error:
                            self.logger.debug(f"Error checking VNet link {link.id}: {str(link_error)}")
                            continue
                except Exception as rg_error:
                    self.logger.debug(f"Error listing VNet links in resource group {resource_group}: {str(rg_error)}")
                    continue

            if linked_zones:
                self.logger.info(f"VNet '{vnet_name}' is linked to private DNS zones: {linked_zones}")
            else:
                self.logger.warning(f"VNet '{vnet_name}' is not linked to any private DNS zones")
            self._vnet_dns_links_cache[vnet_cache_key] = linked_zones
            return linked_zones
        except Exception as e:
            self.logger.error(f"Error checking VNet links to private DNS zones: {str(e)}")
            self._vnet_dns_links_cache[vnet_cache_key] = []
            return []

    def get_bastion_host_name(
        self,
        vnet_name: str,
        resource_group: str,
        subscription_id: str,
        use_local_template: bool = False,
        template_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Get the name of Bastion Host linked to a Virtual Network.
        Enhanced to handle multiple Bicep templates with registered mappings.

        Args:
            vnet_name: Name of the virtual network
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID
            use_local_template: If True, analyze from Bicep template data instead of Azure portal
            template_data: The ARM template data to analyze (when use_local_template=True)

        Returns:
            Optional[str]: The name of the Bastion Host if found, None otherwise
        """
        if use_local_template:
            # Check if we have multiple templates registered
            if self.is_using_multiple_templates():
                # Get template data for this specific resource group
                rg_template_data = self.get_template_data_for_resource_group(resource_group)
                if rg_template_data:
                    return self._get_bastion_host_name_from_template(rg_template_data, vnet_name, resource_group)
                else:
                    self.logger.warning(
                        f"No template data found for resource group '{resource_group}' in registered mappings"
                    )
                    return None
            elif template_data:
                # Single template mode with provided template data
                return self._get_bastion_host_name_from_template(template_data, vnet_name, resource_group)
            else:
                self.logger.warning(
                    "use_local_template=True but no template data provided and no multiple templates registered"
                )
                return None
        else:
            return self._get_bastion_host_name_from_azure(vnet_name, resource_group, subscription_id)

    def _get_bastion_host_name_from_template(
        self, template_data: Dict[str, Any], vnet_name: str, resource_group: str
    ) -> Optional[str]:
        """
        Analyze Bicep template to find Bastion Host linked to a VNet.

        Args:
            template_data: The ARM template data
            vnet_name: Name of the virtual network
            resource_group: Name of the resource group (for logging purposes)

        Returns:
            Optional[str]: The name of the Bastion Host if found, None otherwise
        """
        try:
            resources = template_data.get("resources", [])

            # Find all Bastion Hosts in the template
            for resource in resources:
                resource_type = resource.get("type", "")

                # Check for Bastion Host resources
                if resource_type == "Microsoft.Network/bastionHosts":
                    bastion_name = resource.get("name", "")
                    properties = resource.get("properties", {})

                    # Check if this Bastion Host is linked to our VNet
                    # Bastion Hosts reference VNets through their subnet configuration
                    ip_configurations = properties.get("ipConfigurations", [])

                    for ip_config in ip_configurations:
                        subnet_ref = ip_config.get("properties", {}).get("subnet", {}).get("id", "")

                        # Extract VNet name from subnet reference
                        # Subnet ID format:
                        #   [resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-name', 'subnet-name')]
                        #   /subscriptions/.../providers/Microsoft.Network/virtualNetworks/vnet-name/subnets/subnet-name
                        referenced_vnet_name = None

                        if isinstance(subnet_ref, str):
                            if "resourceId(" in subnet_ref or "[" in subnet_ref:
                                # ARM function - try to extract VNet name
                                if ("'" + vnet_name + "'") in subnet_ref or ('"' + vnet_name + '"') in subnet_ref:
                                    referenced_vnet_name = vnet_name
                            elif "/" in subnet_ref and "virtualNetworks" in subnet_ref:
                                # Full resource ID path - extract VNet name
                                parts = subnet_ref.split("/")
                                for i, part in enumerate(parts):
                                    if part == "virtualNetworks" and i + 1 < len(parts):
                                        referenced_vnet_name = parts[i + 1]
                                        break

                        # If this Bastion Host references our VNet, return its name
                        if referenced_vnet_name == vnet_name:
                            self.logger.info(
                                "Found Bastion Host '"
                                + str(bastion_name)
                                + "' for VNet '"
                                + vnet_name
                                + "' in template"
                            )
                            return str(bastion_name) if bastion_name is not None else None

            self.logger.debug("No Bastion Host found for VNet '" + vnet_name + "' in template")
            return None

        except Exception as e:
            self.logger.error("Failed to analyze template for Bastion Host: " + str(e))
            return None

    def _get_bastion_host_name_from_azure(
        self, vnet_name: str, resource_group: str, subscription_id: str
    ) -> Optional[str]:
        """
        Get Bastion Host name from Azure portal that is linked to a VNet.

        Args:
            vnet_name: Name of the virtual network
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID

        Returns:
            Optional[str]: The name of the Bastion Host if found, None otherwise
        """
        try:
            network_client = self._get_network_client(subscription_id)
            bastions = network_client.bastion_hosts.list_by_resource_group(resource_group)

            for bastion in bastions:
                # Extract VNet name from the VNet ID in the bastion configuration
                if bastion.virtual_network and bastion.virtual_network.id:
                    bastion_vnet_name = bastion.virtual_network.id.split("/")[-1]
                    if bastion_vnet_name == vnet_name:
                        self.logger.info("Found Bastion Host '" + str(bastion.name) + "' for VNet '" + vnet_name + "'")
                        return str(bastion.name) if bastion.name is not None else None

            return None
        except Exception as e:
            self.logger.error("Failed to list bastion hosts for VNet " + vnet_name + ": " + str(e))
            return None

    def _get_subscription_home_tenant(self, subscription_id: str) -> Optional[str]:
        """
        Determine the home tenant ID for a subscription using multiple strategies.

        Strategy chain:
          1. SDK model attribute  (getattr(sub, 'tenant_id'))
          2. Raw deserialized dict (sub.as_dict())
          3. Direct ARM REST call  (api-version 2022-12-01 always includes tenantId)

        Results are cached per subscription for the lifetime of this AzureUtility.
        """
        # Lazy-init cache
        if not hasattr(self, "_home_tenant_cache"):
            self._home_tenant_cache: Dict[str, Optional[str]] = {}
        if subscription_id in self._home_tenant_cache:
            return self._home_tenant_cache[subscription_id]

        home_tenant: Optional[str] = None

        # ── Strategy 1 + 2: SDK model attribute / as_dict() ──
        try:
            sub_client = self._get_subscription_client()
            sub = sub_client.subscriptions.get(subscription_id)
            if sub:
                home_tenant = getattr(sub, "tenant_id", None)
                if not home_tenant and hasattr(sub, "as_dict"):
                    raw = sub.as_dict()
                    home_tenant = raw.get("tenant_id") or raw.get("tenantId")
        except Exception:
            pass

        # ── Strategy 3: Direct REST API call (always returns tenantId) ──
        if not home_tenant:
            try:
                import urllib.request

                token = self._get_credential().get_token("https://management.azure.com/.default")
                url = f"https://management.azure.com/subscriptions/{subscription_id}?api-version=2022-12-01"
                req = urllib.request.Request(
                    url, headers={"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                    home_tenant = data.get("tenantId")
                if home_tenant:
                    self.logger.debug(f"Resolved home tenant for {subscription_id} via REST: {home_tenant}")
            except Exception as e:
                self.logger.debug(f"REST fallback for subscription {subscription_id} home tenant failed: {e}")

        self._home_tenant_cache[subscription_id] = home_tenant
        return home_tenant

    def is_subscription_in_tenant(self, subscription_id: str, tenant_id: str, is_multitenant: bool = False) -> bool:
        """
        Check if a subscription's HOME tenant matches the specified tenant.

        Uses _get_subscription_home_tenant (SDK → as_dict → REST fallback chain)
        to reliably determine the subscription's home tenant, so each subscription
        is only rendered in its home tenant, not in tenants where it's visible via
        guest / B2B access.

        Args:
            subscription_id: Azure subscription ID
            tenant_id: Azure tenant ID
            is_multitenant: True when the caller is iterating multiple tenants
                — in that case AuthorizationFailed / cross-tenant token errors are
                expected noise and downgraded to DEBUG. When False (single tenant)
                AuthorizationFailed is surfaced as a WARNING so the user is alerted
                to the real RBAC issue.

        Returns:
            bool: True if the subscription belongs to (home tenant is) this tenant
        """
        try:
            subscription_client = self._get_subscription_client()
            try:
                sub = subscription_client.subscriptions.get(subscription_id)
                if not sub:
                    return False
            except ResourceNotFoundError:
                return False

            sub_name = getattr(sub, "display_name", subscription_id)
            tenant_name = self.get_tenant_name(tenant_id)

            home_tenant = self._get_subscription_home_tenant(subscription_id)
            if home_tenant:
                if home_tenant != tenant_id:
                    self.logger.info(
                        f"Subscription {sub_name} is accessible from {tenant_name} "
                        f"but its home tenant is {home_tenant} — skipping (guest access)"
                    )
                    return False
                self.logger.info(f"Subscription {sub_name} confirmed in home tenant {tenant_name}")
                return True

            # Could not determine home tenant — fall back to accessibility
            self.logger.warning(
                f"Could not determine home tenant for {sub_name}; "
                f"accepting in {tenant_name} (processed_subscriptions dedup may apply)"
            )
            return True
        except ClientAuthenticationError as auth_error:
            error_str = str(auth_error).lower()
            # Cross-tenant token-mismatch patterns are ALWAYS expected noise
            # (the SP doesn't even exist in the other tenant's directory).
            is_cross_tenant_token_error = any(
                term in error_str
                for term in [
                    "invalidauthenticationtokentenant",
                    "aadsts50020",
                ]
            )
            # AuthorizationFailed (403 RBAC) is suppressed ONLY when iterating
            # multiple tenants — otherwise it indicates a real "missing Reader"
            # condition the user MUST see (and the WebUI raises a popup on it).
            is_authz_failure = any(term in error_str for term in ["authorizationfailed", "does not have authorization"])
            if is_cross_tenant_token_error or (is_multitenant and is_authz_failure):
                self.logger.debug(
                    f"Subscription {subscription_id} not accessible in tenant {tenant_id} "
                    f"— expected cross-tenant auth mismatch, skipping"
                )
            else:
                self.logger.warning(
                    f"Subscription {subscription_id} not accessible in tenant {tenant_id}: {str(auth_error)}"
                )
            return False
        except Exception as e:
            error_str = str(e).lower()
            is_cross_tenant_token_error = any(term in error_str for term in ["aadsts", "invalidauthenticationtoken"])
            is_authz_failure = any(term in error_str for term in ["authorizationfailed", "does not have authorization"])
            if is_cross_tenant_token_error or (is_multitenant and is_authz_failure):
                self.logger.debug(
                    f"Subscription {subscription_id} not accessible in tenant {tenant_id} "
                    f"— expected cross-tenant auth mismatch, skipping"
                )
            else:
                self.logger.warning(f"Subscription {subscription_id} not accessible in tenant {tenant_id}: {str(e)}")
            return False

    def register_multiple_bicep_templates(
        self,
        templates_data: List[Dict[str, Any]],
        resource_groups: List[str],
        subscriptions: List[str],
        tenants: Optional[List[str]] = None,
    ) -> bool:
        """
        Register multiple Bicep templates with their corresponding resource groups, subscriptions, and tenants.

        Args:
            templates_data: List of ARM template data (converted from Bicep)
            resource_groups: List of resource group names corresponding to each template (by index)
            subscriptions: List of subscription IDs corresponding to each template (by index)
            tenants: Optional list of tenant IDs corresponding to each template (by index)

        Returns:
            bool: True if registration successful, False otherwise
        """
        try:
            # Validate input lengths match
            if not (len(templates_data) == len(resource_groups) == len(subscriptions)):
                self.logger.error("Templates, resource groups, and subscriptions lists must have the same length")
                return False

            if tenants and len(tenants) != len(templates_data):
                self.logger.error("If provided, tenants list must have the same length as templates")
                return False

            # If no tenants provided, try to discover them from subscriptions
            if not tenants:
                tenants = []
                for subscription_id in subscriptions:
                    tenant_id = self._discover_tenant_for_subscription(subscription_id)
                    tenants.append(tenant_id or "")

            # Clear existing mappings
            self._template_mappings = {
                "templates": [],
                "resource_groups": [],
                "subscriptions": [],
                "tenants": [],
                "rg_to_subscription": {},
                "subscription_to_tenant": {},
                "template_index_map": {},
            }

            # Store the mappings
            self._template_mappings["templates"] = templates_data
            self._template_mappings["resource_groups"] = resource_groups
            self._template_mappings["subscriptions"] = subscriptions
            self._template_mappings["tenants"] = tenants

            # Build quick lookup mappings
            for i, (rg, sub, tenant) in enumerate(zip(resource_groups, subscriptions, tenants)):
                self._template_mappings["rg_to_subscription"][rg] = sub
                self._template_mappings["subscription_to_tenant"][sub] = tenant
                self._template_mappings["template_index_map"][rg] = i

            self.logger.info(f"Successfully registered {len(templates_data)} Bicep templates with their mappings")
            return True

        except Exception as e:
            self.logger.error(f"Failed to register multiple Bicep templates: {str(e)}")
            return False

    def _discover_tenant_for_subscription(self, subscription_id: str) -> Optional[str]:
        """
        Discover the tenant ID for a given subscription.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            Optional[str]: Tenant ID if found, None otherwise
        """
        try:
            subscription_client = self._get_subscription_client()
            subscription = subscription_client.subscriptions.get(subscription_id)
            # In azure-mgmt-subscription v3, Subscription may not have tenant_id
            tid = getattr(subscription, "tenant_id", None)
            if tid:
                return str(tid)
            # Fallback: iterate tenants and check if this sub is accessible
            # (already authenticated, so just return the tenant we logged into)
            self.logger.warning(
                f"Subscription model lacks tenant_id; cannot auto-discover tenant for {subscription_id}"
            )
            return None
        except Exception as e:
            self.logger.warning(f"Could not discover tenant for subscription {subscription_id}: {str(e)}")
            return None

    def get_template_data_for_resource_group(self, resource_group: str) -> Optional[Dict[str, Any]]:
        """
        Get the template data for a specific resource group.

        Args:
            resource_group: Name of the resource group

        Returns:
            Optional[Dict[str, Any]]: Template data if found, None otherwise
        """
        try:
            if resource_group in self._template_mappings["template_index_map"]:
                index = self._template_mappings["template_index_map"][resource_group]
                result: Optional[Dict[str, Any]] = self._template_mappings["templates"][index]
                return result
            return None
        except Exception as e:
            self.logger.error(f"Error getting template data for resource group {resource_group}: {str(e)}")
            return None

    def get_subscription_for_resource_group(self, resource_group: str) -> Optional[str]:
        """
        Get the subscription ID for a specific resource group from registered mappings.

        Args:
            resource_group: Name of the resource group

        Returns:
            Optional[str]: Subscription ID if found, None otherwise
        """
        return cast(Optional[str], self._template_mappings["rg_to_subscription"].get(resource_group))

    def get_tenant_for_subscription(self, subscription_id: str) -> Optional[str]:
        """
        Get the tenant ID for a specific subscription from registered mappings.

        Args:
            subscription_id: Azure subscription ID

        Returns:
            Optional[str]: Tenant ID if found, None otherwise
        """
        return cast(Optional[str], self._template_mappings["subscription_to_tenant"].get(subscription_id))

    def get_all_registered_resource_groups(self) -> List[str]:
        """
        Get all registered resource groups.

        Returns:
            List[str]: List of all registered resource group names
        """
        return list(self._template_mappings["resource_groups"])

    def get_all_registered_subscriptions(self) -> List[str]:
        """
        Get all registered subscriptions.

        Returns:
            List[str]: List of all registered subscription IDs
        """
        return list(set(self._template_mappings["subscriptions"]))

    def get_all_registered_tenants(self) -> List[str]:
        """
        Get all registered tenants.

        Returns:
            List[str]: List of all registered tenant IDs
        """
        return list(set(filter(None, self._template_mappings["tenants"])))

    def is_using_multiple_templates(self) -> bool:
        """
        Check if multiple Bicep templates are currently registered.

        Returns:
            bool: True if multiple templates are registered, False otherwise
        """
        return len(self._template_mappings["templates"]) > 0

    def clear_all_caches(self) -> Dict[str, int]:
        """
        Clear all centralized API response caches.
        Returns a dict of cache names to the number of entries cleared.
        Useful for debugging or when re-running across different tenants.
        """
        stats: Dict[str, int] = {}
        cache_attrs = [
            "_rg_in_subscription_cache",
            "_subscription_name_cache",
            "_rg_location_cache",
            "_pe_subnet_cache",
            "_dns_zones_cache",
            "_dns_zones_without_vnets_cache",
            "_vnet_dns_links_cache",
            "_rg_has_vnets_cache",
            "_exported_templates",
        ]
        for attr in cache_attrs:
            cache = getattr(self, attr, None)
            if cache is not None:
                stats[attr] = len(cache)
                cache.clear()
        if hasattr(self, "_home_tenant_cache"):
            stats["_home_tenant_cache"] = len(self._home_tenant_cache)
            self._home_tenant_cache.clear()
        self.logger.info(f"Cleared all API caches: {stats}")
        return stats

    def get_cache_stats(self) -> Dict[str, int]:
        """
        Get statistics for all centralized caches.
        Returns a dict of cache names to entry counts.
        """
        stats: Dict[str, int] = {}
        cache_attrs = [
            "_rg_in_subscription_cache",
            "_subscription_name_cache",
            "_rg_location_cache",
            "_pe_subnet_cache",
            "_dns_zones_cache",
            "_dns_zones_without_vnets_cache",
            "_vnet_dns_links_cache",
            "_rg_has_vnets_cache",
            "_exported_templates",
        ]
        for attr in cache_attrs:
            cache = getattr(self, attr, None)
            if cache is not None:
                stats[attr] = len(cache)
        if hasattr(self, "_home_tenant_cache"):
            stats["_home_tenant_cache"] = len(self._home_tenant_cache)
        return stats

    def is_resource_group_in_subscription(
        self, resource_group: str, subscription_id: str, use_local_template: bool = False
    ) -> bool:
        """
        Check if a resource group exists in the specified subscription.
        Enhanced to handle multiple Bicep templates with registered mappings.
        Results are cached for the lifetime of this AzureUtility instance to
        eliminate redundant Azure API round-trips (this method is called 5+ times
        per RG across resource_processor, graph_generator, and edge layout).

        Args:
            resource_group: Name of the resource group
            subscription_id: Azure subscription ID
            use_local_template: If True, use registered template mappings instead of Azure portal

        Returns:
            bool: True if the resource group exists in the subscription, False otherwise
        """
        # Check centralized cache first (covers both Azure and template modes)
        cache_key = (resource_group, subscription_id)
        if cache_key in self._rg_in_subscription_cache:
            return self._rg_in_subscription_cache[cache_key]
        try:
            if use_local_template:
                self.logger.debug(
                    f"Checking resource group '{resource_group}' in subscription '{subscription_id}' using local template mappings"
                )
                # Check if we have multiple templates registered
                if self.is_using_multiple_templates():
                    # Use registered mappings to determine if RG belongs to subscription
                    mapped_subscription = self.get_subscription_for_resource_group(resource_group)
                    if mapped_subscription:
                        result = mapped_subscription == subscription_id
                        if result:
                            self.logger.info(
                                f"Resource group '{resource_group}' found in subscription '{subscription_id}' via template mapping"
                            )
                        else:
                            self.logger.debug(
                                f"Resource group '{resource_group}' is mapped to subscription '{mapped_subscription}', not '{subscription_id}'"
                            )
                        self._rg_in_subscription_cache[cache_key] = result
                        return result
                    else:
                        self.logger.warning(
                            f"Resource group '{resource_group}' not found in registered template mappings"
                        )
                        self._rg_in_subscription_cache[cache_key] = False
                        return False
                else:
                    # Single template mode - assume RG exists in the specified subscription
                    self.logger.debug(
                        f"Single template mode: assuming resource group '{resource_group}' exists in subscription '{subscription_id}'"
                    )
                    self._rg_in_subscription_cache[cache_key] = True
                    return True
            else:
                # Azure portal mode - check actual existence
                self.logger.debug(
                    f"Using Azure portal mode to check resource group '{resource_group}' in subscription '{subscription_id}'"
                )
                resource_client = self._get_resource_client(subscription_id)
                exists = resource_client.resource_groups.check_existence(resource_group)

                if exists:
                    subscription_name = self.get_subscription_name(subscription_id)
                    self.logger.info(f"Resource group {resource_group} found in subscription {subscription_name}")

                self._rg_in_subscription_cache[cache_key] = bool(exists)
                return bool(exists)
        except ClientAuthenticationError as auth_error:
            # Permission denied on check_existence means we cannot access this RG
            # in this subscription — skip it rather than proceeding optimistically
            subscription_name = (
                subscription_id
                if use_local_template
                else (self.get_subscription_name(subscription_id) or subscription_id)
            )
            self.logger.debug(
                f"No permission to check resource group {resource_group} in subscription {subscription_name}. "
                f"Skipping — the RG likely does not belong to this subscription. Error: {str(auth_error)}"
            )
            self._rg_in_subscription_cache[cache_key] = False
            return False
        except Exception as e:
            # Check if the error message contains authorization-related terms
            error_str = str(e).lower()
            if any(
                term in error_str
                for term in ["unauthorized", "forbidden", "permission", "access denied", "authorization", "401", "403"]
            ):
                subscription_name = (
                    subscription_id
                    if use_local_template
                    else (self.get_subscription_name(subscription_id) or subscription_id)
                )
                self.logger.debug(
                    f"No permission to check resource group {resource_group} in subscription {subscription_name}. "
                    f"Skipping — the RG likely does not belong to this subscription. Error: {str(e)}"
                )
                self._rg_in_subscription_cache[cache_key] = False
                return False
            else:
                self.logger.error(
                    f"Error checking resource group {resource_group} in subscription {subscription_id}: {str(e)}"
                )
            self._rg_in_subscription_cache[cache_key] = False
            return False

    def is_resource_group_not_in_all_subscriptions(
        self, resource_group: str, subscriptions: List[str], use_local_template: bool = False
    ) -> bool:
        """
        Check if a resource group exists in any subscription.
        Enhanced to handle multiple Bicep templates with registered mappings.

        Args:
            resource_group: Name of the resource group
            subscriptions: List of Azure subscription IDs
            use_local_template: If True, use registered template mappings instead of Azure portal

        Returns:
            bool: True if the resource group does not exist in any subscription, False otherwise
        """
        try:
            if use_local_template and self.is_using_multiple_templates():
                # Use registered mappings to check if RG exists in any of the provided subscriptions
                mapped_subscription = self.get_subscription_for_resource_group(resource_group)
                if mapped_subscription:
                    # Check if the mapped subscription is in the provided list
                    exists_in_any = mapped_subscription in subscriptions
                    if exists_in_any:
                        self.logger.debug(
                            f"Resource group '{resource_group}' found via template mapping in subscription '{mapped_subscription}'"
                        )
                    else:
                        self.logger.debug(
                            f"Resource group '{resource_group}' is mapped to subscription '{mapped_subscription}' which is not in the provided list"
                        )
                    return not exists_in_any
                else:
                    # RG not found in any registered template mappings
                    self.logger.debug(
                        f"Resource group '{resource_group}' not found in any registered template mappings"
                    )
                    return True
            else:
                # Azure portal mode or single template mode
                for subscription_id in subscriptions:
                    if self.is_resource_group_in_subscription(resource_group, subscription_id, use_local_template):
                        return False
                return True
        except Exception as e:
            self.logger.error(f"Error checking resource group in subscriptions: {str(e)}")
            return False


# Create a global instance for use throughout the application.
# The auth method can be overridden by setting CLOUDHORUS_AUTH_METHOD env var
# before this module is imported (main.py does this from --authMethod CLI arg).
_auth_method = os.environ.get("CLOUDHORUS_AUTH_METHOD", AzureUtility.AUTH_DEVICE_CODE)
az_sdk = AzureUtility(auth_method=_auth_method)


# For backwards compatibility, expose the methods as functions
def get_subscription_name(subscription_id: str) -> Optional[str]:
    """Get subscription name from subscription ID."""
    return az_sdk.get_subscription_name(subscription_id)


def get_resource_group_location(resource_group_name: str, subscription_id: str) -> Optional[str]:
    """Get the location of a resource group."""
    return az_sdk.get_resource_group_location(resource_group_name, subscription_id)


def export_resource_group_template(subscription_id: str, resource_group_name: str) -> Optional[str]:
    """Export a resource group as an ARM template."""
    return az_sdk.export_resource_group_template(subscription_id, resource_group_name)


def get_pe_subnet(pe_name: str, resource_group: str, subscription: str) -> Optional[str]:
    """Get the private endpoint subnet name."""
    return az_sdk.get_pe_subnet_name(pe_name, resource_group, subscription)


def get_private_dns_zones(
    resource_group: str,
    subscription_id: str,
    use_local_template: bool = False,
    template_data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Get private DNS zones in a resource group."""
    return az_sdk.get_private_dns_zones(resource_group, subscription_id, use_local_template, template_data)


def get_private_dns_zones_without_vnets(
    resource_group: str,
    subscription_id: str,
    use_local_template: bool = False,
    template_data: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Get private DNS zones in a resource group that has no VNets."""
    return az_sdk.get_private_dns_zones_without_vnets(
        resource_group, subscription_id, use_local_template, template_data
    )


def is_vnet_linked_to_private_dns_zone(
    vnet_name: str,
    resource_groups: List[str],
    subscription_id: str,
    use_local_template: bool = False,
    template_data: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Check if a VNet is linked to any private DNS zone."""
    return az_sdk.is_vnet_linked_to_private_dns_zone(
        vnet_name, resource_groups, subscription_id, use_local_template, template_data
    )


def login_to_tenant(tenant_id: str) -> Optional[str]:
    """Login to Azure with specific tenant."""
    return az_sdk.login_to_tenant(tenant_id)


def get_bastion_host_name(
    vnet_name: str,
    resource_group: str,
    subscription_id: str,
    use_local_template: bool = False,
    template_data: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Get the name of Bastion Host linked to a Virtual Network."""
    return az_sdk.get_bastion_host_name(vnet_name, resource_group, subscription_id, use_local_template, template_data)


def is_subscription_in_tenant(subscription_id: str, tenant_id: str, is_multitenant: bool = False) -> bool:
    """Check if a subscription exists in the specified tenant.

    When ``is_multitenant`` is True, AuthorizationFailed errors are downgraded
    to DEBUG (expected cross-tenant noise). When False, they surface as WARNING
    so the user is alerted to the real RBAC issue.
    """
    return az_sdk.is_subscription_in_tenant(subscription_id, tenant_id, is_multitenant=is_multitenant)


def is_resource_group_in_subscription(
    resource_group: str, subscription_id: str, use_local_template: bool = False
) -> bool:
    """Check if a resource group exists in the specified subscription."""
    return az_sdk.is_resource_group_in_subscription(resource_group, subscription_id, use_local_template)


def is_resource_group_not_in_all_subscriptions(
    resource_group: str, subscriptions: list, use_local_template: bool = False
) -> bool:
    """Check if a resource group exists in any subscription."""
    return az_sdk.is_resource_group_not_in_all_subscriptions(resource_group, subscriptions, use_local_template)


def get_tenant_name(tenant_id: str) -> Optional[str]:
    """Get the display name of an Azure tenant using its ID."""
    return az_sdk.get_tenant_name(tenant_id)


# New functions for multiple Bicep template support
def register_multiple_bicep_templates(
    templates_data: List[Dict[str, Any]],
    resource_groups: List[str],
    subscriptions: List[str],
    tenants: Optional[List[str]] = None,
) -> bool:
    """Register multiple Bicep templates with their corresponding resource groups, subscriptions, and tenants."""
    return az_sdk.register_multiple_bicep_templates(templates_data, resource_groups, subscriptions, tenants)


def get_template_data_for_resource_group(resource_group: str) -> Optional[Dict[str, Any]]:
    """Get the template data for a specific resource group."""
    return az_sdk.get_template_data_for_resource_group(resource_group)


def get_subscription_for_resource_group(resource_group: str) -> Optional[str]:
    """Get the subscription ID for a specific resource group from registered mappings."""
    return az_sdk.get_subscription_for_resource_group(resource_group)


def get_tenant_for_subscription(subscription_id: str) -> Optional[str]:
    """Get the tenant ID for a specific subscription from registered mappings."""
    return az_sdk.get_tenant_for_subscription(subscription_id)


def get_all_registered_resource_groups() -> List[str]:
    """Get all registered resource groups."""
    return az_sdk.get_all_registered_resource_groups()


def get_all_registered_subscriptions() -> List[str]:
    """Get all registered subscriptions."""
    return az_sdk.get_all_registered_subscriptions()


def get_all_registered_tenants() -> List[str]:
    """Get all registered tenants."""
    return az_sdk.get_all_registered_tenants()


def is_using_multiple_templates() -> bool:
    """Check if multiple Bicep templates are currently registered."""
    return az_sdk.is_using_multiple_templates()


def clear_all_caches() -> Dict[str, int]:
    """Clear all centralized API response caches. Returns {cache_name: entries_cleared}."""
    return az_sdk.clear_all_caches()


def get_api_cache_stats() -> Dict[str, int]:
    """Get statistics for all centralized API caches. Returns {cache_name: entry_count}."""
    return az_sdk.get_cache_stats()
