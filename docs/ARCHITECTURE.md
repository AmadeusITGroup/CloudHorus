# CloudHorus Service Architecture

## Service Dependency Graph

```
                                    main.py
                                       |
                                       v
                          GraphGeneratorService
                                       |
                    +------------------+------------------+
                    |                  |                  |
                    v                  v                  v
         AzureResourceService  BicepService   GraphBuilderService
                    |                  |                  |
                    v                  v                  v
        TemplateRegistryService BicepProcessorService  IconManager
                    |                  |
                    v                  v
         AzureNetworkService  ResourceAnalysisService
                                       |
                                       v
                              SubnetResolverService
```

## Service Categories

### 📦 Data Models
- `VisualizationConfig` - Main configuration container
- `LayoutConfig` - Graph layout settings
- `IconManager` - Resource icon paths

### 🔧 Azure Integration Services
- `AzureResourceService` - Azure SDK client wrapper
  - Manages subscriptions
  - Manages resource groups
  - Exports templates

- `AzureNetworkService` - Network resource operations
  - VNets and subnets
  - Private endpoints
  - Private DNS zones
  - Azure Bastion

### 🏗️ Bicep/ARM Services
- `BicepService` - Bicep CLI operations
  - Validate CLI installation
  - Compile Bicep to ARM
  - Check modular templates

- `BicepProcessorService` - Template processing
  - Load templates
  - Resolve parameters
  - Resolve variables
  - Parse ARM expressions

### 🔍 Analysis Services
- `ResourceAnalysisService` - Dependency analysis
  - Analyze template dependencies
  - Cross-RG dependencies
  - Build dependency graphs

- `SubnetResolverService` - Subnet resolution
  - Extract subnet names from IDs
  - Extract VNet names
  - Identify special subnets

### 📝 Template Management
- `TemplateRegistryService` - Template tracking
  - Register templates
  - Map templates to RGs
  - Track multi-template deployments

### 🎨 Graph Services
- `GraphGeneratorService` - Orchestration
  - Workflow coordination
  - Tenant/subscription/RG processing
  - Resource discovery

- `GraphBuilderService` - Graphviz construction
  - Create graph structure
  - Add clusters (tenant/sub/RG/VNet)
  - Add nodes (resources/subnets)
  - Add edges (dependencies)

### 📤 Export Services
- `PNGExporter` - PNG rendering
- `DOTExporter` - DOT file export
- `DrawioExporter` - Draw.io XML export

## Service Interaction Flow

### 1. Initialization Phase
```
main.py
  → Create VisualizationConfig
  → Instantiate all services
  → Inject dependencies
```

### 2. Template Mode Flow
```
GraphGeneratorService
  → BicepService.compile_bicep_to_arm()
  → BicepProcessorService.load_template()
  → BicepProcessorService.populate_template_parameters()
  → TemplateRegistryService.register_multiple_templates()
```

### 3. Live Mode Flow
```
GraphGeneratorService
  → AzureResourceService.list_resource_groups()
  → AzureResourceService.export_resource_group_template()
  → TemplateRegistryService.register_template()
```

### 4. Analysis Phase
```
GraphGeneratorService
  → ResourceAnalysisService.analyze_template_dependencies()
  → AzureNetworkService.get_pe_subnet_name()
  → AzureNetworkService.get_private_dns_zones()
  → SubnetResolverService.extract_subnet_name_from_id()
```

### 5. Graph Building Phase
```
GraphGeneratorService
  → GraphBuilderService.create_graph()
  → GraphBuilderService.add_tenant_cluster()
  → GraphBuilderService.add_subscription_cluster()
  → GraphBuilderService.add_resource_group_cluster()
  → GraphBuilderService.add_resource_node()
  → GraphBuilderService.add_edge()
```

### 6. Export Phase
```
main.py
  → PNGExporter.export(graph)
  → DOTExporter.export(graph)
  → DrawioExporter.export(graph) [optional]
```

