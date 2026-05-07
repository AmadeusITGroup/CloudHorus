#!/bin/bash
# CloudHorus Express Install with Full Dependencies Support for Linux/macOS
# Auto-detects OS and installs appropriate dependencies

set -e  # Exit on any error
set +o pipefail 2>/dev/null  # Don't fail on pipe errors

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Function to ask for user consent
ask_consent() {
    local component="$1"
    local description="$2"

    echo
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}📦 Install ${component}?${NC}"
    echo -e "${YELLOW}Description: ${description}${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    while true; do
        echo -ne "${BLUE}Do you want to install ${component}? [Y/n]: ${NC}"
        read -r response

        # Default to yes if user just presses Enter
        if [[ -z "$response" ]] || [[ "$response" =~ ^[Yy]([Ee][Ss])?$ ]]; then
            return 0  # Yes
        elif [[ "$response" =~ ^[Nn]([Oo])?$ ]]; then
            echo -e "${YELLOW}Skipping ${component} installation.${NC}"
            return 1  # No
        else
            echo -e "${RED}Please answer yes (y) or no (n).${NC}"
        fi
    done
}

# Detect OS
detect_os() {
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if command -v apt-get >/dev/null 2>&1; then
            OS="ubuntu"
            PACKAGE_MANAGER="apt"
        elif command -v yum >/dev/null 2>&1; then
            OS="centos"
            PACKAGE_MANAGER="yum"
        elif command -v dnf >/dev/null 2>&1; then
            OS="fedora"
            PACKAGE_MANAGER="dnf"
        elif command -v pacman >/dev/null 2>&1; then
            OS="arch"
            PACKAGE_MANAGER="pacman"
        else
            OS="linux"
            PACKAGE_MANAGER="unknown"
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        OS="macos"
        PACKAGE_MANAGER="brew"
    else
        OS="unknown"
        PACKAGE_MANAGER="unknown"
    fi
}

# Print banner
print_banner() {
    echo -e "${BLUE}"
    echo "    ╔═══════════════════════════════════════════════════╗"
    echo "    ║     🦅 CloudHorus Express Installation            ║"
    echo "    ║     Azure Cloud Architecture Guardian            ║"
    echo "    ╚═══════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo
}

# Check if running as root (for package installation)
check_sudo() {
    if [[ $OS != "macos" ]] && [[ $EUID -eq 0 ]]; then
        echo -e "${YELLOW}WARNING: Running as root. This is not recommended.${NC}"
        echo "Please run as a normal user. Sudo will be requested when needed."
        exit 1
    fi
}

# Check Python installation (requires 3.10+)
check_python() {
    echo -e "${CYAN}[1/6] Checking Python installation...${NC}"

    PYTHON_CMD=""
    PYTHON_VERSION=""

    # Helper: check if a python command meets the 3.10+ requirement
    _check_py_candidate() {
        local cmd="$1"
        local ver
        ver=$($cmd --version 2>&1 | cut -d' ' -f2)
        local major minor
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 10 ]]; then
            PYTHON_CMD="$cmd"
            PYTHON_VERSION="$ver"
            return 0
        fi
        return 1
    }

    # 1. Try the default python3 / python first
    if command -v python3 >/dev/null 2>&1; then
        _check_py_candidate python3 2>/dev/null && true
    fi
    if [[ -z "$PYTHON_CMD" ]] && command -v python >/dev/null 2>&1; then
        _check_py_candidate python 2>/dev/null && true
    fi

    # 2. If default is too old, search for versioned binaries (python3.10 .. python3.13)
    if [[ -z "$PYTHON_CMD" ]]; then
        for minor in 13 12 11 10; do
            local candidate="python3.${minor}"
            if command -v "$candidate" >/dev/null 2>&1; then
                _check_py_candidate "$candidate" 2>/dev/null && break
            fi
        done
    fi

    # 3. Nothing suitable found
    if [[ -z "$PYTHON_CMD" ]]; then
        echo -e "${RED}ERROR: No Python 3.10+ interpreter found!${NC}"
        echo "Detected interpreters:"
        for cmd in python3 python python3.13 python3.12 python3.11 python3.10; do
            if command -v "$cmd" >/dev/null 2>&1; then
                echo "  $cmd -> $($cmd --version 2>&1)"
            fi
        done
        echo ""
        echo "Please install Python 3.10 or newer from:"
        if [[ $OS == "macos" ]]; then
            echo "  brew install python@3.12"
        else
            echo "  sudo $PACKAGE_MANAGER install python3.12   (or python3.11, python3.10)"
        fi
        exit 1
    fi
    echo -e "${GREEN}SUCCESS: Python ${PYTHON_VERSION} found (${PYTHON_CMD})${NC}"

    # Check if pip is available
    if ! command -v pip >/dev/null 2>&1 && ! command -v pip3 >/dev/null 2>&1; then
        if ask_consent "pip (Python Package Installer)" "Required for installing Python dependencies like graphviz, dash, etc."; then
            echo "Installing pip..."
            case $OS in
                "ubuntu"|"centos"|"fedora"|"arch")
                    echo "Installing pip via system package manager..."
                    case $OS in
                        "ubuntu")
                            sudo apt-get install -y python3-pip
                            ;;
                        "centos")
                            sudo yum install -y python3-pip
                            ;;
                        "fedora")
                            sudo dnf install -y python3-pip
                            ;;
                        "arch")
                            sudo pacman -S --noconfirm python-pip
                            ;;
                    esac
                    ;;
                *)
                    # Try ensurepip as fallback
                    echo "Trying to install pip via ensurepip..."
                    $PYTHON_CMD -m ensurepip --upgrade
                    ;;
            esac
            echo -e "${GREEN}SUCCESS: pip installed!${NC}"
        else
            echo -e "${RED}ERROR: pip is required for CloudHorus to function!${NC}"
            echo "Please install pip manually and run this script again."
            exit 1
        fi
    else
        echo -e "${GREEN}SUCCESS: pip already available!${NC}"
    fi
}

