<#
.SYNOPSIS
    CloudHorus Windows Setup Wizard — Modern GUI Installer
.DESCRIPTION
    A WinForms-based setup wizard that detects, installs, and configures
    all CloudHorus prerequisites, then launches the application.
    Replaces the legacy CMD terminal experience with a professional UI.
.NOTES
    Requires PowerShell 5.1+ (ships with Windows 10/11).
    No external dependencies — uses built-in .NET WinForms.
#>

#Requires -Version 5.1
param(
    [switch]$SkipLaunch,
    [switch]$Debug
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

# ═══════════════════════════════════════════════════════════════════════
#  Project Root Resolution
# ═══════════════════════════════════════════════════════════════════════

$Script:ProjectRoot = if ($PSScriptRoot) {
    $candidate = Split-Path -Parent $PSScriptRoot
    if (Test-Path (Join-Path $candidate 'src\main.py')) { $candidate }
    elseif (Test-Path (Join-Path $PSScriptRoot 'src\main.py')) { $PSScriptRoot }
    else { $PWD.Path }
} else { $PWD.Path }

# ═══════════════════════════════════════════════════════════════════════
#  Theme — Egyptian Horus Light (Papyrus Day)
# ═══════════════════════════════════════════════════════════════════════

$Script:C = @{
    BgDark      = [System.Drawing.Color]::FromArgb(245, 240, 232)   # warm off-white
    BgSurface   = [System.Drawing.Color]::White                     # cards / inputs
    BgPanel     = [System.Drawing.Color]::FromArgb(250, 246, 239)   # step bar
    BgElevated  = [System.Drawing.Color]::FromArgb(232, 224, 208)   # subtle hover
    BgInput     = [System.Drawing.Color]::FromArgb(250, 246, 239)   # input bg
    Gold        = [System.Drawing.Color]::FromArgb(180, 130, 10)    # strong gold on light
    GoldLight   = [System.Drawing.Color]::FromArgb(246, 211, 101)
    GoldDark    = [System.Drawing.Color]::FromArgb(120, 85, 5)
    Cyan        = [System.Drawing.Color]::FromArgb(0, 130, 180)     # readable cyan
    Text        = [System.Drawing.Color]::FromArgb(30, 25, 18)      # near-black
    TextMuted   = [System.Drawing.Color]::FromArgb(100, 90, 70)     # medium gray-brown
    Green       = [System.Drawing.Color]::FromArgb(40, 140, 50)     # darker green
    Red         = [System.Drawing.Color]::FromArgb(200, 50, 40)     # darker red
    Orange      = [System.Drawing.Color]::FromArgb(200, 120, 0)     # darker orange
    Border      = [System.Drawing.Color]::FromArgb(210, 200, 180)   # tan border
    White       = [System.Drawing.Color]::White
    BtnText     = [System.Drawing.Color]::White                     # button label
}

$Script:F = @{
    Title    = New-Object System.Drawing.Font('Segoe UI', 20, [System.Drawing.FontStyle]::Bold)
    Subtitle = New-Object System.Drawing.Font('Segoe UI', 11)
    Heading  = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
    Normal   = New-Object System.Drawing.Font('Segoe UI', 10)
    NormalB  = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
    Small    = New-Object System.Drawing.Font('Segoe UI', 9)
    Mono     = New-Object System.Drawing.Font('Consolas', 9)
    Btn      = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
    Step     = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
    StepNum  = New-Object System.Drawing.Font('Segoe UI', 8, [System.Drawing.FontStyle]::Bold)
}

# ═══════════════════════════════════════════════════════════════════════
#  Installer State
# ═══════════════════════════════════════════════════════════════════════

$Script:State = @{
    CurrentPage   = 0
    PythonCmd     = $null
    PythonVersion = ''
    Scan          = @{
        Python       = @{ Found = $false; Version = ''; Cmd = '' }
        Pip          = @{ Found = $false }
        Graphviz     = @{ Found = $false }
        Conda        = @{ Found = $false; Cmd = '' }   # conda/miniforge/miniconda
        AzureCLI     = @{ Found = $false }
        BicepCLI     = @{ Found = $false }
        Venv         = @{ Found = $false }
        Drawio       = @{ Found = $false }   # graphviz2drawio
        PipPkgs      = @{} # package_name -> $true/$false
    }
    Install       = @{
        Graphviz    = $true
        AzureCLI    = $true
        BicepCLI    = $true
        Drawio      = $true   # graphviz2drawio for Draw.io export
        Venv        = $true
        PipPackages = $true
    }
    PythonDetectedVersion = $null   # version string when Python found but too old
    InstallLog    = [System.Collections.ArrayList]::new()
    Completed     = $false
    GeneratedFile = $null
    Errors        = [System.Collections.ArrayList]::new()
}

$Script:PageNames = @('Welcome', 'Scan', 'Install', 'Done')

# ═══════════════════════════════════════════════════════════════════════
#  UI References
# ═══════════════════════════════════════════════════════════════════════

$Script:UI = @{
    Form          = $null
    StepPanels    = @()
    StepLabels    = @()
    StepNumbers   = @()
    ContentPanel  = $null
    Pages         = @{}
    BtnBack       = $null
    BtnNext       = $null
    ProgressBar   = $null
    LogBox        = $null
    ScanLabels    = @{}
    Checkboxes    = @{}
}

# ═══════════════════════════════════════════════════════════════════════
#  Helper: Styled Control Factories
# ═══════════════════════════════════════════════════════════════════════

function New-Label {
    param(
        [string]$Text, [System.Drawing.Font]$Font = $Script:F.Normal,
        [System.Drawing.Color]$Color, [int]$X = 0, [int]$Y = 0,
        [int]$W = 0, [int]$H = 0, [switch]$AutoSize
    )
    if (-not $Color) { $Color = $Script:C.Text }
    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text = $Text
    $lbl.Font = $Font
    $lbl.ForeColor = $Color
    $lbl.BackColor = [System.Drawing.Color]::Transparent
    $lbl.Location = New-Object System.Drawing.Point($X, $Y)
    if ($AutoSize) { $lbl.AutoSize = $true }
    else {
        $lbl.Size = New-Object System.Drawing.Size($W, $H)
        $lbl.AutoSize = $false
    }
    return $lbl
}

function New-StyledButton {
    param(
        [string]$Text, [int]$X = 0, [int]$Y = 0, [int]$W = 120, [int]$H = 38,
        [System.Drawing.Color]$BgColor, [System.Drawing.Color]$FgColor,
        [scriptblock]$OnClick
    )
    if (-not $BgColor) { $BgColor = $Script:C.Gold }
    if (-not $FgColor) { $FgColor = $Script:C.BtnText }
    $btn = New-Object System.Windows.Forms.Button
    $btn.Text = $Text
    $btn.Font = $Script:F.Btn
    $btn.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $btn.FlatAppearance.BorderSize = 0
    $btn.BackColor = $BgColor
    $btn.ForeColor = $FgColor
    $btn.Location = New-Object System.Drawing.Point($X, $Y)
    $btn.Size = New-Object System.Drawing.Size($W, $H)
    $btn.Cursor = [System.Windows.Forms.Cursors]::Hand
    if ($OnClick) { $btn.Add_Click($OnClick) }
    return $btn
}

function New-StyledCheckBox {
    param(
        [string]$Text, [int]$X = 0, [int]$Y = 0, [bool]$Checked = $false,
        [bool]$Enabled = $true
    )
    $cb = New-Object System.Windows.Forms.CheckBox
    $cb.Text = $Text
    $cb.Font = $Script:F.Normal
    $cb.ForeColor = $Script:C.Text
    $cb.BackColor = [System.Drawing.Color]::Transparent
    $cb.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $cb.Location = New-Object System.Drawing.Point($X, $Y)
    $cb.AutoSize = $true
    $cb.Checked = $Checked
    $cb.Enabled = $Enabled
    return $cb
}

# ═══════════════════════════════════════════════════════════════════════
#  Detection Functions
# ═══════════════════════════════════════════════════════════════════════

function Find-Python {
    # Helper to check a single python.exe path or simple command name.
    # Returns a hashtable with version info or $null.
    function Test-PythonExe([string]$exePath) {
        try {
            $out = & $exePath --version 2>&1 | Out-String
            if ($out -match 'Python\s+(\d+)\.(\d+)') {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                $ver = ($out -replace '.*Python\s+', '').Trim()
                if ($major -eq 3 -and $minor -ge 10) {
                    return @{ Cmd = $exePath; Major = $major; Minor = $minor; Version = $ver }
                } else {
                    $Script:State.PythonDetectedVersion = $ver
                }
            }
        } catch { }
        return $null
    }

    # Collect ALL valid Python 3.10+ candidates, then pick the best one.
    # Prefer stable versions (3.10-3.13) over bleeding-edge (3.14+)
    # because packages like pythonnet may lack wheels for the newest.
    $candidates = [System.Collections.ArrayList]::new()

    # 1) Try the Windows py launcher with explicit minor versions (most reliable).
    #    Must call: & py -3.12 --version  (two separate args, not one string).
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        foreach ($m in @(13, 12, 11, 10, 14, 15, 16)) {
            try {
                $verFlag = "-3.$m"
                $out = & py $verFlag --version 2>&1 | Out-String
                if ($out -match 'Python\s+(\d+)\.(\d+)') {
                    $major = [int]$Matches[1]
                    $minor = [int]$Matches[2]
                    $ver = ($out -replace '.*Python\s+', '').Trim()
                    if ($major -eq 3 -and $minor -ge 10) {
                        # Resolve to the actual python.exe path immediately
                        $resolved = & py $verFlag -c 'import sys; print(sys.executable)' 2>&1 | Out-String
                        $resolved = $resolved.Trim()
                        if ($resolved -and (Test-Path $resolved)) {
                            [void]$candidates.Add(@{
                                Cmd = $resolved; Major = $major; Minor = $minor; Version = $ver
                            })
                        }
                    }
                }
            } catch { }
        }
    }

    # 2) Check common Windows install paths
    $searchRoots = @(
        "$env:LOCALAPPDATA\Programs\Python",
        "$env:ProgramFiles",
        "${env:ProgramFiles(x86)}",
        "C:\"
    )
    foreach ($root in $searchRoots) {
        if (-not (Test-Path $root)) { continue }
        $dirs = Get-ChildItem -Path $root -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match '^Python3\d+$' }
        foreach ($d in $dirs) {
            $exe = Join-Path $d.FullName 'python.exe'
            if (Test-Path $exe) {
                $result = Test-PythonExe $exe
                if ($result) { [void]$candidates.Add($result) }
            }
        }
    }

    # 3) Try generic commands last (may resolve to any version via PATH/alias)
    foreach ($cmd in @('python', 'python3')) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($found) {
            $result = Test-PythonExe $cmd
            if ($result) { [void]$candidates.Add($result) }
        }
    }

    # Deduplicate candidates by resolved executable path
    $seen = @{}
    $unique = [System.Collections.ArrayList]::new()
    foreach ($c in $candidates) {
        $key = $c.Cmd.ToLower()
        # Resolve to full path if possible for accurate dedup
        try {
            $full = (Resolve-Path $c.Cmd -ErrorAction SilentlyContinue).Path
            if ($full) { $key = $full.ToLower() }
        } catch { }
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            [void]$unique.Add($c)
        }
    }

    if ($unique.Count -eq 0) { return }

    # Pick the best: prefer 3.10-3.13 (stable, best wheel support), then highest minor
    $best = $unique | Sort-Object @{
        Expression = {
            if ($_.Minor -le 13) { 1000 + $_.Minor } else { $_.Minor }
        }
        Descending = $true
    } | Select-Object -First 1

    $Script:State.PythonCmd = $best.Cmd
    $Script:State.Scan.Python.Found = $true
    $Script:State.Scan.Python.Version = $best.Version
    $Script:State.Scan.Python.Cmd = $best.Cmd
}

