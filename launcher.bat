@echo off
REM ════════════════════════════════════════════════════════════════════════
REM  CloudHorus Launcher for Windows
REM  Bootstraps the modern GUI setup wizard (PowerShell WinForms).
REM  Falls back to terminal-based setup if PowerShell is unavailable.
REM ════════════════════════════════════════════════════════════════════════
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ─── Parse /AUTO flag for unattended installation ──────────────────────
set "AUTO_MODE=0"
for %%A in (%*) do (
    if /i "%%~A"=="/AUTO" set "AUTO_MODE=1"
    if /i "%%~A"=="--auto" set "AUTO_MODE=1"
    if /i "%%~A"=="/SILENT" set "AUTO_MODE=1"
    if /i "%%~A"=="--silent" set "AUTO_MODE=1"
)
if "!AUTO_MODE!"=="1" (
    echo   [AUTO] Unattended mode enabled - all prompts auto-accepted
)

REM ─── Attempt GUI Installer via PowerShell (skip in AUTO mode) ────────────
if "!AUTO_MODE!"=="1" goto :no_powershell

where powershell >nul 2>&1
if errorlevel 1 goto :no_powershell

if not exist "scripts\windows-installer.ps1" goto :no_powershell

REM Launch the GUI wizard via PowerShell.
REM The WinForms GUI creates its own visible window.
REM The PowerShell console stays in the background.
start "CloudHorus Setup" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows-installer.ps1"
exit /b 0

:no_powershell
REM ════════════════════════════════════════════════════════════════════════
REM  Terminal Fallback - original CMD-based setup
REM ════════════════════════════════════════════════════════════════════════

echo.
echo    ============================================================
echo    =     CloudHorus Express Installation                      =
echo    =     Azure Cloud Architecture Guardian                    =
echo    ============================================================
echo.

REM ==========================================================================
REM  [1/6] Python
REM ==========================================================================
echo [1/6] Checking Python installation...

python3 --version >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python3"
    goto :python_found
)

python --version >nul 2>&1
if errorlevel 1 goto :python_missing

REM Verify it is Python 3
for /f "tokens=2" %%V in ('python --version 2^>^&1') do set "PY_VER=%%V"
echo !PY_VER! | findstr /b "3." >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 2 detected. Python 3.10+ is required.
    echo         Download from https://python.org
    goto :fatal
)
set "PYTHON_CMD=python"
goto :python_found

:python_missing
echo [ERROR] Python not found!
echo         Download Python 3.10+ from https://python.org
echo         During install, check "Add Python to PATH"
goto :fatal

:python_found
for /f "tokens=*" %%V in ('!PYTHON_CMD! --version 2^>^&1') do set "PY_FULL_VER=%%V"
echo   [OK] !PY_FULL_VER!

REM Check pip
!PYTHON_CMD! -m pip --version >nul 2>&1
if not errorlevel 1 goto :pip_ok

echo   [!!] pip not found. Attempting bootstrap...
!PYTHON_CMD! -m ensurepip --upgrade >nul 2>&1
!PYTHON_CMD! -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Could not install pip.
    echo         Reinstall Python with "pip" option enabled.
    goto :fatal
)

:pip_ok
echo   [OK] pip available

REM ==========================================================================
REM  [2/6] System dependencies
REM ==========================================================================
echo.
echo [2/6] Checking system dependencies...

REM --- Graphviz ---
set "GRAPHVIZ_OK=0"
where dot >nul 2>&1
if not errorlevel 1 (
    set "GRAPHVIZ_OK=1"
    echo   [OK] Graphviz installed
    goto :graphviz_done
)

REM Try common install paths
set "PATH=%PATH%;C:\Program Files\Graphviz\bin;C:\Program Files (x86)\Graphviz\bin"
where dot >nul 2>&1
if not errorlevel 1 (
    set "GRAPHVIZ_OK=1"
    echo   [OK] Graphviz found in standard location
    goto :graphviz_done
)

echo   [!!] Graphviz not found
echo.
echo   Graphviz is REQUIRED for diagram generation.
if "!AUTO_MODE!"=="1" (
    echo   [AUTO] Installing Graphviz automatically...
    goto :graphviz_auto_install
)
choice /c YN /m "  Install Graphviz automatically"
if !errorlevel! equ 2 goto :graphviz_skip
:graphviz_auto_install
call :install_graphviz
goto :graphviz_done

:graphviz_skip
echo   [WARN] Skipping Graphviz. Diagram generation will fail.