# Install system dependencies
install_system_deps() {
    echo -e "${CYAN}\033[1m[2/6] Checking SYSTEM dependencies (apt/dnf binaries: dot, az, etc.)\033[0m${NC}"

    local need_install=false
    local missing_desc=""

    # Check Graphviz
    if command -v dot >/dev/null 2>&1; then
        echo -e "${GREEN}  ✓ Graphviz: installed${NC}"
    else
        echo -e "${YELLOW}  ✗ Graphviz: not found${NC}"
        need_install=true
        missing_desc="Graphviz"
    fi

    # Check Qt/XCB libraries (Linux only)
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if ldconfig -p 2>/dev/null | grep -q "libxcb-xinerama" && \
           ldconfig -p 2>/dev/null | grep -q "libxcb-cursor"; then
            echo -e "${GREEN}  ✓ Qt/XCB libraries: installed${NC}"
        else
            echo -e "${YELLOW}  ✗ Qt/XCB libraries: some missing${NC}"
            need_install=true
            [[ -n "$missing_desc" ]] && missing_desc+=", "
            missing_desc+="Qt/XCB libraries"
        fi
    fi

    if $need_install; then
        case $OS in
            "ubuntu")
                if ask_consent "Missing: $missing_desc" "Install Graphviz + Qt/XCB libraries for Ubuntu/Debian"; then
                    echo "Installing dependencies for Ubuntu/Debian..."
                    sudo apt-get update
                    sudo apt-get install -y graphviz python3-pip python3-venv \
                        libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 \
                        libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 \
                        libxcb-render-util0 libxcb-image0 libgl1-mesa-glx \
                        libegl1-mesa libxkbcommon0 libdbus-1-3
                else
                    echo -e "${YELLOW}Skipping. CloudHorus may not work properly.${NC}"
                fi
                ;;
            "centos")
                if ask_consent "Missing: $missing_desc" "Install Graphviz + GUI libraries for CentOS/RHEL"; then
                    echo "Installing dependencies for CentOS/RHEL..."
                    sudo yum install -y graphviz python3-pip \
                        mesa-libGL mesa-libEGL libxkbcommon dbus-libs
                else
                    echo -e "${YELLOW}Skipping. CloudHorus may not work properly.${NC}"
                fi
                ;;
            "fedora")
                if ask_consent "Missing: $missing_desc" "Install Graphviz + GUI libraries for Fedora"; then
                    echo "Installing dependencies for Fedora..."
                    sudo dnf install -y graphviz python3-pip \
                        mesa-libGL mesa-libEGL libxkbcommon dbus-libs
                else
                    echo -e "${YELLOW}Skipping. CloudHorus may not work properly.${NC}"
                fi
                ;;
            "arch")
                if ask_consent "Missing: $missing_desc" "Install Graphviz + GUI libraries for Arch Linux"; then
                    echo "Installing dependencies for Arch Linux..."
                    sudo pacman -S --noconfirm graphviz python-pip \
                        mesa libxkbcommon dbus
                else
                    echo -e "${YELLOW}Skipping. CloudHorus may not work properly.${NC}"
                fi
                ;;
            "macos")
                if ask_consent "Missing: $missing_desc" "Install Graphviz for macOS"; then
                    echo "Installing dependencies for macOS..."
                    install_homebrew
                    brew install graphviz
                else
                    echo -e "${YELLOW}Skipping. CloudHorus may not work properly.${NC}"
                fi
                ;;
            *)
                echo -e "${YELLOW}WARNING: Unknown OS. Please install manually:${NC}"
                echo "  - graphviz"
                echo "  - Qt/XCB libraries (libxcb-xinerama0, libxcb-cursor0, etc.)"
                ;;
        esac
    else
        echo -e "${GREEN}  All system dependencies already satisfied — skipping.${NC}"
    fi

    # Azure CLI (has its own presence check — only prompts if missing)
    case $OS in
        "ubuntu"|"centos"|"fedora"|"arch"|"linux") install_azure_cli_linux ;;
        "macos") install_azure_cli_macos ;;
    esac

    echo -e "${GREEN}System dependencies check complete!${NC}"
}

