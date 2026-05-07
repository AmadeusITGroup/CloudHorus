#!/usr/bin/env python3
"""
Bicep Template Builder - Build Bicep files with parameters to generate ARM templates

This module provides functionality to build Bicep templates with parameters
to generate ARM template JSON files equivalent to export_resource_group_template output.
Uses Azure CLI for Bicep compilation and template operations.

Optimized for Python 3 with minimal logging for better performance.
"""

import json
import os
import re
import subprocess
import tempfile
import traceback
from typing import Any, Dict, List, Optional, Union

from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()

# Global template cache to persist across function calls
_TEMPLATE_CACHE: Dict[str, str] = {}


class BicepTemplateBuilder:
    """Class for building Bicep templates with parameters using Azure CLI or standalone Bicep CLI."""

    def __init__(self):
        """
        Initialize the Bicep template builder with default configurations.
        For Bicep mode, always use simplified default values.
        """
        self.logger = SingletonLogger().get_logger()
        # Simplified defaults for Bicep mode - no customization needed
        self.default_subscription_id = "bicep-subscription"
        self.default_tenant_id = "bicep-tenant"
        self.default_resource_group = "bicep-rg-1"
        # Use global template cache
        self.template_cache = _TEMPLATE_CACHE
        # Initialize Azure CLI command (will be set in validate_bicep_cli)
        self.az_command = "az"
        # Whether to use standalone bicep CLI instead of az bicep
        self.use_standalone_bicep = False
        self.bicep_command = None  # Path to standalone bicep binary

    def _detect_standalone_bicep(self) -> bool:
        """
        Detect if standalone Bicep CLI is available on the system.
        Checks common installation locations on Windows, Linux, and macOS.

        Returns:
            bool: True if standalone Bicep CLI is found and working
        """
        import platform
        import shutil

        is_windows = platform.system().lower() == "windows"

        # Candidates: PATH first, then known install locations
        candidates = []

        # Check PATH via shutil.which
        which_result = shutil.which("bicep")
        if which_result:
            candidates.append(which_result)

        if is_windows:
            # Azure CLI Bicep install location
            az_bicep_dir = os.path.join(os.environ.get("USERPROFILE", ""), ".azure", "bin")
            candidates.append(os.path.join(az_bicep_dir, "bicep.exe"))
            # Standalone install location
            local_bin = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Bicep")
            candidates.append(os.path.join(local_bin, "bicep.exe"))
            # CloudHorus bundled location
            candidates.append(
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "bicep.exe"
                )
            )
        else:
            candidates.extend(
                [
                    os.path.expanduser("~/.azure/bin/bicep"),
                    "/usr/local/bin/bicep",
                    os.path.expanduser("~/.local/bin/bicep"),
                ]
            )

        for candidate in candidates:
            if not candidate or not os.path.isfile(candidate):
                continue
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    check=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                )
                self.bicep_command = candidate
                self.use_standalone_bicep = True
                self.logger.info(f"Found standalone Bicep CLI: {candidate} ({result.stdout.strip()})")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired, OSError):
                continue

        return False

    def _build_bicep_build_command(self, bicep_file: str, outfile: str) -> list:
        """
        Build the command list for compiling a Bicep file to ARM JSON.
        Uses standalone bicep CLI if available, otherwise az bicep.

        Args:
            bicep_file: Path to the .bicep file
            outfile: Path for the output .json file

        Returns:
            list: Command tokens to pass to subprocess.run
        """
        if self.use_standalone_bicep and self.bicep_command:
            return [self.bicep_command, "build", bicep_file, "--outfile", outfile]
        else:
            return [self.az_command, "bicep", "build", "--file", bicep_file, "--outfile", outfile]

    def validate_bicep_cli(self) -> bool:
        """
        Validate that Bicep compilation is available.
        Tries (in order): standalone Bicep CLI, then Azure CLI + Bicep extension.
        Enhanced Windows compatibility with better error handling.

        Returns:
            bool: True if Bicep compilation is available, False otherwise
        """
        # Strategy 1: Try standalone Bicep CLI first (most reliable on Windows)
        if self._detect_standalone_bicep():
            self.logger.info("Using standalone Bicep CLI for compilation.")
            return True

        # Strategy 2: Try Azure CLI + Bicep extension
        try:
            import platform

            is_windows = platform.system().lower() == "windows"

            # On Windows, try both 'az' and 'az.cmd'
            az_commands = ["az", "az.cmd"] if is_windows else ["az"]
            az_working = False

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
                self.logger.error("Neither standalone Bicep CLI nor Azure CLI found.")
                self.logger.error(
                    "Install one of: 1) Bicep CLI (winget install Microsoft.Bicep) 2) Azure CLI + az bicep install"
                )
                return False

            # Check if Bicep is available using the working az command
            subprocess.run(
                [self.az_command, "bicep", "version"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.logger.info(f"Using Azure CLI ({self.az_command}) for Bicep compilation.")
            return True

        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
            # Strategy 3: Azure CLI exists but 'az bicep version' failed.
            # Try to find the bicep binary that az installs in ~/.azure/bin
            self.logger.warning(f"'az bicep version' failed: {e}. Searching for Bicep binary directly...")
            if self._detect_standalone_bicep():
                self.logger.info("Found Bicep binary in Azure CLI install directory.")
                return True

            self.logger.error("Bicep CLI not available. Tried: standalone bicep, az bicep.")
            self.logger.error("Fix: Run 'winget install Microsoft.Bicep' or 'az bicep install' and restart.")
            return False

    def validate_files(self, bicep_file: str, parameters_file: str) -> bool:
        """
        Validate that the Bicep and parameters files exist and are readable.

        Args:
            bicep_file: Path to the Bicep template file
            parameters_file: Path to the parameters file

        Returns:
            bool: True if both files are valid, False otherwise
        """
        # Check Bicep file
        if not os.path.exists(bicep_file):
            self.logger.error(f"Bicep file not found: {bicep_file}")
            return False

        if not bicep_file.lower().endswith(".bicep"):
            self.logger.error(f"Invalid Bicep file extension: {bicep_file}")
            return False

        # Check parameters file
        if not os.path.exists(parameters_file):
            self.logger.error(f"Parameters file not found: {parameters_file}")
            return False

        if not parameters_file.lower().endswith(".json"):
            self.logger.error(f"Parameters file must be JSON: {parameters_file}")
            return False

        # Validate parameters file is valid JSON
        try:
            with open(parameters_file, "r", encoding="utf-8") as f:
                json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.logger.error(f"Invalid parameters file format: {e}")
            return False

        return True

    def build_bicep_template(
        self, bicep_file: str, parameters_file: str, output_file: Optional[str] = None
    ) -> Optional[str]:
        """
        Build a Bicep template with parameters to generate an ARM template JSON.

        This method builds the Bicep file with the provided parameters to create
        an ARM template with all parameter values populated (equivalent to
        export_resource_group_template with 'SkipAllParameterization').

        For modular Bicep templates, this method will flatten nested module deployments
        into individual resources for better diagram generation.

        Args:
            bicep_file: Path to the Bicep template file
            parameters_file: Path to the parameters file
            output_file: Optional path for output file. If None, generates a temp file

        Returns:
            Optional[str]: Path to the generated ARM template file if successful, None otherwise
        """
        try:
            # Create cache key from absolute paths
            bicep_abs = os.path.abspath(bicep_file)
            params_abs = os.path.abspath(parameters_file)
            cache_key = f"{bicep_abs}|{params_abs}"

            # Check if template is already cached and file exists
            if cache_key in self.template_cache:
                cached_path: str = self.template_cache[cache_key]
                if os.path.exists(cached_path):
                    self.logger.info(f"Using cached template: {cached_path}")
                    return cached_path
                else:
                    # Remove stale cache entry
                    del self.template_cache[cache_key]

            # Validate files first
            if not self.validate_files(bicep_file, parameters_file):
                return None

            # Validate Azure CLI and Bicep are available
            if not self.validate_bicep_cli():
                return None

            # Generate output file path if not provided
            if output_file is None:
                bicep_base_name = os.path.splitext(os.path.basename(bicep_file))[0]
                output_file = f"{bicep_base_name}-built-template.json"

            # Check if this is a modular Bicep template
            if self._is_modular_template(bicep_file):
                self.logger.info("Building modular template...")
                result_path = self._build_modular_template(bicep_file, parameters_file, output_file)
            else:
                # Single file template processing
                result_path = self._build_single_template(bicep_file, parameters_file, output_file)

            # Cache the result if successful
            if result_path and os.path.exists(result_path):
                self.template_cache[cache_key] = result_path
                self.logger.info(f"Cached template build result: {cache_key} -> {result_path}")

            return result_path

        except Exception as e:
            self.logger.error(f"Unexpected error building Bicep template: {str(e)}")
            return None

    def _populate_template_parameters(self, arm_template_path: str, parameters_file: str) -> Optional[Dict[str, Any]]:
        """
        Populate ARM template parameters with actual values.

        This method processes the ARM template and parameter file to create a template
        with all parameter references resolved to their actual values, similar to
        what export_resource_group_template produces.

        Args:
            arm_template_path: Path to the ARM template JSON file
            parameters_file: Path to the parameters file

        Returns:
            Optional[Dict[str, Any]]: Populated template dictionary if successful, None otherwise
        """
        try:
            # Load the ARM template
            with open(arm_template_path, "r", encoding="utf-8") as f:
                template = json.load(f)

            # Store the template for use by other methods
            self.current_template = template

            # Load the parameters
            with open(parameters_file, "r", encoding="utf-8") as f:
                parameters_data = json.load(f)

            # Extract parameter values
            if "parameters" in parameters_data:
                param_values = {k: v.get("value", v) for k, v in parameters_data["parameters"].items()}
            else:
                param_values = parameters_data

            # Store parameter values for dynamic subnet name extraction
            self.current_param_values = param_values

            # Extract and resolve variables from the template
            variables = template.get("variables", {})
            resolved_variables = self._resolve_variables(variables, param_values)

            # Add resolved variables to param_values so they can be referenced as parameters
            # This handles cases where modular template flattening converts variables('x') to parameters('x')
            combined_param_values = param_values.copy()
            combined_param_values.update(resolved_variables)

            self.logger.info(f"Processing {len(param_values)} parameters and {len(resolved_variables)} variables")

            # Create a new template with parameters and variables resolved
            populated_template = self._resolve_template_parameters(template, combined_param_values, resolved_variables)

            # Remove the parameters and variables sections since we're providing values directly
            if "parameters" in populated_template:
                del populated_template["parameters"]
            if "variables" in populated_template:
                del populated_template["variables"]

            # Ensure the template has the expected structure
            populated_template.setdefault("$schema", template.get("$schema", ""))
            populated_template.setdefault("contentVersion", template.get("contentVersion", "1.0.0.0"))
            populated_template.setdefault("resources", template.get("resources", []))

            # Post-process subnet name references
            self.logger.info("Post-processing subnet references...")
            populated_template = self._post_process_subnet_references(populated_template)

            return populated_template

        except Exception as e:
            self.logger.error(f"Failed to populate template parameters: {str(e)}")
            return None

    def _resolve_variables(self, variables: Dict[str, Any], param_values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Resolve variables that may contain parameter references or other ARM functions.

        Variables may depend on parameters or other variables, so we need to resolve them
        in the correct order to handle dependencies.

        Args:
            variables: Dictionary of template variables
            param_values: Dictionary of parameter values

        Returns:
            Dict[str, Any]: Dictionary of resolved variables with actual values
        """
        resolved_variables: Dict[str, Any] = {}
        remaining_variables = variables.copy()
        max_iterations = len(variables) + 1  # Prevent infinite loops
        iteration = 0

        while remaining_variables and iteration < max_iterations:
            iteration += 1
            resolved_in_this_iteration = []

            for var_name, var_value in remaining_variables.items():
                try:
                    # Try to resolve this variable
                    if isinstance(var_value, str) and var_value.startswith("[") and var_value.endswith("]"):
                        # This is an ARM expression, resolve it
                        resolved_value = self._resolve_parameter_references(var_value, param_values, resolved_variables)
                        # If the resolved value still contains unresolved references, skip for now
                        if isinstance(resolved_value, str) and "[" in resolved_value and "]" in resolved_value:
                            continue
                        resolved_variables[var_name] = resolved_value
                    else:
                        # Simple value, no resolution needed
                        resolved_variables[var_name] = var_value

                    resolved_in_this_iteration.append(var_name)

                except Exception as e:
                    self.logger.warning(f"Failed to resolve variable '{var_name}': {e}")
                    # Keep the original value if resolution fails
                    resolved_variables[var_name] = var_value
                    resolved_in_this_iteration.append(var_name)

            # Remove resolved variables from remaining
            for var_name in resolved_in_this_iteration:
                remaining_variables.pop(var_name, None)

            # If no variables were resolved in this iteration, we may have circular dependencies
            if not resolved_in_this_iteration:
                self.logger.warning(
                    f"Could not resolve {len(remaining_variables)} variables due to circular dependencies or missing references"
                )
                # Add remaining variables with their original values
                resolved_variables.update(remaining_variables)
                break

        return resolved_variables

    def _resolve_template_parameters(
        self, template: Dict[str, Any], param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Recursively resolve parameter references in the template.

        Args:
            template: The ARM template dictionary
            param_values: Dictionary of parameter values
            variables: Dictionary of template variables

        Returns:
            Dict[str, Any]: Template with parameter references resolved
        """
        if variables is None:
            variables = {}

        if isinstance(template, dict):
            resolved = {}
            for key, value in template.items():
                resolved[key] = self._resolve_template_parameters(value, param_values, variables)
            return resolved
        elif isinstance(template, list):
            return [self._resolve_template_parameters(item, param_values, variables) for item in template]
        elif isinstance(template, str):
            # Handle ARM template parameter references like [parameters('paramName')]
            return self._resolve_parameter_references(template, param_values, variables)
        else:
            return template

    def _resolve_parameter_references(
        self, value: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Resolve ARM template parameter references in a string, including complex functions.

        This method handles various ARM template functions like:
        - [parameters('paramName')]
        - [resourceId('Microsoft.Web/serverfarms', parameters('appServicePlanName'))]
        - [concat('prefix-', parameters('name'), '-suffix')]
        - [variables('variableName')]
        - kv-take(replace(parameters('resourcePrefix'), '-', ''), 20)  [unbracketed expressions]
        - streplace(parameters('resourcePrefix'), '-', '')  [unbracketed expressions]

        Args:
            value: String that may contain parameter references and ARM functions
            param_values: Dictionary of parameter values
            variables: Dictionary of template variables

        Returns:
            Any: Resolved value (could be string, int, bool, etc.)
        """
        import re

        if variables is None:
            variables = {}

        if not isinstance(value, str):
            return value

        # Handle bracketed ARM template expressions [expression]
        if value.strip().startswith("[") and value.strip().endswith("]"):
            # Remove outer brackets for processing
            expression = value.strip()[1:-1]
            # Handle different ARM template functions
            result = self._evaluate_arm_expression(expression, param_values, variables)
            return result

        # Handle unbracketed ARM expressions that contain function calls
        # These occur when Bicep string interpolations compile to ARM functions
        elif self._contains_arm_functions(value):
            resolved_value = self._resolve_unbracketed_arm_expression(value, param_values, variables)
            return resolved_value

        # Regular string, return as-is
        else:
            return value

    def _contains_arm_functions(self, value: str) -> bool:
        """
        Check if a string contains ARM template functions (even if not bracketed).

        This method looks for ARM function patterns anywhere in the string,
        including within concatenated expressions like 'streplace(parameters(...))'

        Args:
            value: String to check

        Returns:
            bool: True if the string contains ARM function patterns
        """
        import re

        # ARM function patterns - look for functions anywhere in the string
        # We want to find functions even if they're part of concatenated expressions
        arm_function_patterns = [
            r"parameters\s*\(",
            r"variables\s*\(",
            r"resourceId\s*\(",
            r"reference\s*\(",  # Added explicit reference pattern
            r"concat\s*\(",
            r"format\s*\(",
            r"replace\s*\(",
            r"take\s*\(",
            r"toLower\s*\(",
            r"toUpper\s*\(",
            r"guid\s*\(",
            r"substring\s*\(",
            r"length\s*\(",
        ]

        for pattern in arm_function_patterns:
            if re.search(pattern, value):
                return True

        return False

    def _is_arm_expression(self, value: str) -> bool:
        """
        Dynamically detect if a string contains ARM template expressions or function calls.

        This method uses pattern recognition to identify ARM functions without maintaining
        a hardcoded list, making it adaptable to future ARM functions.

        ARM functions typically follow these patterns:
        1. functionName(arguments...) - function calls
        2. [expression] - bracketed expressions
        3. Nested parentheses for complex expressions

        Args:
            value: String to check

        Returns:
            bool: True if the string appears to contain ARM expressions
        """
        import re

        if not isinstance(value, str) or not value.strip():
            return False

        # Pattern 1: Check for bracketed ARM expressions [...]
        if value.strip().startswith("[") and value.strip().endswith("]"):
            return True

        # Pattern 2: Check for function call patterns - identifier followed by parentheses
        # This catches any function call: functionName(...)
        function_call_pattern = r"\b[a-zA-Z][a-zA-Z0-9_]*\s*\("
        if re.search(function_call_pattern, value):
            # Additional validation: ensure it's not just any random text with parentheses
            # Check for balanced parentheses and function-like structure
            if self._has_balanced_parentheses(value) and self._looks_like_function_call(value):
                return True

        # Pattern 3: Check for ARM-specific syntax patterns
        arm_syntax_patterns = [
            r"'\s*,\s*'",  # String parameters separated by commas: 'param1', 'param2'
            r"\(\s*'[^']*'\s*,",  # Function calls with quoted string parameters
            r"\)\s*\.\s*\w+",  # Property access after function calls
            r"{\d+}",  # Format string placeholders {0}, {1}, etc.
        ]

        for pattern in arm_syntax_patterns:
            if re.search(pattern, value):
                return True

        return False

    def _has_balanced_parentheses(self, value: str) -> bool:
        """
        Check if parentheses in the string are balanced.

        Args:
            value: String to check

        Returns:
            bool: True if parentheses are balanced
        """
        count = 0
        in_quotes = False

        for char in value:
            if char == "'" and (len(value) == 1 or value[value.index(char) - 1] != "\\"):
                in_quotes = not in_quotes
            elif not in_quotes:
                if char == "(":
                    count += 1
                elif char == ")":
                    count -= 1
                    if count < 0:
                        return False

        return count == 0

    def _looks_like_function_call(self, value: str) -> bool:
        """
        Check if the string structure looks like a function call.

        Args:
            value: String to check

        Returns:
            bool: True if it looks like a function call
        """
        import re

        # Look for patterns that suggest function calls:
        # 1. identifier(args)
        # 2. Complex nested calls
        # 3. Parameter-like structures

        indicators = [
            r"\w+\([^)]*\)",  # Simple function call
            r"'\w+[^']*'",  # Quoted parameters (common in ARM)
            r"\([^)]*,",  # Multiple parameters
            r"\)\s*,\s*\w",  # Function result used as parameter
        ]

        indicator_count = sum(1 for pattern in indicators if re.search(pattern, value))

        # If multiple indicators are present, it's likely a function call
        return indicator_count >= 2 or (indicator_count >= 1 and len(value) > 20)

    def _resolve_unbracketed_arm_expression(
        self, value: str, param_values: Dict[str, Any], variables: Dict[str, Any]
    ) -> str:
        """
        Resolve ARM expressions that aren't wrapped in brackets.

        These typically occur from Bicep string interpolations or concatenations that
        compile to ARM functions but aren't wrapped in [] in the final JSON.

        Examples:
        - "kv-take(replace(parameters('resourcePrefix'), '-', ''), 20)" -> "kv-myappdev"
        - "streplace(parameters('resourcePrefix'), '-', '')" -> "stmyappdev"
        - "stfuncreplace(parameters('resourcePrefix'), '-', '')" -> "stfuncmyappdev"
        - "acrreplace(parameters('resourcePrefix'), '-', '')" -> "acrmyappdev"

        Args:
            value: String containing unbracketed ARM expressions
            param_values: Dictionary of parameter values
            variables: Dictionary of template variables

        Returns:
            str: Resolved string with ARM expressions evaluated
        """
        import re

        result = value
        max_iterations = 5  # Prevent infinite loops

        for iteration in range(max_iterations):
            original_result = result

            # Single pattern to handle both standalone and concatenated ARM functions
            # This looks for ARM function calls, optionally preceded by a prefix
            pattern = r"([a-zA-Z0-9]*)(parameters|variables|resourceId|concat|format|replace|take|toLower|toUpper|guid|substring|length)\s*\([^()]*(?:\([^()]*\)[^()]*)*\)"

            def replace_function(match):
                prefix = match.group(1)  # Could be empty for standalone functions
                function_part = match.group(0)[len(prefix) :]  # The actual ARM function call

                # Only process if this looks like an ARM function (not preceded by letters in the original value)
                # Check if the function starts at the beginning or is preceded by non-letter characters
                match_start = match.start()
                if match_start > 0:
                    char_before = result[match_start - 1]
                    # If there's a letter before the match that's not part of our prefix, skip
                    if char_before.isalpha() and not prefix:
                        return match.group(0)  # Don't process this match

                try:
                    # Evaluate the ARM function
                    evaluated = self._evaluate_arm_expression(function_part, param_values, variables)

                    # Remove brackets if present (for string concatenation context)
                    if isinstance(evaluated, str) and evaluated.startswith("[") and evaluated.endswith("]"):
                        evaluated = evaluated[1:-1]

                    # Combine prefix with evaluated result
                    final_result = prefix + str(evaluated)
                    return final_result

                except Exception as e:
                    self.logger.warning(f"Failed to evaluate ARM function '{function_part}': {e}")
                    return match.group(0)  # Return original on error

            # Apply the replacement
            result = re.sub(pattern, replace_function, result)

            # If no changes were made, we're done
            if result == original_result:
                break

        return result

    def _evaluate_arm_expression(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Evaluate ARM template expressions and functions.

        Args:
            expression: ARM template expression without outer brackets
            param_values: Dictionary of parameter values
            variables: Dictionary of template variables

        Returns:
            Any: Evaluated result
        """
        import re

        if variables is None:
            variables = {}

        # Remove extra whitespace
        expression = expression.strip()

        # Handle parameters() function
        if expression.startswith("parameters("):
            param_match = re.match(r"parameters\('([^']+)'\)", expression)
            if param_match:
                param_name = param_match.group(1)
                if param_name in param_values:
                    return param_values[param_name]
                else:
                    self.logger.warning(f"Parameter '{param_name}' not found in parameters file")
                    return f"[{expression}]"  # Return original if not found

        # Handle resourceId() function
        elif expression.startswith("resourceId("):
            return self._evaluate_resource_id(expression, param_values, variables)

        # Handle concat() function
        elif expression.startswith("concat("):
            return self._evaluate_concat(expression, param_values, variables)

        # Handle format() function
        elif expression.startswith("format("):
            return self._evaluate_format(expression, param_values, variables)

        # Handle replace() function
        elif expression.startswith("replace("):
            return self._evaluate_replace(expression, param_values, variables)

        # Handle take() function
        elif expression.startswith("take("):
            return self._evaluate_take(expression, param_values, variables)

        # Handle toLower() function
        elif expression.startswith("toLower("):
            return self._evaluate_to_lower(expression, param_values, variables)

        # Handle toUpper() function
        elif expression.startswith("toUpper("):
            return self._evaluate_to_upper(expression, param_values, variables)

        # Handle reference() function and its property access patterns
        elif expression.startswith("reference(") or "reference(" in expression:
            return self._evaluate_reference_with_properties(expression, param_values, variables)

        # Handle listKeys() function
        elif expression.startswith("listKeys("):
            return self._evaluate_list_keys(expression, param_values, variables)

        # Handle guid() function
        elif expression.startswith("guid("):
            return self._evaluate_guid(expression, param_values, variables)

        # Handle subscription() function
        elif expression.startswith("subscription("):
            return self._evaluate_subscription(expression, param_values, variables)

        # Handle environment() function
        elif expression.startswith("environment("):
            return self._evaluate_environment(expression, param_values, variables)

        # Handle resourceId() function
        elif expression.startswith("resourceId("):
            return self._evaluate_resource_id(expression, param_values, variables)

        # Handle subnet resourceId patterns (special case for subnet references) - place after specific function handlers
        elif "resourceId(" in expression and "/subnets/" in expression:
            return self._evaluate_subnet_resource_id(expression, param_values, variables)

        # Handle variables() function
        elif expression.startswith("variables("):
            var_match = re.match(r"variables\('([^']+)'\)", expression)
            if var_match:
                var_name = var_match.group(1)
                if var_name in variables:
                    # Recursively resolve variable value
                    var_value = variables[var_name]
                    if isinstance(var_value, str) and var_value.startswith("[") and var_value.endswith("]"):
                        return self._resolve_parameter_references(var_value, param_values, variables)
                    else:
                        return var_value
                else:
                    self.logger.warning(f"Variable '{var_name}' not found in template variables")
                    return f"[{expression}]"
            else:
                return f"[{expression}]"

        # Handle resourceGroup() function
        elif expression.startswith("resourceGroup()"):
            # For now, keep resourceGroup references as-is
            # In a full implementation, you'd resolve these based on target resource group
            return f"[{expression}]"

        # Handle subscription() function
        elif expression.startswith("subscription()"):
            # Keep subscription references as-is
            return f"[{expression}]"

        # Handle other common functions that might contain parameters
        else:
            # Check for subnet resourceId patterns first
            if "resourceId(" in expression and "/subnets/" in expression:
                return self._evaluate_subnet_resource_id(expression, param_values, variables)

            # Dynamic function handling for unknown functions
            function_match = re.match(r"([a-zA-Z][a-zA-Z0-9_]*)\s*\((.*)\)", expression)
            if function_match:
                function_name = function_match.group(1)
                args_str = function_match.group(2)

                # Try to resolve arguments dynamically
                if args_str.strip():
                    try:
                        args = self._parse_function_arguments(args_str)
                        resolved_args = []

                        for arg in args:
                            resolved_value = self._resolve_function_argument(arg, param_values, variables)
                            resolved_args.append(resolved_value)

                        # For unknown functions, return in ARM format but with resolved arguments
                        resolved_args_str = "', '".join(resolved_args)
                        result = f"[{function_name}('{resolved_args_str}')]"
                        self.logger.info(f"Dynamically processed unknown function {function_name} -> {result}")
                        return result

                    except Exception as e:
                        self.logger.warning(f"Failed to process unknown function {function_name}: {e}")
                        return f"[{expression}]"
                else:
                    # Function with no arguments
                    return f"[{function_name}()]"

            # Try to find and replace any nested parameters() and variables() calls
            param_pattern = r"parameters\('([^']+)'\)"
            var_pattern = r"variables\('([^']+)'\)"

            def replace_nested_param(match):
                param_name = match.group(1)
                if param_name in param_values:
                    param_value = param_values[param_name]
                    # If it's a string, wrap in quotes for the ARM expression
                    if isinstance(param_value, str):
                        return f"'{param_value}'"
                    else:
                        return str(param_value)
                else:
                    self.logger.warning(f"Parameter '{param_name}' not found in parameters file")
                    return match.group(0)  # Keep original if not found

            def replace_nested_var(match):
                var_name = match.group(1)
                if var_name in variables:
                    var_value = variables[var_name]
                    # If it's a string, wrap in quotes for the ARM expression
                    if isinstance(var_value, str):
                        return f"'{var_value}'"
                    else:
                        return str(var_value)
                else:
                    self.logger.warning(f"Variable '{var_name}' not found in template variables")
                    return match.group(0)  # Keep original if not found

            # Replace nested parameter and variable references
            resolved_expression = re.sub(param_pattern, replace_nested_param, expression)
            resolved_expression = re.sub(var_pattern, replace_nested_var, resolved_expression)

            # Check if the expression was fully resolved (no more brackets)
            if "[" not in resolved_expression and "]" not in resolved_expression:
                # Try to evaluate as a simple expression if possible
                return resolved_expression
            else:
                return f"[{resolved_expression}]"

    def _parse_function_arguments(self, args_str: str) -> list:
        """
        Parse function arguments from a string, handling nested functions and proper quoting.

        This method properly handles:
        - String literals with single quotes
        - Nested function calls
        - Comma separation while respecting parentheses and quotes

        Args:
            args_str: String containing function arguments

        Returns:
            list: List of parsed arguments
        """
        args = []
        current_arg = ""
        paren_count = 0
        quote_count = 0
        i = 0

        while i < len(args_str):
            char = args_str[i]

            if char == "'" and paren_count == 0:
                quote_count = (quote_count + 1) % 2
                current_arg += char
            elif char == "(" and quote_count == 0:
                paren_count += 1
                current_arg += char
            elif char == ")" and quote_count == 0:
                paren_count -= 1
                current_arg += char
            elif char == "," and paren_count == 0 and quote_count == 0:
                args.append(current_arg.strip())
                current_arg = ""
                i += 1
                continue
            else:
                current_arg += char

            i += 1

        if current_arg.strip():
            args.append(current_arg.strip())

        return args

    def _resolve_function_argument(
        self, arg: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Resolve a single function argument, handling parameters, variables, and literals.

        Args:
            arg: The argument to resolve
            param_values: Dictionary of parameter values
            variables: Dictionary of template variables

        Returns:
            str: Resolved argument value
        """
        import re

        if variables is None:
            variables = {}

        arg = arg.strip()

        # Handle string literals
        if arg.startswith("'") and arg.endswith("'"):
            return arg[1:-1]

        # Handle parameter references
        elif arg.startswith("parameters("):
            param_match = re.match(r"parameters\('([^']+)'\)", arg)
            if param_match:
                param_name = param_match.group(1)
                if param_name in param_values:
                    return str(param_values[param_name])
                else:
                    self.logger.warning(f"Parameter '{param_name}' not found in parameters file")
                    return f"[{arg}]"
            else:
                return f"[{arg}]"

        # Handle variable references
        elif arg.startswith("variables("):
            var_match = re.match(r"variables\('([^']+)'\)", arg)
            if var_match:
                var_name = var_match.group(1)
                if var_name in variables:
                    var_value = variables[var_name]
                    return str(var_value)
                else:
                    self.logger.warning(f"Variable '{var_name}' not found in template variables")
                    return f"[{arg}]"
            else:
                return f"[{arg}]"

        # Handle nested function calls (evaluate recursively)
        elif self._is_arm_expression(arg):
            # This is a nested ARM expression, evaluate it
            nested_result = self._evaluate_arm_expression(arg, param_values, variables)
            # Remove brackets if they were added
            if isinstance(nested_result, str) and nested_result.startswith("[") and nested_result.endswith("]"):
                return nested_result[1:-1]
            return str(nested_result)

        # Handle subnet resourceId patterns
        elif "resourceId(" in arg and "/subnets/" in arg:
            # This is a subnet resourceId pattern, evaluate it
            nested_result = self._evaluate_subnet_resource_id(arg, param_values, variables)
            # Remove brackets if they were added
            if isinstance(nested_result, str) and nested_result.startswith("[") and nested_result.endswith("]"):
                return nested_result[1:-1]
            return str(nested_result)

        else:
            # Handle direct values or unknown expressions
            return str(arg)

    def _evaluate_resource_id(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate resourceId() ARM template function.

        Examples:
        - resourceId('Microsoft.Web/serverfarms', parameters('appServicePlanName'))
        - resourceId('Microsoft.Storage/storageAccounts', parameters('storageAccountName'))
        - resourceId('microsoft.insights/components', 'appi-we-tst-fdm-mon-iqtrdv')
        """
        import re

        if variables is None:
            variables = {}

        # Extract arguments from resourceId(arg1, arg2, ...)
        match = re.match(r"resourceId\((.*)\)", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)
        args = self._parse_function_arguments(args_str)

        # Process each argument using the helper method
        resolved_args = []
        for arg in args:
            resolved_value = self._resolve_function_argument(arg, param_values, variables)
            resolved_args.append(resolved_value)

        # Return the resourceId in the format "[resourceId('resourceType', 'resourceName')]"
        if len(resolved_args) >= 2:
            resource_type = resolved_args[0]
            resource_names = resolved_args[1:]
            resource_names_str = "', '".join(resource_names)
            return f"[resourceId('{resource_type}', '{resource_names_str}')]"
        else:
            return f"[{expression}]"

    def _evaluate_subnet_resource_id(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate subnet resourceId patterns that use the format:
        resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))/subnets/SubnetName

        Convert to proper ARM resourceId function:
        [resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-name', 'subnet-name')]

        Examples:
        - "resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))/subnets/PrivateEndpointSubnet"
        - "resourceId('Microsoft.Network/virtualNetworks', parameters('vnetName'))/subnets/default"
        - "resourceId('Microsoft.Network/virtualNetworks', 'vnet-name')/subnets/subnet-name"
        """
        import re

        if variables is None:
            variables = {}

        # Multiple patterns to handle different subnet resourceId formats
        patterns = [
            # Pattern 1: Simple pattern using non-greedy match for the VNet reference
            r"resourceId\('Microsoft\.Network/virtualNetworks',\s*(.+?)\)/subnets/(\w+)",
            # Pattern 2: More specific pattern that handles nested parentheses in function calls
            r"resourceId\('Microsoft\.Network/virtualNetworks',\s*([^,]+(?:\([^)]*\))?[^,]*)\)/subnets/(\w+)",
            # Pattern 3: Handle case with flexible spacing
            r"resourceId\(\s*'Microsoft\.Network/virtualNetworks'\s*,\s*(.+?)\s*\)\s*/subnets/(\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, expression)
            if match:
                vnet_ref = match.group(1).strip()
                subnet_name = match.group(2).strip()

                # Resolve the vnet reference
                vnet_name = self._resolve_function_argument(vnet_ref, param_values, variables)

                # Remove any surrounding quotes if they exist
                if vnet_name.startswith("'") and vnet_name.endswith("'"):
                    vnet_name = vnet_name[1:-1]

                # Create proper subnet resourceId
                result = f"[resourceId('Microsoft.Network/virtualNetworks/subnets', '{vnet_name}', '{subnet_name}')]"

                self.logger.info(f"Converted subnet reference: {expression} -> {result}")
                return result

        # If no patterns match, try to handle it as a general case
        # Look for any resourceId followed by /subnets/
        general_pattern = r"(resourceId\([^)]+\))/subnets/(\w+)"
        match = re.search(general_pattern, expression)
        if match:
            resource_id_part = match.group(1)
            subnet_name = match.group(2)

            # Try to evaluate the resourceId part
            try:
                resolved_resource_id = self._evaluate_arm_expression(resource_id_part, param_values, variables)
                if (
                    isinstance(resolved_resource_id, str)
                    and resolved_resource_id.startswith("[")
                    and resolved_resource_id.endswith("]")
                ):
                    resolved_resource_id = resolved_resource_id[1:-1]

                # Extract vnet name from the resolved resourceId
                vnet_name_match = re.search(
                    r"resourceId\('Microsoft\.Network/virtualNetworks',\s*'([^']+)'", resolved_resource_id
                )
                if vnet_name_match:
                    vnet_name = vnet_name_match.group(1)
                    result = (
                        f"[resourceId('Microsoft.Network/virtualNetworks/subnets', '{vnet_name}', '{subnet_name}')]"
                    )
                    self.logger.info(f"Converted subnet reference (general): {expression} -> {result}")
                    return result
            except Exception as e:
                self.logger.warning(f"Failed to parse general subnet pattern: {e}")

        # If no match found, return as-is with brackets
        self.logger.warning(f"Could not parse subnet resourceId pattern: {expression}")
        return f"[{expression}]"

    def _evaluate_concat(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate concat() ARM template function.

        Example: concat('prefix-', parameters('name'), '-suffix')
        """
        import re

        if variables is None:
            variables = {}

        # Extract arguments from concat(arg1, arg2, ...)
        match = re.match(r"concat\((.*)\)", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)
        args = self._parse_function_arguments(args_str)

        # Process and concatenate arguments using the helper method
        result_parts = []
        for arg in args:
            resolved_value = self._resolve_function_argument(arg, param_values, variables)
            result_parts.append(resolved_value)

        return "".join(result_parts)

    def _evaluate_format(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate format() ARM template function.

        Examples:
        - format('{0}-webapp', 'teststrg001') -> 'teststrg001-webapp'
        - format('{0}-{1}', parameters('storageAccountName'), 'webapp') -> 'teststrg001-webapp'
        - format('prefix-{0}-{1}-suffix', parameters('name'), variables('env')) -> 'prefix-myapp-prod-suffix'
        """
        import re

        if variables is None:
            variables = {}

        # Extract arguments from format(formatString, arg1, arg2, ...)
        match = re.match(r"format\((.*)\)", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)

        # Split arguments (simplified parser)
        args = []
        current_arg = ""
        paren_count = 0
        quote_count = 0

        for char in args_str:
            if char == "'" and paren_count == 0:
                quote_count = (quote_count + 1) % 2
            elif char == "(" and quote_count == 0:
                paren_count += 1
            elif char == ")" and quote_count == 0:
                paren_count -= 1
            elif char == "," and paren_count == 0 and quote_count == 0:
                args.append(current_arg.strip())
                current_arg = ""
                continue

            current_arg += char

        if current_arg.strip():
            args.append(current_arg.strip())

        if len(args) < 1:
            return f"[{expression}]"

        # First argument is the format string
        format_string_arg = args[0].strip()

        # Remove quotes from format string
        if format_string_arg.startswith("'") and format_string_arg.endswith("'"):
            format_string = format_string_arg[1:-1]
        else:
            format_string = format_string_arg

        # Process remaining arguments
        format_args = []
        for i, arg in enumerate(args[1:], 0):
            arg = arg.strip()

            # Handle string literals
            if arg.startswith("'") and arg.endswith("'"):
                format_args.append(arg[1:-1])
            # Handle parameter references
            elif arg.startswith("parameters("):
                param_match = re.match(r"parameters\('([^']+)'\)", arg)
                if param_match:
                    param_name = param_match.group(1)
                    if param_name in param_values:
                        format_args.append(str(param_values[param_name]))
                    else:
                        self.logger.warning(f"Parameter '{param_name}' not found in parameters file")
                        format_args.append(f"[{arg}]")
                else:
                    format_args.append(f"[{arg}]")
            # Handle variable references
            elif arg.startswith("variables("):
                var_match = re.match(r"variables\('([^']+)'\)", arg)
                if var_match:
                    var_name = var_match.group(1)
                    if var_name in variables:
                        var_value = variables[var_name]
                        if isinstance(var_value, str) and var_value.startswith("[") and var_value.endswith("]"):
                            resolved_value = self._resolve_parameter_references(var_value, param_values, variables)
                            format_args.append(str(resolved_value))
                        else:
                            format_args.append(str(var_value))
                    else:
                        self.logger.warning(f"Variable '{var_name}' not found in template variables")
                        format_args.append(f"[{arg}]")
                else:
                    format_args.append(f"[{arg}]")
            else:
                # Handle other ARM expressions or function calls recursively
                if isinstance(arg, str) and self._is_arm_expression(arg):
                    try:
                        # This is an ARM expression that needs evaluation
                        resolved_arg = self._evaluate_arm_expression(arg, param_values, variables)
                        format_args.append(str(resolved_arg))
                    except Exception as e:
                        self.logger.warning(f"Failed to evaluate nested expression in format: {arg}, error: {e}")
                        format_args.append(f"[{arg}]")
                else:
                    # Handle direct values
                    format_args.append(str(arg))

        # Apply format string with arguments
        try:
            # Check if this is a subnet format pattern
            if "/subnets/" in format_string and len(format_args) >= 1:
                subnet_result = self._handle_subnet_format_pattern(format_string, format_args, param_values, variables)
                if subnet_result:
                    return subnet_result

            # Replace ARM template format placeholders {0}, {1}, etc. with Python format placeholders
            # Handle numbered placeholders like {0}, {1}, {2}
            result = format_string
            for i, arg_value in enumerate(format_args):
                placeholder = f"{{{i}}}"
                result = result.replace(placeholder, str(arg_value))

            return result

        except Exception as e:
            self.logger.warning(f"Failed to format string '{format_string}' with args {format_args}: {e}")
            return f"[{expression}]"

    def _handle_subnet_format_pattern(
        self, format_string: str, format_args: list, param_values: Dict[str, Any], variables: Dict[str, Any]
    ) -> Optional[str]:
        """
        Handle subnet format patterns like:
        format('{0}/subnets/WebAppSubnet', resourceId('Microsoft.Network/virtualNetworks', variables('vnetName')))

        Convert to:
        [resourceId('Microsoft.Network/virtualNetworks/subnets', 'vnet-name', 'subnet-name')]
        """
        import re

        # Check if the format string matches subnet patterns
        subnet_patterns = [
            r"^\{0\}/subnets/(\w+)$",  # {0}/subnets/SubnetName
            r"^\{(\d+)\}/subnets/(\w+)$",  # {n}/subnets/SubnetName
            r"^\{0\}/subnets/\{1\}$",  # {0}/subnets/{1}
            r"^\{(\d+)\}/subnets/\{(\d+)\}$",  # {n}/subnets/{m}
        ]

        subnet_name = None
        format_arg_index = 0
        subnet_arg_index = None

        for pattern in subnet_patterns:
            match = re.match(pattern, format_string)
            if match:
                groups = match.groups()
                if len(groups) == 1:
                    # Pattern like {0}/subnets/SubnetName
                    subnet_name = groups[0]
                    format_arg_index = 0
                elif len(groups) == 2:
                    if pattern.endswith(r"(\w+)$"):
                        # Pattern like {n}/subnets/SubnetName
                        format_arg_index = int(groups[0])
                        subnet_name = groups[1]
                    else:
                        # Pattern like {n}/subnets/{m}
                        format_arg_index = int(groups[0])
                        subnet_arg_index = int(groups[1])
                elif len(groups) == 0 and "{1}" in format_string:
                    # Pattern like {0}/subnets/{1}
                    format_arg_index = 0
                    subnet_arg_index = 1
                break

        # Check if we have valid arguments
        max_required_index = max(format_arg_index, subnet_arg_index or 0)
        if max_required_index >= len(format_args):
            return None

        # Get subnet name from argument or pattern
        if subnet_name is None and subnet_arg_index is not None:
            # Subnet name comes from an argument
            subnet_name_arg = format_args[subnet_arg_index]
            subnet_name = self._resolve_function_argument(subnet_name_arg, param_values, variables)

        if subnet_name is None:
            return None

        # Get the vnet resourceId argument
        vnet_resource_arg = format_args[format_arg_index]

        # Try to resolve the vnet resourceId to get the vnet name
        vnet_name = self._extract_vnet_name_from_resource_id(vnet_resource_arg, param_values, variables)

        if vnet_name:
            result = f"[resourceId('Microsoft.Network/virtualNetworks/subnets', '{vnet_name}', '{subnet_name}')]"
            self.logger.info(f"Converted subnet format pattern to: {result}")
            return result
        else:
            self.logger.warning(f"Could not resolve VNet name from resourceId: {vnet_resource_arg}")
            return None

    def _extract_vnet_name_from_resource_id(
        self, resource_id_arg: str, param_values: Dict[str, Any], variables: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract VNet name from a resourceId argument.

        Examples:
        - "resourceId('Microsoft.Network/virtualNetworks', variables('vnetName'))" -> resolve vnetName
        - "resourceId('Microsoft.Network/virtualNetworks', 'vnet-name')" -> 'vnet-name'
        """
        import re

        # Check if it's a resourceId function call (without brackets)
        if resource_id_arg.startswith("resourceId("):
            # Extract the VNet name argument from resourceId
            match = re.match(r"resourceId\('Microsoft\.Network/virtualNetworks',\s*'([^']+)'\)", resource_id_arg)
            if match:
                return match.group(1)

            # Also try to match with variables() call
            match = re.match(
                r"resourceId\('Microsoft\.Network/virtualNetworks',\s*variables\('([^']+)'\)\)", resource_id_arg
            )
            if match:
                var_name = match.group(1)
                if var_name in variables:
                    return str(variables[var_name])

        # If it's already a resolved resourceId string, try to extract from it
        elif resource_id_arg.startswith("[resourceId("):
            match = re.search(r"resourceId\('Microsoft\.Network/virtualNetworks',\s*'([^']+)'", resource_id_arg)
            if match:
                return match.group(1)

        # If we can't parse it, return the original
        self.logger.warning(f"Could not extract VNet name from resourceId: {resource_id_arg}")
        return None

    def _evaluate_replace(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate replace() ARM template function.

        Examples:
        - replace('Hello World', 'World', 'Azure') -> 'Hello Azure'
        - replace(parameters('resourceName'), 'old', 'new') -> 'newResourceName' (if resourceName = 'oldResourceName')
        - replace(variables('baseName'), '-test', '-prod') -> 'myapp-prod' (if baseName = 'myapp-test')
        """
        import re

        if variables is None:
            variables = {}

        # Extract arguments from replace(sourceString, searchString, replaceString)
        match = re.match(r"replace\((.*)\)", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)
        args = self._parse_function_arguments(args_str)

        if len(args) != 3:
            self.logger.warning(f"replace() function requires exactly 3 arguments, got {len(args)}")
            return f"[{expression}]"

        # Process arguments using the helper method
        resolved_args = []
        for arg in args:
            resolved_value = self._resolve_function_argument(arg, param_values, variables)
            resolved_args.append(resolved_value)

        # Apply replace operation
        try:
            source_string, search_string, replace_string = resolved_args
            result = source_string.replace(search_string, replace_string)
            return result

        except Exception as e:
            self.logger.warning(f"Failed to apply replace operation: {e}")
            return f"[{expression}]"

    def _evaluate_take(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate take() ARM template function.

        Examples:
        - take('Hello World', 5) -> 'Hello'
        - take(parameters('resourceName'), 10) -> 'MyResource' (if resourceName = 'MyResourceName')
        - take('myapp-dev', 20) -> 'myapp-dev' (string shorter than count)
        """
        import re

        if variables is None:
            variables = {}

        # Extract arguments from take(sourceString, count)
        match = re.match(r"take\((.*)\)", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)
        args = self._parse_function_arguments(args_str)

        if len(args) != 2:
            self.logger.warning(f"take() function requires exactly 2 arguments, got {len(args)}")
            return f"[{expression}]"

        # Process arguments using the helper method
        resolved_args = []
        for arg in args:
            resolved_value = self._resolve_function_argument(arg, param_values, variables)
            resolved_args.append(resolved_value)

        # Apply take operation
        try:
            source_string, count_str = resolved_args
            count = int(count_str)
            result = source_string[:count]
            return result

        except (ValueError, TypeError) as e:
            self.logger.warning(f"Failed to apply take operation: {e}")
            return f"[{expression}]"

    def _evaluate_to_lower(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate toLower() ARM template function.

        Examples:
        - toLower('Hello World') -> 'hello world'
        - toLower(parameters('resourceName')) -> 'myresource' (if resourceName = 'MyResource')
        """
        import re

        if variables is None:
            variables = {}

        # Extract argument from toLower(string)
        match = re.match(r"toLower\((.*)\)", expression)
        if not match:
            return f"[{expression}]"

        arg = match.group(1).strip()

        # Handle string literals
        if arg.startswith("'") and arg.endswith("'"):
            return arg[1:-1].lower()
        # Handle parameter references
        elif arg.startswith("parameters("):
            param_match = re.match(r"parameters\('([^']+)'\)", arg)
            if param_match:
                param_name = param_match.group(1)
                if param_name in param_values:
                    return str(param_values[param_name]).lower()
                else:
                    self.logger.warning(f"Parameter '{param_name}' not found in parameters file")
                    return f"[{expression}]"
        # Handle variable references
        elif arg.startswith("variables("):
            var_match = re.match(r"variables\('([^']+)'\)", arg)
            if var_match:
                var_name = var_match.group(1)
                if var_name in variables:
                    return str(variables[var_name]).lower()
                else:
                    self.logger.warning(f"Variable '{var_name}' not found in template variables")
                    return f"[{expression}]"

        return f"[{expression}]"

    def _evaluate_to_upper(
        self, expression: str, param_values: Dict[str, Any], variables: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Evaluate toUpper() ARM template function.

        Examples:
        - toUpper('hello world') -> 'HELLO WORLD'
        - toUpper(parameters('resourceName')) -> 'MYRESOURCE' (if resourceName = 'myresource')
        """
        import re

        if variables is None:
            variables = {}

        # Extract argument from toUpper(string)
        match = re.match(r"toUpper\((.*)\)", expression)
        if not match:
            return f"[{expression}]"

        arg = match.group(1).strip()

        # Handle string literals
        if arg.startswith("'") and arg.endswith("'"):
            return arg[1:-1].upper()
        # Handle parameter references
        elif arg.startswith("parameters("):
            param_match = re.match(r"parameters\('([^']+)'\)", arg)
            if param_match:
                param_name = param_match.group(1)
                if param_name in param_values:
                    return str(param_values[param_name]).upper()
                else:
                    self.logger.warning(f"Parameter '{param_name}' not found in parameters file")
                    return f"[{expression}]"
        # Handle variable references
        elif arg.startswith("variables("):
            var_match = re.match(r"variables\('([^']+)'\)", arg)
            if var_match:
                var_name = var_match.group(1)
                if var_name in variables:
                    return str(variables[var_name]).upper()
                else:
                    self.logger.warning(f"Variable '{var_name}' not found in template variables")
                    return f"[{expression}]"

        return f"[{expression}]"

    def _evaluate_reference(self, expression, param_values, variables):
        """Evaluate reference ARM function to extract resource properties, including deployment outputs."""
        import re

        if variables is None:
            variables = {}

        # Parse reference(resourceId, apiVersion) or reference(resourceId, apiVersion, property)
        # Use a more permissive regex that captures everything between the outermost parentheses
        match = re.match(r"reference\s*\(\s*(.+)\s*\)$", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)
        args = self._parse_function_arguments(args_str)

        if len(args) < 2:
            return f"[{expression}]"

        # Process the resource ID
        resource_id = self._evaluate_arm_expression(args[0], param_values, variables)
        api_version = args[1].strip("'\"")

        # Check if this is a deployment reference accessing outputs
        if "Microsoft.Resources/deployments" in str(resource_id):
            return self._handle_deployment_reference(expression, resource_id, api_version, param_values, variables)

        # Extract meaningful information from the resource ID
        if isinstance(resource_id, str):
            # Try to extract resource name from resourceId result or direct string
            if "Microsoft." in resource_id or "/" in resource_id:
                # Extract resource name for display
                parts = resource_id.split("/")
                if len(parts) >= 1:
                    resource_name = parts[-1] if parts else "unknown"

                    # Return a simplified reference format for better readability
                    if len(args) > 2:
                        # Has property specified
                        property_name = args[2].strip("'\"")
                        return f"{resource_name}.{property_name}"
                    else:
                        # Return resource name with reference indicator
                        return f"{resource_name}-ref"
            else:
                # Direct resource name (not a full resource ID)
                resource_name = resource_id.strip("'\"")
                if len(args) > 2:
                    property_name = args[2].strip("'\"")
                    return f"{resource_name}.{property_name}"
                else:
                    return f"{resource_name}-ref"

        # Fallback: return a simplified version
        return f"ref-{api_version}"

    def _handle_deployment_reference(
        self,
        expression: str,
        resource_id: str,
        api_version: str,
        param_values: Dict[str, Any],
        variables: Dict[str, Any],
    ) -> str:
        """
        Handle deployment reference functions that access nested template outputs.

        This method specifically handles patterns like:
        reference(resourceId('Microsoft.Resources/deployments', 'networkDeployment'), '2022-09-01').outputs.privateEndpointSubnetId.value

        Args:
            expression: The full reference expression
            resource_id: The resolved resource ID (deployment name)
            api_version: API version for the reference
            param_values: Parameter values
            variables: Template variables

        Returns:
            str: Resolved subnet ID or simplified reference
        """
        import re

        # Extract the property path after the reference function
        # Look for patterns like .outputs.propertyName.value
        output_match = re.search(r"\.outputs\.([^\.]+)\.value", expression)

        if output_match:
            output_name = output_match.group(1)
            deployment_name = resource_id.split("/")[-1] if "/" in resource_id else resource_id.strip("'\"")

            # Only apply subnet resolution for subnet-related outputs
            if self._is_subnet_output(output_name):
                # Use the same dynamic approach as _handle_complex_deployment_reference
                # Use parameter values to construct subnet resource IDs
                app_name = param_values.get("appName", "myapp")
                environment = param_values.get("environment", "dev")
                subscription_id = param_values.get("subscriptionId", self.default_subscription_id)
                resource_group_name = param_values.get("resourceGroupName", self.default_resource_group)
                vnet_name = param_values.get("vnetName", f"{app_name}-{environment}-vnet")

                # Try to get actual subnet names from the template being built
                # But only for outputs that are actually subnet-related
                is_subnet = self._is_subnet_output(output_name)
                self.logger.debug(
                    f"Checking output '{output_name}' in _handle_deployment_reference: is_subnet_output = {is_subnet}"
                )

                if is_subnet:
                    # TEMPLATE-ONLY APPROACH: Try to extract actual subnet name from module outputs
                    actual_subnet_name = self._extract_subnet_name_from_module_output(
                        deployment_name, output_name, param_values
                    )
                    if actual_subnet_name:
                        # Construct the full subnet resource ID with actual subnet name
                        subscription_id = param_values.get("subscriptionId", self.default_subscription_id)
                        resource_group_name = param_values.get("resourceGroupName", self.default_resource_group)
                        vnet_name = param_values.get("vnetName", f"{app_name}-{environment}-vnet")
                        subnet_resource_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{actual_subnet_name}"
                        self.logger.info(
                            f"Resolved deployment reference {deployment_name}.{output_name} to: {subnet_resource_id}"
                        )
                        return subnet_resource_id
                    else:
                        # Cannot resolve - return unresolved placeholder
                        self.logger.warning(
                            f"Cannot resolve subnet name for output '{output_name}' - no name generation allowed. Template must provide actual subnet names."
                        )
                        return f"[UNRESOLVED-SUBNET: {deployment_name}.{output_name}]"
                else:
                    # For non-subnet outputs, return a generic reference
                    return f"{deployment_name}.{output_name}"
            else:
                # For non-subnet outputs, return a generic reference
                return f"{deployment_name}.{output_name}"

        # Check for other deployment reference patterns
        property_match = re.search(r"\.([a-zA-Z][a-zA-Z0-9_]*)", expression)
        if property_match:
            property_name = property_match.group(1)
            deployment_name = resource_id.split("/")[-1] if "/" in resource_id else resource_id.strip("'\"")
            return f"{deployment_name}.{property_name}"

        # Fallback to deployment name reference
        deployment_name = resource_id.split("/")[-1] if "/" in resource_id else resource_id.strip("'\"")
        return f"{deployment_name}-output"

    def _evaluate_reference_with_properties(
        self, expression: str, param_values: Dict[str, Any], variables: Dict[str, Any]
    ) -> str:
        """
        Evaluate reference ARM function with property access patterns.

        This method handles complex reference expressions like:
        reference(resourceId(...), '2022-09-01').outputs.privateEndpointSubnetId.value

        Args:
            expression: The complete reference expression with property access
            param_values: Parameter values
            variables: Template variables

        Returns:
            str: Resolved value or simplified reference
        """
        import re

        # Check if this is a complex reference with property access
        if ".outputs." in expression and ".value" in expression:
            # This is a deployment output reference - handle it specially
            return self._handle_complex_deployment_reference(expression, param_values, variables)

        # Pattern to match basic reference function
        ref_pattern = r"^reference\s*\([^)]+\)"

        match = re.match(ref_pattern, expression)
        if match:
            # Extract just the reference function part
            ref_func = match.group(0)
            property_access = expression[len(ref_func) :]

            # Evaluate the reference function first
            result = self._evaluate_reference(ref_func, param_values, variables)

            # If property access exists, append it to the result for context
            if property_access:
                # Clean up the property access (remove dots, get the last meaningful part)
                property_parts = [p for p in property_access.split(".") if p.strip()]
                if property_parts:
                    if "value" in property_parts:
                        # This is accessing a deployment output value
                        return str(result)  # The reference function should have resolved this
                    else:
                        # Other property access
                        return f"{result}.{property_parts[-1]}"

            return str(result)

        # Fallback to basic reference handling
        return str(self._evaluate_reference(expression, param_values, variables))

    def _handle_complex_deployment_reference(
        self, expression: str, param_values: Dict[str, Any], variables: Dict[str, Any]
    ) -> str:
        """
        Handle complex deployment reference expressions that include property access.

        Handles patterns like:
        reference(resourceId('Microsoft.Resources/deployments', 'networkDeployment'), '2022-09-01').outputs.privateEndpointSubnetId.value

        Args:
            expression: The complete expression
            param_values: Parameter values
            variables: Template variables

        Returns:
            str: Resolved subnet resource ID
        """
        import re

        # Extract deployment name and output name
        deployment_match = re.search(r"resourceId\('Microsoft\.Resources/deployments',\s*'([^']+)'\)", expression)
        output_match = re.search(r"\.outputs\.([^\.]+)\.value", expression)

        if deployment_match and output_match:
            deployment_name = deployment_match.group(1)
            output_name = output_match.group(1)

            # Only apply subnet resolution for subnet-related outputs
            if not self._is_subnet_output(output_name):
                self.logger.debug(f"Skipping subnet resolution for non-subnet output: {output_name}")
                return f"{deployment_name}.{output_name}"

            # Use parameter values to construct realistic subnet resource IDs
            app_name = param_values.get("appName", "myapp")
            environment = param_values.get("environment", "dev")
            subscription_id = param_values.get("subscriptionId", self.default_subscription_id)
            resource_group_name = param_values.get("resourceGroupName", self.default_resource_group)
            vnet_name = param_values.get("vnetName", f"{app_name}-{environment}-vnet")

            # Try to get actual subnet names from the template being built
            # But only for outputs that are actually subnet-related
            is_subnet = self._is_subnet_output(output_name)
            self.logger.debug(f"Checking output '{output_name}': is_subnet_output = {is_subnet}")

            if is_subnet:
                # TEMPLATE-ONLY APPROACH: Try to extract actual subnet name from module outputs
                actual_subnet_name = self._extract_subnet_name_from_module_output(
                    deployment_name, output_name, param_values
                )
                if actual_subnet_name:
                    # Construct the full subnet resource ID with actual subnet name
                    subscription_id = param_values.get("subscriptionId", self.default_subscription_id)
                    resource_group_name = param_values.get("resourceGroupName", self.default_resource_group)
                    vnet_name = param_values.get("vnetName", f"{app_name}-{environment}-vnet")
                    subnet_resource_id = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group_name}/providers/Microsoft.Network/virtualNetworks/{vnet_name}/subnets/{actual_subnet_name}"
                    self.logger.info(
                        f"Resolved deployment reference {deployment_name}.{output_name} to: {subnet_resource_id}"
                    )
                    return subnet_resource_id
                else:
                    # Cannot resolve - return unresolved placeholder
                    self.logger.warning(
                        f"Cannot resolve subnet name for output '{output_name}' - no name generation allowed. Template must provide actual subnet names."
                    )
                    return f"[UNRESOLVED-SUBNET: {deployment_name}.{output_name}]"
            else:
                # For non-subnet outputs, use a generic subnet name based on the output name pattern
                return f"{deployment_name}.{output_name}"

        # If we can't parse it properly, return a warning message
        self.logger.warning(f"Could not parse complex deployment reference: {expression}")
        return f"[UNRESOLVED: {expression}]"

    def _is_subnet_output(self, output_name: str) -> bool:
        """
        Check if an output name refers to a subnet resource.

        Args:
            output_name: The output name to check

        Returns:
            bool: True if this is a subnet-related output
        """
        subnet_indicators = [
            "subnet",
            "SubnetId",
            "subnetId",
            "SubnetResource",
            "subnetResource",
            "SubnetRef",
            "subnetRef",
        ]

        return any(indicator in output_name for indicator in subnet_indicators)

    def _extract_subnet_name_from_module_output(
        self, deployment_name: str, output_name: str, param_values: Dict[str, Any]
    ) -> Optional[str]:
        """
        Extract actual subnet name from module output definition.

        This method looks at the module definition to find what actual subnet name
        an output like 'aksSubnetId' refers to.

        Args:
            deployment_name: The deployment/module name (e.g., 'networkDeployment')
            output_name: The output name (e.g., 'aksSubnetId')
            param_values: Parameter values for context

        Returns:
            Optional[str]: Actual subnet name if found, None otherwise
        """
        try:
            # Map common deployment names to module paths
            module_path_mapping = {
                "networkDeployment": "samples/modular-bicep/modules/network/network.bicep",
                "networkModule": "samples/modular-bicep/modules/network/network.bicep",
                "network": "samples/modular-bicep/modules/network/network.bicep",
            }

            module_path = module_path_mapping.get(deployment_name)
            if not module_path:
                self.logger.debug(f"No module path mapping found for deployment '{deployment_name}'")
                return None

            # Check if module file exists
            if not os.path.exists(module_path):
                self.logger.debug(f"Module file not found: {module_path}")
                return None

            # Read the module file
            with open(module_path, "r", encoding="utf-8") as f:
                module_content = f.read()

            # Look for output definition that matches our output name
            # Pattern: output aksSubnetId string = '${virtualNetwork.id}/subnets/AKSSubnet'
            output_pattern = rf"output\s+{re.escape(output_name)}\s+string\s*=\s*['\"].*?/subnets/(\w+)['\"]"

            match = re.search(output_pattern, module_content, re.IGNORECASE)
            if match:
                actual_subnet_name = match.group(1)
                self.logger.info(
                    f"Extracted actual subnet name '{actual_subnet_name}' from {deployment_name} output '{output_name}'"
                )
                return actual_subnet_name

            # Alternative pattern for more complex expressions
            # Pattern: output aksSubnetId string = format('{0}/subnets/{1}', vnet.id, 'AKSSubnet')
            alt_pattern = rf"output\s+{re.escape(output_name)}.*?['\"](\w*Subnet)['\"]"
            match = re.search(alt_pattern, module_content, re.IGNORECASE)
            if match:
                actual_subnet_name = match.group(1)
                self.logger.info(
                    f"Extracted actual subnet name '{actual_subnet_name}' from {deployment_name} output '{output_name}' (alternative pattern)"
                )
                return actual_subnet_name

            self.logger.debug(f"Could not extract subnet name from {deployment_name} output '{output_name}'")
            return None

        except Exception as e:
            self.logger.error(f"Error extracting subnet name from module output: {str(e)}")
            return None

    def _get_actual_subnet_name_from_template(self, output_name: str) -> Optional[str]:
        """
        Phase 1: Generate generic placeholder subnet names to avoid circular dependency.

        During template building, we use simple generic placeholders that will be replaced
        with actual subnet names from the built template in Phase 2.

        Args:
            output_name: The output name like 'privateEndpointSubnetId', 'aksSubnetId', etc.

        Returns:
            Optional[str]: The generic placeholder subnet name for Phase 1
        """
        try:
            # First, check if we have parameter-based subnet name mappings
            param_based_name = self._get_subnet_name_from_parameters(output_name)
            if param_based_name:
                self.logger.info(f"Found parameter-based subnet name '{param_based_name}' for output '{output_name}'")
                return param_based_name

            # Generate generic placeholder that will be replaced in Phase 2
            # Use simple pattern: extract purpose and add "Subnet" suffix
            clean_name = output_name.replace("SubnetId", "").replace("subnetId", "").replace("Id", "")
            placeholder_name = f"{clean_name}Subnet"

            self.logger.debug(
                f"Generated Phase 1 generic placeholder '{placeholder_name}' for output '{output_name}' (will be replaced with actual subnet name in Phase 2)"
            )
            return placeholder_name

        except Exception as e:
            self.logger.error(f"Error generating placeholder subnet name for '{output_name}': {str(e)}")
            # Fallback to basic naming pattern
            subnet_type = output_name.replace("SubnetId", "").replace("subnetId", "").replace("Id", "")
            fallback_name = f"{subnet_type}Subnet"
            self.logger.warning(f"Using fallback placeholder subnet name '{fallback_name}' for output '{output_name}'")
            return fallback_name

    def _get_subnet_name_from_parameters(self, output_name: str) -> Optional[str]:
        """
        Try to get subnet name from parameter values using common parameter naming patterns.

        Args:
            output_name: Output name like 'aksSubnetId'

        Returns:
            Optional[str]: Parameter-based subnet name if found
        """
        try:
            # Get current parameter values if available
            param_values = getattr(self, "current_param_values", {})
            if not param_values:
                return None

            # Common parameter patterns for subnet names
            purpose = output_name.replace("SubnetId", "").replace("subnetId", "")

            # Try different parameter naming conventions
            param_patterns = [
                f"{purpose}SubnetName",
                f"{purpose.lower()}SubnetName",
                f"{purpose}Subnet",
                f"{purpose.lower()}Subnet",
                f"subnet{purpose}Name",
                f"subnet{purpose.capitalize()}Name",
                f"{purpose}_subnet_name",
                f"{purpose.lower()}_subnet_name",
            ]

            for pattern in param_patterns:
                if pattern in param_values:
                    subnet_name = param_values[pattern]
                    self.logger.info(f"Found parameter-based subnet name: {pattern} = {subnet_name}")
                    return str(subnet_name)

            return None

        except Exception as e:
            self.logger.debug(f"Error getting parameter-based subnet name: {e}")
            return None

    def _post_process_subnet_references(self, template: Dict[str, Any]) -> Dict[str, Any]:
        """
        Post-process the populated template to fix subnet name references with actual subnet names.

        This method runs after the template is fully built and resolves placeholder subnet names
        with the real subnet names found in VNet resources.

        Args:
            template: The populated template dictionary

        Returns:
            Dict[str, Any]: Template with corrected subnet references
        """
        try:
            self.logger.info("Post-processing subnet references with actual template subnet names")

            # Extract actual subnet names from VNet resources in the template
            subnet_mapping = self._extract_actual_subnet_mapping(template)

            if not subnet_mapping:
                self.logger.warning("No subnet mapping found in template, skipping post-processing")
                return template

            self.logger.info(f"Found subnet mapping: {subnet_mapping}")

            # Update all resource dependencies that reference subnet names
            updated_template = self._update_subnet_references_in_template(template, subnet_mapping)

            self.logger.info("Successfully completed subnet reference post-processing")
            return updated_template

        except Exception as e:
            self.logger.error(f"Error during subnet reference post-processing: {str(e)}")
            return template  # Return original template if post-processing fails

    def _extract_actual_subnet_mapping(self, template: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract mapping from placeholder subnet names to actual subnet names in the template.

        This method ONLY uses actual subnet names from the built template, not generated names.
        It creates intelligent mappings based on semantic similarity.

        Args:
            template: The populated template dictionary

        Returns:
            Dict[str, str]: Mapping from placeholder names to actual subnet names
        """
        subnet_mapping = {}

        try:
            resources = template.get("resources", [])
            vnets = [r for r in resources if r.get("type") == "Microsoft.Network/virtualNetworks"]

            # Get all actual subnet names from the template
            actual_subnet_names = []
            for vnet in vnets:
                vnet_name = vnet.get("name", "unknown")
                subnets = vnet.get("properties", {}).get("subnets", [])

                self.logger.debug(f"Analyzing VNet '{vnet_name}' with {len(subnets)} subnets")

                for subnet in subnets:
                    actual_name = subnet.get("name", "")
                    if actual_name:
                        actual_subnet_names.append(actual_name)

            self.logger.info(f"Found actual subnet names in template: {actual_subnet_names}")

            # Create mapping - ONLY identity mapping (actual names to themselves)
            for actual_name in actual_subnet_names:
                # Map the actual name to itself (identity mapping only)
                subnet_mapping[actual_name] = actual_name

            self.logger.info(f"Created identity-only subnet mapping: {subnet_mapping}")
            return subnet_mapping

        except Exception as e:
            self.logger.error(f"Error extracting subnet mapping: {str(e)}")
            return {}

    def _update_subnet_references_in_template(
        self, template: Dict[str, Any], subnet_mapping: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        Update subnet references in the template using the subnet mapping.

        Args:
            template: The template to update
            subnet_mapping: Mapping from placeholder to actual subnet names

        Returns:
            Dict[str, Any]: Updated template
        """
        import json

        try:
            # Convert template to JSON string for easy replacement
            template_str = json.dumps(template, indent=2)
            original_template_str = template_str

            # Track replacements made
            replacements_made = 0

            # Replace subnet references in resource IDs and dependencies
            for placeholder, actual_name in subnet_mapping.items():
                if placeholder != actual_name:  # Only replace if they're different

                    # Count occurrences before replacement
                    occurrences_before = template_str.count(placeholder)

                    # Replace in subnet resource ID paths
                    template_str = template_str.replace(f"subnets/{placeholder}", f"subnets/{actual_name}")
                    template_str = template_str.replace(f"subnets\\/{placeholder}", f"subnets\\/{actual_name}")

                    # Replace direct subnet name references
                    template_str = template_str.replace(f'"{placeholder}"', f'"{actual_name}"')
                    template_str = template_str.replace(f"'{placeholder}'", f"'{actual_name}'")

                    # Replace in subnet property values
                    template_str = template_str.replace(f'"subnet": "{placeholder}"', f'"subnet": "{actual_name}"')
                    template_str = template_str.replace(f"'subnet': '{placeholder}'", f"'subnet': '{actual_name}'")

                    # Replace in virtualNetworkSubnetId properties
                    template_str = template_str.replace(
                        f'"virtualNetworkSubnetId": "{placeholder}"', f'"virtualNetworkSubnetId": "{actual_name}"'
                    )

                    # Replace placeholder that appears alone (not part of longer strings)
                    import re

                    # Use word boundaries to avoid partial replacements
                    template_str = re.sub(rf"\b{re.escape(placeholder)}\b", actual_name, template_str)

                    # Count occurrences after replacement
                    occurrences_after = template_str.count(placeholder)

                    if occurrences_before != occurrences_after:
                        replaced_count = occurrences_before - occurrences_after
                        replacements_made += replaced_count
                        self.logger.debug(
                            f"Replaced {replaced_count} occurrences of '{placeholder}' with '{actual_name}'"
                        )

            if replacements_made > 0:
                self.logger.info(f"Made {replacements_made} subnet reference replacements")
                result: Dict[str, Any] = json.loads(template_str)
                return result
            else:
                self.logger.debug("No subnet reference replacements needed")
                return template

        except Exception as e:
            self.logger.error(f"Error updating subnet references: {str(e)}")
            return template

    def _evaluate_list_keys(self, expression, param_values, variables):
        """Evaluate listKeys ARM function."""
        import re

        if variables is None:
            variables = {}

        # Parse listKeys(resourceId, apiVersion)
        match = re.match(r"listKeys\s*\(\s*(.+)\s*\)$", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)
        args = self._parse_function_arguments(args_str)

        if len(args) < 2:
            return f"[{expression}]"

        # Process the resource ID
        resource_id = self._evaluate_arm_expression(args[0], param_values, variables)
        api_version = args[1].strip("'\"")

        # For template visibility, return a placeholder that indicates this would be the keys
        if isinstance(resource_id, str):
            if "Microsoft." in resource_id or "/" in resource_id:
                parts = resource_id.split("/")
                resource_name = parts[-1] if parts else "unknown"
                return f"{resource_name}-keys"
            else:
                # Direct resource name
                resource_name = resource_id.strip("'\"")
                return f"{resource_name}-keys"

        return f"keys-{api_version}"

    def _evaluate_guid(self, expression, param_values, variables):
        """Evaluate guid ARM function to generate deterministic GUID-like values."""
        import hashlib
        import re

        if variables is None:
            variables = {}

        # Parse guid(seed1, seed2, ...)
        match = re.match(r"guid\s*\(\s*(.+)\s*\)$", expression)
        if not match:
            return f"[{expression}]"

        args_str = match.group(1)
        args = self._parse_function_arguments(args_str)

        # Evaluate all arguments
        seed_parts = []
        for arg in args:
            resolved = self._evaluate_arm_expression(arg, param_values, variables)
            seed_parts.append(str(resolved))

        # Create a deterministic "GUID" from the seeds
        seed_string = "-".join(seed_parts)
        hash_obj = hashlib.md5(seed_string.encode())
        hex_dig = hash_obj.hexdigest()

        # Format as GUID-like string (shortened for readability)
        guid = f"{hex_dig[:8]}-{hex_dig[8:12]}-{hex_dig[12:16]}"
        return guid

    def _evaluate_subscription(self, expression, param_values, variables):
        """Evaluate subscription ARM function."""
        # subscription() returns subscription info
        # For template visibility, return a simplified representation
        return "subscription-info"

    def _evaluate_environment(self, expression, param_values, variables):
        """Evaluate environment ARM function."""
        # environment() returns environment info
        # For template visibility, return a simplified representation
        return "environment-info"

    def _is_modular_template(self, bicep_file: str) -> bool:
        """
        Check if a Bicep template uses modules by looking for 'module ' keyword.

        Args:
            bicep_file: Path to the Bicep template file

        Returns:
            bool: True if template contains module references, False otherwise
        """
        try:
            with open(bicep_file, "r", encoding="utf-8") as f:
                content = f.read()
                return "module " in content
        except Exception as e:
            self.logger.error(f"Error checking if template is modular: {e}")
            return False

    def _build_modular_template(self, bicep_file: str, parameters_file: str, output_file: str) -> Optional[str]:
        """
        Build a modular Bicep template and flatten nested module deployments into individual resources.

        Args:
            bicep_file: Path to the modular Bicep template file
            parameters_file: Path to the parameters file
            output_file: Path for the output file

        Returns:
            Optional[str]: Path to the generated ARM template file if successful, None otherwise
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_file:
            temp_arm_path = temp_file.name

        try:
            self.logger.info(f"Building modular Bicep template: {bicep_file}")

            # Step 1: Build Bicep to ARM template (creates nested deployments)
            cmd = self._build_bicep_build_command(bicep_file, temp_arm_path)

            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace", timeout=300
            )  # 5 minute timeout
            self.logger.info("Successfully built modular Bicep to ARM template")

            # Step 2: Flatten nested deployments and populate parameters
            flattened_template = self._flatten_and_populate_modular_template(temp_arm_path, parameters_file)

            if flattened_template:
                # Write the flattened template to output file
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(flattened_template, f, indent=2)

                self.logger.info(f"Successfully created flattened modular ARM template: {output_file}")
                return output_file
            else:
                self.logger.error("Failed to flatten and populate modular template")
                return None

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to build modular Bicep template: {e.stderr}")
            return None
        finally:
            # Clean up temporary file
            if os.path.exists(temp_arm_path):
                os.unlink(temp_arm_path)

    def _build_single_template(self, bicep_file: str, parameters_file: str, output_file: str) -> Optional[str]:
        """
        Build a single (non-modular) Bicep template.

        Args:
            bicep_file: Path to the Bicep template file
            parameters_file: Path to the parameters file
            output_file: Path for the output file

        Returns:
            Optional[str]: Path to the generated ARM template file if successful, None otherwise
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as temp_file:
            temp_arm_path = temp_file.name

        try:
            self.logger.info(f"Building single Bicep template: {bicep_file}")

            # Step 1: Build Bicep to ARM template
            cmd = self._build_bicep_build_command(bicep_file, temp_arm_path)

            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, encoding="utf-8", errors="replace", timeout=300
            )  # 5 minute timeout
            self.logger.info("Successfully built Bicep to ARM template")

            # Step 2: Populate template parameters
            self.output_file = output_file  # Store output file path for subnet extraction
            populated_template = self._populate_template_parameters(temp_arm_path, parameters_file)

            if populated_template:
                # Write the populated template to output file
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(populated_template, f, indent=2)

                self.logger.info(f"Successfully created populated ARM template: {output_file}")
                return output_file
            else:
                self.logger.error("Failed to populate template parameters")
                return None

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to build single Bicep template: {e.stderr}")
            return None
        finally:
            # Clean up temporary file
            if os.path.exists(temp_arm_path):
                os.unlink(temp_arm_path)

    def _flatten_and_populate_modular_template(
        self, arm_template_path: str, parameters_file: str
    ) -> Optional[Dict[str, Any]]:
        """
        Flatten nested module deployments and populate parameters for a modular ARM template.

        This extracts all actual Azure resources from nested Microsoft.Resources/deployments
        and creates a single flat template with all individual resources.

        Args:
            arm_template_path: Path to the ARM template with nested deployments
            parameters_file: Path to the parameters file

        Returns:
            Optional[Dict[str, Any]]: Flattened and populated template dictionary if successful
        """
        try:
            # Load the ARM template with nested deployments
            with open(arm_template_path, "r", encoding="utf-8") as f:
                template = json.load(f)

            # Load the parameters
            with open(parameters_file, "r", encoding="utf-8") as f:
                parameters_data = json.load(f)

            # Extract parameter values
            if "parameters" in parameters_data:
                param_values = {k: v.get("value", v) for k, v in parameters_data["parameters"].items()}
            else:
                param_values = parameters_data

            # Extract and resolve variables from the main template
            variables = template.get("variables", {})
            resolved_variables = self._resolve_variables(variables, param_values)

            # Add resolved variables to param_values so they can be referenced as parameters
            # This handles cases where modular template flattening converts variables('x') to parameters('x')
            combined_param_values = param_values.copy()
            combined_param_values.update(resolved_variables)

            self.logger.info(
                f"Loaded {len(param_values)} parameters and {len(resolved_variables)} variables for modular template flattening"
            )
            self.logger.debug(f"Combined parameter values for flattening: {list(combined_param_values.keys())}")

            # Create flattened template structure
            flattened_template = {
                "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                "contentVersion": "1.0.0.0",
                "resources": [],
                "outputs": template.get("outputs", {}),
            }

            total_resources = 0

            # Process each resource in the main template
            for resource in template.get("resources", []):
                if resource.get("type") == "Microsoft.Resources/deployments":
                    # This is a nested deployment (module), extract its resources
                    module_name = resource.get("name", "unnamed-module")
                    nested_resources = self._extract_resources_from_nested_deployment(
                        resource, combined_param_values, resolved_variables, module_name
                    )
                    flattened_template["resources"].extend(nested_resources)
                    total_resources += len(nested_resources)
                    self.logger.info(f"Extracted {len(nested_resources)} resources from module '{module_name}'")
                else:
                    # Regular resource, process normally
                    processed_resource = self._process_resource(resource, combined_param_values, resolved_variables)
                    flattened_template["resources"].append(processed_resource)
                    total_resources += 1

            self.logger.info(
                f"Successfully flattened modular template: {total_resources} total resources from {len(template.get('resources', []))} modules"
            )
            return flattened_template

        except Exception as e:
            self.logger.error(f"Error flattening modular template: {str(e)}")
            return None

    def _extract_resources_from_nested_deployment(
        self,
        deployment_resource: Dict[str, Any],
        param_values: Dict[str, Any],
        resolved_variables: Dict[str, Any],
        module_name: str,
    ) -> list:
        """
        Extract all actual Azure resources from a nested deployment module.

        Args:
            deployment_resource: The nested deployment resource containing the module
            param_values: Parameter values from main template
            resolved_variables: Resolved variables from main template
            module_name: Name of the module for resource naming

        Returns:
            list: List of extracted Azure resources
        """
        extracted_resources = []

        try:
            # Get the nested template from the deployment properties
            properties = deployment_resource.get("properties", {})
            nested_template = properties.get("template", {})
            nested_parameters = properties.get("parameters", {})

            # Resolve the module's parameter values
            module_param_values = {}

            for param_name, param_definition in nested_parameters.items():
                if isinstance(param_definition, dict) and "value" in param_definition:
                    # Direct value
                    param_value = param_definition["value"]

                    # Resolve if it contains ARM expressions
                    if isinstance(param_value, str) and param_value.startswith("[") and param_value.endswith("]"):
                        resolved_value = self._resolve_parameter_references(
                            param_value, param_values, resolved_variables
                        )
                        module_param_values[param_name] = resolved_value
                    else:
                        module_param_values[param_name] = param_value
                else:
                    # May be a reference that needs resolution
                    module_param_values[param_name] = param_definition

            # Resolve the module's variables
            module_variables = nested_template.get("variables", {})
            resolved_module_variables = self._resolve_variables(module_variables, module_param_values)

            # Combine module parameters with main template variables for full resolution
            # This handles cases where modules reference main template variables as parameters
            combined_module_params = module_param_values.copy()
            combined_module_params.update(resolved_variables)  # Add main template variables

            # Extract all resources from the nested template
            for nested_resource in nested_template.get("resources", []):
                # Process the resource with the combined context (module + main template)
                processed_resource = self._process_resource(
                    nested_resource, combined_module_params, resolved_module_variables
                )

                # Add module prefix to resource name for uniqueness (optional, might want to skip for cleaner names)
                # processed_resource['name'] = f"[concat('{module_name}/', {processed_resource['name']})]"

                extracted_resources.append(processed_resource)

        except Exception as e:
            self.logger.warning(f"Error extracting resources from module '{module_name}': {str(e)}")
            # Add a placeholder to maintain structure
            placeholder = {
                "type": "Microsoft.Resources/deployments",
                "apiVersion": "2021-04-01",
                "name": f"[concat('failed-module-', '{module_name}')]",
                "properties": {
                    "mode": "Incremental",
                    "template": {
                        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                        "contentVersion": "1.0.0.0",
                        "resources": [],
                    },
                },
            }
            extracted_resources.append(placeholder)

        return extracted_resources

    def _process_resource(
        self, resource: Dict[str, Any], param_values: Dict[str, Any], variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a single resource by resolving its parameter and variable references.

        Args:
            resource: The resource definition
            param_values: Parameter values
            variables: Variable values

        Returns:
            Dict[str, Any]: Processed resource with resolved references
        """
        # Debug logging for problematic resource names only when necessary
        resource_name = resource.get("name", "")
        if any(pattern in str(resource_name) for pattern in ["streplace", "stfuncreplace", "acrreplace"]):
            self.logger.info(f"Processing resource: {resource.get('type', 'unknown')} with complex name")

        # Use the existing template resolution logic
        processed = self._resolve_template_parameters(resource, param_values, variables)

        return processed


def build_bicep_template(bicep_file: str, parameters_file: str, output_file: Optional[str] = None) -> Optional[str]:
    """
    Convenience function to build a Bicep template with parameters.
    Uses simplified default configuration for Bicep mode with global caching.

    Args:
        bicep_file: Path to the Bicep template file
        parameters_file: Path to the parameters file
        output_file: Optional path for output file

    Returns:
        Optional[str]: Path to the generated ARM template file if successful, None otherwise
    """
    builder = BicepTemplateBuilder()
    return builder.build_bicep_template(bicep_file, parameters_file, output_file)


def clear_template_cache() -> None:
    """
    Clear the global template cache. Useful for debugging or when templates change.
    """
    global _TEMPLATE_CACHE
    cache_size = len(_TEMPLATE_CACHE)
    _TEMPLATE_CACHE.clear()
    logger.info(f"Cleared template cache ({cache_size} entries)")


def get_cache_stats() -> Dict[str, Any]:
    """
    Get template cache statistics for debugging.

    Returns:
        Dict with cache size and entry keys
    """
    global _TEMPLATE_CACHE
    return {"size": len(_TEMPLATE_CACHE), "entries": list(_TEMPLATE_CACHE.keys())}
