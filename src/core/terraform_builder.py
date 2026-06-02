"""Terraform JSON builder for CloudHorus offline visualization.

This module converts Terraform `show -json` plan/state documents into the
existing local-template renderer shape used by CloudHorus template mode.
"""

import json
import os
import re
import subprocess
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import hcl2

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource
from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()

_SUPPORTED_PROVIDER_NAMES = {"azurerm", "registry.terraform.io/hashicorp/azurerm"}
_REFERENCE_PATTERN = re.compile(r"\$\{([^}]+)\}")

_TERRAFORM_TO_RENDERER_TYPE = {
    "azurerm_api_management": "Microsoft.ApiManagement/service",
    "azurerm_application_gateway": "Microsoft.Network/applicationGateways",
    "azurerm_bastion_host": "Microsoft.Network/bastionHosts",
    "azurerm_kubernetes_cluster": "Microsoft.ContainerService/managedClusters",
    "azurerm_linux_function_app": "Microsoft.Web/sites",
    "azurerm_linux_web_app": "Microsoft.Web/sites",
    "azurerm_mysql_flexible_server": "Microsoft.DBforMySQL/flexibleServers",
    "azurerm_network_security_group": "Microsoft.Network/networkSecurityGroups",
    "azurerm_postgresql_flexible_server": "Microsoft.DBforPostgreSQL/flexibleServers",
    "azurerm_private_dns_zone": "Microsoft.Network/privateDnsZones",
    "azurerm_private_dns_zone_virtual_network_link": "Microsoft.Network/privateDnsZones/virtualNetworkLinks",
    "azurerm_private_endpoint": "Microsoft.Network/privateEndpoints",
    "azurerm_redis_cache": "Microsoft.Cache/Redis",
    "azurerm_route_table": "Microsoft.Network/routeTables",
    "azurerm_service_plan": "Microsoft.Web/serverfarms",
    "azurerm_storage_account": "Microsoft.Storage/storageAccounts",
    "azurerm_subnet": "Microsoft.Network/virtualNetworks/subnets",
    "azurerm_virtual_network": "Microsoft.Network/virtualNetworks",
    "azurerm_windows_function_app": "Microsoft.Web/sites",
    "azurerm_windows_web_app": "Microsoft.Web/sites",
}