function Find-Pip {
    if (-not $Script:State.PythonCmd) { return }
    try {
        $null = & $Script:State.PythonCmd -m pip --version 2>&1
        if ($LASTEXITCODE -eq 0) { $Script:State.Scan.Pip.Found = $true }
    } catch { }
}

function Find-Graphviz {
    # Also add common Graphviz paths
    $env:PATH = "$env:PATH;C:\Program Files\Graphviz\bin;C:\Program Files (x86)\Graphviz\bin"
    try {
        $null = Get-Command dot -ErrorAction Stop
        $Script:State.Scan.Graphviz.Found = $true
    } catch { }
}

function Find-Conda {
    # Detect conda / miniforge / miniconda anywhere on the system.
    # Needed for pre-built pygraphviz (avoids MSVC Build Tools).
    $condaCmd = $null

    # 1) Check PATH
    $found = Get-Command conda -ErrorAction SilentlyContinue
    if ($found) { $condaCmd = $found.Source }

    # 2) Scan well-known install locations
    if (-not $condaCmd) {
        $searchDirs = @(
            "$env:LOCALAPPDATA\miniforge3",
            "$env:USERPROFILE\miniforge3",
            "$env:LOCALAPPDATA\miniconda3",
            "$env:USERPROFILE\miniconda3",
            "$env:USERPROFILE\anaconda3",
            "C:\Miniforge3",
            "C:\Miniconda3",
            "C:\ProgramData\miniforge3",
            "C:\ProgramData\miniconda3",
            "$env:LOCALAPPDATA\Continuum\miniconda3",
            "$env:LOCALAPPDATA\Continuum\anaconda3"
        )
        foreach ($d in $searchDirs) {
            $exe = Join-Path $d 'Scripts\conda.exe'
            if (Test-Path $exe) { $condaCmd = $exe; break }
            $exe = Join-Path $d 'condabin\conda.bat'
            if (Test-Path $exe) { $condaCmd = $exe; break }
        }
    }

    if ($condaCmd) {
        try {
            $null = & $condaCmd --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                $Script:State.Scan.Conda.Found = $true
                $Script:State.Scan.Conda.Cmd   = $condaCmd
            }
        } catch { }
    }
}

function Find-AzureCLI {
    try {
        $null = Get-Command az -ErrorAction Stop
        $Script:State.Scan.AzureCLI.Found = $true
    } catch { }
}

function Find-BicepCLI {
    # Strategy 1: Check standalone bicep on PATH
    $bicepCmd = Get-Command bicep -ErrorAction SilentlyContinue
    if ($bicepCmd) {
        try {
            $null = & bicep --version 2>&1
            if ($LASTEXITCODE -eq 0) {
                $Script:State.Scan.BicepCLI.Found = $true
                return
            }
        } catch { }
    }
    
    # Strategy 2: Check known standalone install locations
    $standalonePaths = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Bicep\bicep.exe'),
        (Join-Path $env:USERPROFILE '.azure\bin\bicep.exe')
    )
    foreach ($p in $standalonePaths) {
        if (Test-Path $p) {
            try {
                $null = & $p --version 2>&1
                if ($LASTEXITCODE -eq 0) {
                    $Script:State.Scan.BicepCLI.Found = $true
                    # Add to PATH for this session so az/bicep commands work later
                    $dir = Split-Path $p -Parent
                    if ($env:PATH -notlike "*$dir*") { $env:PATH = "$env:PATH;$dir" }
                    return
                }
            } catch { }
        }
    }
    
    # Strategy 3: Check via Azure CLI (az bicep version)
    if (-not $Script:State.Scan.AzureCLI.Found) { return }
    try {
        $null = & az bicep version 2>&1
        if ($LASTEXITCODE -eq 0) { $Script:State.Scan.BicepCLI.Found = $true }
    } catch { }
}

function Find-Venv {
    $venvPython = Join-Path $Script:ProjectRoot 'cloudhorus-env\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        $Script:State.Scan.Venv.Found = $false
        return
    }
    # Venv exists -- check its Python version matches the selected system Python.
    # A mismatch (e.g. venv=3.14, selected=3.12) causes package install failures
    # (pythonnet has no wheel for bleeding-edge Python).
    try {
        $out = & $venvPython --version 2>&1 | Out-String
        if ($out -match 'Python\s+3\.(\d+)') {
            $venvMinor = [int]$Matches[1]
            if ($venvMinor -lt 10) {
                # Too old — force recreation
                $Script:State.Scan.Venv.Found = $false
                return
            }
            # Compare against the selected Python version
            $selectedMinor = -1
            if ($Script:State.Scan.Python.Version -match '3\.(\d+)') {
                $selectedMinor = [int]$Matches[1]
            }
            if ($selectedMinor -gt 0 -and $venvMinor -ne $selectedMinor) {
                # Venv uses a different Python minor version than the preferred one
                # (e.g. venv=3.14 but we selected 3.12 for wheel compatibility)
                $Script:State.Scan.Venv.Found = $false
                return
            }
            $Script:State.Scan.Venv.Found = $true
            return
        }
    } catch { }
    # Venv exists but version check failed — mark as not found (will be recreated)
    $Script:State.Scan.Venv.Found = $false
}

function Find-PipPackages {
    if (-not $Script:State.PythonCmd) { return }

    $pythonCmd = $Script:State.PythonCmd
    # Only use venv python if it passed the version check
    if ($Script:State.Scan.Venv.Found) {
        $venvPython = Join-Path $Script:ProjectRoot 'cloudhorus-env\Scripts\python.exe'
        if (Test-Path $venvPython) { $pythonCmd = $venvPython }
    }

    $packages = @{
        'pywebview'             = 'webview'
        'graphviz'              = 'graphviz'
        'colorama'              = 'colorama'
        'Pillow'                = 'PIL'
        'tqdm'                  = 'tqdm'
        'azure-identity'        = 'azure.identity'
        'azure-mgmt-resource'   = 'azure.mgmt.resource'
        'azure-mgmt-network'    = 'azure.mgmt.network'
    }

    foreach ($pkg in $packages.GetEnumerator()) {
        try {
            $null = & $pythonCmd -c "import $($pkg.Value)" 2>&1
            $Script:State.Scan.PipPkgs[$pkg.Key] = ($LASTEXITCODE -eq 0)
        } catch {
            $Script:State.Scan.PipPkgs[$pkg.Key] = $false
        }
    }
}

function Find-Drawio {
    if (-not $Script:State.PythonCmd) { return }
    $pythonCmd = $Script:State.PythonCmd
    # Only use venv python if it passed the version check
    if ($Script:State.Scan.Venv.Found) {
        $venvPython = Join-Path $Script:ProjectRoot 'cloudhorus-env\Scripts\python.exe'
        if (Test-Path $venvPython) { $pythonCmd = $venvPython }
    }
    try {
        # Check the FULL import chain: graphviz2drawio -> pygraphviz -> _graphviz.pyd + DLLs
        # Just "import graphviz2drawio" succeeds even when pygraphviz is broken
        # because graphviz2drawio catches import errors internally.
        # We must verify pygraphviz itself loads correctly.
        $check = "import os; os.add_dll_directory(r'C:\Program Files\Graphviz\bin') if hasattr(os,'add_dll_directory') else None; import pygraphviz; from graphviz2drawio import graphviz2drawio"
        $null = & $pythonCmd -c $check 2>&1
        if ($LASTEXITCODE -eq 0) { $Script:State.Scan.Drawio.Found = $true }
    } catch { }
}

function Invoke-FullScan {
    Find-Python
    Find-Pip
    Find-Graphviz
    Find-Conda
    Find-AzureCLI
    Find-BicepCLI
    Find-Venv
    Find-PipPackages
    Find-Drawio
}

