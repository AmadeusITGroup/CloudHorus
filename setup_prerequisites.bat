@echo off
REM CloudHorus Prerequisites Setup Script
REM This script installs Python 3.10+ and Graphviz using winget

echo.
echo ===================================================
echo    CloudHorus Prerequisites Setup
echo        Python 3.10 + Graphviz Installation
echo ===================================================
echo.

REM Check if winget is available
winget --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] winget is not available on this system
    echo.
    echo Winget is required for automatic installation. Please:
    echo 1. Update Windows to latest version (Windows 10 1809+ or Windows 11)
    echo 2. Install App Installer from Microsoft Store
    echo 3. Or use manual installation methods below
    echo.
    echo Manual Installation URLs:
    echo - Python 3.10+: https://www.python.org/downloads/
    echo - Graphviz: https://graphviz.org/download/
    echo.
    pause
    goto manual_install_guide
)

echo [INFO] winget found - proceeding with prerequisite checks
winget --version

echo.
echo ===================================================
echo    Prerequisites Installation Consent
echo ===================================================
echo.
echo This script can automatically install:
echo 1. Python 3.10+ (required for CloudHorus)
echo 2. Graphviz (required for visualization)
echo.
echo Both will be installed using winget with default settings.
echo Python will be added to your system PATH automatically.
echo.
set /p install_consent="Do you want to proceed with automatic installation? (y/n): "
if /i not "%install_consent%"=="y" (
    echo.
    echo Installation cancelled by user.
    echo You can install prerequisites manually:
    echo - Python 3.10+: https://www.python.org/downloads/
    echo - Graphviz: https://graphviz.org/download/
    echo.
    pause
    goto manual_install_guide
)

echo.
echo [CONFIRMED] Proceeding with automatic installation...

echo.
echo [STEP 1] Installing Python 3.10+...
echo.

REM Check if Python 3.10+ is already installed
for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set PY_VER=%%V
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
    if %%A GEQ 3 if %%B GEQ 10 (
        echo [INFO] Python %PY_VER% is already installed (meets 3.10+ requirement)
    python --version
    goto check_graphviz
)

REM Ask permission to install Python
echo.
set /p install_python="Python 3.10+ is not installed or outdated. Install it now? (y/n): "
if /i not "%install_python%"=="y" (
    echo [SKIPPED] Python installation cancelled by user
    echo [WARNING] CloudHorus requires Python 3.10+ to function
    goto check_graphviz
)

REM Install Python 3.10 using winget
echo Installing Python 3.10 via winget...
winget install Python.Python.3.10 --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo [WARNING] winget install failed, trying alternative method...
    winget install Python.Python.3.10 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] Failed to install Python via winget
        echo Please install Python 3.10+ manually from:
        echo https://www.python.org/downloads/
        echo Make sure to check "Add Python to PATH" during installation
        pause
        exit /b 1
    )
)

echo [INFO] Python installation completed
echo Refreshing environment variables...
REM Refresh PATH environment variable
call refreshenv.cmd >nul 2>&1

REM Wait a moment for PATH to refresh
timeout /t 3 /nobreak >nul

:check_graphviz
echo.
echo [STEP 2] Installing Graphviz...
echo.

REM Check if Graphviz is already installed
dot -V >nul 2>&1
if not errorlevel 1 (
    echo [INFO] Graphviz is already installed
    dot -V
    goto verify_installation
)

REM Ask permission to install Graphviz
echo.
set /p install_graphviz="Graphviz is not installed. Install it now? (y/n): "
if /i not "%install_graphviz%"=="y" (
    echo [SKIPPED] Graphviz installation cancelled by user
    echo [WARNING] CloudHorus requires Graphviz for visualization
    goto verify_installation
)

REM Install Graphviz using winget
echo Installing Graphviz via winget...
winget install Graphviz.Graphviz --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo [ERROR] Failed to install Graphviz via winget
    echo Please install Graphviz manually from:
    echo https://graphviz.org/download/
    echo After installation, add Graphviz bin folder to PATH:
    echo Example: C:\Program Files\Graphviz\bin
    pause
    set /p continue="Continue without Graphviz? (y/n): "
    if /i not "!continue!"=="y" (
        echo Installation cancelled
        exit /b 1
    )
    goto verify_python
)

