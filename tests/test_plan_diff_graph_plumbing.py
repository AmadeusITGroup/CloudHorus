"""Tests for the plan diff plumbing inside `src/core/graph_generator.py`.

Task 7.3 of the terraform-plan-diff-visualization spec: the trailing
`change_types` parameter forwarded to the builder, the per-template
`change_index`, the run-level aggregates, and the Change_Category reaching the
two real resource-node call sites.

Requirements covered: 1.1, 4.5, 5.1, 5.2, 5.3, 5.4, 5.5, 6.9.
"""

import json
import os
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import DotAnalyzer  # noqa: E402
from core.graph_generator import (  # noqa: E402
    accumulate_change_metadata,
    build_change_index,
    has_rendered_changes,
)

TENANT = "test-tenant-1"
SUB = "test-sub-1"
RG = "test-rg-plan"
VNET = "plan-vnet"
SUBNET = "pe-subnet"


def node_statement(source: str, node_id: str) -> str:
    """Return the first DOT node statement of `node_id`."""
    match = re.search(rf'"{re.escape(node_id)}" \[label=.*', source)
    assert match is not None, f"node {node_id!r} not found in DOT source"
    return match.group(0)


def cluster_block(source: str, cluster_name: str) -> str:
    """Return the brace-balanced bodies of every `cluster_name` subgraph, joined.

    A cluster is emitted once per rendering pass that contributes nodes to it,
    so all occurrences together are the content of that cluster.
    """
    header = f'subgraph "{cluster_name}" {{'
    blocks = []
    search_from = 0
    while True:
        start = source.find(header, search_from)
        if start == -1:
            break
        depth = 0
        for index in range(source.index("{", start), len(source)):
            char = source[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(source[start : index + 1])
                    search_from = index + 1
                    break
        else:
            raise AssertionError(f"unbalanced braces for cluster {cluster_name!r}")

    assert blocks, f"cluster {cluster_name!r} not found in DOT source"
    return "\n".join(blocks)


def plan_template(
    categories: Optional[Dict[str, str]] = None,
    with_metadata: bool = True,
    suffix: str = "",
    resource_group: str = RG,
) -> Dict[str, Any]:
    """A renderer template with one RG-level resource and one subnet-placed resource.

    `categories` maps resource name -> Change_Category. Omitting it produces a
    Legacy_Mode template: no `changeCategory` key and no change metadata.
    """
    categories = categories or {}
    vnet = VNET + suffix
    subnet = SUBNET + suffix
    storage = "planstorage" + suffix.replace("-", "")
    endpoint = "pe-storage" + suffix
    resources: List[Dict[str, Any]] = [
        {
            "type": "Microsoft.Network/virtualNetworks",
            "apiVersion": "2023-04-01",
            "name": vnet,
            "location": "westeurope",
            "properties": {
                "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                "subnets": [{"name": subnet, "properties": {"addressPrefix": "10.0.1.0/24"}}],
            },
        },
        {
            "type": "Microsoft.Storage/storageAccounts",
            "apiVersion": "2023-01-01",
            "name": storage,
            "location": "westeurope",
            "properties": {},
        },
        {
            "type": "Microsoft.Network/privateEndpoints",
            "apiVersion": "2023-04-01",
            "name": endpoint,
            "location": "westeurope",
            "properties": {
                "subnet": {
                    "id": (
                        f"/subscriptions/{SUB}/resourceGroups/{resource_group}/providers/"
                        f"Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}"
                    )
                },
                "privateLinkServiceConnections": [
                    {
                        "name": endpoint,
                        "properties": {
                            "privateLinkServiceId": (
                                f"/subscriptions/{SUB}/resourceGroups/{resource_group}/providers/"
                                f"Microsoft.Storage/storageAccounts/{storage}"
                            ),
                            "groupIds": ["blob"],
                        },
                    }
                ],
            },
            "dependsOn": [
                f"[resourceId('Microsoft.Network/virtualNetworks', '{vnet}')]",
                f"[resourceId('Microsoft.Storage/storageAccounts', '{storage}')]",
            ],
        },
    ]

    for resource in resources:
        category = categories.get(resource["name"])
        if category is not None:
            resource["changeCategory"] = category

    template: Dict[str, Any] = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        "contentVersion": "1.0.0.0",
        "resources": resources,
    }
    if categories and with_metadata:
        counts = {category: 0 for category in ("create", "update", "replace", "delete", "unchanged")}
        for category in categories.values():
            counts[category] = counts.get(category, 0) + 1
        template["metadata"] = {"changeCounts": counts, "changesNotDisplayed": []}
    return template


