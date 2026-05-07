#!/bin/bash
# CloudHorus Express Launcher for macOS
# Optimized for macOS with Homebrew integration
#
# EXECUTION INSTRUCTIONS:
# 1. Open Terminal (Applications > Utilities > Terminal)
# 2. Navigate to CloudHorus folder: cd /path/to/CloudHorus
# 3. Make executable: chmod +x launcher-macos.sh
# 4. Run: ./launcher-macos.sh
#
# OR: bash launcher-macos.sh (no chmod needed)
#
# REQUIREMENTS: macOS 10.14+ (Mojave or later)

set -e  # Exit on any error

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
    echo -e "${YELLOW}-----------------------------------------------------------${NC}"
    echo -e "${CYAN}  Install ${component}?${NC}"
    echo -e "${YELLOW}  ${description}${NC}"
    echo -e "${YELLOW}-----------------------------------------------------------${NC}"

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

# Print banner
print_banner() {
    echo -e "${BLUE}"
    echo "    ============================================================"
    echo "    =     CloudHorus Express Launcher for macOS                ="
    echo "    =     Azure Cloud Architecture Guardian                    ="
    echo "    ============================================================"
    echo -e "${NC}"
    echo
}

# Check if running on macOS
check_macos() {
    if [[ "$OSTYPE" != "darwin"* ]]; then
        echo -e "${RED}ERROR: This script is designed for macOS only!${NC}"
        echo "For Linux/WSL, use: ./launcher.sh"
        echo "For Windows, use:   launcher.bat"
        exit 1
    fi
}

# ==========================================================================
#  [1/6] Homebrew + Python
# ==========================================================================
install_homebrew() {
    echo -e "${CYAN}[1/6] Checking Homebrew and Python...${NC}"

    # --- Homebrew ---
    if ! command -v brew >/dev/null 2>&1; then
        if ask_consent "Homebrew Package Manager" "Package manager for macOS required to install system dependencies"; then
            echo "Installing Homebrew..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

            # Add Homebrew to PATH for Apple Silicon Macs
            if [[ -f "/opt/homebrew/bin/brew" ]]; then
                echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi
            echo -e "${GREEN}  [OK] Homebrew installed${NC}"
        else
            echo -e "${YELLOW}  [SKIP] Homebrew. Other dependencies may not install properly.${NC}"
        fi
    else
        echo -e "${GREEN}  [OK] Homebrew already installed${NC}"
    fi

    # --- Python (requires 3.10+) ---
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
        local py_ver
        py_ver=$(python3 --version 2>&1 | cut -d' ' -f2)
        local py_minor
        py_minor=$(echo "$py_ver" | cut -d. -f2)
        if [[ "$py_minor" -lt 10 ]]; then
            echo -e "${RED}  [ERROR] Python ${py_ver} found but 3.10+ is required${NC}"
            if command -v brew >/dev/null 2>&1; then
                echo "  Run: brew upgrade python3"
            else
                echo "  Install Python 3.10+ from https://python.org"
            fi
            exit 1
        fi
        echo -e "${GREEN}  [OK] Python ${py_ver}${NC}"
    else
        if command -v brew >/dev/null 2>&1; then
            if ask_consent "Python 3.10+" "Required for CloudHorus"; then
                brew install python3
                PYTHON_CMD="python3"
                echo -e "${GREEN}  [OK] Python 3 installed via Homebrew${NC}"
            else
                echo -e "${RED}  [ERROR] Python 3.10+ is required. Cannot continue.${NC}"
                exit 1
            fi
        else
            echo -e "${RED}  [ERROR] Python 3 not found and Homebrew not available.${NC}"
            echo "  Install Python 3.10+ from https://python.org"
            exit 1
        fi
    fi

    # --- pip ---
    if $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] pip available${NC}"
    else
        echo "  Bootstrapping pip..."
        $PYTHON_CMD -m ensurepip --upgrade 2>/dev/null || true
        if ! $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
            echo -e "${RED}  [ERROR] Could not install pip.${NC}"
            exit 1
        fi
        echo -e "${GREEN}  [OK] pip bootstrapped${NC}"
    fi
}

