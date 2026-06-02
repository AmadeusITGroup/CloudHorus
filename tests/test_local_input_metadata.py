from pathlib import Path

from core.local_input_metadata import discover_terraform_source_scope_metadata


def test_discover_terraform_scope_metadata_from_sibling_metadata_dir(tmp_path: Path) -> None:
    scenario_root = tmp_path / "scenario2-crossrg-network"
    scenario_root.mkdir()
    (scenario_root / "main.tf").write_text('resource "azurerm_virtual_network" "example" {}\n', encoding="utf-8")

    metadata_dir = tmp_path / "metadata"
    metadata_dir.mkdir()
    metadata_file = metadata_dir / "scenario2-crossrg-network.scope.json"
    metadata_file.write_text(
        '{"scope": {"provider": "azurerm", "tenant": "t1", "subscription": "s1", "resourceGroup": "rg1"}}',
        encoding="utf-8",
    )

    result = discover_terraform_source_scope_metadata([str(scenario_root)])

    assert result["allFound"] is True
    assert result["files"] == [str(metadata_file)]
    assert result["subscriptions"] == [
        {
            "id": "s1",
            "tenant": "t1",
            "resourceGroups": ["rg1"],
            "provider": "azurerm",
        }
    ]
    assert result["templateSubMap"] == [0]


def test_discover_terraform_scope_metadata_returns_no_match_when_missing(tmp_path: Path) -> None:
    scenario_root = tmp_path / "scenario-without-metadata"
    scenario_root.mkdir()

    result = discover_terraform_source_scope_metadata([str(scenario_root)])

    assert result["allFound"] is False
    assert result["files"] == []
    assert result["missingRoots"] == [str(scenario_root)]