:graphviz_done
REM Verify unflatten (part of Graphviz)
if "!GRAPHVIZ_OK!"=="0" goto :azure_cli_check
unflatten -? >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Graphviz unflatten support available
) else (
    echo   [WARN] unflatten not found. Diagrams may be less optimal.
)

REM --- Azure CLI ---
:azure_cli_check
where az >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Azure CLI installed
    goto :azure_cli_done
)

echo   [!!] Azure CLI not found (needed for Bicep compilation ^& Live Azure mode)
if "!AUTO_MODE!"=="1" (
    echo   [AUTO] Installing Azure CLI automatically...
    goto :azure_cli_auto_install
)
choice /c YN /m "  Install Azure CLI"
if !errorlevel! equ 2 goto :azure_cli_skip
:azure_cli_auto_install
call :install_azure_cli
goto :azure_cli_done

:azure_cli_skip
echo   [WARN] Azure CLI skipped. Bicep template compilation requires Azure CLI + Bicep.

:azure_cli_done

REM ==========================================================================
REM  [3/6] Virtual environment
REM ==========================================================================
echo.
echo [3/6] Checking Python virtual environment...

if exist "cloudhorus-env\Scripts\activate.bat" goto :venv_exists
if exist "cloudhorus-env" goto :venv_corrupted
goto :venv_create_prompt

:venv_exists
echo   [OK] Virtual environment already exists
call cloudhorus-env\Scripts\activate.bat
REM Re-assert delayed expansion (activate.bat may have affected it)
setlocal EnableDelayedExpansion
echo   [OK] Virtual environment activated
goto :venv_done

:venv_corrupted
echo   [!!] Virtual environment appears corrupted (missing activate script)
echo       Consider deleting the cloudhorus-env folder and re-running.
goto :venv_done

:venv_create_prompt
echo   [!!] No virtual environment found
echo.
echo   A virtual environment isolates CloudHorus dependencies from your system.
if "!AUTO_MODE!"=="1" (
    echo   [AUTO] Creating virtual environment automatically...
    goto :venv_auto_create
)
choice /c YN /m "  Create virtual environment (recommended)"
if !errorlevel! equ 2 goto :venv_skip
:venv_auto_create

echo   Creating virtual environment...
!PYTHON_CMD! -m venv cloudhorus-env
if errorlevel 1 (
    echo   [WARN] venv creation failed. Using global Python.
    goto :venv_done
)
call cloudhorus-env\Scripts\activate.bat
REM Re-assert delayed expansion after calling activate.bat
setlocal EnableDelayedExpansion
echo   [OK] Virtual environment created and activated
goto :venv_done

:venv_skip
echo   [SKIP] Using global Python. Package conflicts are possible.

:venv_done

REM ==========================================================================
REM  [4/6] Python dependencies
REM ==========================================================================
echo.
echo [4/6] Checking Python dependencies...

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found!
    echo         Make sure you are in the CloudHorus directory.
    goto :fatal
)

set "MISSING="
set "MISSING_COUNT=0"

REM Check each key package
call :check_pkg webview       pywebview
call :check_pkg graphviz      graphviz
call :check_pkg colorama      colorama
call :check_pkg PIL           Pillow
call :check_pkg tqdm          tqdm

REM Azure SDK packages (optional but needed for live mode)
call :check_pkg azure.identity          azure-identity
call :check_pkg azure.mgmt.resource     azure-mgmt-resource
call :check_pkg azure.mgmt.network      azure-mgmt-network

if "!MISSING_COUNT!"=="0" (
    echo   All Python dependencies satisfied.
    goto :deps_done
)

echo.
echo   Missing packages:!MISSING!
echo.
if "!AUTO_MODE!"=="1" (
    echo   [AUTO] Installing Python dependencies automatically...
    goto :deps_auto_install
)
choice /c YN /m "  Install missing Python dependencies"
if !errorlevel! equ 2 (
    echo [ERROR] Python dependencies are required for CloudHorus.
    echo         Install manually: !PYTHON_CMD! -m pip install -r requirements.txt
    goto :fatal
)
:deps_auto_install

echo   Upgrading pip...
!PYTHON_CMD! -m pip install --upgrade pip --quiet --disable-pip-version-check
echo   Installing from requirements.txt...
!PYTHON_CMD! -m pip install -r requirements.txt --quiet --disable-pip-version-check
if not errorlevel 1 goto :deps_install_ok

echo   [WARN] Quiet install failed. Retrying with verbose output...
!PYTHON_CMD! -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    goto :fatal
)