# Install Homebrew for macOS
install_homebrew() {
    if ! command -v brew >/dev/null 2>&1; then
        if ask_consent "Homebrew Package Manager" "Package manager for macOS required to install system dependencies"; then
            echo "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

            # Add Homebrew to PATH for Apple Silicon Macs
            if [[ -f "/opt/homebrew/bin/brew" ]]; then
                echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi
        else
            echo -e "${YELLOW}Skipping Homebrew installation. Other dependencies may not install properly.${NC}"
            return 1
        fi
    else
        echo "Homebrew already installed"
    fi
}

# Install Azure CLI for Linux
install_azure_cli_linux() {
    if ! command -v az >/dev/null 2>&1; then
        if ask_consent "Azure CLI" "Command-line tool for Azure resource management (optional but recommended)"; then
            echo "Installing Azure CLI..."
            curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
            echo -e "${GREEN}Azure CLI installed!${NC}"
        else
            echo -e "${YELLOW}Skipping Azure CLI installation. You can still use CloudHorus with Bicep templates.${NC}"
        fi
    else
        echo "Azure CLI already installed"
    fi
}

# Install Azure CLI for macOS
install_azure_cli_macos() {
    if ! command -v az >/dev/null 2>&1; then
        if ask_consent "Azure CLI" "Command-line tool for Azure resource management (optional but recommended)"; then
            if command -v brew >/dev/null 2>&1; then
                echo "Installing Azure CLI..."
                brew install azure-cli
                echo -e "${GREEN}Azure CLI installed!${NC}"
            else
                echo -e "${YELLOW}Homebrew not available. Skipping Azure CLI installation.${NC}"
            fi
        else
            echo -e "${YELLOW}Skipping Azure CLI installation. You can still use CloudHorus with Bicep templates.${NC}"
        fi
    else
        echo "Azure CLI already installed"
    fi
}

# Setup Python virtual environment
setup_venv() {
    echo -e "${CYAN}[3/6] Checking Python virtual environment...${NC}"

    if [[ -d "cloudhorus-env" && -f "cloudhorus-env/bin/activate" ]]; then
        echo -e "${GREEN}  ✓ Virtual environment already exists${NC}"
        source cloudhorus-env/bin/activate
        echo -e "${GREEN}  Virtual environment activated!${NC}"
    elif [[ -d "cloudhorus-env" ]]; then
        echo -e "${RED}  ✗ Virtual environment appears corrupted (missing activate script)${NC}"
        echo -e "${YELLOW}  Consider removing cloudhorus-env directory and running the script again${NC}"
    else
        echo -e "${YELLOW}  ✗ No virtual environment found${NC}"
        if ask_consent "Python Virtual Environment" "Isolated Python environment for CloudHorus dependencies (recommended)"; then
            echo "Creating virtual environment..."
            $PYTHON_CMD -m venv cloudhorus-env
            source cloudhorus-env/bin/activate
            echo -e "${GREEN}  Virtual environment created and activated!${NC}"
        else
            echo -e "${YELLOW}Skipping virtual environment creation.${NC}"
            echo -e "${RED}WARNING: Installing packages globally may cause conflicts!${NC}"
            return 0
        fi
    fi
}

