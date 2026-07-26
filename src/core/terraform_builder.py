"""Terraform JSON builder for CloudHorus offline visualization.

This module converts Terraform `show -json` plan/state documents into the
existing local-template renderer shape used by CloudHorus template mode.
"""

import json
import os
import re
import subprocess
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import hcl2

from cloudhorus.models.local_template_document import LocalTemplateDocument, LocalTemplateResource
from core.plan_diff import (
    UNCHANGED_CATEGORY,
    ChangeExtractor,
    ChangeFilter,
    ChangeModel,
    parse_change_types,
)
from utils.logger import SingletonLogger

logger = SingletonLogger().get_logger()

_SUPPORTED_PROVIDER_NAMES = {"azurerm", "registry.terraform.io/hashicorp/azurerm"}
_REFERENCE_PATTERN = re.compile(r"\$\{([^}]+)\}")

# Literal written in place of any value a plan marks as sensitive (Requirement 10.1).
_SENSITIVE_PLACEHOLDER = "(sensitive)"
_SENSITIVE_PHASES = ("before", "after")

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
    "azurerm_mssql_server": "Microsoft.Sql/servers",
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
        # Single-entry identity cache for sensitivity lookups. The document reference is
        # kept alongside its id so the id stays valid while the cache is live.
        self._sensitive_cache: Optional[Tuple[int, Dict[str, Any], Dict[str, Any], Dict[str, Any]]] = None

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

        if not isinstance(data, dict):
            raise ValueError(
                f"Terraform JSON must be a JSON object, got {type(data).__name__}"
            )

        format_version = str(data.get("format_version", "1.0"))
        major_version = format_version.split(".")[0]
        if major_version and major_version != "1":
            raise ValueError(f"Unsupported Terraform JSON format version: {format_version}")

        has_values = isinstance(data.get("planned_values"), dict) or isinstance(data.get("values"), dict)
        if not has_values:
            raise ValueError("Terraform JSON must contain either planned_values or values")

        return data

    def build_document_from_json(
        self,
        terraform_json: Dict[str, Any],
        change_model: Optional[ChangeModel] = None,
    ) -> LocalTemplateDocument:
        """Build a normalized local template document from Terraform JSON.

        `change_model` is optional and trailing: when it is `None` the legacy path runs
        unchanged, producing a document identical to the pre-plan-diff behaviour. When a model
        is supplied (Plan_Diff_Mode), the document additionally carries the resources the plan
        destroys, redacted sensitive leaves, a `change_category` per resource and the change
        metadata (Requirements 3.3, 3.5, 4.1, 4.4, 10.1).
        """
        values_root = terraform_json.get("planned_values") or terraform_json.get("values") or {}
        root_module = values_root.get("root_module", {})
        planned_resources = self._collect_planned_resources(root_module)
        config_resources = self._collect_configuration_resources(terraform_json.get("configuration", {}).get("root_module"))

        source_format = "terraform-plan-json" if terraform_json.get("planned_values") else "terraform-state-json"

        if change_model is not None:
            planned_resources = self._merge_change_resources(terraform_json, planned_resources, change_model)

        document = self._build_document_from_resources(
            planned_resources=planned_resources,
            config_resources=config_resources,
            source_format=source_format,
            metadata={
                "terraformVersion": terraform_json.get("terraform_version"),
                "formatVersion": terraform_json.get("format_version", "1.0"),
            },
        )

        if change_model is not None:
            self._apply_change_model(document, change_model)

        return document

    def _merge_change_resources(
        self,
        terraform_json: Dict[str, Any],
        planned_resources: List[Dict[str, Any]],
        change_model: ChangeModel,
    ) -> List[Dict[str, Any]]:
        """Merge planned resources with reconstructed deletes, redacting sensitive leaves.

        Planned resources come first, so an address present in both `planned_values` and a
        delete record (a `replace`) keeps the `planned_values` values and appears exactly once
        (Requirement 3.3). Deduplication happens before normalization, on the Terraform address.
        Each resource's `values` tree is redacted against its own sensitivity mask:
        `after_sensitive` for planned resources and `before_sensitive` for reconstructed deletes
        (Requirement 10.1).
        """
        merged: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        reconstructed = self._reconstruct_deleted_resources(terraform_json, change_model)

        for phase, resources in (("after", planned_resources), ("before", reconstructed)):
            for resource in resources:
                if not isinstance(resource, dict):
                    continue
                address = resource.get("address")
                if isinstance(address, str) and address:
                    if address in seen:
                        self.logger.warning(
                            "Duplicate Terraform address %s in plan resources; keeping the first entry", address
                        )
                        continue
                    seen.add(address)
                merged.append(self._redact_resource_values(terraform_json, resource, phase))

        return merged

    def _redact_resource_values(
        self, terraform_json: Dict[str, Any], resource: Dict[str, Any], phase: str
    ) -> Dict[str, Any]:
        """Return the resource with every sensitive leaf of its `values` masked."""
        address = resource.get("address")
        if not isinstance(address, str) or not address:
            return resource

        mask = self._sensitive_mask_for(terraform_json, address, phase)
        if mask is None:
            return resource

        redacted = dict(resource)
        redacted["values"] = self._redact_sensitive(resource.get("values"), mask)
        return redacted

    def _apply_change_model(self, document: LocalTemplateDocument, change_model: ChangeModel) -> None:
        """Attach the Change_Category of every resource and the change metadata.

        Resources present in `planned_values` but absent from `resource_changes` default to
        `unchanged` (Requirement 4.1). The metadata gains `changeCounts`, the round-trippable
        `changeModel` payload and `changesNotDisplayed` (Requirement 4.4).
        """
        for resource in document.resources:
            resource.change_category = change_model.category_for(resource.address) or UNCHANGED_CATEGORY

        document.metadata["changeCounts"] = dict(change_model.counts)
        document.metadata["changeModel"] = change_model.to_metadata()
        document.metadata["changesNotDisplayed"] = self._changes_without_resource_entry(document, change_model)

    @staticmethod
    def _changes_without_resource_entry(
        document: LocalTemplateDocument, change_model: ChangeModel
    ) -> List[Dict[str, Any]]:
        """List the changes that reached no resource entry in the document.

        This is the part of the Change_Summary derivable at build time. Reasons that depend on
        rendering (`skip-filter`, `unmapped-type`) are added later by the graph pipeline, which
        keeps this key's shape stable: a list of `{address, terraformType, category, reason}`.
        """
        present = {resource.address for resource in document.resources}
        return [
            {
                "address": record.address,
                "terraformType": record.terraform_type,
                "category": record.category,
                "reason": "no-resource-entry",
            }
            for record in change_model.records.values()
            if record.address not in present
        ]

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

        self._attach_subnets_to_virtual_networks(normalized_resources)

        return LocalTemplateDocument(
            source_format=source_format,
            provider_name="azurerm",
            resources=normalized_resources,
            metadata=metadata,
        )

    def _build_plan_document(
        self, terraform_json: Dict[str, Any], change_types: Optional[Sequence[str]] = None
    ) -> LocalTemplateDocument:
        """Build the document for a plan/state file, in Legacy_Mode or Plan_Diff_Mode.

        A plan without a `resource_changes` key takes the exact legacy path: no Change_Model, no
        filter, so the renderer template stays byte-identical (Requirement 8.1). An empty
        `resource_changes` array is Plan_Diff_Mode with every resource `unchanged`, reported with
        the Requirement 9.5 message.
        """
        raw_changes = terraform_json.get("resource_changes")
        if raw_changes is None:
            return self.build_document_from_json(terraform_json)

        change_model = ChangeExtractor().extract(raw_changes)
        if isinstance(raw_changes, list) and not raw_changes:
            self.logger.info("Plan contains no resource changes")

        document = self.build_document_from_json(terraform_json, change_model=change_model)
        filtered = ChangeFilter(parse_change_types(change_types)).apply(document)
        return filtered if filtered is not None else document

    def build_terraform_template(
        self,
        terraform_json_file: str,
        output_file: Optional[str] = None,
        change_types: Optional[Sequence[str]] = None,
    ) -> Optional[str]:
        """Convert a Terraform show-json file into the current local-template JSON contract.

        `change_types` is trailing and optional. Without a `resource_changes` array in the plan
        the legacy path runs untouched (Requirement 8.1). With one, the Change_Model is extracted,
        the document is built with it and then restricted to the selected Change_Categories
        (Requirements 1.1, 1.2, 6.9). The temp-file contract and the exception guard returning
        `None` are unchanged (Requirements 9.1, 9.3).
        """
        try:
            terraform_json = self.load_terraform_json(terraform_json_file)
            document = self._build_plan_document(terraform_json, change_types)
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

    def _sensitive_indexes(self, terraform_json: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Index a plan document by address for sensitivity lookups.

        Returns `(changes_by_address, planned_sensitive_by_address)` where the first maps an
        address to its `resource_changes[].change` object and the second maps an address to the
        planned resource's own `sensitive_values`.
        """
        cached = self._sensitive_cache
        if cached is not None and cached[0] == id(terraform_json):
            return cached[2], cached[3]

        changes_by_address: Dict[str, Any] = {}
        raw_changes = terraform_json.get("resource_changes")
        if isinstance(raw_changes, list):
            for entry in raw_changes:
                if not isinstance(entry, dict):
                    continue
                address = entry.get("address")
                if isinstance(address, str) and address not in changes_by_address:
                    changes_by_address[address] = entry.get("change")

        planned_sensitive_by_address: Dict[str, Any] = {}
        values_root = terraform_json.get("planned_values") or terraform_json.get("values") or {}
        root_module = values_root.get("root_module", {}) if isinstance(values_root, dict) else {}
        for resource in self._collect_planned_resources(root_module if isinstance(root_module, dict) else {}):
            if not isinstance(resource, dict):
                continue
            address = resource.get("address")
            if isinstance(address, str) and address not in planned_sensitive_by_address:
                planned_sensitive_by_address[address] = resource.get("sensitive_values")

        self._sensitive_cache = (id(terraform_json), terraform_json, changes_by_address, planned_sensitive_by_address)
        return changes_by_address, planned_sensitive_by_address

    def _sensitive_mask_for(self, terraform_json: Dict[str, Any], address: str, phase: str) -> Any:
        """Resolve the sensitivity mask of one resource address for the given phase.

        `phase` is `"after"` for planned resources and `"before"` for reconstructed delete
        resources. An `"after"` lookup falls back to the planned resource's own
        `sensitive_values` when the change object carries no `after_sensitive` (Requirement 10.1).
        Returns `None` when the plan flags nothing for that address.
        """
        if phase not in _SENSITIVE_PHASES or not isinstance(terraform_json, dict) or not isinstance(address, str):
            return None

        changes_by_address, planned_sensitive_by_address = self._sensitive_indexes(terraform_json)

        change = changes_by_address.get(address)
        if isinstance(change, dict):
            mask = change.get(f"{phase}_sensitive")
            if mask is not None:
                return mask

        if phase == "after":
            return planned_sensitive_by_address.get(address)
        return None

    def _redact_sensitive(self, values: Any, mask: Any) -> Any:
        """Replace every leaf the mask flags with `(sensitive)`, preserving all other leaves.

        The mask mirrors the shape of `values`: dictionaries are matched by key (absent keys are
        not sensitive), lists by index, and a scalar `True` marks the whole subtree beneath it.
        """
        if mask is None:
            return values
        if not isinstance(mask, (dict, list)):
            return _SENSITIVE_PLACEHOLDER if bool(mask) else values
        if isinstance(values, dict) and isinstance(mask, dict):
            return {
                key: self._redact_sensitive(child, mask[key]) if key in mask else child
                for key, child in values.items()
            }
        if isinstance(values, list) and isinstance(mask, list):
            return [
                self._redact_sensitive(item, mask[index] if index < len(mask) else None)
                for index, item in enumerate(values)
            ]
        # Shape mismatch between the value tree and the mask: nothing is flagged here.
        return values

    def _reconstruct_deleted_resources(
        self, terraform_json: Dict[str, Any], change_model: Optional[ChangeModel]
    ) -> List[Dict[str, Any]]:
        """Rebuild the resources a plan destroys, which `planned_values` omits.

        `planned_values` describes post-apply state, so every resource scheduled for deletion
        is absent from it and its attributes live only in `resource_changes[].change.before`
        (Requirement 3.1). Each returned entry is shaped exactly like a planned resource
        (`address`, `mode`, `type`, `name`, `provider_name`, `values`) so `_normalize_resource`
        applies the same type mapping and property normalization as for surviving resources
        (Requirement 3.2).

        The entry `name` carries the Terraform address, so `_build_resource_name` falls back to
        the address whenever `before` declares no `name` (Requirement 3.4).
        """
        if not isinstance(terraform_json, dict) or change_model is None:
            return []

        delete_addresses = [
            record.address
            for record in change_model.records.values()
            if record.category == "delete" and record.address
        ]
        if not delete_addresses:
            return []

        values_root = terraform_json.get("planned_values") or terraform_json.get("values") or {}
        root_module = values_root.get("root_module", {}) if isinstance(values_root, dict) else {}
        planned_addresses = {
            resource.get("address")
            for resource in self._collect_planned_resources(root_module if isinstance(root_module, dict) else {})
            if isinstance(resource, dict)
        }

        change_entries = self._index_change_entries(terraform_json)

        reconstructed: List[Dict[str, Any]] = []
        for address in delete_addresses:
            if address in planned_addresses:
                # A surviving planned entry already represents this address (Requirement 3.3).
                continue

            entry = change_entries.get(address)
            if entry is None:
                self.logger.warning(
                    "Cannot reconstruct deleted resource %s: no matching resource_changes entry", address
                )
                continue

            record = change_model.records.get(address)
            change = entry.get("change")
            before = change.get("before") if isinstance(change, dict) else None
            if not isinstance(before, dict):
                self.logger.warning(
                    "Deleted resource %s carries no 'before' object; reconstructing it without values", address
                )
                before = {}

            terraform_type = entry.get("type") or (record.terraform_type if record else "")
            provider_name = entry.get("provider_name") or (record.provider_name if record else "") or "azurerm"

            reconstructed.append(
                {
                    "address": address,
                    "mode": "managed",
                    "type": str(terraform_type or ""),
                    # The address is the Requirement 3.4 display-name fallback for a nameless `before`.
                    "name": address,
                    "provider_name": str(provider_name),
                    "values": dict(before),
                }
            )

        return reconstructed

    def _index_change_entries(self, terraform_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """Index `resource_changes` by address, keeping the first entry per address."""
        entries: Dict[str, Dict[str, Any]] = {}
        raw_changes = terraform_json.get("resource_changes")
        if not isinstance(raw_changes, list):
            return entries
        for entry in raw_changes:
            if not isinstance(entry, dict):
                continue
            address = entry.get("address")
            if isinstance(address, str) and address and address not in entries:
                entries[address] = entry
        return entries

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

        if terraform_type == "azurerm_kubernetes_cluster":
            properties = {}
            agent_pool_profiles = []
            for pool in self._as_block_list(values.get("default_node_pool")):
                subnet_id = pool.get("vnet_subnet_id")
                if not subnet_id:
                    continue
                agent_pool_profile = {
                    "name": pool.get("name", "nodepool1"),
                    "vnetSubnetID": subnet_id,
                }
                if pool.get("type"):
                    agent_pool_profile["type"] = pool.get("type")
                agent_pool_profiles.append(agent_pool_profile)
            if agent_pool_profiles:
                properties["agentPoolProfiles"] = agent_pool_profiles
            return properties

        if terraform_type == "azurerm_private_endpoint":
            properties = {}
            subnet_id = values.get("subnet_id")
            if subnet_id:
                properties["subnet"] = {"id": subnet_id}
            connections = []
            for connection in self._as_block_list(values.get("private_service_connection")):
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
            for ip_configuration in self._as_block_list(values.get("ip_configuration")):
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
            for gateway_configuration in self._as_block_list(values.get("gateway_ip_configuration")):
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

        if resource.renderer_type == "Microsoft.ContainerService/managedClusters" and not resource.properties.get(
            "agentPoolProfiles"
        ):
            subnet_reference = self._first_reference_for_path(config_resource, "default_node_pool", "vnet_subnet_id")
            subnet_resource_id = self._reference_to_resource_id(subnet_reference, address_index)
            if subnet_resource_id:
                resource.properties["agentPoolProfiles"] = [
                    {"name": "nodepool1", "vnetSubnetID": subnet_resource_id}
                ]

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

    def _as_sequence(self, value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _as_block_list(self, value: Any) -> List[Dict[str, Any]]:
        """Return the nested-block entries of `value` as a list of dictionaries.

        Terraform renders a nested block as a list of objects, and a single block as either a
        one-element list or a bare object. Sensitive redaction, however, replaces a whole flagged
        subtree with the literal string ``(sensitive)``, so a block key may hold a scalar instead
        of the expected structure. Every non-dictionary entry is dropped so an opaque redacted
        block is simply not mined for subnet or service ids (Requirements 10.1, 12.8), while a
        normal list of block objects passes through unchanged (Requirement 8.1).
        """
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _attach_subnets_to_virtual_networks(self, resources: List[LocalTemplateResource]) -> None:
        vnet_index = {
            resource.name: resource
            for resource in resources
            if resource.renderer_type == "Microsoft.Network/virtualNetworks"
        }
        if not vnet_index:
            return

        for resource in resources:
            if resource.renderer_type != "Microsoft.Network/virtualNetworks/subnets":
                continue

            vnet_name, _, subnet_name = resource.name.partition("/")
            if not vnet_name or not subnet_name:
                continue

            vnet_resource = vnet_index.get(vnet_name)
            if vnet_resource is None:
                continue

            subnet_entries = vnet_resource.properties.setdefault("subnets", [])
            if any(isinstance(entry, dict) and entry.get("name") == subnet_name for entry in subnet_entries):
                continue

            subnet_entries.append(
                {
                    "name": subnet_name,
                    "properties": dict(resource.properties),
                }
            )


def build_terraform_template(
    terraform_json_file: str,
    output_file: Optional[str] = None,
    change_types: Optional[Sequence[str]] = None,
) -> Optional[str]:
    """Convenience wrapper for Terraform JSON normalization.

    The positional signature is unchanged; `change_types` is trailing and optional so existing
    call sites stay source-compatible.
    """
    builder = TerraformTemplateBuilder()
    return builder.build_terraform_template(terraform_json_file, output_file, change_types)