"""End-to-end integration test of a filtered Plan_Diff_Mode run.

Task 9.4 of the terraform-plan-diff-visualization spec. Unlike
`tests/test_plan_diff_graph_plumbing.py`, which fakes the builder to isolate the
graph plumbing, this module runs the real chain: a fixture Plan_File is parsed by
`TerraformTemplateBuilder`, the Change_Model is extracted, deleted resources are
reconstructed from `change.before`, `ChangeFilter` restricts the document to the
selected Change_Categories, and `generate_resource_graph` renders it. Only the
Graphviz layout call is faked, so the DOT source under assertion is the real one.

The fixture places a resource scheduled for deletion inside a subnet whose own
Change_Category is `unchanged`, itself inside a virtual network whose
Change_Category is `update`. A `--changeTypes delete` run must therefore keep two
containers that the selection does not name (Requirement 6.11) while dropping
every non-delete leaf resource (Requirement 6.9).

Requirements covered: 6.9, 6.11.
"""

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import DotAnalyzer  # noqa: E402

TENANT = "test-tenant-1"
SUB = "test-sub-1"
RG = "test-rg-plan-diff"

VNET = "core-vnet"
SUBNET = "app"
KEPT_STORAGE = "legacystorage"
KEPT_ENDPOINT = "pe-legacy"
DROPPED_STORAGE = "newstorage"
DROPPED_WEB_APP = "api-web"

PROVIDER = "registry.terraform.io/hashicorp/azurerm"

SUBNET_ID = (
    f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/"
    f"Microsoft.Network/virtualNetworks/{VNET}/subnets/{SUBNET}"
)
LEGACY_STORAGE_ID = (
    f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/Microsoft.Storage/storageAccounts/{KEPT_STORAGE}"
)


# ─── Fixture Plan_File ───────────────────────────────────────────────────────


def _planned_resource(address: str, terraform_type: str, name: str, values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "address": address,
        "mode": "managed",
        "type": terraform_type,
        "name": name,
        "provider_name": PROVIDER,
        "values": values,
    }


def _change_entry(
    address: str,
    terraform_type: str,
    name: str,
    actions: List[str],
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "address": address,
        "mode": "managed",
        "type": terraform_type,
        "name": name,
        "provider_name": PROVIDER,
        "change": {"actions": actions, "before": before, "after": after},
    }


def plan_file() -> Dict[str, Any]:
    """A plan mixing every Change_Category around a VNet/subnet container hierarchy.

    `planned_values` holds the post-apply state, so the two resources the plan
    destroys appear only in `resource_changes` and must be reconstructed from
    `change.before`.
    """
    vnet_values = {"name": VNET, "location": "westeurope", "address_space": ["10.20.0.0/16"]}
    subnet_values = {
        "name": SUBNET,
        "virtual_network_name": VNET,
        "address_prefixes": ["10.20.1.0/24"],
    }
    new_storage_values = {"name": DROPPED_STORAGE, "location": "westeurope"}
    web_app_values = {
        "name": DROPPED_WEB_APP,
        "location": "westeurope",
        "virtual_network_subnet_id": SUBNET_ID,
    }
    legacy_storage_values = {"name": KEPT_STORAGE, "location": "westeurope"}
    legacy_endpoint_values = {
        "name": KEPT_ENDPOINT,
        "location": "westeurope",
        "subnet_id": SUBNET_ID,
        "private_service_connection": [
            {
                "name": KEPT_ENDPOINT,
                "private_connection_resource_id": LEGACY_STORAGE_ID,
                "subresource_names": ["blob"],
            }
        ],
    }

    return {
        "format_version": "1.0",
        "terraform_version": "1.8.5",
        "planned_values": {
            "root_module": {
                "resources": [
                    _planned_resource("azurerm_virtual_network.core", "azurerm_virtual_network", "core", vnet_values),
                    _planned_resource("azurerm_subnet.app", "azurerm_subnet", "app", subnet_values),
                    _planned_resource(
                        "azurerm_storage_account.new", "azurerm_storage_account", "new", new_storage_values
                    ),
                    _planned_resource("azurerm_linux_web_app.api", "azurerm_linux_web_app", "api", web_app_values),
                ]
            }
        },
        "resource_changes": [
            # The container hierarchy is not scheduled for deletion.
            _change_entry(
                "azurerm_virtual_network.core", "azurerm_virtual_network", "core", ["update"], vnet_values, vnet_values
            ),
            _change_entry("azurerm_subnet.app", "azurerm_subnet", "app", ["no-op"], subnet_values, subnet_values),
            # Non-delete leaves, dropped by a `delete` selection.
            _change_entry(
                "azurerm_storage_account.new", "azurerm_storage_account", "new", ["create"], None, new_storage_values
            ),
            _change_entry(
                "azurerm_linux_web_app.api", "azurerm_linux_web_app", "api", ["update"], web_app_values, web_app_values
            ),
            # Deletes, absent from planned_values, reconstructed from `before`.
            _change_entry(
                "azurerm_storage_account.legacy",
                "azurerm_storage_account",
                "legacy",
                ["delete"],
                legacy_storage_values,
                None,
            ),
            _change_entry(
                "azurerm_private_endpoint.legacy",
                "azurerm_private_endpoint",
                "legacy",
                ["delete"],
                legacy_endpoint_values,
                None,
            ),
        ],
        "configuration": {
            "root_module": {
                "resources": [
                    {
                        "address": "azurerm_virtual_network.core",
                        "expressions": {"name": {"constant_value": VNET}},
                    },
                    {
                        "address": "azurerm_subnet.app",
                        "expressions": {
                            "virtual_network_name": {
                                "references": ["azurerm_virtual_network.core.name", "azurerm_virtual_network.core"]
                            }
                        },
                    },
                    {
                        "address": "azurerm_storage_account.new",
                        "expressions": {"name": {"constant_value": DROPPED_STORAGE}},
                    },
                    {
                        "address": "azurerm_linux_web_app.api",
                        "expressions": {
                            "virtual_network_subnet_id": {
                                "references": ["azurerm_subnet.app.id", "azurerm_subnet.app"]
                            }
                        },
                    },
                ]
            }
        },
    }


