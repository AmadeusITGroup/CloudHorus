"""Resource filtering patterns and utilities."""

import re
from typing import List, Pattern


class ResourceFilter:
    """Filter for determining which resources to skip in visualization."""

    # Resources to skip entirely from visualization
    SKIP_RESOURCE_PATTERNS: List[str] = [
        r"Microsoft.Network/networkSecurityGroups/.*",
        r"Microsoft.Network/routeTables/.*",
        r"microsoft.insights/scheduledqueryrules.*",
        r"Microsoft.Insights/metricAlerts.*",
        r"Microsoft.Network/privateDnsZones",
        r"Microsoft.Network/bastionHosts",
        r"microsoft.alertsmanagement/smartdetectoralertrules",
        r".*Microsoft.Resources/deploymentScripts.*",
    ]

    # Resources to skip from dependency tracking
    SKIP_DEPENDENCY_PATTERNS: List[str] = [
        r"Microsoft.Network/networkSecurityGroups/.*",
        r"Microsoft.Network/routeTables/.*",
        r"Microsoft.Network/virtualNetworks$",
        r"microsoft.insights/scheduledqueryrules.*",
        r"Microsoft.Insights/metricAlerts.*",
        r"Microsoft.Network/privateDnsZones",
        r"Microsoft.Network/bastionHosts",
        r"microsoft.alertsmanagement/smartdetectoralertrules",
        r".*Microsoft.Resources/deploymentScripts.*",
    ]

    def __init__(self):
        """Initialize the resource filter with compiled patterns."""
        self._skip_patterns: List[Pattern] = [re.compile(pattern) for pattern in self.SKIP_RESOURCE_PATTERNS]
        self._skip_dependency_patterns: List[Pattern] = [
            re.compile(pattern) for pattern in self.SKIP_DEPENDENCY_PATTERNS
        ]

    def should_skip_resource(self, resource_type: str) -> bool:
        """Check if a resource should be skipped from visualization.

        Args:
            resource_type: The Azure resource type (e.g., Microsoft.Network/virtualNetworks)

        Returns:
            True if the resource should be skipped, False otherwise
        """
        return any(pattern.match(resource_type) for pattern in self._skip_patterns)

    def should_skip_dependency(self, resource_type: str) -> bool:
        """Check if a resource's dependencies should be skipped.

        Args:
            resource_type: The Azure resource type

        Returns:
            True if dependencies should be skipped, False otherwise
        """
        return any(pattern.match(resource_type) for pattern in self._skip_dependency_patterns)

    def add_skip_pattern(self, pattern: str) -> None:
        """Add a custom pattern to skip resources.

        Args:
            pattern: Regex pattern to match resource types
        """
        self.SKIP_RESOURCE_PATTERNS.append(pattern)
        self._skip_patterns.append(re.compile(pattern))

    def add_skip_dependency_pattern(self, pattern: str) -> None:
        """Add a custom pattern to skip resource dependencies.

        Args:
            pattern: Regex pattern to match resource types
        """
        self.SKIP_DEPENDENCY_PATTERNS.append(pattern)
        self._skip_dependency_patterns.append(re.compile(pattern))


# Global filter instance
_filter_instance: ResourceFilter = ResourceFilter()


def should_skip(resource_type: str) -> bool:
    """Check if a resource should be skipped (backward compatibility).

    Args:
        resource_type: The Azure resource type

    Returns:
        True if the resource should be skipped
    """
    return _filter_instance.should_skip_resource(resource_type)


def should_skip_dependency(resource_type: str) -> bool:
    """Check if a dependency should be skipped (backward compatibility).

    Args:
        resource_type: The Azure resource type

    Returns:
        True if the dependency should be skipped
    """
    return _filter_instance.should_skip_dependency(resource_type)


def get_filter() -> ResourceFilter:
    """Get the global resource filter instance."""
    return _filter_instance