echo [INFO] Graphviz installation completed
echo Refreshing environment variables...
call refreshenv.cmd >nul 2>&1
timeout /t 3 /nobreak >nul

:verify_installation
echo.
echo [STEP 3] Verifying Installation...
echo.

:verify_python
REM Verify Python installation
echo Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not accessible in PATH
    echo Please restart your command prompt or add Python to PATH manually
    echo Typical Python PATH: C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python310
    pause
) else (
    echo [SUCCESS] Python found:
    python --version
)

REM Verify pip
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip is not accessible
    echo Please reinstall Python with pip included
    pause
) else (
    echo [SUCCESS] pip found:
    python -m pip --version
)

REM Verify Graphviz
echo Checking Graphviz installation...
dot -V >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Graphviz is not accessible in PATH
    echo Please add Graphviz to PATH or install manually
    echo Common Graphviz locations:
    echo - C:\Program Files\Graphviz\bin
    echo - C:\Program Files (x86)\Graphviz\bin
) else (
    echo [SUCCESS] Graphviz found:
    dot -V 2>&1
)

echo.
echo [STEP 4] Installing Python packages...
echo.

REM Ask permission to install Python packages
set /p install_packages="Install essential Python packages (graphviz, colorama, tqdm, requests)? (y/n): "
if /i not "%install_packages%"=="y" (
    echo [SKIPPED] Python packages installation cancelled by user
    echo [INFO] CloudHorus installer will handle package installation later
    goto installation_summary
)

REM Upgrade pip first
echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [WARNING] Failed to upgrade pip, continuing anyway...
)

REM Install essential packages that CloudHorus needs
echo Installing essential Python packages...
python -m pip install --user graphviz colorama tqdm requests
if errorlevel 1 (
    echo [WARNING] Some packages failed to install
    echo This may not be critical - CloudHorus installer will handle remaining dependencies
)

:installation_summary

echo.
echo ===================================================
echo            Prerequisites Setup Complete!
echo ===================================================
echo.
echo Installation Summary:
echo.

REM Show final status
python --version 2>&1 | findstr "Python" && echo [✓] Python installed || echo [✗] Python installation issue
dot -V >nul 2>&1 && echo [✓] Graphviz installed || echo [✗] Graphviz installation issue
python -m pip --version >nul 2>&1 && echo [✓] pip available || echo [✗] pip issue

echo.
echo Next Steps:
echo 1. Close and reopen any command prompts/terminals
echo 2. Run the CloudHorus installer: install_windows.bat
echo 3. If you encounter PATH issues, restart your computer
echo.
echo Optional: Azure CLI for Bicep template compilation
set /p install_azure_cli="Install Azure CLI now? (y/n): "
if /i "%install_azure_cli%"=="y" (
    echo Installing Azure CLI via winget...
    winget install Microsoft.AzureCLI --silent --accept-package-agreements --accept-source-agreements
    if not errorlevel 1 (
        echo [SUCCESS] Azure CLI installed successfully
    ) else (
        echo [WARNING] Azure CLI installation failed
        echo You can install it manually later with: winget install Microsoft.AzureCLI
    )
) else (
    echo [SKIPPED] Azure CLI installation cancelled
    echo You can install it later with: winget install Microsoft.AzureCLI
)
echo.
pause
exit /b 0

:manual_install_guide
echo.
echo ===================================================
echo          Manual Installation Guide
echo ===================================================
echo.
echo Since winget is not available, please install manually:
echo.
echo 1. Python 3.10+:
    echo    - Go to: https://www.python.org/downloads/
echo    - Download: Windows installer (64-bit) or (32-bit)
echo    - Run installer and CHECK "Add Python to PATH"
echo    - Verify: Open new cmd and type "python --version"
echo.
echo 2. Graphviz:
echo    - Go to: https://graphviz.org/download/
echo    - Download: Windows package (.msi installer)
echo    - Run installer (default settings are fine)
echo    - Add to PATH: C:\Program Files\Graphviz\bin
echo    - Verify: Open new cmd and type "dot -V"
echo.
echo 3. After both are installed:
echo    - Run: install_windows.bat
echo.
pause
exit /b 0