# ==========================================================================
#  [2/6] System dependencies
# ==========================================================================
install_dependencies() {
    echo -e "${CYAN}\033[1m[2/6] Checking SYSTEM dependencies (Homebrew binaries: dot, az, etc.)\033[0m${NC}"

    # --- Graphviz ---
    if command -v dot >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Graphviz installed${NC}"
    else
        if ask_consent "Graphviz" "Graph visualization for diagram generation (REQUIRED)"; then
            if command -v brew >/dev/null 2>&1; then
                brew install graphviz
                echo -e "${GREEN}  [OK] Graphviz installed via Homebrew${NC}"
            else
                echo -e "${YELLOW}  [WARN] Homebrew not available. Install Graphviz manually from https://graphviz.org${NC}"
            fi
        else
            echo -e "${YELLOW}  [WARN] Skipping Graphviz. Diagram generation will fail.${NC}"
        fi
    fi

    # --- unflatten (part of Graphviz) ---
    if command -v unflatten >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Graphviz unflatten support available${NC}"
    elif command -v dot >/dev/null 2>&1; then
        echo -e "${YELLOW}  [WARN] unflatten not found. Diagrams may be less optimal.${NC}"
    fi

    # --- Azure CLI ---
    if command -v az >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Azure CLI installed${NC}"
    else
        if ask_consent "Azure CLI" "Command-line tool for Azure resource management (optional - for Live mode)"; then
            if command -v brew >/dev/null 2>&1; then
                brew install azure-cli
                echo -e "${GREEN}  [OK] Azure CLI installed via Homebrew${NC}"
            else
                echo -e "${YELLOW}  [WARN] Homebrew not available. Install Azure CLI from https://aka.ms/installazurecli${NC}"
            fi
        else
            echo -e "${YELLOW}  [SKIP] Azure CLI. Bicep template mode still works.${NC}"
        fi
    fi
}

# ==========================================================================
#  [3/6] Virtual environment
# ==========================================================================
setup_venv() {
    echo -e "${CYAN}[3/6] Checking Python virtual environment...${NC}"

    if [[ -d "cloudhorus-env" && -f "cloudhorus-env/bin/activate" ]]; then
        echo -e "${GREEN}  [OK] Virtual environment already exists${NC}"
        source cloudhorus-env/bin/activate
        echo -e "${GREEN}  [OK] Virtual environment activated${NC}"
    elif [[ -d "cloudhorus-env" ]]; then
        echo -e "${RED}  [!!] Virtual environment appears corrupted (missing activate script)${NC}"
        echo -e "${YELLOW}  Consider removing the cloudhorus-env folder and re-running.${NC}"
    else
        if ask_consent "Python Virtual Environment" "Isolated environment for CloudHorus dependencies (recommended)"; then
            echo "  Creating virtual environment..."
            $PYTHON_CMD -m venv cloudhorus-env
            source cloudhorus-env/bin/activate
            echo -e "${GREEN}  [OK] Virtual environment created and activated${NC}"
        else
            echo -e "${YELLOW}  [SKIP] Using global Python. Package conflicts are possible.${NC}"
        fi
    fi
}