# ─── End-to-end run ──────────────────────────────────────────────────────────


def run_plan_diff_generation(
    plan: Dict[str, Any],
    change_types: Optional[List[str]],
    work_dir: str,
    export_drawio: bool = False,
) -> Tuple[str, DotAnalyzer]:
    """Render a Plan_File end to end, faking only the Graphviz layout call.

    `export_drawio` forwards to `exportDrawio`, which runs the real Draw.io
    converter over the real DOT source; it stays off by default so the callers
    that only inspect DOT keep their current cost.
    """
    os.makedirs(work_dir, exist_ok=True)
    plan_path = os.path.join(work_dir, "plan.json")
    with open(plan_path, "w", encoding="utf-8") as handle:
        json.dump(plan, handle)

    captured: Dict[str, str] = {}

    def mock_render(self, filename=None, format=None, *args, **kwargs):
        captured["source"] = self.source
        if filename:
            with open(f"{filename}.png", "w", encoding="utf-8") as handle:
                handle.write("")
        return filename

    def mock_unflatten(self, *args, **kwargs):
        return self

    with (
        patch("core.graph_generator.get_private_dns_zones_without_vnets", return_value=[]),
        patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", return_value=[]),
        patch("core.graph_generator.get_bastion_host_name", return_value=None),
        patch("graphviz.Digraph.render", mock_render),
        patch("graphviz.Digraph.unflatten", mock_unflatten),
        patch("subprocess.run", return_value=MagicMock()),
    ):
        from core.graph_generator import generate_resource_graph

        previous_dir = os.getcwd()
        os.chdir(work_dir)
        try:
            generate_resource_graph(
                tenants=[TENANT],
                subscriptions=[SUB],
                resource_groups=[RG],
                subnet_optimization=[False],
                direction="TB",
                tenant_minlen="LR",
                max_subnet_in_line=4,
                rankDebug="invis",
                peOptimization=[False],
                privateDnsZonesOptimization=False,
                resourcesEdgeLength=1,
                resourceGroupsEdgeLengthListBySubscription=[4],
                crossPeOptimization=[False],
                discoverResourceGroups=None,
                exportDrawio=export_drawio,
                use_local_template=True,
                local_template_mode="terraform-json",
                terraform_json_files=[plan_path],
                change_types=change_types,
            )
        finally:
            os.chdir(previous_dir)

    source = captured.get("source", "")
    return source, DotAnalyzer(source)


def node_statement(source: str, node_id: str) -> str:
    """Return the first DOT node statement of `node_id`."""
    match = re.search(rf'"{re.escape(node_id)}" \[label=.*', source)
    assert match is not None, f"node {node_id!r} not found in DOT source"
    return match.group(0)


