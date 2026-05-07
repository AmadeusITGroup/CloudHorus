# CloudHorus Windows Distribution Guide

This guide provides comprehensive instructions for creating Windows executables and distributing CloudHorus to non-technical users.

## Option 1: Express Launcher (Recommended)

### For End Users:

**Single-Step Installation and Launch**
1. **Download and Run**: Double-click `launcher.bat`
2. **6-Step Guided Setup**: The launcher checks and installs dependencies step by step:
   - **[1/6] Python**: Detects Python 3.x or shows install guidance
   - **[2/6] System Dependencies**: Graphviz (required) via winget/chocolatey + Azure CLI (optional)
   - **[3/6] Virtual Environment**: Creates isolated `cloudhorus-env` (consent-based)
   - **[4/6] Python Dependencies**: Checks each package individually, asks before installing
   - **[5/6] Bicep CLI**: Optional IaC template analysis support
   - **[6/6] Verification Summary**: Shows what is installed before launch
3. **Automatic Launch**: CloudHorus WebUI opens as a desktop window

### What the Launcher Handles (With Your Permission):
- Consent-based installation - asks before installing each component
- Python 3.10+ detection with version verification
- Graphviz installation via winget or chocolatey (with manual fallback)
- Python virtual environment setup
- Individual Python package dependency checking
- Optional Azure CLI and Bicep CLI installation
- Installation summary and verification
- CloudHorus WebUI launch with pywebview

### Fallback Support:
- **User declines installation**: Provides manual installation guidance with download URLs
- **No winget/chocolatey**: Shows manual installation guide with step-by-step instructions
- **Installation failures**: Offers alternative methods and manual steps
- **PATH issues**: Guides users through environment variable setup
- **Errors**: Window always pauses before closing so you can read the error message

## Option 2: GUI Application

### Using the CloudHorus WebUI:

1. **Start GUI**: `python cloudhorus_webui.py`
2. **Select Mode**:
   - **Bicep Mode**: Analyze ARM/Bicep templates (No authentication needed)
   - **Live Mode**: Scan actual Azure resources (Authentication required)

3. **Authentication (Live Mode Only)**:
   - **Azure CLI Login**: Click "Azure Login" button - opens terminal for `az login`
   - **Interactive Login**: Click "Interactive Login" for device code authentication
   - **Check Status**: Authentication status displayed in real-time

4. **Configuration**:
   - Use file browsers to select inputs
   - Configure output settings
   - Monitor progress with interactive console

### GUI Features:
- **Interactive Authentication**: Handles Azure login prompts seamlessly
- **Real-time Console**: Shows device codes and authentication steps
- **Input Capability**: Send responses to prompts (device codes, confirmations)
- **Authentication Status**: Live monitoring of Azure login state
- **Process Control**: Start, stop, and monitor CloudHorus execution
- **Dual Terminal Support**: CLI login in separate window, device code in GUI

## Platform-Specific Instructions

### Prerequisites Setup (Advanced Users):

**Note**: Prerequisites are now integrated into the main launcher (`launcher.bat`). The separate prerequisites script is available for advanced users who want to install only Python + Graphviz first.

```batch
REM Option A: Complete installation + launch (recommended)
launcher.bat

REM Option B: Prerequisites only (advanced users)
setup_prerequisites.bat
```

### Windows 10/11:

#### Option A: Express Launcher (Recommended)
```batch
REM Double-click or run from Command Prompt:
launcher.bat

REM This automatically handles:
REM - Python 3.10+ detection and pip bootstrap
REM - Graphviz installation via winget/chocolatey
REM - Virtual environment setup (cloudhorus-env)
REM - Python dependency checking and installation
REM - Optional Azure CLI and Bicep CLI installation
REM - CloudHorus WebUI launch
```

#### Option B: Prerequisites First (Advanced)
```batch
REM Step 1: Install Python + Graphviz only
setup_prerequisites.bat

REM Step 2: Full setup + launch
launcher.bat
```

#### Option C: Manual winget Installation
```batch
REM Install Python
winget install Python.Python.3.10

REM Install Graphviz
winget install Graphviz.Graphviz

REM Install Azure CLI (optional, for Bicep and Live mode)
winget install Microsoft.AzureCLI

REM Then run the launcher
launcher.bat
```

#### Option D: Package Managers
```batch
REM Using Chocolatey
choco install python graphviz

REM Using winget (any Python 3.10+ version)
winget install Python.Python.3.10
winget install graphviz
```

#### Option E: Manual Installation
```batch
REM 1. Download Python 3.10+ from python.org
REM 2. Download Graphviz from graphviz.org
REM 3. Install both with "Add to PATH" option
REM 4. Run launcher.bat
```

### Windows Server:
```powershell
# Option A: Use the prerequisites script (if winget available)
.\setup_prerequisites.bat

# Option B: Manual PowerShell installation
# Download and install Python 3.10+ (update version as needed)
Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe" -OutFile "python-installer.exe"
.\python-installer.exe /quiet InstallAllUsers=1 PrependPath=1

# Download and install Graphviz
Invoke-WebRequest -Uri "https://gitlab.com/api/v4/projects/4207231/packages/generic/graphviz-releases/2.50.0/windows_10_cmake_Release_graphviz-install-2.50.0-win64.exe" -OutFile "graphviz-installer.exe"
.\graphviz-installer.exe /S

# Add Graphviz to PATH
$env:PATH += ";C:\Program Files\Graphviz\bin"
[Environment]::SetEnvironmentVariable("PATH", $env:PATH, [EnvironmentVariableTarget]::Machine)

# Verify installations
python --version
dot -V
```

