<!-- Project Logo -->
<p align="center">
  <img src="assets/logo/cloudhorus-icon.png" alt="CloudHorus Logo" width="250" />
</p>

# CloudHorus 🦅☁️

**Soar Above Your Cloud Complexity**

CloudHorus is the divine guardian of Azure cloud architecture, soaring above your infrastructure with the all-seeing eye of Horus. Navigate your cloud kingdom with falcon-sharp precision and divine clarity. Every resource protected, every dependency mapped, every connection blessed by the sky god.

Perfect for cloud architects, Devops, POs, everyone with an login access who demand oversight of their cloud resources.

## 📋 About CloudHorus

**CloudHorus** is an open-source Azure cloud architecture visualization tool that automatically generates rich, hierarchical dependency diagrams from your live Azure infrastructure or Infrastructure-as-Code (IaC) templates. It bridges the gap between raw cloud configuration data and human-readable architectural diagrams, enabling teams to understand, document, and govern their Azure environments at a glance.

### What It Does

CloudHorus ingests Azure resource metadata — either by querying a live subscription in real time or by compiling Bicep/ARM templates offline — and transforms that data into a layered graph that faithfully reflects the structure of your cloud estate. The resulting diagram is organized hierarchically across tenants, subscriptions, resource groups, virtual networks, and subnets, with each Azure service represented by its official icon (200+ services supported).

Beyond simple node placement, CloudHorus analyses and renders the full dependency web between resources: private endpoints, VNet integrations, private DNS zones, cross-resource-group references, and network security boundaries are all captured as directed edges, giving architects and engineers an accurate, always-up-to-date map of how components relate to one another.

### Two Operational Modes

| Mode | Description | Typical Use Case |
|------|-------------|-----------------|
| **Live Scan Mode** | Connects to the Azure control plane via the Azure CLI and exports ARM templates from active subscriptions and resource groups. No template files required. | Auditing deployed environments, incident response, compliance reviews |
| **Bicep Template Mode** | Compiles local Bicep files (with associated parameter files) entirely offline using the Bicep CLI. No Azure credentials needed. | Architecture reviews, design validation, CI/CD pipeline documentation |

Both modes share the same rendering pipeline and produce identical output formats.

### Key Capabilities

- **Multi-scope analysis** — Visualize resources across multiple tenants, subscriptions, and resource groups in a single diagram.
- **Networking topology** — Automatically maps VNets, subnets, private endpoints, private DNS zones, and Azure Bastion relationships.
- **Cross-resource-group dependencies** — Detects and renders references between resources in different resource groups or subscriptions.
- **Intelligent layout engine** — Configurable graph direction, subnet density, edge lengths, and per-subscription optimization flags let you tune the diagram for readability regardless of environment size.
- **Performance optimizations** — Built-in template caching delivers 50–67% faster repeated builds; subnet and private-endpoint optimization flags reduce visual noise in large deployments.
- **Multiple export formats** — Outputs PNG (default), Graphviz DOT, and Draw.io XML so diagrams can be embedded in wikis, presentations, or design documents.
- **GUI and CLI interfaces** — A cross-platform WebUI (Windows, macOS, Linux) provides point-and-click configuration, while the CLI supports full automation and scripting.

### Target Audience

CloudHorus is designed for anyone who needs visibility into Azure infrastructure complexity:
- **Cloud Architects** designing or reviewing landing zones and hub-and-spoke topologies
- **DevOps / Platform Engineers** documenting deployments and validating IaC blueprints before release
- **Security & Compliance Teams** auditing network boundaries, private connectivity, and resource dependencies
- **Product Owners and Managers** needing a clear, non-technical overview of deployed services

### Technical Stack

