"""Bicep Service for compiling and validating Bicep templates.

This module provides operations for interacting with Azure Bicep CLI,
including validation, compilation, and template building.
"""

import json
import os
import platform
import subprocess
import tempfile
from typing import Optional

from cloudhorus.services.base import BaseService


class BicepService(BaseService):
    """Service for Bicep CLI operations and template compilation.

    This service handles:
    - Bicep CLI validation and detection
    - Bicep file compilation to ARM templates
    - Template building with parameter files

    Attributes:
        az_command: The Azure CLI command to use (az or az.cmd on Windows)
    """

    def __init__(self):
        """Initialize the Bicep Service."""
        super().__init__()
        self.az_command = "az"
        self._cli_validated = False

    def validate(self) -> bool:
        """Validate that Azure CLI and Bicep are available.

        Returns:
            True if Azure CLI with Bicep is available, False otherwise
        """
        if self._cli_validated:
            return True

        try:
            is_windows = platform.system().lower() == "windows"
            az_commands = ["az", "az.cmd"] if is_windows else ["az"]
            az_working = False

            # Test Azure CLI commands
            for az_cmd in az_commands:
                try:
                    subprocess.run(
                        [az_cmd, "--version"],
                        capture_output=True,
                        text=True,
                        check=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=30,
                    )
                    az_working = True
                    self.az_command = az_cmd
                    break
                except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                    continue

            if not az_working:
                self.logger.error("Azure CLI not available. Please install Azure CLI.")
                return False

            # Check Bicep availability
            subprocess.run(
                [self.az_command, "bicep", "version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )

            self._cli_validated = True
            self.logger.info("BicepService validated successfully")
            return True

        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            self.logger.error(f"Azure CLI or Bicep not available: {e}")
            self.logger.error("Please install: 1) Azure CLI 2) az bicep install")
            return False

    def validate_bicep_file(self, bicep_file: str) -> bool:
        """Validate that a Bicep file exists and has correct extension.

        Args:
            bicep_file: Path to the Bicep file

        Returns:
            True if file is valid, False otherwise
        """
        if not os.path.exists(bicep_file):
            self.logger.error(f"Bicep file not found: {bicep_file}")
            return False

        if not bicep_file.lower().endswith(".bicep"):
            self.logger.error(f"Invalid Bicep file extension: {bicep_file}")
            return False

        return True

    def validate_parameters_file(self, parameters_file: str) -> bool:
        """Validate that a parameters file exists and contains valid JSON.

        Args:
            parameters_file: Path to the parameters file

        Returns:
            True if file is valid, False otherwise
        """
        if not os.path.exists(parameters_file):
            self.logger.error(f"Parameters file not found: {parameters_file}")
            return False

        if not parameters_file.lower().endswith(".json"):
            self.logger.error(f"Parameters file must be JSON: {parameters_file}")
            return False

        try:
            with open(parameters_file, "r", encoding="utf-8") as f:
                json.load(f)
            return True
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.logger.error(f"Invalid parameters file format: {e}")
            return False

    def compile_bicep_to_arm(self, bicep_file: str, output_file: Optional[str] = None) -> Optional[str]:
        """Compile a Bicep file to ARM template JSON.

        Args:
            bicep_file: Path to the Bicep file
            output_file: Optional path for output. If None, creates temp file

        Returns:
            Path to the compiled ARM template if successful, None otherwise

        Example:
            >>> service.compile_bicep_to_arm("main.bicep", "main.json")
            "main.json"
        """
        if not self.validate_bicep_file(bicep_file):
            return None

        if not self.validate():
            return None

        # Generate output path if not provided
        if output_file is None:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_file:
                output_file = temp_file.name

        try:
            cmd = [self.az_command, "bicep", "build", "--file", bicep_file, "--outfile", output_file]

            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace", timeout=300
            )

            self.logger.info(f"Successfully compiled Bicep to ARM: {output_file}")
            return output_file

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to compile Bicep: {e.stderr}")
            return None

    def is_modular_template(self, bicep_file: str) -> bool:
        """Check if a Bicep template uses modules.

        Args:
            bicep_file: Path to the Bicep file

        Returns:
            True if template contains module references, False otherwise
        """
        try:
            with open(bicep_file, "r", encoding="utf-8") as f:
                content = f.read()
                return "module " in content
        except Exception as e:
            self.logger.error(f"Error checking if template is modular: {e}")
            return False

    def build_bicep_template(
        self, bicep_file: str, parameters_file: str, output_file: Optional[str] = None
    ) -> Optional[str]:
        """Build a Bicep template with parameters to create ARM template.

        This method compiles the Bicep file and returns the path to
        the generated ARM template. For modular templates, the compilation
        will include nested deployments.

        Args:
            bicep_file: Path to the Bicep template file
            parameters_file: Path to the parameters file
            output_file: Optional path for output file

        Returns:
            Path to the generated ARM template if successful, None otherwise

        Example:
            >>> service.build_bicep_template(
            ...     "infrastructure.bicep",
            ...     "production.parameters.json",
            ...     "output.json"
            ... )
            "output.json"
        """
        # Validate inputs
        if not self.validate_bicep_file(bicep_file):
            return None

        if not self.validate_parameters_file(parameters_file):
            return None

        if not self.validate():
            return None

        # Generate output file path if not provided
        if output_file is None:
            bicep_base_name = os.path.splitext(os.path.basename(bicep_file))[0]
            output_file = f"{bicep_base_name}-built-template.json"

        # Check if modular and log it
        is_modular = self.is_modular_template(bicep_file)
        template_type = "modular" if is_modular else "single"
        self.logger.info(f"Building {template_type} Bicep template: {bicep_file}")

        # Compile the template
        result = self.compile_bicep_to_arm(bicep_file, output_file)

        if result:
            self.logger.info(f"Successfully built Bicep template: {output_file}")

        return result

    def get_bicep_version(self) -> Optional[str]:
        """Get the installed Bicep version.

        Returns:
            Version string if successful, None otherwise

        Example:
            >>> service.get_bicep_version()
            "0.24.24"
        """
        if not self.validate():
            return None

        try:
            result = subprocess.run(
                [self.az_command, "bicep", "version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )

            # Extract version from output
            output = result.stdout.strip()
            # Typically format: "Bicep CLI version 0.24.24 (abc123)"
            if "version" in output.lower():
                parts = output.split()
                for i, part in enumerate(parts):
                    if part.lower() == "version" and i + 1 < len(parts):
                        return parts[i + 1]

            return output

        except Exception as e:
            self.logger.error(f"Failed to get Bicep version: {e}")
            return None