def run_terraform_json_generation(
    templates: List[Dict[str, Any]],
    change_types: Optional[List[str]] = None,
    pass_change_types: bool = True,
    pe_optimization: bool = True,
    work_dir: Optional[str] = None,
    interactive_inspector: Optional[bool] = None,
) -> Tuple[str, DotAnalyzer, List[Dict[str, Any]]]:
    """Run `generate_resource_graph` in terraform-json mode against fixed templates.

    Returns the DOT source, a `DotAnalyzer` over it, and the list of recorded
    `build_terraform_template` calls (`{"path": ..., "kwargs": ...}`).

    `interactive_inspector` is passed to `generate_resource_graph` only when it is
    not `None`, so the default run keeps the pre-Inspector argument list.
    """
    work_dir = work_dir or tempfile.mkdtemp(prefix="cloudhorus_plan_diff_")
    os.makedirs(work_dir, exist_ok=True)
    plan_files = []
    for index, template in enumerate(templates):
        plan_path = os.path.join(work_dir, f"plan-{index}.json")
        with open(plan_path, "w") as handle:
            json.dump({"format_version": "1.0"}, handle)
        plan_files.append(plan_path)

    built_by_plan = {}
    for index, (plan_path, template) in enumerate(zip(plan_files, templates)):
        built_path = os.path.join(work_dir, f"template-{index}.json")
        with open(built_path, "w") as handle:
            json.dump(template, handle)
        built_by_plan[plan_path] = built_path

    calls: List[Dict[str, Any]] = []

    def fake_build(terraform_json_file, *args, **kwargs):
        calls.append({"path": terraform_json_file, "args": args, "kwargs": kwargs})
        return built_by_plan[terraform_json_file]

    captured: Dict[str, str] = {}

    def mock_render(self, filename=None, format=None, *args, **kwargs):
        captured["source"] = self.source
        if filename:
            with open(f"{filename}.png", "w") as handle:
                handle.write("")
        return filename

    def mock_unflatten(self, *args, **kwargs):
        return self

    kwargs: Dict[str, Any] = {}
    if pass_change_types:
        kwargs["change_types"] = change_types
    if interactive_inspector is not None:
        kwargs["interactive_inspector"] = interactive_inspector

    with (
        patch("core.graph_generator.build_terraform_template", side_effect=fake_build),
        patch("core.graph_generator.get_private_dns_zones_without_vnets", return_value=[]),
        patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", return_value=[]),
        patch("core.graph_generator.get_bastion_host_name", return_value=None),
        patch("graphviz.Digraph.render", mock_render),
        patch("graphviz.Digraph.unflatten", mock_unflatten),
        patch("subprocess.run", return_value=MagicMock()),
    ):
        from core.graph_generator import generate_resource_graph

        # Generation writes its output folder into the current directory.
        previous_dir = os.getcwd()
        os.chdir(work_dir)
        try:
            generate_resource_graph(
                tenants=[TENANT] * len(templates),
                subscriptions=[SUB] * len(templates),
                resource_groups=[RG if len(templates) == 1 else f"{RG}-{i}" for i in range(len(templates))],
                subnet_optimization=[False] * len(templates),
                direction="TB",
                tenant_minlen="LR",
                max_subnet_in_line=4,
                rankDebug="invis",
                peOptimization=[pe_optimization] * len(templates),
                privateDnsZonesOptimization=False,
                resourcesEdgeLength=1,
                resourceGroupsEdgeLengthListBySubscription=[4] * len(templates),
                crossPeOptimization=[False] * len(templates),
                discoverResourceGroups=None,
                exportDrawio=False,
                use_local_template=True,
                local_template_mode="terraform-json",
                terraform_json_files=plan_files,
                **kwargs,
            )
        finally:
            os.chdir(previous_dir)

    source = captured.get("source", "")
    return source, DotAnalyzer(source), calls


# ─── build_change_index ───────────────────────────────────────────────────────


def test_build_change_index_keys_by_name_and_type():
    template = plan_template({"planstorage": "create", "pe-storage": "delete"})
    index = build_change_index(template)
    assert index[("planstorage", "Microsoft.Storage/storageAccounts")] == "create"
    assert index[("pe-storage", "Microsoft.Network/privateEndpoints")] == "delete"
    assert (VNET, "Microsoft.Network/virtualNetworks") not in index


