"""Provider-aware local template documents for offline rendering inputs."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    change_category: Optional[str] = None
    inspector_values: Optional[Dict[str, Any]] = None
    #: The Terraform address to publish on the renderer contract, set only when
    #: Inspector_Mode is on. `address` itself is always populated, so publishing it
    #: unconditionally would change the Renderer_Template of every offline run;
    #: this field carries the opt-in, exactly as `inspector_values` does, and the
    #: `address` key is emitted only when it is set (Requirements 1.5, 4.4, 5.5).
    inspector_address: Optional[str] = None

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
        if self.inspector_address is not None:
            resource["address"] = self.inspector_address
        if self.change_category is not None:
            resource["changeCategory"] = self.change_category
        if self.inspector_values is not None:
            resource["inspectorValues"] = self.inspector_values
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