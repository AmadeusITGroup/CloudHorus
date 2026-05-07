# CloudHorus Package

CloudHorus refactored into a modular, service-oriented architecture.

## Package Structure

```
cloudhorus/
├── models/              # Data models and configuration
├── config/             # Configuration classes
├── utils/              # Utility functions
├── services/           # Business logic services
└── exporters/          # Output format exporters
```

## Quick Start

### Using the Services

```python
from cloudhorus.services import (
    AzureResourceService,
    GraphGeneratorService,
    GraphBuilderService
)
from cloudhorus.exporters import PNGExporter
from cloudhorus.models import VisualizationConfig, LayoutConfig

# 1. Create configuration
layout = LayoutConfig(
    edge_direction="TB",
    max_subnet_per_line=4
)

config = VisualizationConfig(
    tenants=["tenant1"],
    subscriptions=["sub1"],
    resource_groups=["rg1"],
    layout=layout
)

# 2. Initialize services
azure_resource = AzureResourceService()
# ... initialize other services

generator = GraphGeneratorService(
    config=config,
    azure_resource_service=azure_resource,
    # ... inject other dependencies
)

# 3. Generate graph
graph = generator.generate_graph()

# 4. Export
exporter = PNGExporter()
exporter.export(graph, "output")
```

## Services Overview

### Azure Integration
- `AzureResourceService` - Subscription and resource group operations
- `AzureNetworkService` - Network resource queries (VNets, subnets, PEs, DNS)

### Bicep/ARM Processing
- `BicepService` - Bicep CLI operations
- `BicepProcessorService` - Template parsing and parameter resolution

### Analysis
- `ResourceAnalysisService` - Dependency analysis
- `SubnetResolverService` - Subnet name extraction

### Template Management
- `TemplateRegistryService` - Template to resource mapping

### Graph Generation
- `GraphGeneratorService` - Orchestrates graph generation workflow
- `GraphBuilderService` - Constructs Graphviz graphs

### Export
- `PNGExporter` - Render graphs as PNG images
- `DOTExporter` - Save graphs as DOT files
- `DrawioExporter` - Export to Draw.io XML format

## Design Principles

### 1. Dependency Injection
All services receive dependencies via constructor:
```python
class AzureNetworkService:
    def __init__(
        self,
        azure_resource_service: AzureResourceService,
        template_registry_service: TemplateRegistryService
    ):
        self.azure_resource = azure_resource_service
        self.template_registry = template_registry_service
```

### 2. Type Safety
All methods use type hints:
```python
def get_subscription_name(self, subscription_id: str) -> Optional[str]:
    """Get subscription display name."""
    pass
```

### 3. Single Responsibility
Each service has one clear purpose. Services average 300 lines.

### 4. Testability
Easy to mock dependencies for unit testing:
```python
mock_azure = Mock(spec=AzureResourceService)
network = AzureNetworkService(mock_azure, mock_registry)
```

## Testing

### Unit Tests
```python
def test_azure_resource_service():
    service = AzureResourceService()
    assert service.validate()
```

### Integration Tests
```python
def test_graph_generation():
    config = VisualizationConfig(...)
    generator = GraphGeneratorService(config, ...)
    graph = generator.generate_graph()
    assert graph is not None
```

## Extension

### Add a New Service
1. Inherit from `BaseService`
2. Implement `validate()` method
3. Add type hints
4. Write docstrings
5. Export from `__init__.py`

Example:
```python
from cloudhorus.services.base import BaseService

class MyService(BaseService):
    def __init__(self, dependency: SomeService):
        super().__init__()
        self.dependency = dependency

    def validate(self) -> bool:
        self.logger.info("MyService validated")
        return True

    def do_something(self) -> bool:
        """Do something useful."""
        try:
            result = self.dependency.operation()
            self.logger.info(f"✓ Success: {result}")
            return True
        except Exception as e:
            self.logger.error(f"✗ Failed: {e}")
            return False
```

### Add a New Exporter
1. Inherit from `BaseService`
2. Implement `export(graph, output_path)` method
3. Add to `exporters/__init__.py`

Example:
```python
class SVGExporter(BaseService):
    def validate(self) -> bool:
        return True

    def export(self, graph: Digraph, output_path: str) -> Optional[str]:
        """Export to SVG format."""
        try:
            graph.render(output_path, format='svg', cleanup=False)
            return f"{output_path}.svg"
        except Exception as e:
            self.logger.error(f"SVG export failed: {e}")
            return None
```

## Documentation

- `/docs/ARCHITECTURE.md` - Architecture overview
- `/docs/MIGRATION_GUIDE.md` - Migration from old structure
- `/docs/REFACTORING_COMPLETE.md` - Refactoring summary
- Service docstrings - Implementation details

## Contributing

1. Follow the service pattern (inherit from `BaseService`)
2. Add type hints to all methods
3. Write Google-style docstrings
4. Keep services focused (single responsibility)
5. Write unit tests
6. Update documentation

## License

See project root LICENSE file.