def test_build_change_index_is_empty_for_a_legacy_template():
    assert build_change_index(plan_template()) == {}


@pytest.mark.parametrize(
    "template",
    [
        None,
        "not-a-template",
        {},
        {"resources": "not-a-list"},
        {"resources": [None, "text", 42]},
        {"resources": [{"name": "a", "type": "T"}]},
        {"resources": [{"name": "a", "type": "T", "changeCategory": ""}]},
        {"resources": [{"name": "a", "changeCategory": "create"}]},
        {"resources": [{"type": "T", "changeCategory": "create"}]},
        {"resources": [{"name": 1, "type": 2, "changeCategory": "create"}]},
    ],
)
def test_build_change_index_tolerates_malformed_input(template):
    assert build_change_index(template) == {}


def test_build_change_index_keeps_the_last_entry_for_a_duplicate_key():
    template = {
        "resources": [
            {"name": "dup", "type": "T", "changeCategory": "create"},
            {"name": "dup", "type": "T", "changeCategory": "delete"},
        ]
    }
    assert build_change_index(template) == {("dup", "T"): "delete"}


# ─── accumulate_change_metadata / has_rendered_changes ───────────────────────


def test_accumulate_change_metadata_sums_counts_across_templates():
    counts: Dict[str, int] = {}
    summary: List[Any] = []

    accumulate_change_metadata(plan_template({"planstorage": "create"}), counts, summary)
    accumulate_change_metadata(plan_template({"pe-storage": "delete"}), counts, summary)

    assert counts == {"create": 1, "update": 0, "replace": 0, "delete": 1, "unchanged": 0}
    assert summary == []


def test_accumulate_change_metadata_collects_not_displayed_entries():
    counts: Dict[str, int] = {}
    summary: List[Any] = []
    first = {"metadata": {"changeCounts": {"delete": 1}, "changesNotDisplayed": [{"address": "a"}]}}
    second = {"metadata": {"changeCounts": {"delete": 2}, "changesNotDisplayed": [{"address": "b"}]}}

    accumulate_change_metadata(first, counts, summary)
    accumulate_change_metadata(second, counts, summary)

    assert counts["delete"] == 3
    assert summary == [{"address": "a"}, {"address": "b"}]


@pytest.mark.parametrize(
    "template",
    [
        None,
        "text",
        {},
        {"metadata": "text"},
        {"metadata": {}},
        {"metadata": {"changeCounts": "text", "changesNotDisplayed": "text"}},
    ],
)
def test_accumulate_change_metadata_leaves_aggregates_untouched_for_legacy_templates(template):
    counts: Dict[str, int] = {}
    summary: List[Any] = []
    accumulate_change_metadata(template, counts, summary)
    assert counts == {}
    assert summary == []


def test_accumulate_change_metadata_ignores_non_integer_counts():
    counts: Dict[str, int] = {}
    accumulate_change_metadata({"metadata": {"changeCounts": {"create": True, "delete": "2"}}}, counts, [])
    assert counts == {"create": 0, "update": 0, "replace": 0, "delete": 0, "unchanged": 0}


def test_has_rendered_changes_ignores_the_unchanged_category():
    assert has_rendered_changes({}) is False
    assert has_rendered_changes({"unchanged": 7, "create": 0}) is False
    assert has_rendered_changes({"unchanged": 7, "delete": 1}) is True


# ─── change_types forwarding ─────────────────────────────────────────────────


def test_change_types_is_forwarded_to_the_builder(tmp_path):
    _, _, calls = run_terraform_json_generation(
        [plan_template({"planstorage": "delete"})],
        change_types=["delete"],
        work_dir=str(tmp_path),
    )
    assert len(calls) == 1
    assert calls[0]["kwargs"] == {"change_types": ["delete"]}