# Install Python dependencies
install_python_deps() {
    echo -e "${CYAN}\033[1m[4/6] Checking PYTHON packages inside the virtualenv (separate from system Graphviz)\033[0m${NC}"

    if [[ ! -f "requirements.txt" ]]; then
        echo -e "${RED}ERROR: requirements.txt not found!${NC}"
        echo "Please ensure you're in the CloudHorus directory"
        exit 1
    fi

    local need_install=false
    local missing_pkgs=()

    # Check key Python packages
    local pkg_checks=(
        "webview:pywebview"
        "graphviz:graphviz"
        "dash:dash"
        "colorama:colorama"
        "PIL:Pillow"
        "tqdm:tqdm"
        "azure.identity:azure-identity"
        "azure.mgmt.resource:azure-mgmt-resource"
        "azure.mgmt.network:azure-mgmt-network"
    )

    for entry in "${pkg_checks[@]}"; do
        local import_name="${entry%%:*}"
        local pip_name="${entry##*:}"
        if $PYTHON_CMD -c "import $import_name" >/dev/null 2>&1; then
            echo -e "${GREEN}  ✓ ${pip_name}${NC}"
        else
            # Note for graphviz: this is the Python wrapper package, NOT the system
            # Graphviz binary checked in step [2/6]. Both are required and independent.
            if [[ "$pip_name" == "graphviz" ]]; then
                echo -e "${YELLOW}  ✗ ${pip_name} (Python wrapper, not the apt/dnf binary): not installed${NC}"
            else
                echo -e "${YELLOW}  ✗ ${pip_name}: not installed${NC}"
            fi
            missing_pkgs+=("$pip_name")
            need_install=true
        fi
    done

    # Linux: check Qt backend for pywebview
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        if $PYTHON_CMD -c "import PyQt5" >/dev/null 2>&1 && \
           $PYTHON_CMD -c "import PyQt5.QtWebEngineWidgets" >/dev/null 2>&1 && \
           $PYTHON_CMD -c "import qtpy" >/dev/null 2>&1; then
            echo -e "${GREEN}  ✓ PyQt5 + QtWebEngine (Qt backend)${NC}"
        else
            echo -e "${YELLOW}  ✗ PyQt5/QtWebEngine: not installed${NC}"
            missing_pkgs+=("PyQt5" "PyQtWebEngine" "qtpy")
            need_install=true
        fi
    fi

    if ! $need_install; then
        echo -e "${GREEN}  All Python dependencies already satisfied — skipping.${NC}"
        return 0
    fi

    echo
    echo -e "${YELLOW}  Missing packages: ${missing_pkgs[*]}${NC}"
    if ask_consent "Python Dependencies" "Install missing: ${missing_pkgs[*]}"; then
        PIP_CMD="$PYTHON_CMD -m pip"

        # Ensure pip module is available
        if ! $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
            echo "pip module not found, bootstrapping via ensurepip..."
            $PYTHON_CMD -m ensurepip --upgrade
            if ! $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
                echo -e "${RED}ERROR: Could not install pip!${NC}"
                exit 1
            fi
        fi

        echo "Installing dependencies..."
        $PIP_CMD install --upgrade pip
        $PIP_CMD install -r requirements.txt

        # Install Qt backend on Linux if needed
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            echo "Installing Qt5 backend for pywebview (Linux)..."
            $PIP_CMD install PyQt5 PyQtWebEngine qtpy
        fi
        echo -e "${GREEN}Python dependencies installed!${NC}"
    else
        echo -e "${RED}ERROR: Python dependencies are required for CloudHorus to function!${NC}"
        echo "Please install manually: python3 -m pip install -r requirements.txt"
        exit 1
    fi

    # --- Optional: Draw.io export support (graphviz2drawio) ---
    install_drawio_support
}