## Service Characteristics

### All Services Inherit from BaseService
```python
class BaseService(ABC):
    """Base service with logging and validation."""

    def __init__(self):
        self.logger = SingletonLogger().get_logger()

    @abstractmethod
    def validate(self) -> bool:
        """Validate service is properly configured."""
        pass
```

### Common Patterns

#### 1. Dependency Injection
```python
class AzureNetworkService(BaseService):
    def __init__(
        self,
        azure_resource_service: AzureResourceService,
        template_registry_service: TemplateRegistryService
    ):
        super().__init__()
        self.azure_resource = azure_resource_service
        self.template_registry = template_registry_service
```

#### 2. Type Safety
```python
def get_subscription_name(
    self,
    subscription_id: str
) -> Optional[str]:
    """Get subscription name."""
    pass
```

#### 3. Comprehensive Docstrings
```python
def method(self, param: str) -> bool:
    """Brief description.

    Detailed explanation if needed.

    Args:
        param: Parameter description

    Returns:
        Return value description

    Raises:
        Exception: When it occurs

    Example:
        >>> service.method("value")
        True
    """
```

#### 4. Error Handling
```python
try:
    result = operation()
    self.logger.info(f"✓ Success: {result}")
    return result
except Exception as e:
    self.logger.error(f"✗ Failed: {e}")
    return None
```

## Testing Strategy

### Unit Tests
Each service can be tested in isolation:
```python
def test_azure_resource_service():
    service = AzureResourceService()
    assert service.validate()

    # Mock Azure SDK calls
    with patch('azure.mgmt.resource.SubscriptionClient'):
        result = service.get_subscription_name("sub-id")
        assert result is not None
```

### Integration Tests
Test service combinations:
```python
def test_network_service_integration():
    azure_resource = AzureResourceService()
    template_registry = TemplateRegistryService()
    network_service = AzureNetworkService(
        azure_resource, template_registry
    )

    # Test integration
    result = network_service.get_pe_subnet_name(...)
    assert result is not None
```

### End-to-End Tests
Test complete workflow:
```python
def test_graph_generation():
    config = VisualizationConfig(...)
    generator = GraphGeneratorService(config, ...)

    graph = generator.generate_graph()
    assert graph is not None

    png_path = PNGExporter().export(graph, "test")
    assert os.path.exists(png_path)
```

## Extension Points

### Adding a New Service
1. Inherit from `BaseService`
2. Implement `validate()` method
3. Add type hints to all methods
4. Write comprehensive docstrings
5. Add to `services/__init__.py`
6. Inject dependencies via constructor

### Adding a New Exporter
1. Inherit from `BaseService`
2. Implement `export(graph, output_path)` method
3. Add format-specific options
4. Add to `exporters/__init__.py`

### Adding a New Resource Handler
1. Add handler to `ResourceAnalysisService._RESOURCE_HANDLERS`
2. Implement extraction logic
3. Update docstrings

## Performance Considerations

### Caching
Services cache expensive operations:
- `AzureResourceService` caches Azure SDK clients
- `TemplateRegistryService` uses dictionaries for fast lookup
- `IconManager` caches icon paths

### Lazy Loading
Services load resources on-demand:
- Azure SDK clients created only when needed
- Templates loaded only when accessed

### Parallel Processing
Potential optimization points:
- Process multiple subscriptions in parallel
- Process multiple resource groups in parallel
- Compile multiple Bicep templates in parallel

## Monitoring and Logging

All services log key operations:
- `INFO`: Successful operations
- `WARNING`: Recoverable issues
- `ERROR`: Failures
- `DEBUG`: Detailed debugging info

Log format:
```
[CloudHorus] <Timestamp> <Level> <Service>: <Message>
```

Example:
```
[CloudHorus] 2025-01-15 10:30:45 INFO AzureResourceService: ✓ Retrieved subscription: my-subscription
```