function Invoke-Rescan {
    # Refresh PATH so newly installed programs are found
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + `
                [System.Environment]::GetEnvironmentVariable('Path', 'User')

    # Reset detected-but-old Python info
    $Script:State.PythonDetectedVersion = $null

    # Update info label to show scanning state
    $infoLbl = $Script:UI.ScanLabels['info']
    $infoLbl.Text = 'Rescanning...'
    $infoLbl.ForeColor = $Script:C.TextMuted
    [System.Windows.Forms.Application]::DoEvents()

    # Re-run full scan and update UI
    Invoke-FullScan
    Update-ScanUI

    # Update the Next/Install button based on new scan results
    if ($Script:State.Scan.Python.Found) {
        $Script:UI.BtnNext.Text = '  Install  '
        $Script:UI.BtnNext.BackColor = $Script:C.Gold
        $Script:UI.BtnNext.ForeColor = $Script:C.BtnText
    } else {
        $Script:UI.BtnNext.Text = '  Get Python  '
        $Script:UI.BtnNext.BackColor = $Script:C.Orange
        $Script:UI.BtnNext.ForeColor = $Script:C.BtnText
    }
}

# ═══════════════════════════════════════════════════════════════════════
#  Installation Functions
# ═══════════════════════════════════════════════════════════════════════

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $ts = Get-Date -Format 'HH:mm:ss'
    $entry = "[$ts] $Message"
    [void]$Script:State.InstallLog.Add($entry)

    if ($Script:UI.LogBox) {
        $rtb = $Script:UI.LogBox
        $color = switch ($Level) {
            'OK'      { $Script:C.Green }
            'WARN'    { $Script:C.Orange }
            'ERROR'   { $Script:C.Red }
            'STEP'    { $Script:C.Gold }
            'CMD'     { $Script:C.Cyan }
            default   { $Script:C.TextMuted }
        }
        $rtb.SelectionStart = $rtb.TextLength
        $rtb.SelectionLength = 0
        $rtb.SelectionColor = $color
        $rtb.AppendText("$entry`r`n")
        $rtb.ScrollToCaret()
        [System.Windows.Forms.Application]::DoEvents()
    }
}

function Update-Progress {
    param([int]$Value)
    if ($Script:UI.ProgressBar) {
        $Script:UI.ProgressBar.Value = [Math]::Min($Value, 100)
        [System.Windows.Forms.Application]::DoEvents()
    }
}

function Run-ExternalCommand {
    param([string]$Exe, [string[]]$Arguments, [int]$TimeoutSec = 300)

    # Quote any arguments that contain spaces
    $quotedArgs = $Arguments | ForEach-Object {
        if ($_ -match '\s') { '"' + $_ + '"' } else { $_ }
    }
    Write-Log "  > $Exe $($quotedArgs -join ' ')" 'CMD'

    try {
        # Resolve the actual executable path — handles .cmd/.bat wrappers
        # (e.g. 'az' → 'C:\...\az.cmd') which Process.Start cannot launch directly
        $resolvedExe = $Exe
        $found = Get-Command $Exe -ErrorAction SilentlyContinue
        if ($found) { $resolvedExe = $found.Source }

        $pinfo = New-Object System.Diagnostics.ProcessStartInfo
        $pinfo.FileName = $resolvedExe
        $pinfo.Arguments = $quotedArgs -join ' '
        $pinfo.RedirectStandardOutput = $true
        $pinfo.RedirectStandardError = $true
        $pinfo.UseShellExecute = $false
        $pinfo.CreateNoWindow = $true
        # Use local working directory if project root is a UNC path (e.g. \\wsl.localhost\...)
        # Some tools like winget crash with UNC working directories (error 0x8A15002B)
        $workDir = $Script:ProjectRoot
        if ($workDir -and $workDir.StartsWith('\\')) {
            $workDir = $env:SYSTEMROOT   # C:\Windows — always local and always exists
        }
        $pinfo.WorkingDirectory = $workDir

        $proc = [System.Diagnostics.Process]::Start($pinfo)

        # Read BOTH streams asynchronously so nothing blocks the UI thread
        $stdoutTask = $proc.StandardOutput.ReadToEndAsync()
        $stderrTask = $proc.StandardError.ReadToEndAsync()

        # Poll loop: pump WinForms messages so the UI stays responsive
        $deadline = (Get-Date).AddSeconds($TimeoutSec)
        while (-not $proc.HasExited -and (Get-Date) -lt $deadline) {
            [System.Windows.Forms.Application]::DoEvents()
            Start-Sleep -Milliseconds 100
        }
        if (-not $proc.HasExited) {
            $proc.Kill()
            Write-Log '    Command timed out' 'WARN'
            return -1
        }

        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()

        # Only log the last line of output (minimal progress feedback)
        if ($proc.ExitCode -ne 0 -and $stderr.Trim()) {
            $lastLine = ($stderr.Trim() -split "`n")[-1].TrimEnd()
            if ($lastLine) { Write-Log "    $lastLine" 'WARN' }
        }
        return $proc.ExitCode
    } catch {
        Write-Log "    Error: $_" 'ERROR'
        return -1
    }
}

function Install-ComponentGraphviz {
    Write-Log '-- Installing Graphviz...' 'STEP'

    # ── Method 1: winget (signed package, trusted by Windows) ──
    # Pin to 14.0.x — Graphviz 14.1.x has a broken Windows build (missing DLL: STATUS_DLL_NOT_FOUND)
    $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
    if ($wingetAvailable) {
        Write-Log '  Trying winget (may take a few minutes)...' 'INFO'
        $rc = Run-ExternalCommand 'winget' @('install', '--id', 'Graphviz.Graphviz',
            '--version', '14.0.2',
            '--silent', '--accept-package-agreements', '--accept-source-agreements') -TimeoutSec 600
        if ($rc -eq 0) {
            $env:PATH = "$env:PATH;C:\Program Files\Graphviz\bin"
            Write-Log '  Graphviz installed via winget' 'OK'
            return $true
        }
    }

    # ── Method 2: Chocolatey (fallback) ──
    $chocoAvailable = $null -ne (Get-Command choco -ErrorAction SilentlyContinue)
    if ($chocoAvailable) {
        Write-Log '  Trying Chocolatey...' 'INFO'
        $rc = Run-ExternalCommand 'choco' @('install', 'graphviz', '-y', '--no-progress') -TimeoutSec 600
        if ($rc -eq 0) {
            $env:PATH = "$env:PATH;C:\Program Files\Graphviz\bin"
            Write-Log '  Graphviz installed via Chocolatey' 'OK'
            return $true
        }
    }

    Write-Log '  Could not auto-install Graphviz.' 'WARN'
    Write-Log '  Download manually: https://graphviz.org/download/' 'WARN'
    return $false
}