# Install graphviz2drawio for Draw.io export
install_drawio_support() {
    # Check if already working
    if $PYTHON_CMD -c "from graphviz2drawio import graphviz2drawio" >/dev/null 2>&1; then
        echo -e "${GREEN}  ✓ graphviz2drawio (Draw.io export): installed${NC}"
        return 0
    fi

    echo -e "${CYAN}  Installing Draw.io export support (graphviz2drawio)...${NC}"

    local PIP_CMD="$PYTHON_CMD -m pip"

    # Step 1: Install graphviz development headers (needed to compile pygraphviz)
    echo -e "${CYAN}  Installing Graphviz development headers...${NC}"
    case $OS in
        "ubuntu")
            sudo apt-get install -y graphviz-dev pkg-config
            ;;
        "centos")
            sudo yum install -y graphviz-devel
            ;;
        "fedora")
            sudo dnf install -y graphviz-devel
            ;;
        "arch")
            # graphviz package on Arch includes dev headers
            sudo pacman -S --noconfirm graphviz
            ;;
        *)
            echo -e "${RED}  Cannot auto-install graphviz-dev on this OS.${NC}"
            echo "  Please install graphviz development headers manually, then run:"
            echo "    pip install pygraphviz graphviz2drawio"
            exit 1
            ;;
    esac

    # Step 2: Install pygraphviz (C extension)
    echo -e "${CYAN}  Installing pygraphviz...${NC}"
    if ! $PIP_CMD install pygraphviz 2>&1; then
        echo -e "${RED}  ERROR: pygraphviz compilation failed.${NC}"
        echo "  Ensure graphviz development headers are installed, then retry: pip install pygraphviz"
        exit 1
    fi

    # Step 3: Install graphviz2drawio
    echo -e "${CYAN}  Installing graphviz2drawio...${NC}"
    if $PIP_CMD install "graphviz2drawio>=1.1.0"; then
        echo -e "${GREEN}  ✓ Draw.io export support installed successfully!${NC}"
    else
        echo -e "${RED}  ERROR: graphviz2drawio installation failed.${NC}"
        exit 1
    fi
}

# Install Bicep
install_bicep() {
    echo -e "${CYAN}[5/6] Checking Bicep CLI...${NC}"

    if ! command -v az >/dev/null 2>&1; then
        echo -e "${YELLOW}  Azure CLI not available — skipping Bicep check${NC}"
        return 0
    fi

    if az bicep version >/dev/null 2>&1; then
        local bicep_ver
        bicep_ver=$(az bicep version 2>&1 | head -1)
        echo -e "${GREEN}  ✓ Bicep CLI: already installed (${bicep_ver})${NC}"
    else
        echo -e "${YELLOW}  ✗ Bicep CLI: not installed${NC}"
        if ask_consent "Bicep CLI" "Azure Bicep language support for IaC templates (optional)"; then
            az bicep install
            echo -e "${GREEN}Bicep installed!${NC}"
        else
            echo -e "${YELLOW}Skipping Bicep installation.${NC}"
        fi
    fi
}

# Verify installation
verify_installation() {
    echo -e "${CYAN}[6/6] Verifying installation...${NC}"

    # Test basic dependencies
    echo -n "Testing Python... "
    if $PYTHON_CMD --version >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    echo -n "Testing pip... "
    if $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    echo -n "Testing Graphviz... "
    if command -v dot >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    echo -n "Testing pywebview... "
    if $PYTHON_CMD -c "import webview" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    echo -n "Testing Pillow... "
    if $PYTHON_CMD -c "import PIL" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    echo -n "Testing Azure CLI... "
    if command -v az >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${YELLOW}○ (optional)${NC}"
    fi

    echo -n "Testing Draw.io export... "
    if $PYTHON_CMD -c "from graphviz2drawio import graphviz2drawio" >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
    fi

    echo
    echo -e "${GREEN}Installation verification complete!${NC}"
    echo
    echo -e "${BLUE}    ╔═══════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}    ║               Installation Summary                ║${NC}"
    echo -e "${BLUE}    ╚═══════════════════════════════════════════════════╝${NC}"

    # Show what's available
    if $PYTHON_CMD --version >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Python: Available${NC}"
    fi

    if $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
        echo -e "${GREEN}✓ pip: Available${NC}"
    fi

    if command -v dot >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Graphviz: Available${NC}"
    else
        echo -e "${YELLOW}○ Graphviz: Not available (may affect visualization)${NC}"
    fi

    if $PYTHON_CMD -c "import webview" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ pywebview: Available${NC}"
    else
        echo -e "${YELLOW}○ pywebview: Not available (run: python3 -m pip install pywebview)${NC}"
    fi

    if $PYTHON_CMD -c "import PIL" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Pillow: Available${NC}"
    else
        echo -e "${YELLOW}○ Pillow: Not available (may affect image processing)${NC}"
    fi

    if command -v az >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Azure CLI: Available${NC}"
    else
        echo -e "${YELLOW}○ Azure CLI: Not available (Bicep mode still works)${NC}"
    fi

    if $PYTHON_CMD -c "from graphviz2drawio import graphviz2drawio" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ Draw.io export: Available${NC}"
    else
        echo -e "${RED}✗ Draw.io export: Not available (run: pip install pygraphviz graphviz2drawio)${NC}"
    fi

    if [[ -d "cloudhorus-env" ]]; then
        echo -e "${GREEN}✓ Virtual Environment: Created${NC}"
    else
        echo -e "${YELLOW}○ Virtual Environment: Using global Python${NC}"
    fi
}