:deps_install_ok
echo   [OK] Python dependencies installed

:deps_done

REM ==========================================================================
REM  [5/6] Bicep CLI
REM ==========================================================================
echo.
echo [5/6] Checking Bicep CLI...

REM First check if standalone Bicep CLI is already available
where bicep >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%B in ('bicep --version 2^>^&1') do echo   [OK] Standalone Bicep CLI: %%B
    goto :bicep_done
)
REM Check common standalone install location
if exist "%LOCALAPPDATA%\Programs\Bicep\bicep.exe" (
    set "PATH=!PATH!;%LOCALAPPDATA%\Programs\Bicep"
    for /f "tokens=*" %%B in ('"%LOCALAPPDATA%\Programs\Bicep\bicep.exe" --version 2^>^&1') do echo   [OK] Standalone Bicep CLI: %%B
    goto :bicep_done
)
REM Check Azure CLI's own bicep binary location
if exist "%USERPROFILE%\.azure\bin\bicep.exe" (
    for /f "tokens=*" %%B in ('"%USERPROFILE%\.azure\bin\bicep.exe" --version 2^>^&1') do echo   [OK] Bicep CLI (Azure dir): %%B
    goto :bicep_done
)

REM Detect the working az command (az vs az.cmd on Windows)
set "AZ_CMD="
where az.cmd >nul 2>&1
if not errorlevel 1 (
    set "AZ_CMD=az.cmd"
    goto :az_cmd_found
)
where az >nul 2>&1
if not errorlevel 1 (
    set "AZ_CMD=az"
    goto :az_cmd_found
)
echo   [SKIP] Azure CLI not available - skipping Bicep check
goto :bicep_done

:az_cmd_found
echo   [OK] Azure CLI found as: !AZ_CMD!

REM Check if Bicep is already installed
call !AZ_CMD! bicep version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%B in ('call !AZ_CMD! bicep version 2^>^&1') do echo   [OK] %%B
    goto :bicep_done
)

echo   [!!] Bicep CLI not installed (required for IaC template analysis)
if "!AUTO_MODE!"=="1" (
    echo   [AUTO] Installing Bicep CLI automatically...
    goto :bicep_auto_install
)
choice /c YN /m "  Install Bicep CLI"
if !errorlevel! equ 2 goto :bicep_skip
:bicep_auto_install

REM ---- Method 1: az bicep install with retry ----
set "BICEP_RETRY=0"
:bicep_install_attempt
echo   Installing Bicep via Azure CLI (attempt !BICEP_RETRY! of 2)...
call !AZ_CMD! bicep install 2>&1
if not errorlevel 1 goto :bicep_verify

REM Retry once after a short wait
if !BICEP_RETRY! lss 2 (
    set /a BICEP_RETRY+=1
    echo   [WARN] az bicep install failed. Retrying in 5 seconds...
    timeout /t 5 /nobreak >nul
    goto :bicep_install_attempt
)
echo   [WARN] az bicep install failed after retries. Trying standalone install...
goto :try_standalone_bicep

:bicep_verify
REM Verify Bicep actually works after installation
timeout /t 2 /nobreak >nul
call !AZ_CMD! bicep version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%B in ('call !AZ_CMD! bicep version 2^>^&1') do echo   [OK] Bicep installed: %%B
    goto :bicep_done
)

REM Bicep install claimed success but version check fails - try upgrade
echo   [WARN] Bicep version check failed after install. Attempting upgrade...
call !AZ_CMD! bicep upgrade 2>&1
timeout /t 2 /nobreak >nul
call !AZ_CMD! bicep version >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%B in ('call !AZ_CMD! bicep version 2^>^&1') do echo   [OK] Bicep upgraded: %%B
    goto :bicep_done
)

echo   [WARN] az bicep not responding after install. Trying standalone Bicep...

:try_standalone_bicep
REM ---- Method 2: Standalone Bicep CLI via winget ----
echo   Attempting standalone Bicep CLI installation...
where winget >nul 2>&1
if errorlevel 1 goto :try_bicep_direct_download

echo   Trying: winget install Microsoft.Bicep ...
winget install --id Microsoft.Bicep --silent --accept-package-agreements --accept-source-agreements 2>&1
if errorlevel 1 goto :try_bicep_direct_download