function Install-ComponentAzureCLI {
    Write-Log '-- Installing Azure CLI...' 'STEP'

    $azPath = 'C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin'

    # NOTE: We do NOT use Run-ExternalCommand for winget here because it sets
    # WorkingDirectory to $Script:ProjectRoot which may be a UNC path (\\wsl.localhost\...).
    # Winget cannot handle UNC working directories and fails with 0x8A15002B.
    # Instead we use Start-Process with a safe local WorkingDirectory.

    $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
    $safeDir = $env:SYSTEMROOT  # C:\Windows — always exists, always local

    if ($wingetAvailable) {
        # Refresh winget sources first (needed after long idle / fresh install)
        Write-Log '  Updating winget sources...' 'INFO'
        try {
            Start-Process winget -ArgumentList 'source','update','--disable-interactivity' `
                -WorkingDirectory $safeDir -NoNewWindow -Wait -ErrorAction SilentlyContinue
        } catch { }
    }

    # ── Method 1: winget (non-elevated, works if user is admin) ──
    # --force handles stale winget metadata left after a manual uninstall
    if ($wingetAvailable) {
        Write-Log '  Trying winget (may take a few minutes)...' 'INFO'
        Write-Log '  > winget install --id Microsoft.AzureCLI --source winget --silent --force' 'CMD'
        try {
            $proc = Start-Process winget -ArgumentList 'install','--id','Microsoft.AzureCLI',
                '--source','winget','--silent','--force',
                '--accept-package-agreements','--accept-source-agreements' `
                -WorkingDirectory $safeDir -NoNewWindow -Wait -PassThru
            if ($proc.ExitCode -eq 0) {
                if ((Test-Path $azPath) -and ($env:PATH -notlike "*$azPath*")) {
                    $env:PATH = "$env:PATH;$azPath"
                }
                Write-Log '  Azure CLI installed via winget' 'OK'
                return $true
            }
            Write-Log "  Standard winget returned exit code $($proc.ExitCode). Retrying elevated..." 'WARN'
        } catch {
            Write-Log "  Standard winget failed: $_. Retrying elevated..." 'WARN'
        }
    }

    # ── Method 2: Elevated winget via powershell.exe (Azure CLI installs to
    #    Program Files which requires admin; winget.exe is an AppX alias that
    #    cannot be launched directly with -Verb RunAs so we wrap in powershell.exe) ──
    if ($wingetAvailable) {
        Write-Log '  Trying elevated winget install (UAC prompt expected)...' 'INFO'
        try {
            $cmd = 'Set-Location $env:SYSTEMROOT; winget install --id Microsoft.AzureCLI --source winget --silent --force --accept-package-agreements --accept-source-agreements; exit $LASTEXITCODE'
            $proc = Start-Process powershell.exe `
                -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command',$cmd `
                -Verb RunAs -WorkingDirectory $safeDir -Wait -PassThru
            if ($proc.ExitCode -eq 0 -or (Test-Path (Join-Path $azPath 'az.cmd'))) {
                if ($env:PATH -notlike "*$azPath*") {
                    $env:PATH = "$env:PATH;$azPath"
                }
                Write-Log '  Azure CLI installed via elevated winget' 'OK'
                return $true
            }
            Write-Log "  Elevated winget returned exit code $($proc.ExitCode)" 'WARN'
        } catch {
            Write-Log "  Elevated winget failed: $_" 'WARN'
        }
    }

    # ── Method 3: Download official MSI and install with msiexec (Microsoft-signed) ──
    Write-Log '  Trying MSI download from aka.ms (Microsoft-signed installer)...' 'INFO'
    try {
        $msiPath = Join-Path $env:TEMP 'AzureCLI.msi'
        Write-Log '  > Downloading https://aka.ms/installazurecliwindows ...' 'CMD'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        (New-Object Net.WebClient).DownloadFile('https://aka.ms/installazurecliwindows', $msiPath)
        if (Test-Path $msiPath) {
            Write-Log '  Running MSI installer (UAC prompt expected)...' 'INFO'
            $proc = Start-Process msiexec -ArgumentList '/i',$msiPath,'/quiet','/norestart' `
                -Verb RunAs -Wait -PassThru
            Remove-Item $msiPath -Force -ErrorAction SilentlyContinue
            if ($proc.ExitCode -eq 0 -or (Test-Path (Join-Path $azPath 'az.cmd'))) {
                if ($env:PATH -notlike "*$azPath*") {
                    $env:PATH = "$env:PATH;$azPath"
                }
                Write-Log '  Azure CLI installed via MSI' 'OK'
                return $true
            }
            Write-Log "  MSI installer returned exit code $($proc.ExitCode)" 'WARN'
        }
    } catch {
        Write-Log "  MSI download/install failed: $_" 'WARN'
    }

    Write-Log '  Could not auto-install Azure CLI.' 'WARN'
    Write-Log '  Download: https://aka.ms/installazurecliwindows' 'WARN'
    return $false
}

function Install-ComponentVenv {
    Write-Log '-- Creating virtual environment...' 'STEP'

    $venvDir = Join-Path $Script:ProjectRoot 'cloudhorus-env'

    # Remove stale venv if it exists (e.g. created with old Python)
    if (Test-Path $venvDir) {
        Write-Log '  Removing outdated virtual environment...' 'INFO'
        try {
            Remove-Item -Path $venvDir -Recurse -Force -ErrorAction Stop
            Write-Log '  Old environment removed' 'INFO'
        } catch {
            Write-Log "  Warning: Could not fully remove old venv: $_" 'WARN'
        }
    }

    $rc = Run-ExternalCommand $Script:State.PythonCmd @('-m', 'venv', $venvDir)
    if ($rc -eq 0) {
        Write-Log "  Virtual environment created (using $($Script:State.Scan.Python.Version))" 'OK'
        return $true
    }
    Write-Log '  Failed to create virtual environment' 'ERROR'
    return $false
}

function Install-ComponentPip {
    Write-Log '-- Installing Python packages...' 'STEP'

    $pythonCmd = Join-Path $Script:ProjectRoot 'cloudhorus-env\Scripts\python.exe'
    if (-not (Test-Path $pythonCmd)) { $pythonCmd = $Script:State.PythonCmd }

    # Upgrade pip + setuptools + wheel first (helps building native extensions)
    Write-Log '  Upgrading pip, setuptools, wheel...' 'INFO'
    Run-ExternalCommand $pythonCmd @('-m', 'pip', 'install', '--upgrade',
        'pip', 'setuptools', 'wheel',
        '--quiet', '--disable-pip-version-check') | Out-Null

    $reqFile = Join-Path $Script:ProjectRoot 'requirements.txt'
    # Fallback: try script directory's parent, or current working directory
    if (-not (Test-Path $reqFile)) {
        $altPaths = @(
            (Join-Path (Split-Path -Parent $PSScriptRoot) 'requirements.txt'),
            (Join-Path $PWD.Path 'requirements.txt')
        )
        foreach ($alt in $altPaths) {
            if (Test-Path $alt) { $reqFile = $alt; break }
        }
    }
    if (-not (Test-Path $reqFile)) {
        Write-Log "  requirements.txt not found! Searched: $Script:ProjectRoot" 'ERROR'
        return $false
    }
    Write-Log "  Found requirements.txt at: $reqFile" 'INFO'

    # ── Strategy: install in two phases ──
    # Phase 1: Core packages (everything except pywebview which pulls pythonnet)
    # Phase 2: pywebview + pythonnet (may fail on bleeding-edge Python)
    # This prevents a single problematic dependency from blocking all packages.

    # Read requirements and split into core vs GUI packages
    $allReqs = Get-Content $reqFile | Where-Object {
        $_ -and ($_.Trim()) -and (-not $_.Trim().StartsWith('#'))
    }
    $guiPackages = @()   # packages that pull pythonnet (Windows GUI backend)
    $coreReqs = @()
    foreach ($line in $allReqs) {
        $pkgName = ($line.Trim() -split '[>=<\[\]]')[0].Trim().ToLower()
        if ($pkgName -eq 'pywebview') {
            $guiPackages += $line.Trim()
        } else {
            $coreReqs += $line.Trim()
        }
    }

    $allOk = $true

    # Phase 1 — Core packages
    if ($coreReqs.Count -gt 0) {
        Write-Log "  Phase 1: Installing $($coreReqs.Count) core packages..." 'INFO'
        $coreArgs = @('-m', 'pip', 'install', '--quiet', '--disable-pip-version-check')
        $coreArgs += $coreReqs
        $rc = Run-ExternalCommand $pythonCmd $coreArgs
        if ($rc -eq 0) {
            Write-Log '  Core packages installed' 'OK'
        } else {
            Write-Log '  Some core packages failed — retrying without --quiet...' 'WARN'
            $coreArgs = @('-m', 'pip', 'install', '--disable-pip-version-check')
            $coreArgs += $coreReqs
            $rc = Run-ExternalCommand $pythonCmd $coreArgs
            if ($rc -eq 0) {
                Write-Log '  Core packages installed (retry succeeded)' 'OK'
            } else {
                Write-Log '  Core package installation failed' 'ERROR'
                $allOk = $false
            }
        }
    }

    # Phase 2 — GUI packages (pywebview → pythonnet on Windows)
    if ($guiPackages.Count -gt 0) {
        Write-Log "  Phase 2: Installing GUI packages (pywebview)..." 'INFO'

        # Pre-install pythonnet with --only-binary to avoid source builds
        Write-Log '  Pre-installing pythonnet (binary wheel)...' 'INFO'
        $rc = Run-ExternalCommand $pythonCmd @('-m', 'pip', 'install',
            'pythonnet', '--only-binary', ':all:',
            '--quiet', '--disable-pip-version-check')
        if ($rc -ne 0) {
            # No binary wheel available — try allowing source build
            Write-Log '  No binary wheel for pythonnet — trying source build...' 'WARN'
            $rc = Run-ExternalCommand $pythonCmd @('-m', 'pip', 'install',
                'pythonnet', '--disable-pip-version-check')
        }

        if ($rc -eq 0) {
            Write-Log '  pythonnet installed' 'OK'
        } else {
            # Check Python version — pythonnet may not support it yet
            $pyVer = ''
            try { $pyVer = (& $pythonCmd --version 2>&1 | Out-String).Trim() } catch { }
            Write-Log "  pythonnet failed to install ($pyVer)" 'WARN'
            Write-Log '  pythonnet has no wheel for this Python version.' 'WARN'
            Write-Log '  TIP: Use Python 3.12 or 3.13 for full GUI support.' 'WARN'
            Write-Log '  CloudHorus CLI mode will still work without pywebview.' 'WARN'
            $allOk = $false
        }

        # Now install pywebview itself
        foreach ($guiPkg in $guiPackages) {
            $rc = Run-ExternalCommand $pythonCmd @('-m', 'pip', 'install',
                $guiPkg, '--quiet', '--disable-pip-version-check')
            if ($rc -eq 0) {
                Write-Log "  $guiPkg installed" 'OK'
            } else {
                Write-Log "  $guiPkg installation failed (GUI may not be available)" 'WARN'
                $allOk = $false
            }
        }
    }

    if ($allOk) {
        Write-Log '  All Python packages installed' 'OK'
    } else {
        Write-Log '  Installed with warnings — some optional GUI packages may be missing' 'WARN'
        Write-Log '  CLI/Bicep mode will work. For GUI, consider Python 3.12 or 3.13.' 'WARN'
    }
    # Return true even with partial success so installation continues
    # (core packages are what matter; GUI is optional)
    return ($coreReqs.Count -eq 0 -or $allOk -or ($rc -eq 0))
}

function Install-ComponentBicep {
    Write-Log '-- Installing Bicep CLI...' 'STEP'

    # Helper: search common install locations for bicep.exe and add to PATH
    function Find-BicepAfterInstall {
        $searchPaths = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Bicep\bicep.exe'),
            (Join-Path $env:USERPROFILE '.azure\bin\bicep.exe'),
            'C:\Program Files\Bicep\bicep.exe',
            'C:\Program Files (x86)\Bicep\bicep.exe'
        )
        # Also search winget packages directory (winget installs Bicep here)
        $wingetPkgRoot = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
        if (Test-Path $wingetPkgRoot) {
            $wingetBicep = Get-ChildItem -Path $wingetPkgRoot -Filter 'bicep.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($wingetBicep) {
                $searchPaths += $wingetBicep.FullName
            }
        }
        foreach ($p in $searchPaths) {
            if (Test-Path $p) {
                $dir = Split-Path $p -Parent
                if ($env:PATH -notlike "*$dir*") { $env:PATH = "$env:PATH;$dir" }
                try {
                    $null = & $p --version 2>&1
                    if ($LASTEXITCODE -eq 0) { return $true }
                } catch { }
            }
        }
        # Last attempt: check if it's now on PATH after env refresh
        $bicepExe = Get-Command bicep -ErrorAction SilentlyContinue
        if ($bicepExe) { return $true }
        return $false
    }

    # ── Method 1: winget install Microsoft.Bicep (signed package, trusted by Windows) ──
    $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
    if ($wingetAvailable) {
        Write-Log '  Trying: winget install Microsoft.Bicep (signed package)...' 'INFO'
        $rc = Run-ExternalCommand 'winget' @('install', '--id', 'Microsoft.Bicep',
            '--silent', '--accept-package-agreements', '--accept-source-agreements') -TimeoutSec 600
        if ($rc -eq 0) {
            Start-Sleep -Seconds 3
            if (Find-BicepAfterInstall) {
                Write-Log '  Standalone Bicep CLI installed via winget' 'OK'
                return $true
            }
            Write-Log '  winget succeeded but bicep not yet in PATH (may need shell restart)' 'WARN'
        } else {
            Write-Log '  winget install failed' 'WARN'
        }
    }

    # ── Method 2: az bicep install (if Azure CLI is available) ──
    if ($Script:State.Scan.AzureCLI.Found) {
        Write-Log '  Trying: az bicep install...' 'INFO'
        $rc = Run-ExternalCommand 'az' @('bicep', 'install')
        if ($rc -eq 0) {
            Start-Sleep -Seconds 2
            if (Find-BicepAfterInstall) {
                Write-Log '  Bicep CLI installed via Azure CLI' 'OK'
                return $true
            }
            Write-Log '  az bicep install returned 0 but verification failed' 'WARN'
        } else {
            Write-Log "  az bicep install failed (exit code $rc)" 'WARN'
        }
    }

    Write-Log '  All Bicep installation methods failed. Install manually:' 'WARN'
    Write-Log '    winget install Microsoft.Bicep' 'WARN'
    Write-Log '    or download from https://github.com/Azure/bicep/releases' 'WARN'
    return $false
}

function Install-ComponentDrawio {
    Write-Log '-- Installing graphviz2drawio (Draw.io export)...' 'STEP'
    $pythonCmd = Join-Path $Script:ProjectRoot 'cloudhorus-env\Scripts\python.exe'
    if (-not (Test-Path $pythonCmd)) { $pythonCmd = $Script:State.PythonCmd }

    # graphviz2drawio depends on pygraphviz, a C extension that wraps the
    # Graphviz C library (cgraph).  On Windows, compiling from source needs
    # MSVC Build Tools (~4-8 GB).  Instead we use Miniforge (conda-forge)
    # which provides a pre-built pygraphviz binary (~80 MB total).
    #
    # Strategy:
    #   1. Detect or install Miniforge (lightweight conda)
    #   2. Use conda to install pygraphviz into a temp env, then copy
    #      the pre-built files into the pip venv's site-packages
    #   3. Install graphviz2drawio via pip (--no-deps, sub-deps via pip)
    #   4. Ensure Graphviz DLLs are findable at runtime
    #   5. Verify import

    $venvSitePackages = Join-Path $Script:ProjectRoot 'cloudhorus-env\Lib\site-packages'

    # -- Step 1: Detect or install Miniforge/conda --------------------
    $condaCmd = $Script:State.Scan.Conda.Cmd

    if (-not $condaCmd -or -not (Test-Path $condaCmd -ErrorAction SilentlyContinue)) {
        Write-Log '  Conda/Miniforge not found. Installing Miniforge3 (~80 MB)...' 'INFO'
        Write-Log '  (Miniforge provides pre-built pygraphviz -- no C compiler needed)' 'INFO'

        $wingetAvailable = $null -ne (Get-Command winget -ErrorAction SilentlyContinue)
        if ($wingetAvailable) {
            $rc = Run-ExternalCommand 'winget' @(
                'install', '--id', 'CondaForge.Miniforge3',
                '--silent',
                '--accept-package-agreements', '--accept-source-agreements'
            ) -TimeoutSec 600   # 10 min

            # Refresh PATH
            $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                        [System.Environment]::GetEnvironmentVariable('Path', 'User')

            if ($rc -eq 0) {
                Write-Log '  Miniforge3 installed via winget' 'OK'
            } else {
                Write-Log "  Miniforge3 winget install returned exit code $rc -- checking anyway..." 'WARN'
            }
        }

        # Re-detect conda after install (check known paths)
        $condaCmd = $null
        $searchDirs = @(
            "$env:LOCALAPPDATA\miniforge3",
            "$env:USERPROFILE\miniforge3",
            "C:\Miniforge3",
            "$env:ProgramData\miniforge3",
            "$env:LOCALAPPDATA\miniconda3",
            "$env:USERPROFILE\miniconda3",
            "C:\Miniconda3"
        )
        foreach ($d in $searchDirs) {
            $exe = Join-Path $d 'Scripts\conda.exe'
            if (Test-Path $exe) { $condaCmd = $exe; break }
            $exe = Join-Path $d 'condabin\conda.bat'
            if (Test-Path $exe) { $condaCmd = $exe; break }
        }
        # Also try PATH
        if (-not $condaCmd) {
            $found = Get-Command conda -ErrorAction SilentlyContinue
            if ($found) { $condaCmd = $found.Source }
        }

        if (-not $condaCmd) {
            if (-not $wingetAvailable) {
                Write-Log '  winget not available for auto-install.' 'WARN'
            }
            Write-Log '  Could not locate conda after install.' 'WARN'
            Write-Log '  Install Miniforge manually: https://conda-forge.org/miniforge/' 'WARN'
            Write-Log '  Then click Rescan and re-run the installer.' 'INFO'
        } else {
            Write-Log "  Conda found at: $condaCmd" 'OK'
            $Script:State.Scan.Conda.Found = $true
            $Script:State.Scan.Conda.Cmd   = $condaCmd
        }
    }

    # -- Step 2: Install pygraphviz via conda (pre-built binary) ------
    $pygraphvizOK = $false
    if ($condaCmd) {
        Write-Log '  Installing pygraphviz via conda-forge (pre-built binary)...' 'INFO'

        # Create a temporary conda env with pygraphviz.
        # We copy the built files into the pip venv afterwards.
        $condaTmpEnv = Join-Path $env:TEMP 'cloudhorus-conda-pygraphviz'
        if (Test-Path $condaTmpEnv) {
            Remove-Item -Path $condaTmpEnv -Recurse -Force -ErrorAction SilentlyContinue
        }

        # Match the Python version from the venv
        $pyVer = ''
        try {
            $pyVer = (& $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1 | Out-String).Trim()
        } catch { }
        if (-not $pyVer) { $pyVer = '3.12' }

        $rc = Run-ExternalCommand $condaCmd @(
            'create', '-p', $condaTmpEnv,
            "python=$pyVer", 'pygraphviz',
            '-c', 'conda-forge',
            '-y', '--quiet'
        ) -TimeoutSec 600

        if ($rc -eq 0) {
            Write-Log '  pygraphviz conda env created' 'OK'

            # Copy pygraphviz package files from conda env -> venv site-packages
            $condaSitePackages = Join-Path $condaTmpEnv 'Lib\site-packages'
            $pygvSrc = Join-Path $condaSitePackages 'pygraphviz'

            if (Test-Path $pygvSrc) {
                $pygvDst = Join-Path $venvSitePackages 'pygraphviz'
                if (Test-Path $pygvDst) {
                    Remove-Item -Path $pygvDst -Recurse -Force -ErrorAction SilentlyContinue
                }
                Copy-Item -Path $pygvSrc -Destination $pygvDst -Recurse -Force
                Write-Log '  pygraphviz package copied to venv' 'OK'

                # Copy dist-info for pip to recognize the package
                $distInfoSrc = Get-ChildItem -Path $condaSitePackages -Directory -Filter 'pygraphviz*dist-info' -ErrorAction SilentlyContinue | Select-Object -First 1
                if ($distInfoSrc) {
                    $distInfoDst = Join-Path $venvSitePackages $distInfoSrc.Name
                    if (Test-Path $distInfoDst) {
                        Remove-Item -Path $distInfoDst -Recurse -Force -ErrorAction SilentlyContinue
                    }
                    Copy-Item -Path $distInfoSrc.FullName -Destination $distInfoDst -Recurse -Force
                }

                # Copy Graphviz C library DLLs from conda env
                # (cgraph.dll, cdt.dll, gvc.dll, etc. that _graphviz.pyd links against)
                $condaLibBin = Join-Path $condaTmpEnv 'Library\bin'
                if (Test-Path $condaLibBin) {
                    $gvDlls = Get-ChildItem -Path $condaLibBin -Filter '*.dll' -ErrorAction SilentlyContinue
                    if ($gvDlls.Count -gt 0) {
                        foreach ($dll in $gvDlls) {
                            Copy-Item -Path $dll.FullName -Destination $pygvDst -Force -ErrorAction SilentlyContinue
                        }
                        Write-Log "  Copied $($gvDlls.Count) runtime DLLs alongside pygraphviz" 'OK'
                    }
                }

                # Copy Graphviz layout plugin DLLs (e.g. gvplugin_dot_layout.dll)
                $condaGvPlugins = Join-Path $condaTmpEnv 'Library\lib\graphviz'
                if (Test-Path $condaGvPlugins) {
                    $pluginDst = Join-Path $pygvDst 'graphviz-plugins'
                    if (-not (Test-Path $pluginDst)) { New-Item -Path $pluginDst -ItemType Directory -Force | Out-Null }
                    Get-ChildItem -Path $condaGvPlugins -Filter '*.dll' -ErrorAction SilentlyContinue | ForEach-Object {
                        Copy-Item -Path $_.FullName -Destination $pluginDst -Force -ErrorAction SilentlyContinue
                    }
                }

                $pygraphvizOK = $true
            } else {
                Write-Log '  pygraphviz package not found in conda env' 'WARN'
            }

            # Clean up temporary conda environment
            Write-Log '  Cleaning up temporary conda env...' 'INFO'
            Run-ExternalCommand $condaCmd @('env', 'remove', '-p', $condaTmpEnv, '-y', '--quiet') -TimeoutSec 120 | Out-Null
            if (Test-Path $condaTmpEnv) {
                Remove-Item -Path $condaTmpEnv -Recurse -Force -ErrorAction SilentlyContinue
            }
        } else {
            Write-Log '  conda create for pygraphviz failed' 'WARN'
        }
    }

    # -- Step 3: Ensure Graphviz DLLs are findable at runtime ---------
    # pygraphviz _graphviz.pyd loads Graphviz C DLLs at import time.
    # Add Graphviz\bin to PATH as a safety net.
    $gvBin = 'C:\Program Files\Graphviz\bin'
    if ((Test-Path $gvBin) -and ($env:PATH -notlike "*$gvBin*")) {
        $env:PATH = "$gvBin;$env:PATH"
    }

    # -- Step 4: Install graphviz2drawio + pure-Python sub-deps -------
    # Use --no-deps since pygraphviz is already handled above (or absent).
    # Install the remaining pure-Python dependencies via pip.
    if ($pygraphvizOK) {
        Write-Log '  Installing graphviz2drawio...' 'INFO'
    } else {
        Write-Log '  Installing graphviz2drawio (without pygraphviz -- .drawio export disabled)...' 'WARN'
    }
    $rc = Run-ExternalCommand $pythonCmd @('-m', 'pip', 'install',
        'graphviz2drawio>=1.1.0', '--no-deps', '--quiet', '--disable-pip-version-check')
    if ($rc -eq 0) {
        foreach ($dep in @('puremagic', 'svg.path')) {
            Write-Log "  Installing sub-dep: $dep..." 'INFO'
            Run-ExternalCommand $pythonCmd @('-m', 'pip', 'install', $dep,
                '--quiet', '--disable-pip-version-check') | Out-Null
        }
    }

    if ($rc -ne 0) {
        Write-Log '  graphviz2drawio installation failed' 'ERROR'
        return $false
    }

    # -- Step 5: Verify import ----------------------------------------
    try {
        $importCheck = "import os; os.add_dll_directory(r'C:\Program Files\Graphviz\bin') if hasattr(os,'add_dll_directory') else None; from graphviz2drawio import graphviz2drawio"
        $null = & $pythonCmd -c $importCheck 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Log '  graphviz2drawio fully operational (pygraphviz OK)' 'OK'
        } else {
            if ($pygraphvizOK) {
                Write-Log '  graphviz2drawio installed but import check failed' 'WARN'
                Write-Log '  This may work at runtime when Graphviz\bin is on PATH' 'INFO'
            } else {
                Write-Log '  graphviz2drawio installed but .drawio export unavailable (pygraphviz missing)' 'WARN'
                Write-Log '  To enable: install Miniforge (https://conda-forge.org/miniforge/) then re-run installer' 'INFO'
            }
        }
    } catch {
        Write-Log '  graphviz2drawio import check failed' 'WARN'
    }

    return $true
}

# ═══════════════════════════════════════════════════════════════════════
#  Build Main Form
# ═══════════════════════════════════════════════════════════════════════

function Build-MainForm {

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'CloudHorus Setup'
    $form.Size = New-Object System.Drawing.Size(760, 570)
    $form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedSingle
    $form.MaximizeBox = $false
    $form.BackColor = $Script:C.BgDark
    $form.ForeColor = $Script:C.Text
    $form.Font = $Script:F.Normal

    # Try to set icon from project logo (PNG -> high-quality Icon)
    $iconPath = Join-Path $Script:ProjectRoot 'assets\logo\cloudhorus-icon.png'
    if (Test-Path $iconPath) {
        try {
            $srcBmp = [System.Drawing.Bitmap]::new($iconPath)
            # Create a proper 32x32 bitmap with high-quality interpolation
            $icon32 = New-Object System.Drawing.Bitmap(32, 32)
            $g = [System.Drawing.Graphics]::FromImage($icon32)
            $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
            $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $g.DrawImage($srcBmp, 0, 0, 32, 32)
            $g.Dispose()
            $hIcon = $icon32.GetHicon()
            $form.Icon = [System.Drawing.Icon]::FromHandle($hIcon)
            $srcBmp.Dispose()
        } catch { }
    }
    # Fallback: try .ico if exists
    if (-not $form.Icon) {
        $icoPath = Join-Path $Script:ProjectRoot 'assets\logo\cloudhorus-icon.ico'
        if (Test-Path $icoPath) {
            try { $form.Icon = New-Object System.Drawing.Icon($icoPath) } catch { }
        }
    }

    $Script:UI.Form = $form

    # ─── Header ──────────────────────────────────────────────────────

    $header = New-Object System.Windows.Forms.Panel
    $header.Dock = [System.Windows.Forms.DockStyle]::Top
    $header.Height = 90
    $header.BackColor = $Script:C.BgSurface

    # Title
    $titleLabel = New-Label -Text '  CloudHorus' -Font $Script:F.Title -Color $Script:C.Gold -X 10 -Y 10 -AutoSize
    $header.Controls.Add($titleLabel)

    # Subtitle
    $subLabel = New-Label -Text '  Azure Cloud Architecture Guardian' -Font $Script:F.Subtitle -Color $Script:C.TextMuted -X 12 -Y 48 -AutoSize
    $header.Controls.Add($subLabel)

    # Gold accent line
    $gold_line = New-Object System.Windows.Forms.Panel
    $gold_line.Location = New-Object System.Drawing.Point(0, 86)
    $gold_line.Size = New-Object System.Drawing.Size(760, 3)
    $gold_line.BackColor = $Script:C.Gold
    $header.Controls.Add($gold_line)

    $form.Controls.Add($header)

    # ─── Step Indicator Bar ──────────────────────────────────────────

    $stepBar = New-Object System.Windows.Forms.Panel
    $stepBar.Location = New-Object System.Drawing.Point(0, 90)
    $stepBar.Size = New-Object System.Drawing.Size(760, 48)
    $stepBar.BackColor = $Script:C.BgPanel

    $stepNames = @('Welcome', 'Scan & Select', 'Install', 'Complete')
    $stepWidth = 170
    $startX = [int](((760 - ($stepWidth * 4)) / 2))

    for ($i = 0; $i -lt 4; $i++) {
        $x = $startX + ($i * $stepWidth)

        # Number circle (small label)
        $numLbl = New-Label -Text "$($i + 1)" -Font $Script:F.StepNum -X ($x + 4) -Y 12 -W 22 -H 22
        $numLbl.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
        $numLbl.BackColor = if ($i -eq 0) { $Script:C.Gold } else { $Script:C.BgElevated }
        $numLbl.ForeColor = if ($i -eq 0) { $Script:C.BtnText } else { $Script:C.TextMuted }
        $stepBar.Controls.Add($numLbl)
        $Script:UI.StepNumbers += $numLbl

        # Step name
        $stepLbl = New-Label -Text $stepNames[$i] -Font $Script:F.Step -X ($x + 30) -Y 13 -AutoSize
        $stepLbl.ForeColor = if ($i -eq 0) { $Script:C.Text } else { $Script:C.TextMuted }
        $stepBar.Controls.Add($stepLbl)
        $Script:UI.StepLabels += $stepLbl

        # Connector line
        if ($i -lt 3) {
            $linePanel = New-Object System.Windows.Forms.Panel
            $linePanel.Location = New-Object System.Drawing.Point(($x + $stepWidth - 20), 22)
            $linePanel.Size = New-Object System.Drawing.Size(24, 2)
            $linePanel.BackColor = $Script:C.BgElevated
            $stepBar.Controls.Add($linePanel)
        }
    }

    # Bottom border
    $stepBorder = New-Object System.Windows.Forms.Panel
    $stepBorder.Location = New-Object System.Drawing.Point(0, 46)
    $stepBorder.Size = New-Object System.Drawing.Size(760, 1)
    $stepBorder.BackColor = $Script:C.Border
    $stepBar.Controls.Add($stepBorder)

    $form.Controls.Add($stepBar)

    # ─── Content Area ────────────────────────────────────────────────

    $contentPanel = New-Object System.Windows.Forms.Panel
    $contentPanel.Location = New-Object System.Drawing.Point(0, 138)
    $contentPanel.Size = New-Object System.Drawing.Size(760, 340)
    $contentPanel.BackColor = $Script:C.BgDark
    $Script:UI.ContentPanel = $contentPanel
    $form.Controls.Add($contentPanel)

    # ─── Footer ──────────────────────────────────────────────────────

    $footer = New-Object System.Windows.Forms.Panel
    $footer.Dock = [System.Windows.Forms.DockStyle]::Bottom
    $footer.Height = 60
    $footer.BackColor = $Script:C.BgSurface

    $footBorder = New-Object System.Windows.Forms.Panel
    $footBorder.Dock = [System.Windows.Forms.DockStyle]::Top
    $footBorder.Height = 1
    $footBorder.BackColor = $Script:C.Border
    $footer.Controls.Add($footBorder)

    $btnBack = New-StyledButton -Text '  Back  ' -X 480 -Y 12 -W 110 -H 36 `
        -BgColor $Script:C.BgElevated -FgColor $Script:C.Text `
        -OnClick { Navigate-Back }
    $btnBack.Visible = $false
    $footer.Controls.Add($btnBack)
    $Script:UI.BtnBack = $btnBack

    $btnNext = New-StyledButton -Text '  Next  ' -X 600 -Y 12 -W 130 -H 36 `
        -BgColor $Script:C.Gold -FgColor $Script:C.BtnText `
        -OnClick { Navigate-Next }
    $footer.Controls.Add($btnNext)
    $Script:UI.BtnNext = $btnNext

    $form.Controls.Add($footer)

    # ─── Build Pages ─────────────────────────────────────────────────

    Build-WelcomePage
    Build-ScanPage
    Build-InstallPage
    Build-CompletePage

    Show-Page 0
}

# ═══════════════════════════════════════════════════════════════════════
#  Page: Welcome
# ═══════════════════════════════════════════════════════════════════════

function Build-WelcomePage {
    $page = New-Object System.Windows.Forms.Panel
    $page.Size = New-Object System.Drawing.Size(760, 340)
    $page.BackColor = $Script:C.BgDark
    $page.Visible = $false

    $y = 30

    $welcome = New-Label -Text 'Welcome to CloudHorus Setup' -Font $Script:F.Heading -Color $Script:C.Gold -X 50 -Y $y -AutoSize
    $page.Controls.Add($welcome); $y += 45

    $desc = New-Label -Text @"
This wizard will check your system and install the required dependencies
for CloudHorus -- Azure Cloud Architecture Guardian.

CloudHorus generates professional architecture diagrams from your live
Azure environments or Bicep Infrastructure-as-Code templates.
"@ -Font $Script:F.Normal -Color $Script:C.Text -X 50 -Y $y -W 660 -H 100
    $page.Controls.Add($desc); $y += 110

    # What will be checked
    $checklist = New-Label -Text @"
The setup will verify and install:

    Python 3.10+  and  pip                       (required)
    Graphviz  --  diagram rendering engine        (required)
    Virtual environment  and  Python packages     (required)
    Azure CLI  --  for live subscription scans    (required)
    Bicep CLI  --  for IaC template analysis      (required)
    graphviz2drawio  --  Draw.io export support   (required)
"@ -Font $Script:F.Small -Color $Script:C.TextMuted -X 50 -Y $y -W 660 -H 140
    $page.Controls.Add($checklist)

    $Script:UI.Pages['Welcome'] = $page
    $Script:UI.ContentPanel.Controls.Add($page)
}

# ═══════════════════════════════════════════════════════════════════════
#  Page: Scan & Select
# ═══════════════════════════════════════════════════════════════════════

function Build-ScanPage {
    $page = New-Object System.Windows.Forms.Panel
    $page.Size = New-Object System.Drawing.Size(760, 340)
    $page.BackColor = $Script:C.BgDark
    $page.Visible = $false

    $y = 15

    $heading = New-Label -Text 'System Scan Results' -Font $Script:F.Heading -Color $Script:C.Gold -X 30 -Y $y -AutoSize
    $page.Controls.Add($heading); $y += 38

    # Component rows -- ALL required (auto-installed when missing)
    $components = @(
        @{ Key = 'Python';   Label = 'Python 3.10+'          },
        @{ Key = 'Pip';      Label = 'pip (package manager)' },
        @{ Key = 'Graphviz'; Label = 'Graphviz'              },
        @{ Key = 'Conda';    Label = 'Conda / Miniforge (for Draw.io export)' },
        @{ Key = 'Venv';     Label = 'Virtual Environment'   },
        @{ Key = 'PipPkgs';  Label = 'Python Packages'       },
        @{ Key = 'AzureCLI'; Label = 'Azure CLI'             },
        @{ Key = 'BicepCLI'; Label = 'Bicep CLI'             },
        @{ Key = 'Drawio';   Label = 'Draw.io Export (graphviz2drawio)' }
    )

    foreach ($comp in $components) {
        # Status icon label (will be updated after scan)
        $statusLbl = New-Label -Text '  ...' -Font $Script:F.Normal -Color $Script:C.TextMuted -X 35 -Y $y -W 40 -H 22
        $page.Controls.Add($statusLbl)
        $Script:UI.ScanLabels["$($comp.Key)_status"] = $statusLbl

        # Name
        $nameLbl = New-Label -Text $comp.Label -Font $Script:F.Normal -Color $Script:C.Text -X 80 -Y $y -W 400 -H 22
        $page.Controls.Add($nameLbl)
        $Script:UI.ScanLabels["$($comp.Key)_name"] = $nameLbl

        # Required tag
        $tagLbl = New-Label -Text '(required)' -Font $Script:F.Small -Color $Script:C.Gold -X 345 -Y ($y + 1) -AutoSize
        $page.Controls.Add($tagLbl)

        $y += 30
    }

    # Separator
    $sep = New-Object System.Windows.Forms.Panel
    $sep.Location = New-Object System.Drawing.Point(30, ($y + 5))
    $sep.Size = New-Object System.Drawing.Size(700, 1)
    $sep.BackColor = $Script:C.Border
    $page.Controls.Add($sep)
    $y += 20

    # Info text
    $infoLbl = New-Label -Text 'Scanning will begin automatically...' `
        -Font $Script:F.Small -Color $Script:C.TextMuted -X 30 -Y $y -W 530 -H 22
    $page.Controls.Add($infoLbl)
    $Script:UI.ScanLabels['info'] = $infoLbl

    # Rescan button — allows re-checking after external installs (e.g. Python upgrade)
    $btnRescan = New-StyledButton -Text '  Rescan  ' -X 580 -Y ($y - 3) -W 120 -H 28 `
        -BgColor $Script:C.BgElevated -FgColor $Script:C.Gold `
        -OnClick { Invoke-Rescan }
    $btnRescan.Font = $Script:F.Small
    $btnRescan.FlatAppearance.BorderSize = 1
    $btnRescan.FlatAppearance.BorderColor = $Script:C.Gold
    $page.Controls.Add($btnRescan)
    $Script:UI.BtnRescan = $btnRescan

    $Script:UI.Pages['Scan'] = $page
    $Script:UI.ContentPanel.Controls.Add($page)
}

function Update-ScanUI {
    $scan = $Script:State.Scan

    # Conda is only needed to install pygraphviz.
    # If Drawio (pygraphviz) already works, Conda is irrelevant — show green.
    $condaStatus = if ($scan.Drawio.Found) { $true } else { $scan.Conda.Found }

    $items = @{
        'Python'   = $scan.Python.Found
        'Pip'      = $scan.Pip.Found
        'Graphviz' = $scan.Graphviz.Found
        'Conda'    = $condaStatus
        'Venv'     = $scan.Venv.Found
        'AzureCLI' = $scan.AzureCLI.Found
        'BicepCLI' = $scan.BicepCLI.Found
        'Drawio'   = $scan.Drawio.Found
    }

    # PipPkgs: consider found if all required packages are installed
    $allPkgs = $true
    foreach ($v in $scan.PipPkgs.Values) { if (-not $v) { $allPkgs = $false; break } }
    $items['PipPkgs'] = $allPkgs

    foreach ($kv in $items.GetEnumerator()) {
        $statusLbl = $Script:UI.ScanLabels["$($kv.Key)_status"]
        if ($statusLbl) {
            if ($kv.Value) {
                $statusLbl.Text = [char]0x2713  # check mark
                $statusLbl.ForeColor = $Script:C.Green
            } else {
                $statusLbl.Text = [char]0x2717  # cross mark
                $statusLbl.ForeColor = $Script:C.Red
            }
        }
    }

    # If Drawio works, update the Conda label to say "not needed"
    $condaNameLbl = $Script:UI.ScanLabels['Conda_name']
    if ($condaNameLbl -and $scan.Drawio.Found -and -not $scan.Conda.Found) {
        $condaNameLbl.Text = 'Conda / Miniforge (not needed - pygraphviz OK)'
    }

    # Update info based on Python version
    $infoLbl = $Script:UI.ScanLabels['info']
    if ($scan.Python.Found) {
        $v = $scan.Python.Version
        $missing = @()
        if (-not $scan.Graphviz.Found) { $missing += 'Graphviz' }
        if (-not $scan.Venv.Found) { $missing += 'Virtual Environment' }
        if (-not $allPkgs) { $missing += 'Some Python packages' }

        if ($missing.Count -eq 0) {
            $infoLbl.Text = "Python $v detected. All required components are installed."
            $infoLbl.ForeColor = $Script:C.Green
        } else {
            $infoLbl.Text = "Python $v detected. Missing: $($missing -join ', '). Click Next to install."
            $infoLbl.ForeColor = $Script:C.Orange
        }
    } else {
        $oldVer = $Script:State.PythonDetectedVersion
        if ($oldVer) {
            $infoLbl.Text = "Python $oldVer detected but 3.10+ is required. Install it, then click Rescan."
        } else {
            $infoLbl.Text = 'Python 3.10+ is required. Install it, then click Rescan.'
        }
        $infoLbl.ForeColor = $Script:C.Red
    }

    # Auto-determine what needs installing (all components are required)
    $Script:State.Install.Graphviz    = -not $scan.Graphviz.Found
    $Script:State.Install.AzureCLI    = -not $scan.AzureCLI.Found
    $Script:State.Install.BicepCLI    = -not $scan.BicepCLI.Found
    $Script:State.Install.Venv        = -not $scan.Venv.Found
    $Script:State.Install.PipPackages = -not $allPkgs
    $Script:State.Install.Drawio      = -not $scan.Drawio.Found
}

# ═══════════════════════════════════════════════════════════════════════
#  Page: Install
# ═══════════════════════════════════════════════════════════════════════

function Build-InstallPage {
    $page = New-Object System.Windows.Forms.Panel
    $page.Size = New-Object System.Drawing.Size(760, 340)
    $page.BackColor = $Script:C.BgDark
    $page.Visible = $false

    $heading = New-Label -Text 'Installing Components' -Font $Script:F.Heading -Color $Script:C.Gold -X 30 -Y 10 -AutoSize
    $page.Controls.Add($heading)

    # Progress bar
    $pb = New-Object System.Windows.Forms.ProgressBar
    $pb.Location = New-Object System.Drawing.Point(30, 48)
    $pb.Size = New-Object System.Drawing.Size(695, 22)
    $pb.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
    $pb.Minimum = 0
    $pb.Maximum = 100
    $pb.Value = 0
    $page.Controls.Add($pb)
    $Script:UI.ProgressBar = $pb

    # Log output (RichTextBox)
    $rtb = New-Object System.Windows.Forms.RichTextBox
    $rtb.Location = New-Object System.Drawing.Point(30, 80)
    $rtb.Size = New-Object System.Drawing.Size(695, 245)
    $rtb.BackColor = $Script:C.BgPanel
    $rtb.ForeColor = $Script:C.Text
    $rtb.Font = $Script:F.Mono
    $rtb.ReadOnly = $true
    $rtb.BorderStyle = [System.Windows.Forms.BorderStyle]::None
    $rtb.ScrollBars = [System.Windows.Forms.RichTextBoxScrollBars]::Vertical
    $page.Controls.Add($rtb)
    $Script:UI.LogBox = $rtb

    $Script:UI.Pages['Install'] = $page
    $Script:UI.ContentPanel.Controls.Add($page)
}

function Start-Installation {
    $Script:UI.BtnNext.Enabled = $false
    $Script:UI.BtnBack.Enabled = $false
    $Script:UI.LogBox.Clear()

    $steps = @()
    $scan = $Script:State.Scan
    $inst = $Script:State.Install

    if (-not $scan.Python.Found) {
        Write-Log 'Python 3.10+ is not installed. Cannot proceed.' 'ERROR'
        Write-Log 'Download from https://python.org and re-run this installer.' 'ERROR'
        $Script:UI.BtnBack.Enabled = $true
        return
    }

    # Pip bootstrap
    if (-not $scan.Pip.Found) {
        $steps += @{ Name = 'Bootstrap pip'; Action = {
            Write-Log '-- Bootstrapping pip...' 'STEP'
            $rc = Run-ExternalCommand $Script:State.PythonCmd @('-m', 'ensurepip', '--upgrade')
            return ($rc -eq 0)
        }}
    }

    # Graphviz
    if ($inst.Graphviz -and -not $scan.Graphviz.Found) {
        $steps += @{ Name = 'Install Graphviz'; Action = { Install-ComponentGraphviz } }
    }

    # Azure CLI
    if ($inst.AzureCLI -and -not $scan.AzureCLI.Found) {
        $steps += @{ Name = 'Install Azure CLI'; Action = { Install-ComponentAzureCLI } }
    }

    # Virtual environment
    if ($inst.Venv -and -not $scan.Venv.Found) {
        $steps += @{ Name = 'Create Virtual Environment'; Action = { Install-ComponentVenv } }
    }

    # Pip packages (always re-check after venv creation)
    if ($inst.PipPackages) {
        # Read requirements.txt to list explicit packages in the consent dialog
        $reqPath = Join-Path $Script:ProjectRoot 'requirements.txt'
        $pkgList = @()
        if (Test-Path $reqPath) {
            $pkgList = @(Get-Content $reqPath | Where-Object {
                $_ -match '^[A-Za-z]' -and $_ -notmatch '^#'
            } | ForEach-Object { ($_ -split '[><=;]')[0].Trim() })
        }
        # graphviz2drawio is handled separately (not in requirements.txt)
        # but include it in the display list so the user knows
        $pkgList += 'graphviz2drawio'
        if ($pkgList.Count -gt 0) {
            $pkgDisplay = ($pkgList | ForEach-Object { "      $_" }) -join "`n"
            $steps += @{ Name = "Install Python Packages:`n$pkgDisplay"; Action = { Install-ComponentPip } }
        } else {
            $steps += @{ Name = 'Install Python Packages (from requirements.txt)'; Action = { Install-ComponentPip } }
        }
    }

    # Bicep CLI
    if ($inst.BicepCLI -and -not $scan.BicepCLI.Found) {
        $steps += @{ Name = 'Install Bicep CLI'; Action = { Install-ComponentBicep } }
    }

    # graphviz2drawio — installed separately because it depends on pygraphviz
    # (a C extension requiring MSVC + Graphviz headers to compile).
    if (-not $scan.Drawio.Found) {
        $steps += @{ Name = 'Install graphviz2drawio (Draw.io export)'; Action = { Install-ComponentDrawio } }
    }

    if ($steps.Count -eq 0) {
        Write-Log 'All components already installed. Nothing to do!' 'OK'
        Update-Progress 100
        $Script:State.Completed = $true
        $Script:UI.BtnNext.Enabled = $true
        $Script:UI.BtnNext.Text = '  Finish  '
        return
    }

    # ── Consent dialog: list what will be installed ──
    $itemList = ($steps | ForEach-Object { "  - $($_.Name)" }) -join "`n"
    $consentMsg = "The following $($steps.Count) component(s) will be installed:`n`n$itemList`n`nDo you want to proceed?"
    $consent = [System.Windows.Forms.MessageBox]::Show(
        $consentMsg,
        'Confirm Installation',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    if ($consent -ne [System.Windows.Forms.DialogResult]::Yes) {
        Write-Log 'Installation cancelled by user.' 'WARN'
        $Script:UI.BtnBack.Enabled = $true
        $Script:UI.BtnNext.Enabled = $true
        $Script:UI.BtnNext.Text = '  Install  '
        return
    }

    Write-Log "Starting installation ($($steps.Count) steps)..." 'STEP'
    Write-Log '' 'INFO'

    $stepIndex = 0
    $hasErrors = $false
    foreach ($step in $steps) {
        $stepIndex++
        $pct = [int](($stepIndex / $steps.Count) * 100)
        Update-Progress ([int](($stepIndex - 1) / $steps.Count * 100))

        Write-Log '' 'INFO'
        $result = & $step.Action
        if (-not $result) {
            $hasErrors = $true
            [void]$Script:State.Errors.Add($step.Name)
        }
        Update-Progress $pct
    }

    Write-Log '' 'INFO'
    if ($hasErrors) {
        Write-Log '-- Installation completed with warnings. Some components may not be available.' 'WARN'
    } else {
        Write-Log '-- All components installed successfully!' 'OK'
    }

    Update-Progress 100
    $Script:State.Completed = $true
    $Script:UI.BtnNext.Enabled = $true
    $Script:UI.BtnNext.Text = '  Finish  '
}

# ═══════════════════════════════════════════════════════════════════════
#  Page: Complete
# ═══════════════════════════════════════════════════════════════════════

function Build-CompletePage {
    $page = New-Object System.Windows.Forms.Panel
    $page.Size = New-Object System.Drawing.Size(760, 340)
    $page.BackColor = $Script:C.BgDark
    $page.Visible = $false

    $y = 30

    $heading = New-Label -Text 'Setup Complete!' -Font $Script:F.Heading -Color $Script:C.Green -X 50 -Y $y -AutoSize
    $page.Controls.Add($heading); $y += 45

    $summaryLbl = New-Label -Text 'CloudHorus is ready to use.' `
        -Font $Script:F.Normal -Color $Script:C.Text -X 50 -Y $y -W 660 -H 26
    $page.Controls.Add($summaryLbl)
    $Script:UI.ScanLabels['summary'] = $summaryLbl
    $y += 40

    $detailLbl = New-Label -Text '' -Font $Script:F.Small -Color $Script:C.TextMuted `
        -X 50 -Y $y -W 660 -H 110
    $page.Controls.Add($detailLbl)
    $Script:UI.ScanLabels['details'] = $detailLbl
    $y += 115

    # Launch button (big, prominent)
    $launchBtn = New-StyledButton -Text '  Launch CloudHorus  ' -X 230 -Y $y -W 280 -H 48 `
        -BgColor $Script:C.Gold -FgColor $Script:C.BtnText `
        -OnClick {
            Launch-CloudHorus
        }
    $page.Controls.Add($launchBtn)
    $Script:UI.ScanLabels['launchBtn'] = $launchBtn

    $Script:UI.Pages['Complete'] = $page
    $Script:UI.ContentPanel.Controls.Add($page)
}

function Update-CompletePage {
    $summaryLbl = $Script:UI.ScanLabels['summary']
    $detailLbl = $Script:UI.ScanLabels['details']

    if ($Script:State.Errors.Count -gt 0) {
        $summaryLbl.Text = 'Setup completed with some warnings.'
        $summaryLbl.ForeColor = $Script:C.Orange
        $detailLbl.Text = "The following could not be installed automatically:`r`n" +
            ($Script:State.Errors -join ', ') + "`r`n`r`n" +
            "CloudHorus may still work depending on your use case.`r`n" +
            "Bicep template mode works without Azure CLI."
    } else {
        $summaryLbl.Text = 'All components installed successfully. CloudHorus is ready!'
        $summaryLbl.ForeColor = $Script:C.Green
        $detailLbl.Text = "Click the button below to launch CloudHorus.`r`n`r`n" +
            "You can also run launcher.bat anytime to start CloudHorus.`r`n" +
            "The application will open as a desktop window."
    }
}

function Launch-CloudHorus {
    $pythonCmd = Join-Path $Script:ProjectRoot 'cloudhorus-env\Scripts\python.exe'
    if (-not (Test-Path $pythonCmd)) { $pythonCmd = $Script:State.PythonCmd }

    $webuiScript = Join-Path $Script:ProjectRoot 'cloudhorus_webui.py'
    if (-not (Test-Path $webuiScript)) {
        [System.Windows.Forms.MessageBox]::Show(
            "Could not find cloudhorus_webui.py in:`n$Script:ProjectRoot",
            'Launch Error',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
        return
    }

    # Quick sanity check: verify pywebview is importable
    $importCheck = & $pythonCmd -c "import webview; print('ok')" 2>&1
    if ($importCheck -notmatch 'ok') {
        $errMsg = ($importCheck | Out-String).Trim()
        [System.Windows.Forms.MessageBox]::Show(
            "pywebview is not installed or has an import error:`n`n$errMsg`n`nTry re-running the installer.",
            'Launch Error - Missing pywebview',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
        return
    }

    try {
        $pinfo = New-Object System.Diagnostics.ProcessStartInfo
        $pinfo.FileName = $pythonCmd
        $pinfo.Arguments = "`"$webuiScript`""
        $pinfo.WorkingDirectory = $Script:ProjectRoot
        $pinfo.UseShellExecute = $false
        $pinfo.CreateNoWindow = $true
        [System.Diagnostics.Process]::Start($pinfo) | Out-Null

        # Close the installer after a short delay
        Start-Sleep -Milliseconds 500
        $Script:UI.Form.Close()
    } catch {
        [System.Windows.Forms.MessageBox]::Show(
            "Failed to launch CloudHorus:`n$_",
            'Launch Error',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    }
}

# ═══════════════════════════════════════════════════════════════════════
#  Navigation
# ═══════════════════════════════════════════════════════════════════════

function Show-Page([int]$Index) {
    $pageKeys = @('Welcome', 'Scan', 'Install', 'Complete')

    # Hide all pages
    foreach ($key in $pageKeys) {
        if ($Script:UI.Pages.ContainsKey($key)) {
            $Script:UI.Pages[$key].Visible = $false
        }
    }

    # Show target
    $Script:UI.Pages[$pageKeys[$Index]].Visible = $true
    $Script:State.CurrentPage = $Index

    # Update step indicator
    for ($i = 0; $i -lt 4; $i++) {
        if ($i -lt $Index) {
            # Completed step
            $Script:UI.StepNumbers[$i].BackColor = $Script:C.Green
            $Script:UI.StepNumbers[$i].ForeColor = $Script:C.BtnText
            $Script:UI.StepNumbers[$i].Text = [char]0x2713
            $Script:UI.StepLabels[$i].ForeColor = $Script:C.Green
        } elseif ($i -eq $Index) {
            # Current step
            $Script:UI.StepNumbers[$i].BackColor = $Script:C.Gold
            $Script:UI.StepNumbers[$i].ForeColor = $Script:C.BtnText
            $Script:UI.StepNumbers[$i].Text = "$($i + 1)"
            $Script:UI.StepLabels[$i].ForeColor = $Script:C.Text
        } else {
            # Future step
            $Script:UI.StepNumbers[$i].BackColor = $Script:C.BgElevated
            $Script:UI.StepNumbers[$i].ForeColor = $Script:C.TextMuted
            $Script:UI.StepNumbers[$i].Text = "$($i + 1)"
            $Script:UI.StepLabels[$i].ForeColor = $Script:C.TextMuted
        }
    }

    # Update buttons
    $Script:UI.BtnBack.Visible = ($Index -gt 0 -and $Index -lt 3)
    $Script:UI.BtnBack.Enabled = ($Index -gt 0 -and $Index -ne 2)  # Disabled during install

    switch ($Index) {
        0 {
            $Script:UI.BtnNext.Text = '  Next  '
            $Script:UI.BtnNext.Enabled = $true
            $Script:UI.BtnNext.Visible = $true
            $Script:UI.BtnNext.BackColor = $Script:C.Gold
            $Script:UI.BtnNext.ForeColor = $Script:C.BtnText
        }
        1 {
            $Script:UI.BtnNext.Visible = $true
            $Script:UI.BtnNext.Enabled = $true
            $Script:UI.BtnNext.BackColor = $Script:C.Gold
            $Script:UI.BtnNext.ForeColor = $Script:C.BtnText
            # Auto-scan
            Invoke-FullScan
            Update-ScanUI
            # Button text depends on Python state
            if ($Script:State.Scan.Python.Found) {
                $Script:UI.BtnNext.Text = '  Install  '
            } else {
                $Script:UI.BtnNext.Text = '  Get Python  '
                $Script:UI.BtnNext.BackColor = $Script:C.Orange
            }
        }
        2 {
            $Script:UI.BtnNext.Text = '  Installing...  '
            $Script:UI.BtnNext.Enabled = $false
            $Script:UI.BtnNext.Visible = $true
            $Script:UI.BtnNext.BackColor = $Script:C.BgElevated
            $Script:UI.BtnNext.ForeColor = $Script:C.TextMuted
            $Script:UI.BtnBack.Enabled = $false
            # Start installation
            Start-Installation
        }
        3 {
            $Script:UI.BtnNext.Text = '  Close  '
            $Script:UI.BtnNext.Enabled = $true
            $Script:UI.BtnNext.Visible = $true
            $Script:UI.BtnNext.BackColor = $Script:C.BgElevated
            $Script:UI.BtnNext.ForeColor = $Script:C.Text
            $Script:UI.BtnBack.Visible = $false
            Update-CompletePage
        }
    }
}

function Navigate-Next {
    $current = $Script:State.CurrentPage

    switch ($current) {
        0 { Show-Page 1 }
        1 {
            # Validate before proceeding to install
            if (-not $Script:State.Scan.Python.Found) {
                $oldVer = $Script:State.PythonDetectedVersion
                $msg = if ($oldVer) {
                    "Python $oldVer was detected but CloudHorus requires 3.10+.`n`nClick OK to open the Python download page in your browser.`nAfter installing, click the Rescan button to re-check."
                } else {
                    "Python 3.10+ is required but was not found.`n`nClick OK to open the Python download page in your browser.`nAfter installing, click the Rescan button to re-check."
                }
                $result = [System.Windows.Forms.MessageBox]::Show(
                    $msg,
                    'Python 3.10+ Required',
                    [System.Windows.Forms.MessageBoxButtons]::OKCancel,
                    [System.Windows.Forms.MessageBoxIcon]::Warning
                )
                if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
                    Start-Process 'https://www.python.org/downloads/'
                }
                return
            }
            Show-Page 2
        }
        2 { Show-Page 3 }
        3 { $Script:UI.Form.Close() }
    }
}

function Navigate-Back {
    $current = $Script:State.CurrentPage
    if ($current -gt 0 -and $current -ne 2) {
        Show-Page ($current - 1)
    }
}

# ═══════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════

function Start-Installer {
    Build-MainForm

    # Ensure the form is visible and in foreground.
    $Script:UI.Form.Add_Shown({
        $this.WindowState = [System.Windows.Forms.FormWindowState]::Normal
        $this.Activate()
        $this.BringToFront()
    })

    [System.Windows.Forms.Application]::Run($Script:UI.Form)
}

Start-Installer
