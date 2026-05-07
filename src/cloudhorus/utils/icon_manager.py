"""Icon management utilities."""

import os
from pathlib import Path
from typing import Optional

from ..config.settings import get_settings


class IconManager:
    """Manager for Azure resource icons."""

    def __init__(self, icons_directory: Optional[Path] = None):
        """Initialize the icon manager.

        Args:
            icons_directory: Optional path to icons directory. If None, uses settings.
        """
        if icons_directory is None:
            settings = get_settings()
            self.icons_directory = settings.icons_directory
        else:
            self.icons_directory = Path(icons_directory)

        self._icon_cache: dict[str, str] = {}

    def get_icon_path(self, resource_type: str) -> str:
        """Get the icon path for a resource type.

        Args:
            resource_type: The Azure resource type (e.g., Microsoft.Network/virtualNetworks)

        Returns:
            Path to the icon file
        """
        # Check cache first
        if resource_type in self._icon_cache:
            return self._icon_cache[resource_type]

        # Extract the icon name from resource type
        icon_name = self._extract_icon_name(resource_type)

        # Try to find the icon file
        icon_path = self._find_icon_file(icon_name)

        # Cache the result
        self._icon_cache[resource_type] = icon_path

        return icon_path

    def _extract_icon_name(self, resource_type: str) -> str:
        """Extract icon name from resource type.

        Args:
            resource_type: The Azure resource type

        Returns:
            Icon name
        """
        # Handle special cases
        if "Microsoft.Web/sites" in resource_type:
            return "webapp"
        elif "Microsoft.Network/virtualNetworks/subnets" in resource_type:
            return "subnet"
        elif "Microsoft.ManagedIdentity" in resource_type:
            return "managedidentity"

        # Default: use the last part of the resource type
        parts = resource_type.split("/")
        if len(parts) > 1:
            return parts[-1].lower()

        return resource_type.lower()

    def _find_icon_file(self, icon_name: str) -> str:
        """Find the icon file in the icons directory.

        Args:
            icon_name: Name of the icon to find

        Returns:
            Path to the icon file, or default icon if not found
        """
        # Try common extensions
        for ext in [".png", ".svg", ".jpg", ".jpeg"]:
            icon_path = self.icons_directory / f"{icon_name}{ext}"
            if icon_path.exists():
                return str(icon_path)

        # Try with different case variations
        for ext in [".png", ".svg"]:
            # Lowercase
            icon_path = self.icons_directory / f"{icon_name.lower()}{ext}"
            if icon_path.exists():
                return str(icon_path)

            # Capitalize first letter
            icon_path = self.icons_directory / f"{icon_name.capitalize()}{ext}"
            if icon_path.exists():
                return str(icon_path)

        # Return default icon
        settings = get_settings()
        default_path = self.icons_directory / settings.default_icon

        if default_path.exists():
            return str(default_path)

        # Last resort: return the icon name as-is
        return icon_name

    def clear_cache(self) -> None:
        """Clear the icon cache."""
        self._icon_cache.clear()


# Global icon manager instance
_icon_manager: Optional[IconManager] = None


def get_icon_manager() -> IconManager:
    """Get the global icon manager instance."""
    global _icon_manager
    if _icon_manager is None:
        _icon_manager = IconManager()
    return _icon_manager


def get_icon(resource_type: str) -> str:
    """Get icon path for a resource type (backward compatibility).

    Args:
        resource_type: The Azure resource type

    Returns:
        Path to the icon file
    """
    return get_icon_manager().get_icon_path(resource_type)
