"""Unit tests for delete reconstruction in the Terraform plan builder.

Covers Requirements 3.1, 3.2 and 3.4: resources a plan destroys are absent from
`planned_values`, so they are rebuilt from `resource_changes[].change.before`,
shaped like a planned resource so the existing normalization applies, with the
Terraform address as the display-name fallback.
"""

from typing import Any, Dict, List, Optional

from core.plan_diff import ChangeExtractor, ChangeModel, ChangeRecord
from core.terraform_builder import TerraformTemplateBuilder

PROVIDER = "registry.terraform.io/hashicorp/azurerm"


def _builder() -> TerraformTemplateBuilder:
    return TerraformTemplateBuilder()


def _change_entry(
    address: str,
    terraform_type: str,
    actions: List[str],
    before: Optional[Dict[str, Any]] = None,
    *,
    name: str = "instance",
    provider_name: str = PROVIDER,
    mode: str = "managed",
) -> Dict[str, Any]:
    """Build one `resource_changes` entry."""
    return {
        "address": address,
        "mode": mode,
        "type": terraform_type,
        "name": name,
        "provider_name": provider_name,
        "change": {"actions": actions, "before": before, "after": None},
    }


def _planned_resource(address: str, terraform_type: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Build one `planned_values.root_module.resources` entry."""
    return {
        "address": address,
        "mode": "managed",
        "type": terraform_type,
        "name": address.rsplit(".", 1)[-1],
        "provider_name": PROVIDER,
        "values": values,
    }


def _plan(
    change_entries: List[Dict[str, Any]],
    planned_resources: Optional[List[Dict[str, Any]]] = None,
    child_modules: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build a minimal plan document around the given change and planned entries."""
    root_module: Dict[str, Any] = {"resources": list(planned_resources or [])}
    if child_modules:
        root_module["child_modules"] = child_modules
    return {
        "format_version": "1.2",
        "terraform_version": "1.7.5",
        "planned_values": {"root_module": root_module},
        "resource_changes": list(change_entries),
    }


def _model(plan: Dict[str, Any]) -> ChangeModel:
    return ChangeExtractor().extract(plan.get("resource_changes"))


# ─── Entry shape ──────────────────────────────────────────────────────────────


def test_delete_absent_from_planned_values_is_reconstructed_from_before() -> None:
    """A delete record missing from planned_values yields a planned-shaped entry."""
    before = {"name": "app-web", "location": "westeurope", "https_only": True}
    plan = _plan([_change_entry("azurerm_linux_web_app.web", "azurerm_linux_web_app", ["delete"], before)])

    reconstructed = _builder()._reconstruct_deleted_resources(plan, _model(plan))

    assert reconstructed == [
        {
            "address": "azurerm_linux_web_app.web",
            "mode": "managed",
            "type": "azurerm_linux_web_app",
            "name": "azurerm_linux_web_app.web",
            "provider_name": PROVIDER,
            "values": before,
        }
    ]


def test_reconstructed_values_are_copies_of_the_plan_before_object() -> None:
    """Mutating the reconstruction never reaches back into the plan document."""
    before = {"name": "app-web", "tags": {"env": "prod"}}
    plan = _plan([_change_entry("azurerm_linux_web_app.web", "azurerm_linux_web_app", ["delete"], before)])

    reconstructed = _builder()._reconstruct_deleted_resources(plan, _model(plan))
    reconstructed[0]["values"]["name"] = "mutated"

    assert before["name"] == "app-web"


def test_module_prefixed_addresses_are_reconstructed() -> None:
    """The full Terraform address, module prefix included, is preserved."""
    address = "module.app.azurerm_storage_account.data"
    plan = _plan([_change_entry(address, "azurerm_storage_account", ["delete"], {"name": "stdata"})])

    reconstructed = _builder()._reconstruct_deleted_resources(plan, _model(plan))

    assert [entry["address"] for entry in reconstructed] == [address]


# ─── Selection rules ──────────────────────────────────────────────────────────


def test_only_delete_records_are_reconstructed() -> None:
    """create, update, replace and unchanged records produce no entry."""
    plan = _plan(
        [
            _change_entry("azurerm_storage_account.new", "azurerm_storage_account", ["create"], None),
            _change_entry("azurerm_storage_account.mod", "azurerm_storage_account", ["update"], {"name": "stmod"}),
            _change_entry("azurerm_storage_account.rep", "azurerm_storage_account", ["delete", "create"], {"name": "strep"}),
            _change_entry("azurerm_storage_account.same", "azurerm_storage_account", ["no-op"], {"name": "stsame"}),
            _change_entry("azurerm_storage_account.gone", "azurerm_storage_account", ["delete"], {"name": "stgone"}),
        ]
    )

    reconstructed = _builder()._reconstruct_deleted_resources(plan, _model(plan))

    assert [entry["address"] for entry in reconstructed] == ["azurerm_storage_account.gone"]


def test_delete_address_present_in_planned_values_is_not_duplicated() -> None:
    """An address that planned_values still carries is left to the planned entry."""
    address = "azurerm_storage_account.data"
    plan = _plan(
        [_change_entry(address, "azurerm_storage_account", ["delete"], {"name": "stold"})],
        planned_resources=[_planned_resource(address, "azurerm_storage_account", {"name": "stnew"})],
    )

    assert _builder()._reconstruct_deleted_resources(plan, _model(plan)) == []


def test_planned_addresses_in_child_modules_are_recognized() -> None:
    """Child-module planned resources suppress reconstruction just like root ones."""
    address = "module.app.azurerm_storage_account.data"
    plan = _plan(
        [_change_entry(address, "azurerm_storage_account", ["delete"], {"name": "stold"})],
        child_modules=[{"resources": [_planned_resource(address, "azurerm_storage_account", {"name": "stnew"})]}],
    )

    assert _builder()._reconstruct_deleted_resources(plan, _model(plan)) == []


def test_no_change_model_or_no_deletes_yields_no_entries() -> None:
    """Absent model, empty model and a plan without deletes all yield nothing."""
    builder = _builder()
    plan = _plan([_change_entry("azurerm_storage_account.new", "azurerm_storage_account", ["create"], None)])

    assert builder._reconstruct_deleted_resources(plan, None) == []
    assert builder._reconstruct_deleted_resources(plan, ChangeModel()) == []
    assert builder._reconstruct_deleted_resources(plan, _model(plan)) == []


def test_record_without_a_matching_change_entry_is_skipped() -> None:
    """A model carrying an address the plan no longer declares is skipped."""
    model = ChangeModel.from_records(
        {
            "azurerm_storage_account.ghost": ChangeRecord(
                address="azurerm_storage_account.ghost",
                category="delete",
                actions=("delete",),
                terraform_type="azurerm_storage_account",
                provider_name=PROVIDER,
            )
        }
    )

    assert _builder()._reconstruct_deleted_resources(_plan([]), model) == []


def test_missing_before_object_reconstructs_with_empty_values() -> None:
    """A delete entry without a usable `before` still yields a renderable entry."""
    plan = _plan([_change_entry("azurerm_storage_account.gone", "azurerm_storage_account", ["delete"], None)])

    reconstructed = _builder()._reconstruct_deleted_resources(plan, _model(plan))

    assert len(reconstructed) == 1
    assert reconstructed[0]["values"] == {}
    assert reconstructed[0]["name"] == "azurerm_storage_account.gone"


# ─── Normalization of reconstructed entries (Requirements 3.2, 3.4) ───────────


def test_reconstructed_entry_normalizes_like_a_planned_resource() -> None:
    """Type mapping and property normalization match the planned-values path."""
    builder = _builder()
    values = {"name": "vnet-hub", "address_space": ["10.0.0.0/16"], "location": "westeurope"}
    plan = _plan([_change_entry("azurerm_virtual_network.hub", "azurerm_virtual_network", ["delete"], values)])

    reconstructed = builder._reconstruct_deleted_resources(plan, _model(plan))
    deleted = builder._normalize_resource(reconstructed[0])
    planned = builder._normalize_resource(_planned_resource("azurerm_virtual_network.hub", "azurerm_virtual_network", values))

    assert deleted is not None and planned is not None
    assert deleted.renderer_type == "Microsoft.Network/virtualNetworks"
    assert deleted.name == planned.name == "vnet-hub"
    assert deleted.properties == planned.properties == {"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}
    assert deleted.extra_fields == planned.extra_fields


def test_reconstructed_subnet_keeps_the_composite_name() -> None:
    """A deleted subnet is still named `<vnet>/<subnet>` for the renderer."""
    builder = _builder()
    values = {"name": "snet-app", "virtual_network_name": "vnet-hub", "address_prefixes": ["10.0.1.0/24"]}
    plan = _plan([_change_entry("azurerm_subnet.app", "azurerm_subnet", ["delete"], values)])

    normalized = builder._normalize_resource(builder._reconstruct_deleted_resources(plan, _model(plan))[0])

    assert normalized is not None
    assert normalized.renderer_type == "Microsoft.Network/virtualNetworks/subnets"
    assert normalized.name == "vnet-hub/snet-app"
    assert normalized.properties == {"addressPrefix": "10.0.1.0/24"}


def test_nameless_before_falls_back_to_the_terraform_address() -> None:
    """Requirement 3.4: no `name` in `before` means the address is displayed."""
    builder = _builder()
    address = "module.app.azurerm_redis_cache.cache"
    plan = _plan([_change_entry(address, "azurerm_redis_cache", ["delete"], {"location": "westeurope"})])

    normalized = builder._normalize_resource(builder._reconstruct_deleted_resources(plan, _model(plan))[0])

    assert normalized is not None
    assert normalized.name == address
    assert normalized.address == address


def test_unsupported_provider_entries_never_reach_reconstruction() -> None:
    """Extraction already drops non-azurerm entries, so nothing is rebuilt."""
    plan = _plan(
        [
            _change_entry(
                "aws_s3_bucket.data",
                "aws_s3_bucket",
                ["delete"],
                {"bucket": "data"},
                provider_name="registry.terraform.io/hashicorp/aws",
            )
        ]
    )

    assert _builder()._reconstruct_deleted_resources(plan, _model(plan)) == []