# Launch GUI
launch_gui() {
    echo
    echo -e "${BLUE}    ╔═══════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}    ║              Installation Complete!               ║${NC}"
    echo -e "${BLUE}    ╚═══════════════════════════════════════════════════╝${NC}"
    echo
    echo -e "${GREEN}CloudHorus is ready!${NC}"
    echo -e "${CYAN}Starting Interactive GUI...${NC}"
    echo
    echo -e "${YELLOW}🦅 CloudHorus handles Azure authentication automatically${NC}"
    echo -e "${YELLOW}🔄 Keep this terminal open - you may need to interact with prompts${NC}"
    echo -e "${RED}WARNING: Do NOT close this terminal while CloudHorus is running${NC}"
    echo
    echo -e "${PURPLE}===================================================${NC}"
    echo -e "${PURPLE}    CloudHorus Interactive GUI Starting...${NC}"
    echo -e "${PURPLE}===================================================${NC}"
    echo

    # Make sure we're in the virtual environment if it exists
    if [[ -d "cloudhorus-env" && -f "cloudhorus-env/bin/activate" ]]; then
        source cloudhorus-env/bin/activate
        echo -e "${CYAN}Using virtual environment: cloudhorus-env${NC}"
    elif [[ -d "cloudhorus-env" ]]; then
        echo -e "${RED}WARNING: Virtual environment appears corrupted (missing activate script)${NC}"
        echo -e "${YELLOW}Using global Python environment${NC}"
    else
        echo -e "${YELLOW}Using global Python environment${NC}"
    fi

    # Launch Web UI (pywebview)
    if $PYTHON_CMD -c "import webview" >/dev/null 2>&1; then
        echo -e "${GREEN}Launching CloudHorus Web UI...${NC}"

        # WSL/Linux: Stabilize Qt WebEngine to prevent WSLg shared-memory crashes
        # (e.g. fullscreen freeze can corrupt Weston RDP memory → invisible windows)
        if [[ "$OSTYPE" == "linux-gnu"* ]]; then
            export QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu-compositing --disable-gpu-rasterization"
            export QT_QPA_PLATFORM=xcb
        fi

        $PYTHON_CMD cloudhorus_webui.py
    else
        echo -e "${RED}pywebview not installed. Run: python3 -m pip install pywebview${NC}"
        echo -e "${YELLOW}Then restart this launcher.${NC}"
    fi

    # When CloudHorus stops, show completion message
    echo
    echo -e "${PURPLE}===================================================${NC}"
    echo -e "${GREEN}CloudHorus session completed.${NC}"
    echo -e "${CYAN}You can run this script again anytime to restart.${NC}"
    echo -e "${PURPLE}===================================================${NC}"

    # Keep terminal open
    echo
    echo -e "${YELLOW}Press Enter to exit...${NC}"
    read
}

# Error handling
handle_error() {
    echo -e "${RED}ERROR: Installation failed at step: $1${NC}"
    echo "Please check the error messages above and try again."
    echo "You can also install dependencies manually following the README."
    exit 1
}

# Main execution
main() {
    # Change to script directory
    cd "$(dirname "$0")"

    print_banner
    detect_os

    echo -e "${CYAN}Detected OS: ${OS} (Package Manager: ${PACKAGE_MANAGER})${NC}"
    echo

    check_sudo

    # Install dependencies
    check_python || handle_error "Python check"
    install_system_deps || handle_error "System dependencies"
    setup_venv || true  # Non-critical: global Python is acceptable
    install_python_deps || handle_error "Python dependencies"
    install_bicep || true  # Non-critical: optional component
    verify_installation || true  # Summary never fails the script

    # Launch GUI
    launch_gui
}

# Run main function
main "$@"