class TerraformTemplateBuilder:
    """Convert Terraform JSON documents into CloudHorus local template inputs."""

    def __init__(self) -> None:
        self.logger = logger

    def validate_terraform_cli(self) -> bool:
        """Return True when the Terraform CLI is available."""
        try:
            subprocess.run(
                ["terraform", "version"],
                capture_output=True,
                check=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return False

    def load_terraform_json(self, terraform_json_file: str) -> Dict[str, Any]:
        """Load and validate a Terraform plan/state JSON file."""
        if not os.path.exists(terraform_json_file):
            raise FileNotFoundError(terraform_json_file)

        with open(terraform_json_file, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        format_version = str(data.get("format_version", "1.0"))
        major_version = format_version.split(".")[0]
        if major_version and major_version != "1":
            raise ValueError(f"Unsupported Terraform JSON format version: {format_version}")

        has_values = isinstance(data.get("planned_values"), dict) or isinstance(data.get("values"), dict)
        if not has_values:
            raise ValueError("Terraform JSON must contain either planned_values or values")

        return data

    def build_document_from_json(self, terraform_json: Dict[str, Any]) -> LocalTemplateDocument:
        """Build a normalized local template document from Terraform JSON."""
        values_root = terraform_json.get("planned_values") or terraform_json.get("values") or {}
        root_module = values_root.get("root_module", {})
        planned_resources = self._collect_planned_resources(root_module)
        config_resources = self._collect_configuration_resources(terraform_json.get("configuration", {}).get("root_module"))

        source_format = "terraform-plan-json" if terraform_json.get("planned_values") else "terraform-state-json"
        return self._build_document_from_resources(
            planned_resources=planned_resources,
            config_resources=config_resources,
            source_format=source_format,
            metadata={
                "terraformVersion": terraform_json.get("terraform_version"),
                "formatVersion": terraform_json.get("format_version", "1.0"),
            },
        )

    def build_document_from_source(
        self, terraform_root_dir: str, var_files: Optional[List[str]] = None
    ) -> LocalTemplateDocument:
        """Build a normalized local template document from local Terraform source files."""
        abs_root_dir = os.path.abspath(terraform_root_dir)
        if not os.path.isdir(abs_root_dir):
            raise FileNotFoundError(terraform_root_dir)

        variable_values = self._load_tfvars_values(var_files or [])
        raw_resources, config_resources = self._collect_source_module_resources(abs_root_dir, variable_values)
        planned_resources = self._build_planned_resources_from_source(raw_resources)

        return self._build_document_from_resources(
            planned_resources=planned_resources,
            config_resources=config_resources,
            source_format="terraform-source-hcl",
            metadata={
                "sourceRoot": abs_root_dir,
                "varFiles": [os.path.abspath(path) for path in (var_files or [])],
            },
        )

    def _build_document_from_resources(
        self,
        planned_resources: List[Dict[str, Any]],
        config_resources: Dict[str, Dict[str, Any]],
        source_format: str,
        metadata: Dict[str, Any],
    ) -> LocalTemplateDocument:
        """Normalize planned/config resources into the renderer-friendly local document model."""

        normalized_resources: List[LocalTemplateResource] = []
        address_index: Dict[str, Tuple[str, str]] = {}

        for resource in planned_resources:
            normalized_resource = self._normalize_resource(resource)
            if normalized_resource is None:
                continue
            normalized_resources.append(normalized_resource)
            address_index[normalized_resource.address] = (
                normalized_resource.renderer_type,
                normalized_resource.name,
            )

        for resource in normalized_resources:
            config_resource = config_resources.get(resource.address)
            references = self._collect_dependency_references(config_resource)
            resource.depends_on = self._references_to_depends_on(references, address_index, resource.address)
            self._populate_reference_backed_properties(resource, config_resource, address_index)

        return LocalTemplateDocument(
            source_format=source_format,
            provider_name="azurerm",
            resources=normalized_resources,
            metadata=metadata,
        )

    def build_terraform_template(
        self, terraform_json_file: str, output_file: Optional[str] = None
    ) -> Optional[str]:
        """Convert a Terraform show-json file into the current local-template JSON contract."""
        try:
            terraform_json = self.load_terraform_json(terraform_json_file)
            document = self.build_document_from_json(terraform_json)
            renderer_template = document.to_renderer_template()

            if output_file is None:
                handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
                output_file = handle.name
                handle.close()

            with open(output_file, "w", encoding="utf-8") as handle:
                json.dump(renderer_template, handle, indent=2)

            return output_file
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            self.logger.error(f"Failed to build Terraform template from {terraform_json_file}: {exc}")
            return None

    def build_terraform_source(
        self, terraform_root_dir: str, var_files: Optional[List[str]] = None, output_file: Optional[str] = None
    ) -> Optional[str]:
        """Parse local Terraform HCL source files into the renderer contract without contacting Azure."""
        try:
            document = self.build_document_from_source(terraform_root_dir, var_files)
            renderer_template = document.to_renderer_template()

            if output_file is None:
                handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
                output_file = handle.name
                handle.close()

            with open(output_file, "w", encoding="utf-8") as handle:
                json.dump(renderer_template, handle, indent=2)

            return output_file
        except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
            self.logger.error(f"Failed to build Terraform source from {terraform_root_dir}: {exc}")
            return None

    def _load_tfvars_values(self, var_files: List[str]) -> Dict[str, Any]:
        """Load and merge tfvars files without invoking Terraform CLI."""
        values: Dict[str, Any] = {}
        for var_file in var_files:
            abs_var_file = os.path.abspath(var_file)
            if not os.path.exists(abs_var_file):
                raise FileNotFoundError(abs_var_file)
            with open(abs_var_file, "r", encoding="utf-8") as handle:
                data = hcl2.load(handle)
            for key, raw_value in data.items():
                values[key] = self._resolve_hcl_value(raw_value, values, {}, "")
        return values

    def _load_hcl_documents(self, module_dir: str) -> Dict[str, List[Any]]:
        """Load all `.tf` files in a module directory and merge the parsed blocks."""
        merged: Dict[str, List[Any]] = {}
        tf_files = sorted(
            file_name for file_name in os.listdir(module_dir) if file_name.endswith(".tf") and os.path.isfile(os.path.join(module_dir, file_name))
        )
        if not tf_files:
            raise FileNotFoundError(f"No Terraform files found in {module_dir}")

        for file_name in tf_files:
            file_path = os.path.join(module_dir, file_name)
            with open(file_path, "r", encoding="utf-8") as handle:
                document = hcl2.load(handle)
            for key, value in document.items():
                if isinstance(value, list):
                    merged.setdefault(key, []).extend(value)
                else:
                    merged[key] = value
        return merged

    def _load_variable_defaults(self, module_documents: Dict[str, List[Any]]) -> Dict[str, Any]:
        """Collect variable defaults from a module's `variable` blocks."""
        defaults: Dict[str, Any] = {}
        for variable_block in module_documents.get("variable", []):
            if not isinstance(variable_block, dict):
                continue
            for variable_name_key, attrs in variable_block.items():
                variable_name = self._strip_hcl_quotes(variable_name_key)
                if isinstance(attrs, dict) and "default" in attrs:
                    defaults[variable_name] = self._resolve_hcl_value(attrs["default"], defaults, {}, "")
        return defaults

    def _collect_source_module_resources(
        self,
        module_dir: str,
        variable_values: Dict[str, Any],
        module_path: str = "",
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Parse local Terraform resources and child modules into Terraform-like resource/config dictionaries."""
        module_documents = self._load_hcl_documents(module_dir)
        scoped_variables = {**self._load_variable_defaults(module_documents), **(variable_values or {})}

        raw_resources: List[Dict[str, Any]] = []
        config_resources: Dict[str, Dict[str, Any]] = {}

        for resource_block in module_documents.get("resource", []):
            if not isinstance(resource_block, dict):
                continue
            for terraform_type_key, instances in resource_block.items():
                terraform_type = self._strip_hcl_quotes(terraform_type_key)
                if not isinstance(instances, dict):
                    continue
                for resource_name_key, raw_attributes in instances.items():
                    if not isinstance(raw_attributes, dict):
                        continue
                    resource_name = self._strip_hcl_quotes(resource_name_key)
                    address = f"{module_path}{terraform_type}.{resource_name}"
                    raw_resources.append(
                        {
                            "address": address,
                            "mode": "managed",
                            "type": terraform_type,
                            "name": resource_name,
                            "provider_name": "registry.terraform.io/hashicorp/azurerm",
                            "raw_attributes": raw_attributes,
                            "variables": dict(scoped_variables),
                        }
                    )
                    config_resources[address] = {
                        "address": address,
                        "expressions": self._build_expression_tree(raw_attributes, module_path),
                    }

        local_planned_resources = self._build_planned_resources_from_source(raw_resources)
        local_resource_state = self._extract_resource_state(local_planned_resources)

        for module_block in module_documents.get("module", []):
            if not isinstance(module_block, dict):
                continue
            for module_name_key, module_attrs in module_block.items():
                if not isinstance(module_attrs, dict):
                    continue
                module_name = self._strip_hcl_quotes(module_name_key)
                child_module_dir = self._resolve_module_source(module_dir, module_attrs.get("source"))
                child_variables: Dict[str, Any] = {}
                for attr_name, raw_value in module_attrs.items():
                    if attr_name in {"source", "__is_block__"}:
                        continue
                    child_variables[attr_name] = self._resolve_hcl_value(
                        raw_value,
                        scoped_variables,
                        local_resource_state,
                        module_path,
                    )

                child_resources, child_config_resources = self._collect_source_module_resources(
                    child_module_dir,
                    child_variables,
                    f"{module_path}module.{module_name}.",
                )
                raw_resources.extend(child_resources)
                config_resources.update(child_config_resources)

        return raw_resources, config_resources

    def _build_planned_resources_from_source(self, raw_resources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Resolve source resources iteratively so local name/id references settle without Terraform plan output."""
        resource_state: Dict[str, Dict[str, Any]] = {}
        planned_resources_by_address: Dict[str, Dict[str, Any]] = {}
        max_passes = max(2, len(raw_resources) * 2)

        for _ in range(max_passes):
            changed = False
            for raw_resource in raw_resources:
                module_path = self._module_path_for_address(raw_resource["address"])
                values = self._resolve_hcl_value(
                    raw_resource.get("raw_attributes", {}),
                    raw_resource.get("variables", {}),
                    resource_state,
                    module_path,
                )
                if not isinstance(values, dict):
                    values = {}

                planned_resource = {
                    "address": raw_resource["address"],
                    "mode": raw_resource["mode"],
                    "type": raw_resource["type"],
                    "name": raw_resource["name"],
                    "provider_name": raw_resource["provider_name"],
                    "values": values,
                }

                if planned_resources_by_address.get(raw_resource["address"]) != planned_resource:
                    planned_resources_by_address[raw_resource["address"]] = planned_resource
                    changed = True

                normalized_resource = self._normalize_resource(planned_resource)
                if normalized_resource is None:
                    continue

                resolved_state = {
                    "name": normalized_resource.name,
                    "id": self._resource_id_expression(normalized_resource.renderer_type, normalized_resource.name),
                }
                if resource_state.get(raw_resource["address"]) != resolved_state:
                    resource_state[raw_resource["address"]] = resolved_state
                    changed = True

            if not changed:
                break

        return [planned_resources_by_address[raw_resource["address"]] for raw_resource in raw_resources if raw_resource["address"] in planned_resources_by_address]

    def _extract_resource_state(self, planned_resources: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Extract name/id lookup state from planned resources for expression resolution."""
        resource_state: Dict[str, Dict[str, Any]] = {}
        for planned_resource in planned_resources:
            normalized_resource = self._normalize_resource(planned_resource)
            if normalized_resource is None:
                continue
            resource_state[planned_resource["address"]] = {
                "name": normalized_resource.name,
                "id": self._resource_id_expression(normalized_resource.renderer_type, normalized_resource.name),
            }
        return resource_state

    def _build_expression_tree(self, node: Any, module_path: str) -> Any:
        """Convert parsed HCL into a Terraform-JSON-like expressions tree with references."""
        if isinstance(node, dict):
            expression_tree: Dict[str, Any] = {}
            for key, value in node.items():
                if key == "__is_block__":
                    continue
                expression_tree[key] = self._build_expression_tree(value, module_path)
            return expression_tree

        if isinstance(node, list):
            return [self._build_expression_tree(item, module_path) for item in node]

        if isinstance(node, str):
            cleaned_value = self._strip_hcl_quotes(node)
            references = [self._qualify_reference(ref, module_path) for ref in self._extract_hcl_references(cleaned_value)]
            if references:
                return {"references": references}
            return {"constant_value": cleaned_value}

        return {"constant_value": node}

    def _resolve_hcl_value(
        self,
        node: Any,
        variables: Dict[str, Any],
        resource_state: Dict[str, Dict[str, Any]],
        module_path: str,
    ) -> Any:
        """Resolve simple Terraform expressions locally using tfvars and already-known resource names/ids."""
        if isinstance(node, dict):
            resolved: Dict[str, Any] = {}
            for key, value in node.items():
                if key == "__is_block__":
                    continue
                resolved[key] = self._resolve_hcl_value(value, variables, resource_state, module_path)
            return resolved

        if isinstance(node, list):
            return [self._resolve_hcl_value(item, variables, resource_state, module_path) for item in node]

        if isinstance(node, str):
            return self._resolve_hcl_string(node, variables, resource_state, module_path)

        return node

    def _resolve_hcl_string(
        self,
        raw_value: str,
        variables: Dict[str, Any],
        resource_state: Dict[str, Dict[str, Any]],
        module_path: str,
    ) -> Any:
        """Resolve Terraform interpolation strings against local variables and resource lookups."""
        cleaned_value = self._strip_hcl_quotes(raw_value)
        references = self._extract_hcl_references(cleaned_value)
        if not references:
            return cleaned_value

        if len(references) == 1 and cleaned_value == f"${{{references[0]}}}":
            resolved_value = self._resolve_expression(references[0], variables, resource_state, module_path)
            return cleaned_value if resolved_value is None else resolved_value

        resolved_text = cleaned_value
        for reference in references:
            resolved_value = self._resolve_expression(reference, variables, resource_state, module_path)
            if resolved_value is None:
                replacement = f"${{{reference}}}"
            elif isinstance(resolved_value, (dict, list)):
                replacement = json.dumps(resolved_value)
            else:
                replacement = str(resolved_value)
            resolved_text = resolved_text.replace(f"${{{reference}}}", replacement)
        return resolved_text

    def _resolve_expression(
        self,
        expression: str,
        variables: Dict[str, Any],
        resource_state: Dict[str, Dict[str, Any]],
        module_path: str,
    ) -> Any:
        """Resolve a Terraform reference expression against local variables and known resources."""
        expression = expression.strip()
        if expression.startswith("var."):
            return variables.get(expression[4:])

        qualified_reference = self._qualify_reference(expression, module_path)
        for candidate in sorted(resource_state.keys(), key=len, reverse=True):
            if qualified_reference.startswith(f"{candidate}."):
                attribute_name = qualified_reference[len(candidate) + 1 :]
                return resource_state.get(candidate, {}).get(attribute_name)

        return None

    def _extract_hcl_references(self, value: str) -> List[str]:
        """Extract Terraform interpolation references from a parsed HCL string."""
        return [match.strip() for match in _REFERENCE_PATTERN.findall(value)]

    def _qualify_reference(self, reference: str, module_path: str) -> str:
        """Qualify local resource references with their module path so addresses match Terraform JSON style."""
        reference = reference.strip()
        if reference.startswith("var."):
            return reference
        if reference.startswith("module."):
            return f"{module_path}{reference}" if module_path else reference

        first_segment = reference.split(".", 1)[0]
        if first_segment.startswith("azurerm_"):
            return f"{module_path}{reference}" if module_path else reference
        return reference

    def _resolve_module_source(self, module_dir: str, raw_source: Any) -> str:
        """Resolve a local module `source` attribute to an absolute directory path."""
        source_value = self._resolve_hcl_value(raw_source, {}, {}, "")
        if not isinstance(source_value, str):
            raise ValueError(f"Unsupported module source in {module_dir}: {raw_source}")

        if source_value.startswith("./") or source_value.startswith("../"):
            return os.path.abspath(os.path.join(module_dir, source_value))

        if os.path.isabs(source_value):
            return source_value

        raise ValueError(f"Only local module sources are supported in offline Terraform mode: {source_value}")

    def _module_path_for_address(self, address: str) -> str:
        """Return the Terraform module path prefix for a resource address."""
        parts = address.split(".")
        if len(parts) <= 2:
            return ""
        return ".".join(parts[:-2]) + "."

    def _strip_hcl_quotes(self, value: str) -> str:
        """Normalize HCL parser string output by removing literal wrapping quotes when present."""
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value[1:-1]
        return value

    def _collect_planned_resources(self, module_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        resources = list(module_data.get("resources", [])) if module_data else []
        for child_module in module_data.get("child_modules", []) if module_data else []:
            resources.extend(self._collect_planned_resources(child_module))
        return resources

    def _collect_configuration_resources(self, module_data: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        resources: Dict[str, Dict[str, Any]] = {}
        if not module_data:
            return resources

        for resource in module_data.get("resources", []):
            address = resource.get("address")
            if isinstance(address, str):
                resources[address] = resource

        for module_call in module_data.get("module_calls", {}).values():
            child_module = module_call.get("module")
            resources.update(self._collect_configuration_resources(child_module))

        return resources

    def _normalize_resource(self, terraform_resource: Dict[str, Any]) -> Optional[LocalTemplateResource]:
        if terraform_resource.get("mode") != "managed":
            return None

        provider_name = terraform_resource.get("provider_name")
        terraform_type = terraform_resource.get("type", "")
        if provider_name not in _SUPPORTED_PROVIDER_NAMES and not terraform_type.startswith("azurerm_"):
            return None

        renderer_type = _TERRAFORM_TO_RENDERER_TYPE.get(terraform_type)
        if renderer_type is None:
            renderer_type = f"Terraform.Azurerm/{terraform_type.replace('azurerm_', '', 1)}"

        values = dict(terraform_resource.get("values") or {})
        name = self._build_resource_name(terraform_type, terraform_resource, values)
        properties = self._build_resource_properties(terraform_type, values)
        extra_fields = self._build_extra_fields(values)

        return LocalTemplateResource(
            address=str(terraform_resource.get("address", name)),
            provider_name=str(provider_name or "azurerm"),
            source_type=terraform_type,
            renderer_type=renderer_type,
            name=name,
            properties=properties,
            extra_fields=extra_fields,
            raw_values=values,
        )

    def _build_resource_name(self, terraform_type: str, terraform_resource: Dict[str, Any], values: Dict[str, Any]) -> str:
        resource_name = values.get("name") or terraform_resource.get("name") or terraform_resource.get("address", "resource")
        if terraform_type == "azurerm_subnet":
            vnet_name = values.get("virtual_network_name")
            if vnet_name and resource_name:
                return f"{vnet_name}/{resource_name}"
        if terraform_type == "azurerm_private_dns_zone_virtual_network_link":
            zone_name = values.get("private_dns_zone_name")
            if zone_name and resource_name:
                return f"{zone_name}/{resource_name}"
        return str(resource_name)

    def _build_resource_properties(self, terraform_type: str, values: Dict[str, Any]) -> Dict[str, Any]:
        if terraform_type == "azurerm_virtual_network":
            return {
                "addressSpace": {
                    "addressPrefixes": values.get("address_space", []),
                }
            }

        if terraform_type == "azurerm_subnet":
            properties: Dict[str, Any] = {}
            address_prefixes = values.get("address_prefixes") or []
            if address_prefixes:
                if len(address_prefixes) == 1:
                    properties["addressPrefix"] = address_prefixes[0]
                else:
                    properties["addressPrefixes"] = address_prefixes
            if values.get("service_endpoints"):
                properties["serviceEndpoints"] = values.get("service_endpoints")
            return properties

        if terraform_type in {"azurerm_linux_web_app", "azurerm_windows_web_app", "azurerm_linux_function_app", "azurerm_windows_function_app"}:
            properties = {}
            subnet_id = values.get("virtual_network_subnet_id")
            if subnet_id:
                properties["virtualNetworkSubnetId"] = subnet_id
            return properties

        if terraform_type == "azurerm_private_endpoint":
            properties = {}
            subnet_id = values.get("subnet_id")
            if subnet_id:
                properties["subnet"] = {"id": subnet_id}
            connections = []
            for connection in values.get("private_service_connection", []) or []:
                service_id = connection.get("private_connection_resource_id")
                if service_id:
                    connections.append({"properties": {"privateLinkServiceId": service_id}})
            if connections:
                properties["privateLinkServiceConnections"] = connections
            return properties

        if terraform_type == "azurerm_private_dns_zone_virtual_network_link":
            vnet_id = values.get("virtual_network_id")
            return {"virtualNetwork": {"id": vnet_id}} if vnet_id else {}

        if terraform_type == "azurerm_bastion_host":
            ip_configurations = []
            for ip_configuration in values.get("ip_configuration", []) or []:
                subnet_id = ip_configuration.get("subnet_id")
                if not subnet_id:
                    continue
                ip_configurations.append(
                    {
                        "name": ip_configuration.get("name", "ipconfig"),
                        "properties": {"subnet": {"id": subnet_id}},
                    }
                )
            return {"ipConfigurations": ip_configurations} if ip_configurations else {}

        if terraform_type == "azurerm_application_gateway":
            gateway_configs = []
            for gateway_configuration in values.get("gateway_ip_configuration", []) or []:
                subnet_id = gateway_configuration.get("subnet_id")
                if not subnet_id:
                    continue
                gateway_configs.append(
                    {
                        "name": gateway_configuration.get("name", "gateway"),
                        "properties": {"subnet": {"id": subnet_id}},
                    }
                )
            return {"gatewayIPConfigurations": gateway_configs} if gateway_configs else {}

        return {}

    def _build_extra_fields(self, values: Dict[str, Any]) -> Dict[str, Any]:
        extra_fields: Dict[str, Any] = {}
        for key in ("kind", "location", "sku", "tags"):
            value = values.get(key)
            if value is not None:
                extra_fields[key] = value
        return extra_fields

    def _collect_dependency_references(self, config_resource: Optional[Dict[str, Any]]) -> List[str]:
        if not config_resource:
            return []

        references = list(dict.fromkeys(self._extract_references(config_resource.get("expressions", {}))))
        explicit_depends_on = config_resource.get("depends_on") or []
        for ref in explicit_depends_on:
            if isinstance(ref, str) and ref not in references:
                references.append(ref)
        return references

    def _extract_references(self, node: Any) -> List[str]:
        references: List[str] = []
        if isinstance(node, dict):
            value = node.get("references")
            if isinstance(value, list):
                references.extend(ref for ref in value if isinstance(ref, str))
            for child in node.values():
                references.extend(self._extract_references(child))
        elif isinstance(node, list):
            for item in node:
                references.extend(self._extract_references(item))
        return references

    def _references_to_depends_on(
        self, references: Iterable[str], address_index: Dict[str, Tuple[str, str]], self_address: str
    ) -> List[str]:
        depends_on: List[str] = []
        seen: Set[str] = set()
        for reference in references:
            resolved_reference = self._resolve_reference_target(reference, address_index)
            if resolved_reference == self_address:
                continue
            target = address_index.get(resolved_reference) if resolved_reference else None
            if not target:
                continue
            resource_id = self._resource_id_expression(target[0], target[1])
            if resource_id not in seen:
                seen.add(resource_id)
                depends_on.append(resource_id)
        return depends_on

    def _populate_reference_backed_properties(
        self,
        resource: LocalTemplateResource,
        config_resource: Optional[Dict[str, Any]],
        address_index: Dict[str, Tuple[str, str]],
    ) -> None:
        if not config_resource:
            return

        if resource.renderer_type == "Microsoft.Web/sites" and "virtualNetworkSubnetId" not in resource.properties:
            reference = self._first_reference_for_path(config_resource, "virtual_network_subnet_id")
            resource_id = self._reference_to_resource_id(reference, address_index)
            if resource_id:
                resource.properties["virtualNetworkSubnetId"] = resource_id

        if resource.renderer_type == "Microsoft.Network/privateEndpoints":
            subnet_reference = self._first_reference_for_path(config_resource, "subnet_id")
            subnet_resource_id = self._reference_to_resource_id(subnet_reference, address_index)
            if subnet_resource_id and "subnet" not in resource.properties:
                resource.properties["subnet"] = {"id": subnet_resource_id}

            service_reference = self._first_reference_for_path(
                config_resource, "private_service_connection", "private_connection_resource_id"
            )
            service_resource_id = self._reference_to_resource_id(service_reference, address_index)
            if service_resource_id and "privateLinkServiceConnections" not in resource.properties:
                resource.properties["privateLinkServiceConnections"] = [
                    {"properties": {"privateLinkServiceId": service_resource_id}}
                ]

        if resource.renderer_type == "Microsoft.Network/privateDnsZones/virtualNetworkLinks":
            vnet_reference = self._first_reference_for_path(config_resource, "virtual_network_id")
            vnet_resource_id = self._reference_to_resource_id(vnet_reference, address_index)
            if vnet_resource_id and resource.properties.get("virtualNetwork", {}).get("id") is None:
                resource.properties["virtualNetwork"] = {"id": vnet_resource_id}

        if resource.renderer_type == "Microsoft.Network/bastionHosts" and not resource.properties.get("ipConfigurations"):
            subnet_reference = self._first_reference_for_path(config_resource, "ip_configuration", "subnet_id")
            subnet_resource_id = self._reference_to_resource_id(subnet_reference, address_index)
            if subnet_resource_id:
                resource.properties["ipConfigurations"] = [
                    {"name": "ipconfig", "properties": {"subnet": {"id": subnet_resource_id}}}
                ]

        if resource.renderer_type == "Microsoft.Network/applicationGateways" and not resource.properties.get(
            "gatewayIPConfigurations"
        ):
            subnet_reference = self._first_reference_for_path(config_resource, "gateway_ip_configuration", "subnet_id")
            subnet_resource_id = self._reference_to_resource_id(subnet_reference, address_index)
            if subnet_resource_id:
                resource.properties["gatewayIPConfigurations"] = [
                    {"name": "gateway", "properties": {"subnet": {"id": subnet_resource_id}}}
                ]

    def _first_reference_for_path(self, config_resource: Dict[str, Any], *path: str) -> Optional[str]:
        current: Any = config_resource.get("expressions", {})
        for key in path:
            if isinstance(current, list):
                current = current[0] if current else None
            if not isinstance(current, dict):
                return None
            current = current.get(key)
            if current is None:
                return None

        references = self._extract_references(current)
        return references[0] if references else None

    def _reference_to_resource_id(
        self, reference: Optional[str], address_index: Dict[str, Tuple[str, str]]
    ) -> Optional[str]:
        if not reference:
            return None
        resolved_reference = self._resolve_reference_target(reference, address_index)
        target = address_index.get(resolved_reference) if resolved_reference else None
        if not target:
            return None
        return self._resource_id_expression(target[0], target[1])

    def _resolve_reference_target(
        self, reference: str, address_index: Dict[str, Tuple[str, str]]
    ) -> Optional[str]:
        if reference in address_index:
            return reference

        for candidate in sorted(address_index.keys(), key=len, reverse=True):
            if reference.startswith(f"{candidate}."):
                return candidate

        return None

    def _resource_id_expression(self, renderer_type: str, resource_name: str) -> str:
        escaped_name_parts = [segment.replace("'", "''") for segment in resource_name.split("/") if segment]
        quoted_name_parts = ", ".join(f"'{segment}'" for segment in escaped_name_parts)
        if quoted_name_parts:
            return f"[resourceId('{renderer_type}', {quoted_name_parts})]"
        return f"[resourceId('{renderer_type}')]"


def build_terraform_template(terraform_json_file: str, output_file: Optional[str] = None) -> Optional[str]:
    """Convenience wrapper for Terraform JSON normalization."""
    builder = TerraformTemplateBuilder()
    return builder.build_terraform_template(terraform_json_file, output_file)