CloudHorus is built in Python 3 and relies on [Graphviz](https://graphviz.org/) for graph rendering, the [Azure CLI](https://learn.microsoft.com/cli/azure/) and [Bicep CLI](https://learn.microsoft.com/azure/azure-resource-manager/bicep/) for resource data acquisition, and [pywebview](https://pywebview.flowrl.com/) for the desktop GUI. It runs on Linux, macOS, and Windows with no cloud-side components — all processing happens locally.

## 📁 Repository Structure

```
CloudHorus/
├── src/                        # Application source code
│   ├── main.py                 # Main entry point and CLI interface
│   ├── core/                   # Core business logic modules
│   │   ├── graph_generator.py  # Graph generation and visualization
│   │   ├── azure_cli.py        # Azure CLI integration
│   │   ├── bicep_builder.py    # Bicep template processing
│   │   └── resource_processor.py # Resource analysis and mapping
│   └── utils/                  # Utility modules and helpers
│       ├── logger.py           # Logging configuration
│       └── skip_patterns.py    # Resource filtering patterns
│
├── docs/                       # Project documentation
│   ├── user-guides/            # User documentation and guides
│   └── development-summaries/  # Technical implementation notes
│
├── examples/                   # Usage examples and demos
├── samples/                    # Sample templates and test data
├── scripts/                    # Build and maintenance scripts
├── tests/                      # Unit and integration tests
├── test-data/                  # Test fixtures and mock data
└── icons/                      # Azure service icon assets (200+)
```

## ✨ Divine Powers

- **🦅 Divine Flight Modes**: Automatically detects Template mode (Bicep template analysis) vs Live resource Scaning mode (actcual resources deployed in Azure portal)
- **👁️ All-Seeing Eye**: Divine defaults for subscriptions, tenants, and resource groups
- **�️ Multi-Scope Support**: Comprehensive analysis of multiple infrastructure templates
- **⚡ Falcon Speed**: Optimized performance with intelligent caching
- **🛡️ Divine Protection**: Guardian oversight of complex cloud architectures
- **🧹 Clean Interface**: Simplified command-line arguments with validation
- **📊 Rich Visualizations**: Beautiful diagrams with Azure service icons (200+ services)
- **🔗 Dependency Mapping**: Cross-resource group dependencies visualization
- **🛡️ Security Focused**: Private endpoints and networking relationships
- **⚡ Template Caching**: Intelligent caching prevents duplicate template builds (50-67% faster)
- **🚫 Error Prevention**: Built-in validation prevents common configuration mistakes
- **🎨 Flexible Output**: Multiple graph orientations and optimization options

## 🚀 Quick Start

### Installation

```bash
# Download the Zip file from the latest release

cd CloudHorus

# Optional: Create and activate a virtual environment (recommended)
python3 -m venv cloudhorus-env
source cloudhorus-env/bin/activate  # Linux/macOS
# cloudhorus-env\Scripts\activate  # Windows
```

### Prerequisites

Choose your operating system for tailored installation instructions:

#### 🐧 Linux Users (Ubuntu/Debian/WSL)

**Option 1: Express Launcher (Recommended)**
```bash
# Make executable and run
chmod +x launcher.sh
./launcher.sh
```

**Option 2: Manual Installation**
```bash
# Install Python dependencies
pip install -r requirements.txt

# Install system dependencies
sudo apt-get update
sudo apt-get install graphviz python3-tk xclip

# Install clipboard support (optional, for GUI authentication dialogs)
sudo apt install xclip

# Install Azure CLI (optional, for Bicep compilation)
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Install Bicep (after Azure CLI)
az bicep install

# For non-Debian systems, use your package manager:
# CentOS/RHEL: sudo yum install graphviz python3-tkinter
# Fedora: sudo dnf install graphviz python3-tkinter
# Arch: sudo pacman -S graphviz tk
```

#### 🍎 macOS Users

**Option 1: Express Launcher (Recommended)**
```bash
# Open Terminal (Applications → Utilities → Terminal)
# Navigate to CloudHorus folder
cd /path/to/CloudHorus

# Make executable and run
chmod +x launcher-macos.sh
./launcher-macos.sh
```

**Alternative Methods:**
```bash
# Method 2: Direct execution without chmod
bash launcher-macos.sh

# Method 3: Double-click launcher-macos.sh in Finder
# → Right-click → "Open With" → "Terminal"
```

**Option 2: Manual Installation**
```bash
# Install Python dependencies
pip install -r requirements.txt

# Ensure Homebrew is installed first (if not already)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install system dependencies
brew install graphviz azure-cli

# Install Bicep
az bicep install
```

#### 🪟 Windows Users

**Option 1: Package Managers (Recommended)**
```powershell
# Install Python dependencies
pip install -r requirements.txt

# Using Chocolatey (install choco first if needed)
choco install graphviz

# Using winget (Windows 10+)
winget install graphviz Microsoft.AzureCLI

# Install Bicep
az bicep install
```

**Option 2: Manual Installation**
```powershell
# Install Python dependencies
pip install -r requirements.txt

# Manual Graphviz installation:
# 1. Download from: https://graphviz.org/download/
# 2. Install and add to PATH: C:\Program Files\Graphviz\bin
# 3. Download Azure CLI MSI from: https://aka.ms/installazurecliwindows

# Install Bicep (after Azure CLI)
az bicep install

# Note: pywebview is installed via pip (included in requirements.txt)
```

### Quick Verification

```bash
# Verify installation
python3 --version          # Should show Python 3.x
dot -V                     # Should show Graphviz version
az --version              # Should show Azure CLI version (optional)
az bicep version          # Should show Bicep version (optional)

# Verify GUI dependencies
python3 -c "import webview; print('pywebview ready')"
python3 -c "import PIL; print('Pillow ready')"

# Test the tool with a sample (if available)
python3 src/main.py --help

# Test GUI (if planning to use GUI interface)
python3 cloudhorus_webui.py --help || echo "GUI available for interactive use"
```

### Authentication

**For Bicep Mode**: No authentication required - works completely offline
**For Azure Export Mode**: Authentication will be prompted automatically when needed

Ready to start! 🚀

## 🖥️ GUI Interface

CloudHorus provides both command-line and graphical user interfaces for different user preferences.

### 🚀 Quick GUI Launch (Cross-Platform)

**Express Launchers** (Recommended):
```bash
# Windows
launcher.bat

# Linux/Unix
./launcher.sh

# macOS (optimized for Homebrew)
./launcher-macos.sh
```

All launcher scripts will:
- ✅ **Check dependencies individually** (Python, Graphviz, pip, Azure CLI, Bicep)
- ✅ **Ask before installing** each missing component (consent-based)
- ✅ **Setup virtual environment** (cloudhorus-env) automatically
- ✅ **Verify installation** with a summary before launching
- ✅ **Launch the WebUI** with pywebview desktop window
- ✅ **Keep terminal open** for Azure authentication prompts

### 🎯 Manual GUI Launch (Cross-Platform)

**WebUI** (Advanced users):
```bash
# Launch the CloudHorus WebUI directly
python3 cloudhorus_webui.py
```

### 🌟 GUI Features

- **📁 File Browser**: Easy Bicep template and parameter file selection
- **🔧 Visual Configuration**: Point-and-click optimization settings
- **👁️ Live Progress**: Real-time command execution with console output
- **🔐 Authentication Helper**: Automatic Azure login prompt detection
- **📊 Result Viewer**: Instant PNG visualization when generation completes
- **💾 Session History**: Remember previous configurations and settings

### 💡 GUI Usage Tips

- **Windows users**: Use `launcher.bat` for the smoothest experience
- **Keep terminal open**: The GUI needs the terminal window for Azure CLI interactions
- **Authentication prompts**: Follow browser redirects for Azure sign-in when prompted
- **Large templates**: GUI shows progress indicators for long-running operations
- **Result viewing**: Generated diagrams automatically open when completed

## ⚠️ Important Notes

- **Cross-Platform Support**: CloudHorus works on Linux, macOS, and Windows
  - **Windows users**: Use PowerShell or Command Prompt. WSL is also supported
  - **macOS users**: Ensure Homebrew is installed for easy dependency management
  - **Linux users**: Tested on Ubuntu/Debian, should work on other distributions
- **GUI Requirements**: pywebview is the GUI backend; on Linux it also needs PyQt5 + QtWebEngine
- **Bicep Mode Restrictions**: When using `--bicepFiles`, you cannot specify `--subscriptions`, `--tenants`, or `--resourcegroups` - defaults will be used automatically
- **Template Caching**: Templates are automatically cached to improve performance. Same template + parameters combinations are only compiled once per session
- **Resource Icons**: The tool includes 200+ Azure service icons. Missing icons will use generic placeholders
- **Resource limitation**: Large resource groups with more than 200 resources can't be exported ( Azure limitation )

## 📖 Usage

CloudHorus offers multiple ways to visualize your Azure architecture:

### 🖥️ GUI Mode (Recommended for Beginners)

**Cross-Platform Express Launch:**
```bash
# Windows
launcher.bat

# Linux/Unix
./launcher.sh

# macOS
./launcher-macos.sh
```

**Manual GUI Launch:**
```bash
# CloudHorus WebUI
python3 cloudhorus_webui.py
```

The GUI provides:
- Visual file selection for Bicep templates and parameters
- Point-and-click configuration of optimization settings
- Real-time progress monitoring with console output
- Automatic result viewing when generation completes

### ⌨️ Command Line Mode (Advanced Users)

### 🎯 Bicep Mode (Recommended for Devs)

**Single Template:**
```bash
python3 src/main.py \
  --bicepFiles samples/test-template.bicep \
  --parametersFiles samples/test-parameters.json
```

**Multiple Environments:**
```bash
python3 src/main.py \
  --bicepFiles multi-bicep-templates/environments/development/main.bicep \
               multi-bicep-templates/environments/staging/main.bicep \
  --parametersFiles multi-bicep-templates/environments/development/main.parameters.json \
                    multi-bicep-templates/environments/staging/main.parameters.json
```

**With Custom Resource Groups:**
```bash
python3 src/main.py \
  --bicepFiles samples/test-template.bicep \
  --parametersFiles samples/test-parameters.json \
  --resourcegroups my-custom-rg \
  --subscriptions my-subscription
```

⚠️ **Note**: The above command will fail with an error! In Bicep mode, you cannot specify custom subscriptions, tenants, or resource groups. Remove those parameters:

```bash
# ✅ Correct usage - let the tool use defaults
python3 src/main.py \
  --bicepFiles samples/test-template.bicep \
  --parametersFiles samples/test-parameters.json
```

### ☁️ Azure Export Mode (Recommended for Architects)

```bash
python3 src/main.py \
  --subscriptions <subscription-id> \
  --resourcegroups <resource-group-name> \
  --tenants <tenant-id>
```

### 🛠️ Using Scripts

```bash
# View all examples (check examples/ directory)
ls examples/

# Run a specific example
python3 examples/example_integration.py

# Check available sample templates
ls samples/
```

## 🎛️ Configuration Options

### Core Parameters

| Parameter | Description | Default | Bicep Mode Restriction |
|-----------|-------------|---------|----------------------|
| `--bicepFiles` | **Bicep template paths** - Enables Bicep mode when provided. Can specify multiple files for multi-environment deployments. | None | - |
| `--parametersFiles` | **Parameters file paths** - Must match the number and order of `--bicepFiles`. Contains parameter values for template compilation. | None | - |
| `--subscriptions` | **Azure subscription IDs** - List of subscription UUIDs to query. Required in Azure mode. | `bicep-subscription` (auto-generated) | ❌ Cannot specify in Bicep mode |
| `--tenants` | **Azure tenant IDs** - Tenant UUIDs for authentication context. Required in Azure mode. | `bicep-tenant` (auto-generated) | ❌ Cannot specify in Bicep mode |
| `--resourcegroups` | **Resource group names** - Names of resource groups to visualize. Required in Azure mode. | `bicep-rg-1, bicep-rg-2...` (auto-generated) | ❌ Cannot specify in Bicep mode |

### Graph Layout & Direction

| Parameter | Description | Options | Default |
|-----------|-------------|---------|---------|
| `--edgeDirection` | **Main graph direction** - Controls overall flow of the diagram | `TB` (Top-Bottom), `BT` (Bottom-Top), `LR` (Left-Right), `RL` (Right-Left) | `TB` |
| `--tenantDirection` | **Tenant layout direction** - How tenants are arranged when multiple exist | `TB` (Top-Bottom), `LR` (Left-Right) | `LR` |
| `--maxSubnetPerline` | **Subnets per line** - Maximum number of subnets displayed per line within a VNet | Any positive integer | `4` |
| `--rankDebug` | **Debug mode** - Shows invisible nodes and edges for troubleshooting layout issues | `true/false` | `false` |

### Performance & Optimization

| Parameter | Description | Per-Subscription | Default | Effect |
|-----------|-------------|------------------|---------|---------|
| `--subnetOptimization` | **Subnet display optimization** - Simplifies subnet representation for cleaner diagrams | ✅ Yes (space-separated list) | `false` for all | Reduces visual clutter in network-heavy templates |
| `--peOptimization` | **Private Endpoints optimization** - Optimizes PE display within subnets | ✅ Yes (space-separated list) | `true` for all | Groups private endpoints for better readability |
| `--crossPeOptimization` | **Cross-RG Private Endpoints** - Optimizes PE display across resource groups | ✅ Yes (space-separated list) | `false` for all | Simplifies cross-boundary connections |
| `--privateDnsZonesOptimization` | **Private DNS Zones optimization** - Groups DNS zones for cleaner visualization | ❌ Global setting | `true` | Reduces DNS zone visual noise |

### Advanced Layout Control

| Parameter | Description | Per-Subscription | Default | Usage |
|-----------|-------------|------------------|---------|--------|
| `--resourcesEdgeLength` | **Resource edge length** - Controls spacing between resources | ❌ Global setting | `1` | Higher values = more spacing |
| `--resourceGroupsEdgeLengthListBySubscription` | **Resource group spacing** - Controls spacing between RGs per subscription | ✅ Yes (space-separated list) | `4` for all | Fine-tune RG layout per subscription |

### Performance Options Detail

**Template Caching**:
- Automatically enabled - improves performance by 50-67% for repeated builds
- Caches compiled templates based on file paths
- No configuration required

**Per-Subscription Settings**:
When using multiple subscriptions, several parameters accept lists of values:
```bash
# Example: 3 subscriptions with different optimizations
--subscriptions sub1 sub2 sub3 \
--subnetOptimization true false true \
--peOptimization false true true \
--crossPeOptimization false false true \
--resourceGroupsEdgeLengthListBySubscription 2 4 6
```

### Memory Management:
- **Large templates**: Use `--subnetOptimization true` to reduce memory usage
- **Network-heavy deployments**: Enable `--privateDnsZonesOptimization true`
- **Complex multi-subscription**: Consider optimizing PE settings per subscription

### Example Configurations

**Basic Bicep visualization:**
```bash
python3 src/main.py \
  --bicepFiles template.bicep \
  --parametersFiles params.json
```

**Optimized network-heavy template:**
```bash
python3 src/main.py \
  --bicepFiles network.bicep \
  --parametersFiles network.params.json \
  --subnetOptimization true \
  --edgeDirection LR \
  --maxSubnetPerline 6
```

**Multi-subscription Azure export:**
```bash
python3 src/main.py \
  --subscriptions sub1 sub2 \
  --tenants tenant1 tenant1 \
  --resourcegroups rg1 rg2 \
  --subnetOptimization true false \
  --peOptimization true true \
  --resourceGroupsEdgeLengthListBySubscription 3 5
```

## 📚 Documentation

### User Guides
- **[Security & Trust Model](docs/SECURITY.md)**: Trust, permissions, and execution model — start here for security/compliance reviews
- **[Complex Scenarios Guide](docs/COMPLEX_SCENARIOS.md)**: Cross-tenant visualization and pre-deployment Bicep workflows
- **[Bicep Support Guide](docs/BICEP_SUPPORT.md)**: Comprehensive Bicep template support
- **[Multi-Environment Guide](docs/MULTIPLE_BICEP_TEMPLATES_GUIDE.md)**: Working with multiple environments
- **[Complex Templates](docs/COMPLEX_TEMPLATE_GUIDE.md)**: Advanced template scenarios

### Development Documentation
- **[Template Caching Implementation](docs/development-summaries/TEMPLATE_CACHING_IMPLEMENTATION.md)**: Performance optimization details
- **[Bicep Builder Optimization](docs/development-summaries/BICEP_BUILDER_OPTIMIZATION_SUMMARY.md)**: Code optimization summary
- **[Dynamic Subnet Solution](docs/development-summaries/DYNAMIC_SUBNET_SOLUTION.md)**: Advanced networking features

## 🔧 Development

### Testing
```bash
# Run all tests
python3 -m pytest tests/

# Test specific functionality
python3 tests/test_bicep.py

# Check template building
python3 examples/example_integration.py
```

### Debugging & Performance
```bash
# Enable verbose logging
export LOG_LEVEL=DEBUG

# Check template cache stats (programmatically)
python3 -c "from src.core.bicep_builder import get_cache_stats; print(get_cache_stats())"
```

### Project Structure
- **Core Logic**: `src/core/` contains the main graph generation and Bicep building logic
- **Template Caching**: Built-in caching system prevents duplicate template compilation
- **Examples**: `examples/` provides usage patterns and integration examples
- **Tests**: `tests/` contains unit tests
- **Documentation**: `docs/` has user guides and development summaries

## 🆕 Recent Improvements

### Latest Updates (August 2025)
- ✅ **Template Caching**: 50-67% performance improvement through intelligent template caching
- ✅ **Repository Cleanup**: Organized structure with proper documentation hierarchy
- ✅ **Enhanced Error Handling**: Clear error messages for common configuration mistakes
- ✅ **Bicep Mode Restrictions**: Prevents invalid parameter combinations in Bicep mode

### Previous Improvements
- ✅ **Simplified Interface**: Removed redundant `--useLocalTemplate` and `--bicepFile` arguments
- ✅ **Auto-Detection**: Bicep mode automatically detected when `--bicepFiles` is provided
- ✅ **Smart Defaults**: Automatic generation of subscriptions, tenants, and resource groups
- ✅ **Multi-Template Support**: Single interface for both single and multiple templates

## 🎯 Examples

Check out the `examples/` directory for:
- **[Integration Scripts](examples/)**: Real-world usage patterns
- **[Sample Templates](samples/)**: Ready-to-use Bicep templates
- **[Advanced Scenarios](examples/example_multiple_templates_complete.py)**: Complex multi-environment setups

### Quick Example Commands
```bash
# Basic Bicep visualization
python3 src/main.py --bicepFiles samples/simple-vnet.bicep --parametersFiles samples/simple-vnet.parameters.json

# Multiple templates
python3 src/main.py --bicepFiles template1.bicep template2.bicep --parametersFiles params1.json params2.json

# With optimization
python3 src/main.py --bicepFiles samples/network-template.bicep --parametersFiles samples/network-params.json --subnetOptimization
```

## 💡 Tips & Best Practices

- **GUI vs CLI**: Use GUI for interactive exploration, CLI for automation and scripting
- **Express Launchers**: Use platform-specific launchers for the smoothest experience:
  - Windows: `launcher.bat`
  - Linux/Unix: `./launcher.sh`
  - macOS: `./launcher-macos.sh`
- **Start Simple**: Use single templates first, then move to multi-template scenarios
- **Leverage Caching**: Template caching automatically improves performance on repeated runs
- **Use Subnet Optimization**: For network-heavy templates, enable `--subnetOptimization`
- **Check Examples**: The `examples/` directory has practical usage patterns
- **Validate Templates**: Ensure your Bicep templates compile successfully with `az bicep build`
- **GUI Authentication**: Keep terminal windows visible during authentication flows
- **Session Management**: GUI remembers your settings between launches

## 🔧 Platform-Specific Usage

### Windows Users
```powershell
# Option 1: Express GUI Launcher (Recommended)
launcher.bat

# Option 2: Manual launch after setup
python cloudhorus_webui.py              # WebUI
python src/main.py --bicepFiles samples/test-template.bicep --parametersFiles samples/test-parameters.json
```

### macOS Users
```bash
# Option 1: Express GUI Launcher (Recommended)
chmod +x launcher-macos.sh && ./launcher-macos.sh

# Option 2: Alternative execution methods
bash launcher-macos.sh                      # No chmod needed
open -a Terminal launcher-macos.sh          # Open with Terminal app

# Option 3: Manual launch after setup
python3 cloudhorus_webui.py              # WebUI
python3 src/main.py --bicepFiles samples/test-template.bicep --parametersFiles samples/test-parameters.json
```

### Linux Users
```bash
# Option 1: Express GUI Launcher (Recommended)
./launcher.sh

# Option 2: Manual launch after setup
python3 cloudhorus_webui.py              # WebUI
python3 src/main.py --bicepFiles samples/test-template.bicep --parametersFiles samples/test-parameters.json
```

## 🚨 Troubleshooting

### Common Issues

**"dot command not found" or "FileNotFoundError: dot"**
- Graphviz system binaries not installed or not in PATH
- Solution: Install graphviz using your OS package manager (see Prerequisites)
- Windows: Make sure `C:\Program Files\Graphviz\bin` is in your PATH

**"az command not found"**
- Azure CLI not installed or not in PATH
- Solution: Install Azure CLI using your OS method (see Prerequisites)

**"No module named 'graphviz'"**
- Python graphviz library not installed
- Solution: `pip install -r requirements.txt`

**"No module named 'webview'" (pywebview)**
- GUI backend missing
- Solution: `python3 -m pip install pywebview`
- **Linux**: Also install Qt backend: `pip install PyQt5 PyQtWebEngine qtpy`

**"No module named 'PIL'" or Pillow errors**
- Image processing library missing
- Solution: `pip install Pillow>=9.0.0`

**"pip: command not found" or "'pip' is not recognized"**
- Python package installer missing
- **Ubuntu/Debian**: `sudo apt-get install python3-pip`
- **CentOS/RHEL**: `sudo yum install python3-pip`
- **Fedora**: `sudo dnf install python3-pip`
- **Arch**: `sudo pacman -S python-pip`
- **macOS**: `brew install python3` (includes pip)
- **Windows**: Reinstall Python from python.org with pip option checked
- **Alternative**: `python3 -m ensurepip --upgrade`

**Permission denied errors**
- Windows: Run as Administrator or use PowerShell as Administrator
- Linux/macOS: Check file permissions, use `chmod +x` if needed

### GUI-Specific Issues

**GUI window doesn't open**
- Check if pywebview is installed: `python3 -c "import webview; print('OK')"`
- **Linux/WSL**: Ensure Qt WebEngine is available: `pip install PyQt5 PyQtWebEngine qtpy`
- Try launching directly: `python3 cloudhorus_webui.py`

**"Module not found" errors in GUI**
- Ensure you're in the CloudHorus directory when launching
- Try: `cd path/to/CloudHorus && python3 cloudhorus_webui.py`

**Authentication prompts not appearing**
- Keep the terminal window visible (don't minimize)
- Check if a browser window opened for Azure authentication
- Try running once from command line first: `az login`

**launcher.bat window closes immediately**
- The latest launcher.bat pauses on errors; if it still closes, right-click > Run as Administrator
- Ensure Python is installed and in PATH
- Check if Windows Defender or antivirus is blocking the script

**macOS launcher permission issues**
- Make script executable: `chmod +x launcher-macos.sh`
- If "Operation not permitted": `sudo chmod +x launcher-macos.sh`
- For Gatekeeper warnings: System Preferences → Security & Privacy → Allow
- Alternative: `bash launcher-macos.sh` (doesn't require chmod)

**"bash: ./launcher-macos.sh: Permission denied"**
- Run: `chmod +x launcher-macos.sh` then `./launcher-macos.sh`
- Or use: `bash launcher-macos.sh` directly

**GUI shows "Command failed" errors**
- Check the console output in the GUI for detailed error messages
- Ensure all dependencies (graphviz, azure-cli) are properly installed
- Try the same command in CLI mode to isolate the issue

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📜 License

---

**Happy Visualizing! 🎨📊**
