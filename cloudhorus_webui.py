#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CloudHorus Modern Web UI — pywebview Backend

A modern, dynamic web-based GUI for CloudHorus using pywebview.
Replaces the legacy Tkinter interface with HTML/CSS/JS powered UI.
"""

import glob
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import webview
from core.local_input_metadata import discover_terraform_source_scope_metadata, parse_scope_metadata_files
from core.plan_diff import CHANGE_CATEGORIES

# ─── Constants ───────────────────────────────────────────────────────────
WEBUI_DIR = os.path.join(PROJECT_ROOT, "webui")
AUTH_FILE = os.path.join(PROJECT_ROOT, "azure_auth_prompt.txt")
_LOGO_DIR = os.path.join(PROJECT_ROOT, "assets", "logo")
# Windows taskbar requires .ico format; WSL renders to a Windows desktop so also needs .ico
_is_wsl = sys.platform == "linux" and "microsoft" in (
    open("/proc/version").read().lower() if os.path.exists("/proc/version") else ""
)
_use_ico = sys.platform.startswith("win") or _is_wsl
ICON_PATH = (
    os.path.join(_LOGO_DIR, "cloudhorus-icon.ico") if _use_ico else os.path.join(_LOGO_DIR, "cloudhorus-icon.png")
)


def _load_version() -> str:
    """Load the project version dynamically from src/version.py."""
    version_file = os.path.join(PROJECT_ROOT, "src", "version.py")
    try:
        ns: Dict[str, Any] = {}
        with open(version_file, "r", encoding="utf-8") as f:
            exec(f.read(), ns)  # noqa: S102
        return str(ns.get("__version__", "0.0.0"))
    except Exception:
        return "0.0.0"


APP_VERSION = _load_version()

#: Fallback suffix of the Change_Summary sidecar written next to the PNG.
#: The authoritative constant is ``core.graph_generator.CHANGE_SUMMARY_SUFFIX``, but
#: that module pulls Graphviz and the Azure SDK, which the GUI host process has no
#: reason to load just to read a small JSON file next to the diagram.
_CHANGE_SUMMARY_SUFFIX_FALLBACK = ".change-summary.json"


def _change_summary_suffix() -> str:
    """Return the Change_Summary sidecar suffix, preferring the shared constant."""
    try:
        from core.graph_generator import CHANGE_SUMMARY_SUFFIX  # noqa: PLC0415

        return CHANGE_SUMMARY_SUFFIX
    except Exception:
        return _CHANGE_SUMMARY_SUFFIX_FALLBACK


def normalize_change_types(change_types: Any) -> List[str]:
    """Normalize a Change_Filter selection to canonical order, dropping unknowns.

    Returns the categories in ``CHANGE_CATEGORIES`` order with duplicates removed,
    so two selections carrying the same categories in a different order marshal to
    the same CLI arguments (Requirement 6.5).
    """
    if not isinstance(change_types, (list, tuple, set, frozenset)):
        return []
    selected = {value for value in change_types if isinstance(value, str)}
    return [category for category in CHANGE_CATEGORIES if category in selected]


class CloudHorusAPI:
    """
    Python API exposed to pywebview JavaScript via `window.pywebview.api`.
    Handles generation, file picking, auth monitoring, and output streaming.
    """

    def __init__(self, window: Optional[webview.Window] = None):
        self._window = window
        self._process: Optional[subprocess.Popen] = None
        self._output_queue: queue.Queue = queue.Queue()
        self._running = False
        self._last_auth_check: float = 0
        self._last_auth_data: Optional[Dict] = None
        self._generation_start_time: float = 0  # epoch when generation started

    def set_window(self, window: webview.Window):
        self._window = window

    def get_version(self) -> str:
        """Return the current CloudHorus version."""
        return APP_VERSION

    # ─── File Picker ──────────────────────────────────────────────────

    def pick_files(self, file_type: str) -> List[str]:
        """Open native file picker dialog.

        Args:
            file_type: 'bicep' for .bicep files, 'params' for .json files,
                'terraform-main' for .tf files, 'terraform-vars' for .tfvars files,
                'terraform-plan' for `terraform show -json` plan documents

        Returns:
            List of selected file paths
        """
        if not self._window:
            return []

        try:
            if file_type == "bicep":
                file_types = ("Bicep Files (*.bicep)", "All Files (*.*)")
            elif file_type == "terraform-main":
                file_types = ("Terraform Entry Files (*.tf)", "All Files (*.*)")
            elif file_type == "terraform-vars":
                file_types = ("Terraform Variable Files (*.tfvars)", "All Files (*.*)")
            elif file_type == "terraform-plan":
                # Plan JSON produced by `terraform show -json <planfile>` (Requirement 1.3)
                file_types = ("Terraform Plan JSON (*.json)", "All Files (*.*)")
            else:
                file_types = ("JSON Files (*.json)", "All Files (*.*)")

            result = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=file_types,
            )
            return list(result) if result else []
        except Exception as exc:
            print(f"[CloudHorus WebUI] File picker failed for {file_type}: {exc}", file=sys.stderr)
            traceback.print_exc()
            return []

    # ─── Bicep Metadata Parsing ──────────────────────────────────────

    def parse_params_metadata(self, file_paths: List[str]) -> Dict[str, Any]:
        """Parse _cloudHorus metadata from parameter files.

        Extracts tenant/subscription/resourceGroup from each parameter file
        and returns unique subscriptions with their metadata for per-subscription
        optimization controls in the UI.

        Args:
            file_paths: List of parameter file paths

        Returns:
            Dict with 'subscriptions' (ordered unique list of dicts with
            id, tenant, resourceGroups) and 'errors' (list of error strings)
        """
        return parse_scope_metadata_files(file_paths)

    def parse_scope_metadata(self, file_paths: List[str]) -> Dict[str, Any]:
        """Parse explicit scope metadata files for Terraform JSON inputs."""
        return parse_scope_metadata_files(file_paths)

    def discover_terraform_source_metadata(self, terraform_root_dirs: List[str]) -> Dict[str, Any]:
        """Auto-discover Terraform scope metadata files for selected root directories."""
        return discover_terraform_source_scope_metadata(terraform_root_dirs)

    # ─── Generation ──────────────────────────────────────────────────

    def start_generation(self, args_json: str) -> Dict[str, Any]:
        """Start the CloudHorus generation process.

        Args:
            args_json: JSON string of all configuration arguments

        Returns:
            Dict with 'success' bool and optional 'file' path
        """
        if self._running:
            return {"success": False, "error": "Already running"}

        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid args: {e}"}

        cmd = self._build_command(args)
        self._running = True

        # Reset auth state so stale prompts don't re-trigger the modal
        self._generation_start_time = time.time()
        self._last_auth_check = self._generation_start_time
        self._last_auth_data = None
        if os.path.exists(AUTH_FILE):
            try:
                os.remove(AUTH_FILE)
            except OSError:
                pass

        # Clear output queue
        while not self._output_queue.empty():
            try:
                self._output_queue.get_nowait()
            except queue.Empty:
                break

        try:
            # Build subprocess environment
            proc_env = {**os.environ, "PYTHONUNBUFFERED": "1"}

            # Pass Service Principal credentials as env vars (never in CLI args)
            sp = args.get("servicePrincipal")
            if args.get("authMethod") == "service-principal" and sp:
                proc_env["AZURE_CLIENT_ID"] = sp.get("clientId", "")
                proc_env["AZURE_TENANT_ID"] = sp.get("tenantId", "")
                if sp.get("secret"):
                    proc_env["AZURE_CLIENT_SECRET"] = sp["secret"]
                proc_env["CLOUDHORUS_AUTH_METHOD"] = "service-principal"
            elif args.get("authMethod") == "environment":
                proc_env["CLOUDHORUS_AUTH_METHOD"] = "environment"

            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=PROJECT_ROOT,
                env=proc_env,
            )

            # Stream output in a thread
            reader_thread = threading.Thread(target=self._read_output, daemon=True)
            reader_thread.start()

            # Wait for process to complete
            self._process.wait()
            reader_thread.join(timeout=5)

            if self._process.returncode == 0:
                generated = self._find_latest_output()
                self._running = False
                return {"success": True, "file": generated}
            else:
                self._running = False
                return {"success": False, "error": f"Process exited with code {self._process.returncode}"}

        except Exception as e:
            self._running = False
            return {"success": False, "error": str(e)}

    def rerun_with_change_types(self, args_json: str, change_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Re-run generation with a new Change_Filter selection.

        Used by the filter chips: the front end keeps the original argument payload
        and only swaps the selected Change_Categories, so a filtered re-run differs
        from the first run by `--changeTypes` alone (Requirement 6.9).

        Args:
            args_json: JSON string of the configuration arguments of the original run
            change_types: Change_Categories to display; unknown values are dropped

        Returns:
            Same shape as `start_generation`
        """
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Invalid args: {e}"}

        if not isinstance(args, dict):
            return {"success": False, "error": "Invalid args: expected a JSON object"}

        args["changeTypes"] = normalize_change_types(change_types)
        return self.start_generation(json.dumps(args))

    def stop_generation(self) -> bool:
        """Stop the running generation process."""
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._running = False
            return True
        return False

    def validate_service_principal(self, client_id: str, tenant_id: str, secret: str) -> Dict[str, Any]:
        """Validate Service Principal credentials by attempting a token acquisition."""
        try:
            from azure.identity import ClientSecretCredential

            if not secret:
                return {"valid": False, "error": "No client secret provided"}

            cred = ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=secret,
            )
            # Attempt to get a token for Azure management — this validates the credentials
            token = cred.get_token("https://management.azure.com/.default")
            if token and token.token:
                return {"valid": True}
            return {"valid": False, "error": "Token acquisition returned empty token"}
        except Exception as e:
            return {"valid": False, "error": str(e)}

    def get_output_lines(self) -> List[str]:
        """Get buffered output lines from the generation process."""
        lines = []
        while not self._output_queue.empty():
            try:
                lines.append(self._output_queue.get_nowait())
            except queue.Empty:
                break
        return lines

    def _read_output(self):
        """Read subprocess output using raw OS reads for zero buffering.

        By reading directly from the pipe's file descriptor with
        ``os.read()``, we bypass Python's ``BufferedReader`` and
        ``TextIOWrapper`` layers entirely.  This guarantees that output
        is surfaced **as soon as** the child process writes it, regardless
        of how large or small the write is.

        Both ``\\n`` and ``\\r`` are treated as line terminators so that
        tqdm progress bars (which use ``\\r``) appear in real time.
        """
        if not self._process or not self._process.stdout:
            return
        fd = self._process.stdout.fileno()
        buf = bytearray()
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:  # EOF
                break
            buf.extend(chunk)
            # Extract and enqueue every complete line
            for line in self._flush_lines(buf):
                self._output_queue.put(line)
        # Enqueue any trailing partial line
        if buf:
            line = buf.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                self._output_queue.put(line)
        try:
            self._process.stdout.close()
        except Exception:
            pass

    @staticmethod
    def _flush_lines(buf: bytearray) -> list:
        """Extract complete lines from *buf* and return them.

        Handles ``\\n``, ``\\r``, and ``\\r\\n`` as line terminators.
        *buf* is modified in-place — consumed bytes are removed.
        """
        lines = []
        while True:
            nl = buf.find(b"\n")
            cr = buf.find(b"\r")
            if nl < 0 and cr < 0:
                break
            # Determine the earliest terminator and how many bytes to skip
            if nl < 0:
                pos, skip = cr, 1
            elif cr < 0:
                pos, skip = nl, 1
            elif cr < nl:
                # \r\n counts as a single terminator
                pos, skip = (cr, 2) if nl == cr + 1 else (cr, 1)
            else:
                pos, skip = nl, 1
            line = buf[:pos].decode("utf-8", errors="replace")
            del buf[: pos + skip]
            if line:
                lines.append(line)
        return lines

    def _build_command(self, args: Dict[str, Any]) -> List[str]:
        """Build the CLI command from arguments dict."""
        python = sys.executable or "python3"
        cmd = [python, os.path.join("src", "main.py")]

        # Authentication method
        auth_method = args.get("authMethod", "device-code")
        if auth_method == "service-principal":
            cmd.extend(["--authMethod", "service-principal"])

        mode = args.get("mode", "live")
        if mode is None:
            # Detect mode from presence of local template inputs
            if args.get("terraformRootDirs") or args.get("terraformJsonFiles"):
                mode = "terraform"
            else:
                mode = "bicep" if args.get("bicepFiles") else "live"

        if mode == "live":
            # Live mode args
            tenants = args.get("tenants", "").strip()
            subs = args.get("subscriptions", "").strip()
            rgs = args.get("resourcegroups", "").strip()

            if tenants:
                cmd.extend(["--tenants"] + tenants.split())
            if subs:
                cmd.extend(["--subscriptions"] + subs.split())
            if rgs:
                cmd.extend(["--resourcegroups"] + rgs.split())

            discoverRgs = args.get("discoverResourceGroups", [])
            if discoverRgs and len(discoverRgs) > 0:
                cmd.extend(["--discoverResourceGroups"] + discoverRgs)
        elif mode == "terraform":
            # A Terraform run carries either a plan JSON or HCL source directories,
            # never both (Requirement 1.5). The plan branch is additive: without a
            # plan file the source marshalling below is byte-identical to before
            # this feature (Requirement 8.8).
            terraform_json_files = args.get("terraformJsonFiles", [])
            terraform_root_dirs = args.get("terraformRootDirs", [])
            terraform_var_files = args.get("terraformVarFiles", [])
            if terraform_json_files:
                cmd.extend(["--terraformJsonFiles"] + terraform_json_files)
                # `--changeTypes` only means something for plan JSON input, and only
                # a strict subset narrows the diagram: the full set is the CLI
                # default, so it stays off the command line (Requirement 8.3).
                change_types = normalize_change_types(args.get("changeTypes"))
                if 0 < len(change_types) < len(CHANGE_CATEGORIES):
                    cmd.extend(["--changeTypes"] + change_types)
            else:
                if terraform_root_dirs:
                    cmd.extend(["--terraformRootDirs"] + terraform_root_dirs)
                if terraform_var_files:
                    cmd.extend(["--terraformVarFiles"] + terraform_var_files)
        else:
            # Bicep mode args
            bicep_files = args.get("bicepFiles", [])
            param_files = args.get("parametersFiles", [])
            if bicep_files:
                cmd.extend(["--bicepFiles"] + bicep_files)
            if param_files:
                cmd.extend(["--parametersFiles"] + param_files)

        scope_metadata_files = args.get("scopeMetadataFiles", [])
        if scope_metadata_files:
            cmd.extend(["--scopeMetadataFiles"] + scope_metadata_files)

        # Layout parameters
        cmd.extend(["--edgeDirection", args.get("edgeDirection", "TB")])
        cmd.extend(["--tenantDirection", args.get("tenantDirection", "LR")])
        cmd.extend(["--maxSubnetPerline", str(args.get("maxSubnetPerline", 4))])
        cmd.extend(["--resourcesEdgeLength", str(args.get("resourcesEdgeLength", 1))])
        cmd.extend(["--rankDebug", "true" if args.get("rankDebug") else "false"])
        cmd.extend(
            ["--privateDnsZonesOptimization", "true" if args.get("privateDnsZonesOptimization", True) else "false"]
        )

        if args.get("exportDrawio"):
            cmd.extend(["--exportDrawio", "true"])

        # Per-subscription array parameters
        subnet_opt = args.get("subnetOptimization", [])
        pe_opt = args.get("peOptimization", [])
        cross_pe_opt = args.get("crossPeOptimization", [])
        rg_edge = args.get("resourceGroupsEdgeLengthListBySubscription", [])

        if subnet_opt:
            cmd.extend(["--subnetOptimization"] + ["true" if v else "false" for v in subnet_opt])
        if pe_opt:
            cmd.extend(["--peOptimization"] + ["true" if v else "false" for v in pe_opt])
        if cross_pe_opt:
            cmd.extend(["--crossPeOptimization"] + ["true" if v else "false" for v in cross_pe_opt])
        if rg_edge:
            cmd.extend(["--resourceGroupsEdgeLengthListBySubscription"] + [str(v) for v in rg_edge])

        return cmd

    def _find_latest_output(self) -> Optional[str]:
        """Find the most recently generated PNG file (now inside output folders)."""
        patterns = [
            os.path.join(PROJECT_ROOT, "azure_resources_*", "azure_resources_*.png"),
            os.path.join(PROJECT_ROOT, "azure_resources_*.png"),
            os.path.join(PROJECT_ROOT, "*.png"),
        ]
        latest = None
        latest_time = 0

        for pattern in patterns:
            for f in glob.glob(pattern):
                mtime = os.path.getmtime(f)
                if mtime > latest_time:
                    latest_time = mtime
                    latest = f

        # Only return if created recently (within last 5 minutes)
        if latest and (time.time() - latest_time) < 300:
            return latest
        return None

    # ─── Auth Monitoring ─────────────────────────────────────────────

    def check_auth_prompt(self) -> Optional[Dict[str, str]]:
        """Check for Azure authentication prompt file.

        Only returns data when:
        - Generation is actively running
        - The auth file was written AFTER generation started
        - The file has changed since the last check

        Returns:
            Dict with url, code, expires if auth is needed, None otherwise
        """
        # Only check while generation is actively running
        if not self._running:
            return None

        if not os.path.exists(AUTH_FILE):
            self._last_auth_data = None
            return None

        try:
            mtime = os.path.getmtime(AUTH_FILE)

            # Ignore files that existed before generation started
            if mtime < self._generation_start_time:
                return None

            # Only process if file changed since last check
            if mtime <= self._last_auth_check:
                return None

            self._last_auth_check = mtime

            with open(AUTH_FILE, "r") as f:
                content = f.read().strip()

            if not content:
                return None

            # Parse auth prompt: extract URL, code, expiry ISO timestamp
            data = {}
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("URL:"):
                    import re

                    urls = re.findall(r"https?://\S+", line)
                    if urls:
                        data["url"] = urls[0]
                elif line.startswith("CODE:"):
                    import re

                    codes = re.findall(r"\b[A-Z0-9]{6,12}\b", line)
                    if codes:
                        data["code"] = codes[0]
                elif line.startswith("EXPIRES_ON:"):
                    # Pass the ISO 8601 timestamp to the frontend for live countdown
                    data["expires_on"] = line.replace("EXPIRES_ON:", "").strip()

            if "url" in data and "code" in data:
                self._last_auth_data = data
                return data

        except Exception:
            pass

        return None

    # ─── File Operations ─────────────────────────────────────────────

    @staticmethod
    def _is_wsl() -> bool:
        """Detect if running inside Windows Subsystem for Linux."""
        try:
            with open("/proc/version", "r") as f:
                return "microsoft" in f.read().lower()
        except Exception:
            return False

    @staticmethod
    def _wsl_path(linux_path: str) -> str:
        """Convert a Linux path to a Windows path via wslpath."""
        try:
            result = subprocess.run(["wslpath", "-w", linux_path], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return linux_path

    def open_file(self, file_path: str) -> bool:
        """Open a file with the system default application."""
        try:
            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", file_path])
            elif self._is_wsl():
                win_path = self._wsl_path(os.path.abspath(file_path))
                subprocess.Popen(["explorer.exe", win_path])
            else:
                subprocess.Popen(["xdg-open", file_path])
            return True
        except Exception:
            return False

    def open_file_location(self, file_path: str) -> bool:
        """Open the folder containing a file, highlighting it if possible."""
        try:
            abs_path = os.path.abspath(file_path)
            folder = os.path.dirname(abs_path)
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", abs_path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", abs_path])
            elif self._is_wsl():
                win_folder = self._wsl_path(folder)
                subprocess.Popen(["explorer.exe", win_folder])
            else:
                subprocess.Popen(["xdg-open", folder])
            return True
        except Exception:
            return False

    def find_drawio_file(self, png_path: str) -> Optional[str]:
        """Given a generated PNG path, find the corresponding .drawio file."""
        try:
            base = os.path.splitext(png_path)[0]
            drawio_path = base + ".drawio"
            if os.path.exists(drawio_path):
                return drawio_path
            # Also check without extension suffix variations
            folder = os.path.dirname(png_path)
            basename = os.path.basename(base)
            for f in os.listdir(folder):
                if f.endswith(".drawio") and f.startswith(basename[:20]):
                    return os.path.join(folder, f)
        except Exception:
            pass
        return None

    def read_change_summary(self, png_path: str) -> Optional[Dict[str, Any]]:
        """Given a generated PNG path, read the Change_Summary sidecar beside it.

        The sidecar is `<diagram>.change-summary.json` in the output folder of the
        diagram (Requirement 7.5). It only exists for a Plan_Diff_Mode run, so a
        missing file is a normal Legacy_Mode outcome and returns `None` rather than
        an error. The payload feeds the filter chips and the undisplayed-changes
        badge.
        """
        suffix = _change_summary_suffix()
        try:
            base = os.path.splitext(png_path)[0]
            candidates = [base + suffix]
            # Also tolerate naming variations, like find_drawio_file does
            folder = os.path.dirname(png_path)
            basename = os.path.basename(base)
            if folder and os.path.isdir(folder):
                candidates.extend(
                    os.path.join(folder, f)
                    for f in sorted(os.listdir(folder))
                    if f.endswith(suffix) and f.startswith(basename[:20])
                )
            for candidate in candidates:
                if not os.path.exists(candidate):
                    continue
                with open(candidate, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            pass
        return None

    def get_image_base64(self, file_path: str) -> Optional[str]:
        """Read an image file and return as base64 data URL for display."""
        import base64

        try:
            with open(file_path, "rb") as f:
                data = f.read()
            ext = os.path.splitext(file_path)[1].lower()
            mime = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".svg": "image/svg+xml",
            }.get(ext, "image/png")
            b64 = base64.b64encode(data).decode("utf-8")
            return f"data:{mime};base64,{b64}"
        except Exception:
            return None


