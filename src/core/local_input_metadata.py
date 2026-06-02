"""Helpers for parsing local input scope metadata across offline modes."""

import json
from typing import Any, Dict, List

DEFAULT_PROVIDER = "azurerm"
DEFAULT_SUBSCRIPTION = "cloudhorus-subscription"
DEFAULT_TENANT = "cloudhorus-tenant"


def synthesize_scope_metadata(count: int, provider: str = DEFAULT_PROVIDER) -> List[Dict[str, str]]:
    """Create default scope metadata entries for offline inputs without explicit scope files."""
    return [
        {
            "provider": provider,
            "subscription": DEFAULT_SUBSCRIPTION,
            "tenant": DEFAULT_TENANT,
            "resourceGroup": f"cloudhorus-rg-{index + 1}",
        }
        for index in range(count)
    ]


def parse_scope_metadata_files(file_paths: List[str], provider: str = DEFAULT_PROVIDER) -> Dict[str, Any]:
    """Parse scope metadata files or parameter files containing `_cloudHorus` metadata."""
    scopes: List[Dict[str, str]] = []
    subscriptions: List[Dict[str, Any]] = []
    sub_order: List[str] = []
    sub_map: Dict[str, Dict[str, Any]] = {}
    template_sub_map: List[int] = []
    errors: List[str] = []

    for index, file_path in enumerate(file_paths):
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            scope = _extract_scope_metadata(data, index, provider)
            scopes.append(scope)

            subscription_id = scope["subscription"]
            if subscription_id not in sub_map:
                sub_map[subscription_id] = {
                    "tenant": scope["tenant"],
                    "resourceGroups": [],
                    "provider": scope["provider"],
                }
                sub_order.append(subscription_id)

            resource_group = scope["resourceGroup"]
            if resource_group not in sub_map[subscription_id]["resourceGroups"]:
                sub_map[subscription_id]["resourceGroups"].append(resource_group)

            template_sub_map.append(sub_order.index(subscription_id))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{file_path}: {exc}")
            template_sub_map.append(-1)

    subscriptions = [
        {
            "id": subscription_id,
            "tenant": sub_map[subscription_id]["tenant"],
            "resourceGroups": sub_map[subscription_id]["resourceGroups"],
            "provider": sub_map[subscription_id]["provider"],
        }
        for subscription_id in sub_order
    ]

    return {
        "scopes": scopes,
        "subscriptions": subscriptions,
        "templateSubMap": template_sub_map,
        "errors": errors,
    }


def scope_lists_from_scopes(scopes: List[Dict[str, str]]) -> Dict[str, List[str]]:
    """Convert parsed scope metadata into argument lists used by the renderer."""
    return {
        "tenants": [scope["tenant"] for scope in scopes],
        "subscriptions": [scope["subscription"] for scope in scopes],
        "resourcegroups": [scope["resourceGroup"] for scope in scopes],
    }


def _extract_scope_metadata(data: Dict[str, Any], index: int, provider: str) -> Dict[str, str]:
    if not isinstance(data, dict):
        data = {}

    scope_source = data.get("_cloudHorus") or data.get("scope") or data

    return {
        "provider": str(scope_source.get("provider", provider)),
        "subscription": str(scope_source.get("subscription", DEFAULT_SUBSCRIPTION)),
        "tenant": str(scope_source.get("tenant", DEFAULT_TENANT)),
        "resourceGroup": str(scope_source.get("resourceGroup", f"cloudhorus-rg-{index + 1}")),
    }