# ==========================================================================
#  [4/6] Python dependencies
# ==========================================================================
install_python_deps() {
    echo -e "${CYAN}\033[1m[4/6] Checking PYTHON packages inside the virtualenv (separate from system Graphviz)\033[0m${NC}"

    if [[ ! -f "requirements.txt" ]]; then
        echo -e "${RED}  [ERROR] requirements.txt not found!${NC}"
        echo "  Make sure you are in the CloudHorus directory."
        exit 1
    fi

    local need_install=false
    local missing_pkgs=()

    # Check key Python packages individually
    local pkg_checks=(
        "webview:pywebview"
        "graphviz:graphviz"
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
            echo -e "${GREEN}  [OK] ${pip_name}${NC}"
        else
            # Note for graphviz: this is the Python wrapper package, NOT the system
            # Graphviz binary checked in step [2/6]. Both are required and independent.
            if [[ "$pip_name" == "graphviz" ]]; then
                echo -e "${YELLOW}  [!!] ${pip_name} (Python wrapper, not the brew binary): not installed${NC}"
            else
                echo -e "${YELLOW}  [!!] ${pip_name}: not installed${NC}"
            fi
            missing_pkgs+=("$pip_name")
            need_install=true
        fi
    done

    if ! $need_install; then
        echo -e "${GREEN}  All Python dependencies satisfied.${NC}"
        return 0
    fi

    echo
    echo -e "${YELLOW}  Missing packages: ${missing_pkgs[*]}${NC}"
    if ask_consent "Python Dependencies" "Install missing: ${missing_pkgs[*]}"; then
        local PIP_CMD="$PYTHON_CMD -m pip"

        # Ensure pip module is available
        if ! $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
            echo "  Bootstrapping pip..."
            $PYTHON_CMD -m ensurepip --upgrade
        fi

        echo "  Upgrading pip..."
        $PIP_CMD install --upgrade pip
        echo "  Installing from requirements.txt..."
        $PIP_CMD install -r requirements.txt
        echo -e "${GREEN}  [OK] Python dependencies installed${NC}"
    else
        echo -e "${RED}  [ERROR] Python dependencies are required for CloudHorus.${NC}"
        echo "  Install manually: $PYTHON_CMD -m pip install -r requirements.txt"
        exit 1
    fi

    # --- Optional: Draw.io export support (graphviz2drawio) ---
    install_drawio_support
}

# Install graphviz2drawio for Draw.io export
install_drawio_support() {
    # Check if already working
    if $PYTHON_CMD -c "from graphviz2drawio import graphviz2drawio" >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] graphviz2drawio (Draw.io export): installed${NC}"
        return 0
    fi

    echo -e "${CYAN}  Installing Draw.io export support (graphviz2drawio)...${NC}"

    local PIP_CMD="$PYTHON_CMD -m pip"

    # Step 1: Install graphviz development headers via Homebrew
    echo -e "${CYAN}  Installing Graphviz (with headers) via Homebrew...${NC}"
    if command -v brew >/dev/null 2>&1; then
        brew install graphviz
    else
        echo -e "${RED}  ERROR: Homebrew not available. Please install Homebrew first, then retry.${NC}"
        exit 1
    fi

    # Step 2: Install pygraphviz (C extension) — point to Homebrew's graphviz
    echo -e "${CYAN}  Installing pygraphviz...${NC}"
    local gv_prefix
    gv_prefix=$(brew --prefix graphviz 2>/dev/null || echo "/opt/homebrew")
    if ! $PIP_CMD install pygraphviz \
        --config-settings="--global-option=build_ext" \
        --config-settings="--global-option=-I${gv_prefix}/include" \
        --config-settings="--global-option=-L${gv_prefix}/lib" 2>&1; then
        # Fallback: try without config-settings (newer pip/pygraphviz)
        if ! $PIP_CMD install pygraphviz 2>&1; then
            echo -e "${RED}  ERROR: pygraphviz compilation failed.${NC}"
            echo "  Ensure graphviz is installed via Homebrew, then retry: pip install pygraphviz"
            exit 1
        fi
    fi

    # Step 3: Install graphviz2drawio
    echo -e "${CYAN}  Installing graphviz2drawio...${NC}"
    if $PIP_CMD install "graphviz2drawio>=1.1.0"; then
        echo -e "${GREEN}  [OK] Draw.io export support installed successfully!${NC}"
    else
        echo -e "${RED}  ERROR: graphviz2drawio installation failed.${NC}"
        exit 1
    fi
}

# ==========================================================================
#  [5/6] Bicep CLI
# ==========================================================================
install_bicep() {
    echo -e "${CYAN}[5/6] Checking Bicep CLI...${NC}"

    if ! command -v az >/dev/null 2>&1; then
        echo -e "${YELLOW}  [SKIP] Azure CLI not available - skipping Bicep check${NC}"
        return 0
    fi

    if az bicep version >/dev/null 2>&1; then
        local bicep_ver
        bicep_ver=$(az bicep version 2>&1 | head -1)
        echo -e "${GREEN}  [OK] Bicep CLI: ${bicep_ver}${NC}"
    else
        if ask_consent "Bicep CLI" "Azure Bicep language support for IaC template analysis (optional)"; then
            az bicep install
            echo -e "${GREEN}  [OK] Bicep CLI installed${NC}"
        else
            echo -e "${YELLOW}  [SKIP] Bicep CLI skipped${NC}"
        fi
    fi
}