def test_builder_is_called_exactly_as_before_when_change_types_is_omitted(tmp_path):
    """A legacy run must reach the builder with the pre-feature argument list."""
    _, _, calls = run_terraform_json_generation(
        [plan_template()],
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    assert len(calls) == 1
    assert calls[0]["args"] == ()
    assert calls[0]["kwargs"] == {}


def test_an_empty_selection_is_forwarded_as_a_real_selection(tmp_path):
    _, _, calls = run_terraform_json_generation(
        [plan_template({"planstorage": "create"})],
        change_types=[],
        work_dir=str(tmp_path),
    )
    assert calls[0]["kwargs"] == {"change_types": []}


# ─── Change_Category at the two node call sites ──────────────────────────────

CATEGORY_STYLES = [
    ("create", "#107C10", "+"),
    ("update", "#0078D4", "~"),
    ("replace", "#D13438", "±"),
    ("delete", "#D13438", "-"),
]


CATEGORY_TINTS = {
    "create": "#DBEBDB",
    "update": "#D9EBF9",
    "replace": "#F8E1E1",
    "delete": "#F8E1E1",
}


@pytest.mark.parametrize("category,color,flag", CATEGORY_STYLES)
def test_resource_group_node_carries_the_change_category(category, color, flag, tmp_path):
    """The resource-group call site styles the node from `resource["changeCategory"]`."""
    source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": category})],
        work_dir=str(tmp_path),
    )
    statement = node_statement(source, "planstorage-test-rg-plan")
    # The border and the tint are node attributes; Graphviz quotes their values
    # with double quotes, unlike the single-quoted HTML label markup.
    assert f'color="{color}"' in statement
    assert f'fillcolor="{CATEGORY_TINTS[category]}"' in statement
    assert "penwidth=2" in statement
    assert 'style="filled,rounded"' in statement and "shape=box" in statement
    assert f"<FONT COLOR='{color}'><B>{flag}</B></FONT> planstorage" in statement
    # Icon and geometry attributes stay exactly as Legacy_Mode emits them.
    assert "Storage-Accounts.png" in statement
    assert "imagescale=false" in statement and "width=1.8" in statement


@pytest.mark.parametrize("category,color,flag", CATEGORY_STYLES)
def test_subnet_placed_node_carries_the_change_category(category, color, flag, tmp_path):
    """The subnet call site recovers the category through the `change_index`."""
    source, _, _ = run_terraform_json_generation(
        [plan_template({"pe-storage": category})],
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    subnet_block = cluster_block(source, "cluster_subnetpe-subnet")
    statement = node_statement(subnet_block, "pe-storage-test-rg-plan")
    assert f'color="{color}"' in statement
    assert f'fillcolor="{CATEGORY_TINTS[category]}"' in statement
    assert "penwidth=2" in statement
    assert f"<FONT COLOR='{color}'><B>{flag}</B></FONT> pe-storage" in statement
    assert "privateendpoint.png" in statement


def test_change_index_spans_every_registered_template(tmp_path):
    """Categories of all templates reach their nodes, not only the last one."""
    templates = [
        plan_template({"planstorage0": "create"}, suffix="-0", resource_group=f"{RG}-0"),
        plan_template({"planstorage1": "delete"}, suffix="-1", resource_group=f"{RG}-1"),
    ]
    source, _, calls = run_terraform_json_generation(templates, work_dir=str(tmp_path))

    assert len(calls) == 2
    first = node_statement(source, f"planstorage0-{RG}-0")
    second = node_statement(source, f"planstorage1-{RG}-1")
    assert "<B>+</B>" in first
    assert "<B>-</B>" in second


# ─── Legacy parity ───────────────────────────────────────────────────────────


def test_legacy_template_renders_without_any_change_decoration(tmp_path):
    source, _, _ = run_terraform_json_generation(
        [plan_template()],
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    for color in ("#107C10", "#0078D4", "#D13438"):
        assert color not in source
    assert "<B>+</B>" not in source


def test_an_all_unchanged_plan_renders_byte_identical_dot(tmp_path):
    """`unchanged` and Legacy_Mode take the same styling path (Requirement 5.5)."""
    legacy_source, _, _ = run_terraform_json_generation(
        [plan_template()],
        pass_change_types=False,
        work_dir=str(tmp_path / "legacy"),
    )
    unchanged_source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "unchanged", "pe-storage": "unchanged", VNET: "unchanged"})],
        change_types=None,
        work_dir=str(tmp_path / "unchanged"),
    )
    assert unchanged_source == legacy_source


def test_an_out_of_set_category_renders_like_unchanged(tmp_path):
    """Rendering continues with Legacy_Mode styling (Requirement 4.6)."""
    legacy_source, _, _ = run_terraform_json_generation(
        [plan_template()],
        pass_change_types=False,
        work_dir=str(tmp_path / "legacy"),
    )
    odd_source, _, _ = run_terraform_json_generation(
        [plan_template({"planstorage": "forget"})],
        work_dir=str(tmp_path / "odd"),
    )
    assert odd_source == legacy_source