timeout /t 3 /nobreak >nul
REM winget installs to PATH; also check common location
set "PATH=!PATH!;%LOCALAPPDATA%\Programs\Bicep"
where bicep >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%B in ('bicep --version 2^>^&1') do echo   [OK] Standalone Bicep installed via winget: %%B
    goto :bicep_done
)
echo   [WARN] winget install succeeded but bicep not found in PATH.

:try_bicep_direct_download
REM ---- Method 3: Direct download of bicep.exe ----
echo   Attempting direct download of Bicep CLI...
set "BICEP_INSTALL_DIR=%LOCALAPPDATA%\Programs\Bicep"
if not exist "!BICEP_INSTALL_DIR!" mkdir "!BICEP_INSTALL_DIR!"

REM Use PowerShell to download the latest Bicep release
powershell -NoProfile -Command ^
    "try {" ^
    "  $ProgressPreference = 'SilentlyContinue';" ^
    "  $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/Azure/bicep/releases/latest' -TimeoutSec 30;" ^
    "  $asset = $release.assets | Where-Object { $_.name -eq 'bicep-win-x64.exe' } | Select-Object -First 1;" ^
    "  if (-not $asset) { Write-Error 'Asset not found'; exit 1 }" ^
    "  $dest = Join-Path '%LOCALAPPDATA%\Programs\Bicep' 'bicep.exe';" ^
    "  Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $dest -TimeoutSec 120;" ^
    "  Write-Host 'Downloaded' $asset.browser_download_url;" ^
    "  exit 0" ^
    "} catch { Write-Error $_.Exception.Message; exit 1 }" 2>&1

if errorlevel 1 (
    echo   [WARN] Direct download failed.
    goto :bicep_install_failed
)

set "PATH=!PATH!;!BICEP_INSTALL_DIR!"
timeout /t 2 /nobreak >nul
where bicep >nul 2>&1
if not errorlevel 1 (
    for /f "tokens=*" %%B in ('bicep --version 2^>^&1') do echo   [OK] Standalone Bicep CLI downloaded: %%B
    goto :bicep_done
)

:bicep_install_failed
echo.
echo   [WARN] All Bicep installation methods failed.
echo          Please install manually using ONE of:
echo            1. winget install Microsoft.Bicep
echo            2. az bicep install   (if Azure CLI works)
echo            3. Download from https://github.com/Azure/bicep/releases
echo          Then restart this launcher.

:bicep_skip
echo   [SKIP] Bicep CLI skipped

:bicep_done

REM ==========================================================================
REM  [6/6] Verification
REM ==========================================================================
echo.
echo [6/6] Verifying installation...
echo.
echo   ============================================================
echo   =               Installation Summary                       =
echo   ============================================================

call :verify_cmd "Python"      "!PYTHON_CMD! --version"
call :verify_cmd "pip"         "!PYTHON_CMD! -m pip --version"
call :verify_sys "Graphviz"    dot
call :verify_pkg "pywebview"   webview
call :verify_pkg "Pillow"      PIL
call :verify_pkg "colorama"    colorama
call :verify_pkg "tqdm"        tqdm
call :verify_sys "Azure CLI"   az
call :verify_bicep

if exist "cloudhorus-env\Scripts\activate.bat" (
    echo   [OK] Virtual Environment: cloudhorus-env
) else (
    echo   [  ] Virtual Environment: using global Python
)

echo   ============================================================

REM ==========================================================================
REM  Launch GUI
REM ==========================================================================
echo.
echo   ============================================================
echo   =              Installation Complete!                       =
echo   ============================================================
echo.
echo   CloudHorus is ready!
echo   Starting Interactive GUI...
echo.
echo   CloudHorus will open as a desktop application window
echo   CloudHorus handles Azure authentication automatically
echo   Keep this window open - you may need to interact with prompts
echo   WARNING: Do NOT close this window while CloudHorus is running
echo.
echo   ===================================================
echo      CloudHorus Interactive GUI Starting...
echo   ===================================================
echo.

REM Ensure venv is active for launch
if exist "cloudhorus-env\Scripts\activate.bat" (
    call cloudhorus-env\Scripts\activate.bat
)

REM Verify pywebview before launch
!PYTHON_CMD! -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pywebview not installed.
    echo         Run: !PYTHON_CMD! -m pip install pywebview
    echo         Then restart this launcher.
    goto :fatal
)

echo   Launching cloudhorus_webui.py ...
echo.
!PYTHON_CMD! cloudhorus_webui.py

if errorlevel 1 (
    echo.
    echo   [ERROR] CloudHorus exited with an error.
    echo   Check the output above for details.
    goto :fatal
)

