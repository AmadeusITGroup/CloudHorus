# Changelog

All notable changes to CloudHorus will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.1] - 2026-03-11

_Release created automatically._

## [2.0.0] - 2026-02-27

### Added
- **Modern Web UI** — Desktop GUI powered by pywebview + HTML/CSS/JS
- **Bicep Mode** — Visualize infrastructure from local Bicep/ARM templates without Azure access
- **Multi-tenant support** — Scan multiple Azure tenants in a single diagram
- **Cross-RG Private Endpoint rendering** — PEs linked to resources in other resource groups
- **Subnet optimization** — Hide subnets without VNet integration
- **Private Endpoint optimization** — Group/move PEs by subnet context
- **Cross-PE optimization** — Hide PEs without cross-tenant dependencies
- **Private DNS Zone aggregation** — Aggregate DNS zones per VNet
- **Per-subscription optimization flags** — Fine-grained control per subscription
- **Multiple Bicep template support** — Analyze multi-file Bicep blueprints
- **PNG, DOT, and Draw.io export formats**
- **Template caching** — Reuse exported ARM templates across runs
- **Service-oriented architecture** (`src/cloudhorus/`) alongside core engine

### Changed
- Replaced legacy Tkinter GUI with modern pywebview-based Web UI
- Improved graph layout with configurable edge directions and lengths
- Enhanced icon resolution for Azure resource types

## [1.0.0] - 2025-06-01

### Added
- Initial release
- Azure resource graph visualization via CLI
- Graphviz DOT output
- Azure resource icon mapping
- Subnet and VNet rendering
- Private Endpoint dependency tracking