# ─── Application Entry Point ─────────────────────────────────────────


def main():
    # ── Windows taskbar icon fix ──────────────────────────────────────
    # By default, Windows groups the window under python.exe and shows
    # Python's icon in the taskbar.  Setting a custom AppUserModelID
    # tells Windows to treat this as a standalone app with its own icon.
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CloudHorus.AzureGuardian")
        except Exception:
            pass

    api_instance = CloudHorusAPI()

    # Create the pywebview window
    window = webview.create_window(
        title=f"CloudHorus v{APP_VERSION} — Azure Cloud Architecture Guardian",
        url=os.path.join(WEBUI_DIR, "index.html"),
        js_api=api_instance,
        width=1400,
        height=900,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
        background_color="#0a0c10",
    )

    api_instance.set_window(window)

    # Start pywebview — force Qt backend to avoid GTK probe warnings on WSL/Linux
    #   Windows: EdgeChromium (auto)
    #   macOS: WebKit (auto)
    #   Linux/WSL: Qt (forced, avoids 'gi' module not found warning)
    gui_backend = None
    if sys.platform.startswith("linux"):
        gui_backend = "qt"

    def _apply_icon():
        """Force-set the application icon via the native GUI toolkit.

        pywebview's ``icon`` parameter in ``start()`` doesn't always propagate
        to the window manager on every backend (especially Qt on Linux/WSL).
        This helper runs *after* the event-loop is up and patches the icon
        through the toolkit's own API so the taskbar / title-bar show the
        CloudHorus falcon instead of the default Python icon.
        """
        if not os.path.isfile(ICON_PATH):
            return
        try:
            if gui_backend == "qt":
                # Qt backend — set via QApplication.setWindowIcon + individual windows
                try:
                    from qtpy.QtGui import QIcon
                    from qtpy.QtWidgets import QApplication
                except ImportError:
                    try:
                        from PyQt5.QtGui import QIcon
                        from PyQt5.QtWidgets import QApplication
                    except ImportError:
                        from PyQt6.QtGui import QIcon
                        from PyQt6.QtWidgets import QApplication
                app = QApplication.instance()
                if app:
                    icon = QIcon(ICON_PATH)
                    app.setWindowIcon(icon)
                    # Also force-set on every top-level widget so WSLg / X11
                    # taskbar picks up the correct icon via _NET_WM_ICON.
                    for widget in app.topLevelWidgets():
                        widget.setWindowIcon(icon)
            elif sys.platform.startswith("win"):
                # Windows EdgeChromium fallback — explicitly push the icon
                # via Win32 SendMessage(WM_SETICON) in case the pywebview
                # ``icon`` parameter didn't propagate to the taskbar.
                _win32_force_icon()
            elif sys.platform == "darwin":
                pass  # macOS: handled natively by pywebview / .app bundle
        except Exception:
            pass  # Icon is cosmetic — never break startup

    def _win32_force_icon():
        """Set the window icon through Win32 API as a robust fallback.

        Enumerates all visible windows belonging to the current process
        and sends WM_SETICON to each.  Uses retries because the pywebview
        EdgeChromium window may not be ready the instant ``func`` fires.
        """
        try:
            import ctypes
            import ctypes.wintypes as wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            GW_OWNER = 4

            ico = os.path.normpath(ICON_PATH)
            hicon_big = user32.LoadImageW(0, ico, IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
            hicon_small = user32.LoadImageW(0, ico, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            if not hicon_big and not hicon_small:
                return  # .ico failed to load — nothing to do

            my_pid = kernel32.GetCurrentProcessId()

            # Callback type for EnumWindows
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def _set_icon_on_pid_windows():
                """Find all top-level visible windows owned by this PID and set icon."""
                found = []

                @WNDENUMPROC
                def _cb(hwnd, _lp):
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value != my_pid:
                        return True  # not our window, keep enumerating
                    # Only top-level windows that are visible or will become visible
                    if user32.GetWindow(hwnd, GW_OWNER) != 0:
                        return True  # owned popup, skip
                    found.append(hwnd)
                    return True

                user32.EnumWindows(_cb, 0)

                for hwnd in found:
                    if hicon_big:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
                    if hicon_small:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
                return len(found)

            # Retry up to 10 times (5 s total) to let the window appear
            for _ in range(10):
                if _set_icon_on_pid_windows() > 0:
                    return
                time.sleep(0.5)

        except Exception:
            pass

    webview.start(
        func=_apply_icon,
        debug=("--debug" in sys.argv),
        http_server=True,  # Enable local HTTP server for proper asset loading
        gui=gui_backend,
        icon=ICON_PATH,
    )


if __name__ == "__main__":
    main()