REM Session ended normally
:done
echo.
echo   ===================================================
echo   CloudHorus session completed.
echo   ===================================================
pause
exit /b 0

REM ==========================================================================
REM  Fatal error handler - always pauses before closing
REM ==========================================================================
:fatal
echo.
echo   ===================================================
echo   Press any key to close this window...
echo   ===================================================
pause >nul
exit /b 1


REM ==========================================================================
REM  Helper subroutines
REM ==========================================================================

:check_pkg
REM Usage: call :check_pkg <import_name> <pip_name>
!PYTHON_CMD! -c "import %~1" >nul 2>&1
if errorlevel 1 (
    echo   [!!] %~2: not installed
    set "MISSING=!MISSING! %~2"
    set /a MISSING_COUNT+=1
) else (
    echo   [OK] %~2
)
goto :eof

:verify_cmd
REM Usage: call :verify_cmd "Label" "command"
%~2 >nul 2>&1
if not errorlevel 1 (
    echo   [OK] %~1
) else (
    echo   [!!] %~1: not available
)
goto :eof

:verify_sys
REM Usage: call :verify_sys "Label" <command>
where %~2 >nul 2>&1
if not errorlevel 1 (
    echo   [OK] %~1
) else (
    echo   [  ] %~1: not available (optional)
)
goto :eof

:verify_pkg
REM Usage: call :verify_pkg "Label" <import_name>
!PYTHON_CMD! -c "import %~2" >nul 2>&1
if not errorlevel 1 (
    echo   [OK] %~1
) else (
    echo   [!!] %~1: not available
)
goto :eof

:verify_bicep
REM Check standalone bicep first
where bicep >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Bicep CLI (standalone)
    goto :eof
)
REM Check in common standalone install dir
if exist "%LOCALAPPDATA%\Programs\Bicep\bicep.exe" (
    echo   [OK] Bicep CLI (standalone - %LOCALAPPDATA%\Programs\Bicep)
    goto :eof
)
REM Fall back to az bicep
set "_VB_AZ="
where az.cmd >nul 2>&1
if not errorlevel 1 (
    set "_VB_AZ=az.cmd"
    goto :verify_bicep_run
)
where az >nul 2>&1
if not errorlevel 1 (
    set "_VB_AZ=az"
    goto :verify_bicep_run
)
echo   [!!] Bicep CLI: not available - Bicep template mode will fail
goto :eof
:verify_bicep_run
call !_VB_AZ! bicep version >nul 2>&1
if not errorlevel 1 (
    echo   [OK] Bicep CLI (via Azure CLI)
) else (
    echo   [!!] Bicep CLI: not available - Bicep template mode will fail
)
goto :eof

:install_graphviz
echo   Attempting Graphviz installation...
REM Try winget first (Windows 10/11)
where winget >nul 2>&1
if errorlevel 1 goto :try_choco_graphviz

echo   Trying winget...
winget install --id Graphviz.Graphviz --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
if errorlevel 1 goto :try_choco_graphviz

echo   [OK] Graphviz installed via winget
set "PATH=%PATH%;C:\Program Files\Graphviz\bin"
timeout /t 3 /nobreak >nul
where dot >nul 2>&1
if not errorlevel 1 set "GRAPHVIZ_OK=1"
goto :eof

:try_choco_graphviz
where choco >nul 2>&1
if errorlevel 1 goto :graphviz_manual

echo   Trying chocolatey...
choco install graphviz -y --no-progress >nul 2>&1
if errorlevel 1 goto :graphviz_manual

echo   [OK] Graphviz installed via chocolatey
call refreshenv >nul 2>&1
set "GRAPHVIZ_OK=1"
goto :eof

:graphviz_manual
echo.
echo   [WARN] Automatic installation failed.
echo          Please install Graphviz manually:
echo          1. Visit: https://graphviz.org/download/
echo          2. Download the Windows installer
echo          3. During install, check "Add Graphviz to PATH"
echo          4. Restart this script
echo.
goto :eof

:install_azure_cli
echo   Attempting Azure CLI installation...
where winget >nul 2>&1
if errorlevel 1 goto :azure_cli_manual

echo   Installing via winget...
winget install --id Microsoft.AzureCLI --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
if errorlevel 1 goto :azure_cli_manual

echo   [OK] Azure CLI installed via winget
goto :eof

:azure_cli_manual
echo.
echo   [WARN] Automatic installation failed.
echo          Install manually: https://aka.ms/installazurecliwindows
echo.
goto :eof