# ==========================================================================
#  [6/6] Verification
# ==========================================================================
verify_installation() {
    echo -e "${CYAN}[6/6] Verifying installation...${NC}"
    echo
    echo -e "${BLUE}  ============================================================${NC}"
    echo -e "${BLUE}  =               Installation Summary                       =${NC}"
    echo -e "${BLUE}  ============================================================${NC}"

    # Python & pip
    if $PYTHON_CMD --version >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Python${NC}"
    else
        echo -e "${RED}  [!!] Python: not available${NC}"
    fi

    if $PYTHON_CMD -m pip --version >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] pip${NC}"
    else
        echo -e "${RED}  [!!] pip: not available${NC}"
    fi

    # Graphviz
    if command -v dot >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Graphviz${NC}"
    else
        echo -e "${YELLOW}  [  ] Graphviz: not available (optional)${NC}"
    fi

    # Key Python packages
    for entry in "webview:pywebview" "PIL:Pillow" "colorama:colorama" "tqdm:tqdm"; do
        local import_name="${entry%%:*}"
        local pip_name="${entry##*:}"
        if $PYTHON_CMD -c "import $import_name" >/dev/null 2>&1; then
            echo -e "${GREEN}  [OK] ${pip_name}${NC}"
        else
            echo -e "${RED}  [!!] ${pip_name}: not available${NC}"
        fi
    done

    # Azure CLI
    if command -v az >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Azure CLI${NC}"
    else
        echo -e "${YELLOW}  [  ] Azure CLI: not available (optional)${NC}"
    fi

    # Bicep
    if command -v az >/dev/null 2>&1 && az bicep version >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Bicep CLI${NC}"
    else
        echo -e "${YELLOW}  [  ] Bicep CLI: not available (optional)${NC}"
    fi

    # Draw.io export
    if $PYTHON_CMD -c "from graphviz2drawio import graphviz2drawio" >/dev/null 2>&1; then
        echo -e "${GREEN}  [OK] Draw.io export (graphviz2drawio)${NC}"
    else
        echo -e "${RED}  [!!] Draw.io export: not available${NC}"
    fi

    # Venv
    if [[ -d "cloudhorus-env" ]]; then
        echo -e "${GREEN}  [OK] Virtual Environment: cloudhorus-env${NC}"
    else
        echo -e "${YELLOW}  [  ] Virtual Environment: using global Python${NC}"
    fi

    echo -e "${BLUE}  ============================================================${NC}"
}

# ==========================================================================
#  Launch GUI
# ==========================================================================
launch_gui() {
    echo
    echo -e "${BLUE}  ============================================================${NC}"
    echo -e "${BLUE}  =              Installation Complete!                       =${NC}"
    echo -e "${BLUE}  ============================================================${NC}"
    echo
    echo -e "${GREEN}  CloudHorus is ready!${NC}"
    echo -e "${CYAN}  Starting Interactive GUI...${NC}"
    echo
    echo -e "${YELLOW}  CloudHorus will open as a desktop application window${NC}"
    echo -e "${YELLOW}  CloudHorus handles Azure authentication automatically${NC}"
    echo -e "${YELLOW}  Keep this terminal open - you may need to interact with prompts${NC}"
    echo -e "${RED}  WARNING: Do NOT close this terminal while CloudHorus is running${NC}"
    echo
    echo -e "${PURPLE}  ===================================================${NC}"
    echo -e "${PURPLE}     CloudHorus Interactive GUI Starting...${NC}"
    echo -e "${PURPLE}  ===================================================${NC}"
    echo

    # Make sure we're in the virtual environment if it exists
    if [[ -d "cloudhorus-env" && -f "cloudhorus-env/bin/activate" ]]; then
        source cloudhorus-env/bin/activate
        echo -e "${CYAN}  Using virtual environment: cloudhorus-env${NC}"
    elif [[ -d "cloudhorus-env" ]]; then
        echo -e "${RED}  WARNING: Virtual environment appears corrupted (missing activate script)${NC}"
        echo -e "${YELLOW}  Using global Python environment${NC}"
    else
        echo -e "${YELLOW}  Using global Python environment${NC}"
    fi

    # Verify pywebview before launch
    if ! $PYTHON_CMD -c "import webview" >/dev/null 2>&1; then
        echo -e "${RED}  [ERROR] pywebview not installed.${NC}"
        echo "  Run: $PYTHON_CMD -m pip install pywebview"
        echo "  Then restart this launcher."
        echo
        echo -e "${YELLOW}Press Enter to exit...${NC}"
        read
        exit 1
    fi

    # Launch the CloudHorus WebUI
    $PYTHON_CMD cloudhorus_webui.py

    # When CloudHorus stops, show completion message
    echo
    echo -e "${PURPLE}  ===================================================${NC}"
    echo -e "${GREEN}  CloudHorus session completed.${NC}"
    echo -e "${CYAN}  Run ./launcher-macos.sh again anytime to restart.${NC}"
    echo -e "${PURPLE}  ===================================================${NC}"

    # Keep terminal open
    echo
    echo -e "${YELLOW}Press Enter to exit...${NC}"
    read
}

# ==========================================================================
#  Main execution
# ==========================================================================
main() {
    # Change to script directory
    cd "$(dirname "$0")"

    print_banner
    check_macos

    echo -e "${CYAN}  macOS detected - Using Homebrew for dependency management${NC}"
    echo

    install_homebrew
    install_dependencies
    setup_venv
    install_python_deps
    install_bicep
    verify_installation

    launch_gui
}

# Run main function
main "$@"
