"""Bicep Processor Service for template parsing and parameter resolution.

This module provides operations for processing compiled ARM templates,
resolving parameters, and extracting resource information.
"""

import json
import re
from typing import Any, Dict, List, Optional, cast

from cloudhorus.services.base import BaseService


class BicepProcessorService(BaseService):
    """Service for processing and analyzing ARM/Bicep templates.

    This service handles:
    - ARM template parsing
    - Parameter resolution and substitution
    - Variable expansion
    - Resource extraction

    Attributes:
        current_template: Currently loaded template
        current_param_values: Currently loaded parameter values
    """

    def __init__(self):
        """Initialize the Bicep Processor Service."""
        super().__init__()
        self.current_template = None
        self.current_param_values = None

    def validate(self) -> bool:
        """Validate the service is properly configured.

        Returns:
            True if service is valid
        """
        self.logger.info("BicepProcessorService validated successfully")
        return True

    def load_template(self, template_path: str) -> Optional[Dict[str, Any]]:
        """Load an ARM template from a file.

        Args:
            template_path: Path to the ARM template JSON file

        Returns:
            Template dictionary if successful, None otherwise
        """
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                self.current_template = json.load(f)
            self.logger.info(f"Loaded template: {template_path}")
            return cast(Optional[Dict[str, Any]], self.current_template)
        except Exception as e:
            self.logger.error(f"Failed to load template: {e}")
            return None

    def load_parameters(self, parameters_path: str) -> Optional[Dict[str, Any]]:
        """Load parameters from a file.

        Args:
            parameters_path: Path to the parameters JSON file

        Returns:
            Parameters dictionary if successful, None otherwise
        """
        try:
            with open(parameters_path, "r", encoding="utf-8") as f:
                parameters_data = json.load(f)

            # Extract parameter values
            if "parameters" in parameters_data:
                self.current_param_values = {k: v.get("value", v) for k, v in parameters_data["parameters"].items()}
            else:
                self.current_param_values = parameters_data

            self.logger.info(f"Loaded {len(self.current_param_values)} parameters")
            return cast(Optional[Dict[str, Any]], self.current_param_values)

        except Exception as e:
            self.logger.error(f"Failed to load parameters: {e}")
            return None

    def populate_template_parameters(self, template_path: str, parameters_path: str) -> Optional[Dict[str, Any]]:
        """Populate ARM template parameters with actual values.

        This resolves all parameter references to their actual values,
        similar to what export_resource_group_template produces.

        Args:
            template_path: Path to the ARM template JSON file
            parameters_path: Path to the parameters file

        Returns:
            Populated template dictionary if successful, None otherwise
        """
        try:
            # Load template and parameters
            template = self.load_template(template_path)
            if not template:
                return None

            param_values = self.load_parameters(parameters_path)
            if not param_values:
                return None

            # Resolve variables
            variables = template.get("variables", {})
            resolved_variables = self._resolve_variables(variables, param_values)

            # Combine parameters and variables for resolution
            combined_values = param_values.copy()
            combined_values.update(resolved_variables)

            self.logger.info(f"Processing {len(param_values)} parameters and " f"{len(resolved_variables)} variables")

            # Resolve all parameter references
            populated_template = self._resolve_template_recursively(template, combined_values, resolved_variables)

            # Remove parameters and variables sections
            if "parameters" in populated_template:
                del populated_template["parameters"]
            if "variables" in populated_template:
                del populated_template["variables"]

            # Ensure required structure
            populated_template.setdefault("$schema", template.get("$schema", ""))
            populated_template.setdefault("contentVersion", template.get("contentVersion", "1.0.0.0"))
            populated_template.setdefault("resources", template.get("resources", []))

            return cast(Optional[Dict[str, Any]], populated_template)

        except Exception as e:
            self.logger.error(f"Failed to populate template parameters: {e}")
            return None

    def _resolve_variables(self, variables: Dict[str, Any], param_values: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve variables that may contain parameter references.

        Args:
            variables: Dictionary of template variables
            param_values: Dictionary of parameter values

        Returns:
            Dictionary of resolved variables
        """
        resolved_variables: Dict[str, Any] = {}
        remaining_variables = variables.copy()
        max_iterations = len(variables) + 1
        iteration = 0

        while remaining_variables and iteration < max_iterations:
            iteration += 1
            resolved_in_this_iteration = []

            for var_name, var_value in remaining_variables.items():
                try:
                    if isinstance(var_value, str) and var_value.startswith("[") and var_value.endswith("]"):
                        resolved_value = self._resolve_arm_expression(var_value[1:-1], param_values, resolved_variables)
                        # Check if still has unresolved references
                        if isinstance(resolved_value, str) and "[" in resolved_value and "]" in resolved_value:
                            continue
                        resolved_variables[var_name] = resolved_value
                    else:
                        resolved_variables[var_name] = var_value

                    resolved_in_this_iteration.append(var_name)

                except Exception as e:
                    self.logger.warning(f"Failed to resolve variable '{var_name}': {e}")
                    resolved_variables[var_name] = var_value
                    resolved_in_this_iteration.append(var_name)

            # Remove resolved variables
            for var_name in resolved_in_this_iteration:
                remaining_variables.pop(var_name, None)

            # Check for circular dependencies
            if not resolved_in_this_iteration:
                self.logger.warning(
                    f"Could not resolve {len(remaining_variables)} variables "
                    f"(circular dependencies or missing references)"
                )
                resolved_variables.update(remaining_variables)
                break

        return resolved_variables

    def _resolve_template_recursively(
        self, template: Any, param_values: Dict[str, Any], variables: Dict[str, Any]
    ) -> Any:
        """Recursively resolve parameter references in template.

        Args:
            template: Template or template section to process
            param_values: Dictionary of parameter values
            variables: Dictionary of template variables

        Returns:
            Resolved template structure
        """
        if isinstance(template, dict):
            resolved = {}
            for key, value in template.items():
                resolved[key] = self._resolve_template_recursively(value, param_values, variables)
            return resolved
        elif isinstance(template, list):
            return [self._resolve_template_recursively(item, param_values, variables) for item in template]
        elif isinstance(template, str):
            return self._resolve_parameter_references(template, param_values, variables)
        else:
            return template

    def _resolve_parameter_references(self, value: str, param_values: Dict[str, Any], variables: Dict[str, Any]) -> Any:
        """Resolve ARM template parameter references in a string.

        Handles expressions like:
        - [parameters('paramName')]
        - [variables('varName')]
        - [concat('prefix-', parameters('name'))]
        - [resourceId(...)]

        Args:
            value: String that may contain parameter references
            param_values: Dictionary of parameter values
            variables: Dictionary of variables

        Returns:
            Resolved value
        """
        if not isinstance(value, str):
            return value

        # Handle bracketed ARM expressions
        if value.strip().startswith("[") and value.strip().endswith("]"):
            expression = value.strip()[1:-1]
            return self._resolve_arm_expression(expression, param_values, variables)

        return value

    def _resolve_arm_expression(self, expression: str, param_values: Dict[str, Any], variables: Dict[str, Any]) -> Any:
        """Resolve an ARM template expression.

        Args:
            expression: ARM expression without brackets
            param_values: Dictionary of parameter values
            variables: Dictionary of variables

        Returns:
            Resolved value
        """
        expression = expression.strip()

        # Handle parameters() function
        if expression.startswith("parameters('") or expression.startswith('parameters("'):
            param_name = expression[12:-2]  # Extract param name
            return param_values.get(param_name, f"[parameters('{param_name}')]")

        # Handle variables() function
        if expression.startswith("variables('") or expression.startswith('variables("'):
            var_name = expression[11:-2]  # Extract variable name
            return variables.get(var_name, f"[variables('{var_name}')]")

        # Handle concat() function
        if expression.startswith("concat("):
            try:
                # Simple concat resolution
                inner = expression[7:-1]  # Remove 'concat(' and ')'
                parts = []
                for part in self._split_function_args(inner):
                    part = part.strip().strip("'\"")
                    if part.startswith("parameters(") or part.startswith("variables("):
                        resolved = self._resolve_arm_expression(part, param_values, variables)
                        parts.append(str(resolved))
                    else:
                        parts.append(part)
                return "".join(parts)
            except Exception as e:
                self.logger.debug(f"Failed to resolve concat: {e}")
                return f"[{expression}]"

        # Handle resourceId() function - return as-is for now
        if expression.startswith("resourceId("):
            return f"[{expression}]"

        # For other functions, return as-is
        return f"[{expression}]"

    def _split_function_args(self, args_string: str) -> List[str]:
        """Split function arguments respecting nested parentheses and quotes.

        Args:
            args_string: String containing function arguments

        Returns:
            List of argument strings
        """
        args = []
        current_arg = []
        paren_depth = 0
        in_quotes = False
        quote_char = None

        for char in args_string:
            if char in ('"', "'") and (not in_quotes or char == quote_char):
                in_quotes = not in_quotes
                quote_char = char if in_quotes else None
                current_arg.append(char)
            elif char == "(" and not in_quotes:
                paren_depth += 1
                current_arg.append(char)
            elif char == ")" and not in_quotes:
                paren_depth -= 1
                current_arg.append(char)
            elif char == "," and paren_depth == 0 and not in_quotes:
                args.append("".join(current_arg))
                current_arg = []
            else:
                current_arg.append(char)

        if current_arg:
            args.append("".join(current_arg))

        return args

    def extract_resources(self, template: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Extract resources from a template.

        Args:
            template: Template to extract from (uses current_template if None)

        Returns:
            List of resource dictionaries
        """
        if template is None:
            template = self.current_template

        if not template:
            self.logger.warning("No template loaded")
            return []

        resources: List[Dict[str, Any]] = template.get("resources", [])
        return resources

    def extract_resource_by_type(
        self, resource_type: str, template: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Extract resources of a specific type from template.

        Args:
            resource_type: Azure resource type to filter by
            template: Template to extract from (uses current_template if None)

        Returns:
            List of matching resource dictionaries
        """
        resources = self.extract_resources(template)
        return [resource for resource in resources if resource.get("type") == resource_type]