## Troubleshooting Guide

### Common Issues:

1. **"Python not found"**:
   - **Recommended**: Re-run `launcher.bat` (it detects Python and guides you)
   - **Alternative**: Run `setup_prerequisites.bat` for prerequisites only
   - **Manual fix**: Download Python 3.10+ from python.org with "Add to PATH"
   - **Verify**: Restart command prompt and type `python --version`

2. **"Graphviz not found"**:
   - **Recommended**: Re-run `launcher.bat` (it offers winget/chocolatey install)
   - **Alternative**: `winget install Graphviz.Graphviz` or `choco install graphviz`
   - **Path fix**: Add to PATH: `C:\Program Files\Graphviz\bin`
   - **Verify**: Type `dot -V` in command prompt

3. **"winget not found"** (during installation):
   - **Update Windows**: Ensure Windows 10 1809+ or Windows 11
   - **Install App Installer**: Get from Microsoft Store
   - **Alternative**: The installer provides manual installation guidance with download URLs

4. **"Azure CLI not found"** (Bicep mode only):
   - **Install**: `winget install Microsoft.AzureCLI`
   - **Verify**: Restart terminal and type `az --version`

5. **Installation script fails**:
   - **Try as admin**: Right-click `launcher.bat` > "Run as administrator"
   - **Check winget**: Ensure winget is available (`winget --version`)
   - **Manual fallback**: The launcher provides manual installation guidance
   - **Path issues**: Restart computer after installation
   - **Window closes immediately**: The latest launcher.bat pauses on all errors

6. **Authentication Issues (Live Mode)**:
   - **Device Code Not Showing**: Use the WebUI (`cloudhorus_webui.py`)
   - **Login Timeout**: Click "Azure Login" for CLI-based authentication
   - **Multiple Tenants**: Use "Interactive Login" to select specific tenant
   - **Permission Errors**: Ensure your account has Reader permissions on subscriptions

5. **Permission errors**:
   - Run as Administrator
   - Check antivirus software

6. **Missing dependencies**:
   - Run: `pip install -r requirements.txt`
   - Update pip: `python -m pip install --upgrade pip`

### Authentication Troubleshooting:

1. **Device Code Authentication**:
   - Use Interactive GUI for device code display
   - Follow the URL and enter the code shown in the console
   - Code expires in 15 minutes - restart if needed

2. **Azure CLI Authentication**:
   - Use "Azure Login" button to open separate terminal
   - Complete `az login` in the terminal window
   - Return to GUI and check authentication status

3. **Service Principal Authentication**:
   - Set environment variables: `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
   - No GUI interaction needed

4. **Multi-Tenant Scenarios**:
   - Specify tenant IDs in the Live Mode configuration
   - Use "Interactive Login" to switch between tenants

### Performance Optimization:

1. **Template Caching**: Automatic (50-67% improvement)
2. **Memory Usage**: Use `--batch-size` for large datasets
3. **Network**: Use `--timeout` for slow connections

## Distribution Checklist

### For Developers:

- [ ] Test `launcher.bat` on clean Windows system
- [ ] Test GUI application with sample data
- [ ] Validate output file generation
- [ ] Test both Bicep and Live Azure modes
- [ ] Test `setup_prerequisites.bat` standalone

### For End Users:

- [ ] Download CloudHorus package
- [ ] Run `launcher.bat`
- [ ] Load sample Bicep template or Azure credentials
- [ ] Generate first visualization
- [ ] Verify PNG output file

## Advanced Configuration

### Environment Variables:

```batch
# Set default configuration
set CLOUDHORUS_OUTPUT_DIR=C:\CloudHorus\Output
set CLOUDHORUS_CACHE_DIR=C:\CloudHorus\Cache
set CLOUDHORUS_TEMPLATES_DIR=C:\CloudHorus\Templates
```

## Support and Documentation

### Quick Reference:

```bash
# Complete installation + launch (recommended)
launcher.bat

# Prerequisites only (advanced users)
setup_prerequisites.bat

# Manual launch after setup
python cloudhorus_webui.py

# Basic usage examples
python src/main.py --help
python src/main.py --bicepFiles template.bicep --parametersFiles params.json
python src/main.py --subscriptions YOUR_SUBSCRIPTION_ID

# GUI modes
python cloudhorus_webui.py                    # WebUI with auth support

# Authentication commands (for CLI usage)
az login                                       # Azure CLI login
az account show                                # Check current authentication
az account list --output table                # List available subscriptions

# Verification commands
python --version                               # Should show Python 3.10+
dot -V                                        # Should show Graphviz version
winget --version                              # Check winget availability
```

### File Locations:
- **Output**: `azure_resources_TIMESTAMP.png`
- **Logs**: `cloudhorus.log` (if enabled)
- **Cache**: `_TEMPLATE_CACHE` (automatic)
- **Config**: Environment variables or CLI args

This comprehensive guide ensures non-technical Windows users can easily install, configure, and use CloudHorus for Azure architecture visualization.

