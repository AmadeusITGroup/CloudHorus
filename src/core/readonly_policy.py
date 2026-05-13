"""Read-only HTTP pipeline policy for Azure SDK clients.

This policy intercepts every HTTP request at the SDK pipeline level and
blocks any operation that could modify Azure resources (PUT, PATCH, DELETE,
and non-whitelisted POST endpoints).  This provides defense-in-depth on
top of the RBAC Reader role recommendation: even if the identity happens
to have write permissions, the SDK will never send a mutating call.
"""

from azure.core.pipeline import PipelineRequest, PipelineResponse
from azure.core.pipeline.policies import HTTPPolicy

from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()

# POST URL-path segments that are read-only operations.
# Matched against the last segment of the URL path (the ARM action name).
_SAFE_POST_ACTIONS = (
    "exportTemplate",  # resource group ARM template export
    "list",  # generic ARM list actions (e.g. subscriptions.list)
)

# Token endpoint hosts — always allowed (not ARM operations).
_TOKEN_HOSTS = (
    "https://login.microsoftonline.com/",
    "https://login.microsoft.com/",
    "https://sts.windows.net/",
)


class ReadOnlyPolicy(HTTPPolicy):
    """Azure SDK pipeline policy that blocks all write operations.

    Attach via ``per_call_policies=[ReadOnlyPolicy()]`` on any ARM client.
    """

    def send(self, request: PipelineRequest) -> PipelineResponse:
        http_request = request.http_request
        method = http_request.method.upper()
        url = http_request.url

        # Always allow token acquisition (exact prefix match)
        if any(url.startswith(host) for host in _TOKEN_HOSTS):
            return self.next.send(request)

        # GET / HEAD / OPTIONS are always safe
        if method in ("GET", "HEAD", "OPTIONS"):
            return self.next.send(request)

        # Block all PUT, PATCH, DELETE unconditionally
        if method in ("PUT", "PATCH", "DELETE"):
            logger.warning(
                f"[ReadOnlyPolicy] BLOCKED {method} {url} — " "CloudHorus enforces read-only access at the SDK level."
            )
            raise PermissionError(
                f"ReadOnlyPolicy: {method} operations are blocked. "
                "CloudHorus only requires read access to Azure resources."
            )

        # POST — allow only known read-only endpoints
        if method == "POST":
            path = url.split("?", 1)[0]  # strip query string
            # Extract the last path segment (the ARM action name)
            action = path.rstrip("/").rsplit("/", 1)[-1]

            if action in _SAFE_POST_ACTIONS or action.startswith("list"):
                return self.next.send(request)

            logger.warning(f"[ReadOnlyPolicy] BLOCKED POST {url} — " "endpoint not in the read-only allowlist.")
            raise PermissionError(
                f"ReadOnlyPolicy: POST to {path} is blocked. "
                "CloudHorus only requires read access to Azure resources."
            )

        # Unknown method — block by default
        logger.warning(f"[ReadOnlyPolicy] BLOCKED unknown method {method} {url}")
        raise PermissionError(f"ReadOnlyPolicy: {method} operations are blocked.")
