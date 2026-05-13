"""Azure authentication service."""

import os
from datetime import datetime
from typing import Optional

from azure.identity import ChainedTokenCredential, ClientSecretCredential, DefaultAzureCredential, DeviceCodeCredential
from azure.mgmt.subscription import SubscriptionClient

from core.readonly_policy import ReadOnlyPolicy

from .base import BaseService


class AzureAuthService(BaseService):
    """Handles Azure authentication and credential management."""

    def __init__(self):
        """Initialize the authentication service."""
        super().__init__()
        self._credentials = None
        self._subscription_client: Optional[SubscriptionClient] = None
        self._readonly_policy = ReadOnlyPolicy()
        self._auth_method = os.environ.get("CLOUDHORUS_AUTH_METHOD", "device-code")

    def _is_non_interactive(self) -> bool:
        """Check if running in non-interactive / CI-CD mode."""
        return os.environ.get("CLOUDHORUS_NON_INTERACTIVE", "").lower() in ("true", "1", "yes")

    def _device_code_callback(self, verification_uri: str, user_code: str, expires_on: datetime) -> None:
        """Display device code authentication information to user."""
        import sys
        from datetime import timezone

        # expires_on is an absolute datetime; compute remaining for console display
        remaining = int(max(0, (expires_on - datetime.now(timezone.utc)).total_seconds()))
        minutes, secs = divmod(remaining, 60)
        expires_display = f"{minutes} min {secs} sec" if minutes else f"{secs} seconds"

        auth_message = f"\n{'='*60}\n"
        auth_message += "🚨 AZURE AUTHENTICATION REQUIRED 🚨\n"
        auth_message += f"{'='*60}\n"
        auth_message += f"To sign in, use a web browser to open:\n"
        auth_message += f"    {verification_uri}\n\n"
        auth_message += f"And enter the code:\n"
        auth_message += f"    {user_code}\n\n"
        auth_message += f"This code will expire in {expires_display}.\n"
        auth_message += f"{'='*60}\n"

        print(auth_message, flush=True)
        sys.stdout.flush()

    def get_credential(self):
        """Get or create Azure credential.

        Supports three methods based on CLOUDHORUS_AUTH_METHOD:
        - service-principal: ClientSecretCredential from env vars
        - environment: DefaultAzureCredential (auto-detects pre-existing auth)
        - device-code: Interactive with DefaultAzureCredential fallback

        Returns:
            Token credential for Azure authentication
        """
        if self._credentials is None:
            if self._auth_method == "service-principal":
                self._credentials = self._create_sp_credential()
                self._subscription_client = SubscriptionClient(
                    self._credentials,
                    per_call_policies=[self._readonly_policy],
                )
                self.logger.info("Successfully authenticated with Service Principal")
            elif self._auth_method == "environment":
                self._credentials = DefaultAzureCredential(
                    exclude_interactive_browser_credential=True,
                    exclude_developer_cli_credential=True,
                )
                self._subscription_client = SubscriptionClient(
                    self._credentials,
                    per_call_policies=[self._readonly_policy],
                )
                self.logger.info(
                    "Successfully authenticated with environment credentials "
                    "(auto-detected: env vars / managed identity / az login)"
                )
            else:
                # Guard: fail-fast in CI/CD instead of blocking on device-code
                if self._is_non_interactive():
                    raise EnvironmentError(
                        "Non-interactive mode is enabled but authentication requires device-code flow. "
                        "Use --authMethod service-principal or --authMethod environment for CI/CD pipelines."
                    )
                try:
                    default_credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
                    device_credential = DeviceCodeCredential(prompt_callback=self._device_code_callback)
                    self._credentials = ChainedTokenCredential(default_credential, device_credential)

                    self._subscription_client = SubscriptionClient(
                        self._credentials,
                        per_call_policies=[self._readonly_policy],
                    )
                    list(self._subscription_client.subscriptions.list())

                    self.logger.info("Successfully authenticated with Azure")
                except Exception as e:
                    self.logger.error(f"Failed to authenticate: {str(e)}")
                    self.logger.info("Attempting interactive device code authentication...")

                    self._subscription_client = SubscriptionClient(
                        self._credentials,
                        per_call_policies=[self._readonly_policy],
                    )
                    list(self._subscription_client.subscriptions.list())
                    self.logger.info("Successfully authenticated with interactive login")

        assert self._credentials is not None
        return self._credentials

    def _create_sp_credential(self) -> ClientSecretCredential:
        """Create a ClientSecretCredential from environment variables.

        Returns:
            ClientSecretCredential

        Raises:
            EnvironmentError: If required env vars are missing.
        """
        tenant_id = os.environ.get("AZURE_TENANT_ID", "").strip()
        client_id = os.environ.get("AZURE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("AZURE_CLIENT_SECRET", "").strip()

        if not tenant_id or not client_id:
            raise EnvironmentError("Service-principal auth requires AZURE_TENANT_ID and AZURE_CLIENT_ID.")
        if not client_secret:
            raise EnvironmentError("Service-principal auth requires AZURE_CLIENT_SECRET environment variable.")

        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

    def get_subscription_client(self) -> SubscriptionClient:
        """Get the Azure Subscription client.

        Returns:
            SubscriptionClient instance
        """
        if self._subscription_client is None:
            self._subscription_client = SubscriptionClient(
                self.get_credential(),
                per_call_policies=[self._readonly_policy],
            )
        return self._subscription_client

    def login_to_tenant(self, tenant_id: str) -> bool:
        """Login to specific Azure tenant.

        Args:
            tenant_id: The Azure tenant ID

        Returns:
            True if login successful, False otherwise
        """
        try:
            self.logger.info(f"Logging in to tenant {tenant_id}...")

            if self._auth_method in ("service-principal", "environment"):
                # SP / environment credential is pre-scoped; just validate
                cred = self.get_credential()
                cred.get_token("https://management.azure.com/.default")
                self._subscription_client = SubscriptionClient(
                    cred,
                    per_call_policies=[self._readonly_policy],
                )
                self.logger.info(f"{self._auth_method} authenticated to tenant {tenant_id}")
                return True

            # Guard: fail-fast in CI/CD instead of blocking on device-code
            if self._is_non_interactive():
                raise EnvironmentError(
                    "Non-interactive mode: device-code login required but not allowed. "
                    "Use --authMethod service-principal or --authMethod environment for CI/CD pipelines."
                )

            credential = DeviceCodeCredential(tenant_id=tenant_id, prompt_callback=self._device_code_callback)
            self._credentials = credential

            self._subscription_client = SubscriptionClient(
                credential,
                per_call_policies=[self._readonly_policy],
            )
            list(self._subscription_client.subscriptions.list())

            self.logger.info(f"Successfully logged in to tenant {tenant_id}")
            return True

        except Exception as e:
            self.logger.error(f"Login to tenant failed: {str(e)}")
            return False

    def validate(self) -> bool:
        """Validate authentication is working.

        Returns:
            True if authenticated successfully
        """
        try:
            self.get_credential()
            return True
        except Exception:
            return False