def subnet_cluster_block(source: str, subnet_name: str) -> str:
    """Return the joined bodies of every `cluster_subnet<name>` subgraph.

    A cluster is re-opened once per rendering pass that contributes nodes to it,
    so all occurrences together are the content of that cluster. Graphviz only
    quotes a subgraph name when it needs escaping, so both forms are matched.
    """
    pattern = re.compile(rf'subgraph\s+"?cluster_subnet{re.escape(subnet_name)}"?\s*\{{')
    blocks: List[str] = []
    position = 0
    while True:
        match = pattern.search(source, position)
        if match is None:
            break
        start = match.start()
        depth = 0
        for index in range(source.index("{", start), len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(source[start : index + 1])
                    position = index + 1
                    break
        else:
            raise AssertionError(f"unbalanced braces for subnet cluster {subnet_name!r}")

    assert blocks, f"subnet cluster {subnet_name!r} not found in DOT source"
    return "\n".join(blocks)


@pytest.fixture(scope="module")
def unfiltered_run(tmp_path_factory) -> Tuple[str, DotAnalyzer]:
    return run_plan_diff_generation(plan_file(), None, str(tmp_path_factory.mktemp("unfiltered")))


@pytest.fixture(scope="module")
def delete_only_run(tmp_path_factory) -> Tuple[str, DotAnalyzer]:
    return run_plan_diff_generation(plan_file(), ["delete"], str(tmp_path_factory.mktemp("delete_only")))


def test_unfiltered_run_renders_every_resource_of_the_plan(unfiltered_run):
    """Baseline: without a selection the diagram holds planned and deleted resources."""
    source, analyzer = unfiltered_run

    for name in (KEPT_STORAGE, KEPT_ENDPOINT, DROPPED_STORAGE, DROPPED_WEB_APP):
        assert analyzer.has_node(f"{name}-{RG}"), f"{name} missing from the unfiltered diagram"
    assert analyzer.has_cluster(f"vnet{VNET}")
    assert analyzer.has_cluster(f"subnet{SUBNET}")


def test_filtered_run_keeps_only_deletes_and_their_containers(delete_only_run):
    """`--changeTypes delete` renders the deletes plus the containers they need.

    Requirement 6.9: the diagram is restricted to the listed Change_Categories.
    Requirement 6.11: the subnet (`unchanged`) and the virtual network (`update`)
    survive because a displayed resource resides inside them.
    """
    source, analyzer = delete_only_run

    # The two resources the plan destroys are rendered.
    assert analyzer.has_node(f"{KEPT_STORAGE}-{RG}")
    assert analyzer.has_node(f"{KEPT_ENDPOINT}-{RG}")

    # Their containers are retained even though neither is a delete.
    assert analyzer.has_cluster(f"vnet{VNET}")
    assert analyzer.has_cluster(f"subnet{SUBNET}")
    assert node_statement(subnet_cluster_block(source, SUBNET), f"{KEPT_ENDPOINT}-{RG}")

    # Every non-delete leaf resource is gone: the resource-group scoped nodes are
    # exactly the two deletes, so nothing outside the selection slipped through.
    assert analyzer.get_nodes_containing(DROPPED_STORAGE) == []
    assert analyzer.get_nodes_containing(DROPPED_WEB_APP) == []
    assert set(analyzer.get_nodes_containing(f"-{RG}")) == {
        f"{KEPT_STORAGE}-{RG}",
        f"{KEPT_ENDPOINT}-{RG}",
    }


def test_filtered_delete_nodes_carry_the_delete_style(delete_only_run):
    """The rendered deletes keep the Change_Style of the `delete` category."""
    source, _ = delete_only_run

    for name in (KEPT_STORAGE, KEPT_ENDPOINT):
        statement = node_statement(source, f"{name}-{RG}")
        # Border and tint on the node (Graphviz quotes attribute values with
        # double quotes), Flag_Token in the single-quoted HTML label markup.
        assert 'color="#D13438"' in statement
        assert 'fillcolor="#F8E1E1"' in statement
        assert "penwidth=2" in statement
        assert f"<FONT COLOR='#D13438'><B>-</B></FONT> {name}" in statement


def test_filtered_run_renders_fewer_resource_nodes_than_the_unfiltered_run(unfiltered_run, delete_only_run):
    """Filtering removes nodes rather than only restyling them."""
    _, unfiltered = unfiltered_run
    _, filtered = delete_only_run

    assert len(filtered.get_nodes_containing(f"-{RG}")) < len(unfiltered.get_nodes_containing(f"-{RG}"))
