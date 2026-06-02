"""Provider-aware local template documents for offline rendering inputs."""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class LocalTemplateResource:
    """Normalized local template resource used by offline input builders."""

    address: str
    provider_name: str
    source_type: str
    renderer_type: str
    name: str
    properties: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    extra_fields: Dict[str, Any] = field(default_factory=dict)
    raw_values: Dict[str, Any] = field(default_factory=dict)

    def to_renderer_resource(self) -> Dict[str, Any]:
        """Convert the normalized resource into the current renderer contract."""
        resource = {
            "type": self.renderer_type,
            "name": self.name,
            "properties": self.properties,
        }
        if self.depends_on:
            resource["dependsOn"] = self.depends_on
        for key, value in self.extra_fields.items():
            if value is not None:
                resource[key] = value
        return resource


@dataclass
class LocalTemplateDocument:
    """Provider-aware local template document that can feed the current renderer."""

    source_format: str
    provider_name: str
    resources: List[LocalTemplateResource] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_renderer_template(self) -> Dict[str, Any]:
        """Return the renderer-compatible document shape used by offline modes."""
        template = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "resources": [resource.to_renderer_resource() for resource in self.resources],
        }
        if self.metadata:
            template["metadata"] = self.metadata
        return template