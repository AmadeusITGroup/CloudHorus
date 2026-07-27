"""Inspector plumbing inside `src/core/graph_generator.py`.

Tasks 7.1 and 7.2 of the interactive-resource-inspector spec:

* the trailing `interactive_inspector` parameter on `generate_resource_graph` and
  `_generate_resource_graph_inner`, forwarded to the Terraform builder as
  `collect_inspector_values`;
* the collector selection — `InspectorCollector` in Inspector_Mode,
  `NullInspectorCollector` otherwise;
* one record per drawn node and per drawn container, keyed by the Node_Key
  `<resource_name>-<resource_group>` and by the Cluster_Keys
  `cluster_vnet<name>` / `cluster_subnet<name>`;
* the source resolution of a subnet cluster: standalone resource by compound name
  first, bare name second, embedded `subnets` entry last, asserted both as a
  function and through a render pass against the Attribute_Entry rows the record
  of `cluster_subnet<name>` ends up carrying (task 7.6), because a regression
  there yields an empty Inspector_Panel rather than a missing record;
* disabled-mode parity: the emitted DOT with Inspector_Mode off is byte-identical
  to the DOT of a run that never passes the parameter.

The render call itself is task 7.3 and is faked out throughout; the payload write
of task 7.4 is used, not asserted, by the sections that read the Inspector_Records
back off disk.

Requirements covered: 1.3, 1.5, 2.8, 3.2, 3.3, 3.4, 3.5, 4.1, 4.2, 4.6, 4.8, 9.5,
9.6, 10.1.
"""

import os
import sys
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.graph_generator import (  # noqa: E402
    SUBNET_RENDERER_TYPE,
    build_inspector_source_index,
    resolve_subnet_inspector_source,
    style_subnet_cluster,
)
from core.inspector import (  # noqa: E402
    NODE_KIND,
    SUBNET_KIND,
    VNET_KIND,
    InspectorCollector,
    NullInspectorCollector,
)
from test_plan_diff_graph_plumbing import (  # noqa: E402
    RG,
    SUB,
    SUBNET,
    VNET,
    plan_template,
    run_terraform_json_generation,
)

STORAGE_NODE = f"planstorage-{RG}"
ENDPOINT_NODE = f"pe-storage-{RG}"
VNET_CLUSTER = f"cluster_vnet{VNET}"
SUBNET_CLUSTER = f"cluster_subnet{SUBNET}"


class _RecordingSubgraph:
    """The minimum of the Graphviz subgraph surface `style_subnet_cluster` uses."""

    def __init__(self) -> None:
        self.attributes: Dict[str, Any] = {}

    def attr(self, **kwargs: Any) -> None:
        self.attributes.update(kwargs)


def run_with_collector(
    templates: List[Dict[str, Any]],
    interactive_inspector: Optional[bool] = None,
    **kwargs: Any,
):
    """Run a generation pass, capturing the collectors the run constructs.

    Returns `(dot_source, builder_calls, collectors, null_collectors)`, where the
    two collector lists hold the instances `_generate_resource_graph_inner`
    constructed through the module attributes.
    """
    collectors: List[InspectorCollector] = []
    null_collectors: List[NullInspectorCollector] = []

    def make_collector(*args: Any, **collector_kwargs: Any) -> InspectorCollector:
        collector = InspectorCollector(*args, **collector_kwargs)
        collectors.append(collector)
        return collector

    def make_null_collector(*args: Any, **collector_kwargs: Any) -> NullInspectorCollector:
        collector = NullInspectorCollector(*args, **collector_kwargs)
        null_collectors.append(collector)
        return collector

    with (
        patch("core.graph_generator.InspectorCollector", side_effect=make_collector),
        patch("core.graph_generator.NullInspectorCollector", side_effect=make_null_collector),
    ):
        source, _, calls = run_terraform_json_generation(
            templates,
            interactive_inspector=interactive_inspector,
            **kwargs,
        )
    return source, calls, collectors, null_collectors


# ─── 7.1 parameter forwarding ────────────────────────────────────────────────


def test_inspector_mode_forwards_collect_inspector_values_to_the_builder(tmp_path):
    _, calls, _, _ = run_with_collector(
        [plan_template()],
        interactive_inspector=True,
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    assert len(calls) == 1
    assert calls[0]["kwargs"] == {"collect_inspector_values": True}


def test_inspector_mode_forwards_both_optional_builder_keywords(tmp_path):
    _, calls, _, _ = run_with_collector(
        [plan_template({"planstorage": "delete"})],
        interactive_inspector=True,
        change_types=["delete"],
        work_dir=str(tmp_path),
    )
    assert calls[0]["kwargs"] == {"change_types": ["delete"], "collect_inspector_values": True}


@pytest.mark.parametrize("interactive_inspector", [None, False])
def test_disabled_mode_reaches_the_builder_with_the_pre_feature_arguments(
    interactive_inspector, tmp_path
):
    """Requirement 1.5: nothing new reaches the builder when Inspector_Mode is off."""
    _, calls, _, _ = run_with_collector(
        [plan_template()],
        interactive_inspector=interactive_inspector,
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    assert calls[0]["args"] == ()
    assert calls[0]["kwargs"] == {}


# ─── 7.1 collector selection ─────────────────────────────────────────────────


def test_inspector_mode_constructs_the_real_collector(tmp_path):
    _, _, collectors, null_collectors = run_with_collector(
        [plan_template()],
        interactive_inspector=True,
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    assert len(collectors) == 1
    assert null_collectors == []


@pytest.mark.parametrize("interactive_inspector", [None, False])
def test_disabled_mode_constructs_the_null_collector(interactive_inspector, tmp_path):
    _, _, collectors, null_collectors = run_with_collector(
        [plan_template()],
        interactive_inspector=interactive_inspector,
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    assert collectors == []
    assert len(null_collectors) == 1


def test_the_null_collector_records_nothing(tmp_path):
    """The disabled path must make the collection calls free (Requirement 1.3)."""
    _, _, _, null_collectors = run_with_collector(
        [plan_template()],
        interactive_inspector=False,
        pass_change_types=False,
        work_dir=str(tmp_path),
    )
    collector = null_collectors[0]
    assert collector.keys() == []
    assert collector.build_payload().records == []


# ─── 7.2 one record per drawn element ────────────────────────────────────────


def test_every_drawn_node_and_container_is_recorded_once(tmp_path):
    """Requirements 3.2-3.5, 4.1, 4.2: the keys are the Node_Keys and Cluster_Keys."""
    _, _, collectors, _ = run_with_collector(
        [plan_template()],
        interactive_inspector=True,
        pass_change_types=False,
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    keys = collectors[0].keys()

    assert set(keys) == {STORAGE_NODE, ENDPOINT_NODE, VNET_CLUSTER, SUBNET_CLUSTER}
    assert len(keys) == len(set(keys))


def test_an_element_created_twice_yields_one_record(tmp_path):
    """Requirement 4.5: first-write-wins, and the duplicate is counted.

    A resource placed inside a subnet is declared a second time at
    resource-group level, and the subnet cluster is opened once per resource it
    holds, so the render pass reaches both creation sites more than once for the
    same Inspector_Key.
    """
    _, _, collectors, _ = run_with_collector(
        [plan_template()],
        interactive_inspector=True,
        pass_change_types=False,
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    collector = collectors[0]

    assert collector.keys().count(ENDPOINT_NODE) == 1
    assert collector.keys().count(SUBNET_CLUSTER) == 1
    assert collector.key_collisions >= 1


def test_recorded_kinds_match_the_way_the_diagram_draws_each_element(tmp_path):
    _, _, collectors, _ = run_with_collector(
        [plan_template()],
        interactive_inspector=True,
        pass_change_types=False,
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    kinds = {record.key: record.kind for record in collectors[0].build_payload().records}

    assert kinds == {
        STORAGE_NODE: NODE_KIND,
        ENDPOINT_NODE: NODE_KIND,
        VNET_CLUSTER: VNET_KIND,
        SUBNET_CLUSTER: SUBNET_KIND,
    }


def test_records_carry_the_identity_of_the_element_they_describe(tmp_path):
    _, _, collectors, _ = run_with_collector(
        [plan_template({"planstorage": "create", "pe-storage": "delete"})],
        interactive_inspector=True,
        pass_change_types=False,
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    records = {record.key: record for record in collectors[0].build_payload().records}

    storage = records[STORAGE_NODE]
    assert storage.name == "planstorage"
    assert storage.resource_type == "Microsoft.Storage/storageAccounts"
    assert storage.resource_group == RG
    assert storage.change_category == "create"

    endpoint = records[ENDPOINT_NODE]
    assert endpoint.name == "pe-storage"
    assert endpoint.resource_type == "Microsoft.Network/privateEndpoints"
    assert endpoint.change_category == "delete"

    assert records[VNET_CLUSTER].name == VNET
    assert records[SUBNET_CLUSTER].name == SUBNET


def test_a_skipped_resource_is_absent_from_the_records(tmp_path):
    """Requirement 4.6: the Skip_Filter removes the record with the node."""
    template = plan_template()
    template["resources"].append(
        {
            "type": "Microsoft.Insights/metricAlerts",
            "apiVersion": "2018-03-01",
            "name": "skipped-alert",
            "location": "global",
            "properties": {},
        }
    )
    _, _, collectors, _ = run_with_collector(
        [template],
        interactive_inspector=True,
        pass_change_types=False,
        pe_optimization=False,
        work_dir=str(tmp_path),
    )
    assert f"skipped-alert-{RG}" not in collectors[0].keys()


# ─── 7.2 subnet source resolution ────────────────────────────────────────────


def test_build_inspector_source_index_keys_by_name_and_type():
    template = plan_template()
    index = build_inspector_source_index(template["resources"])

    assert index[("planstorage", "Microsoft.Storage/storageAccounts")]["name"] == "planstorage"
    assert index[(VNET, "Microsoft.Network/virtualNetworks")]["type"] == (
        "Microsoft.Network/virtualNetworks"
    )


@pytest.mark.parametrize(
    "resources",
    [None, "text", {}, [None, 42], [{"name": "a"}], [{"type": "T"}], [{"name": 1, "type": 2}]],
)
def test_build_inspector_source_index_tolerates_malformed_input(resources):
    assert build_inspector_source_index(resources) == {}


def test_build_inspector_source_index_keeps_the_first_entry_of_a_duplicate_key():
    first = {"name": "dup", "type": "T", "properties": {"order": 1}}
    second = {"name": "dup", "type": "T", "properties": {"order": 2}}
    index = build_inspector_source_index([first, second])
    assert index[("dup", "T")] is first


def test_subnet_source_prefers_the_compound_name():
    """Requirement 9.6: `<vnet>/<subnet>` wins over the bare subnet name."""
    compound = {"name": f"{VNET}/{SUBNET}", "type": SUBNET_RENDERER_TYPE}
    bare = {"name": SUBNET, "type": SUBNET_RENDERER_TYPE}
    index = build_inspector_source_index([bare, compound])

    assert resolve_subnet_inspector_source(index, VNET, SUBNET, {"embedded": True}) is compound


def test_subnet_source_falls_back_to_the_bare_name():
    bare = {"name": SUBNET, "type": SUBNET_RENDERER_TYPE}
    index = build_inspector_source_index([bare])

    assert resolve_subnet_inspector_source(index, VNET, SUBNET, {"embedded": True}) is bare


def test_subnet_source_falls_back_to_the_embedded_entry():
    """Requirement 9.5: a subnet drawn from the VNet's `subnets` list is described."""
    embedded = {"name": SUBNET, "properties": {"addressPrefix": "10.0.1.0/24"}}

    assert resolve_subnet_inspector_source({}, VNET, SUBNET, embedded) is embedded


# ─── 7.2 the shared subnet cluster helper ────────────────────────────────────


def test_style_subnet_cluster_records_the_cluster_key():
    collector = InspectorCollector()
    subgraph = _RecordingSubgraph()
    source = {"name": SUBNET, "type": SUBNET_RENDERER_TYPE, "properties": {}}

    style_subnet_cluster(subgraph, SUBNET, "10.0.1.0/24", VNET, {}, collector, source, RG)

    record = collector.build_payload().records[0]
    assert record.key == SUBNET_CLUSTER
    assert record.kind == SUBNET_KIND
    assert record.resource_group == RG


def test_style_subnet_cluster_emits_the_same_attributes_with_and_without_a_collector():
    """Collection must not touch the DOT the helper emits (Requirement 1.3)."""
    with_collector = _RecordingSubgraph()
    without_collector = _RecordingSubgraph()

    style_subnet_cluster(
        with_collector, SUBNET, "10.0.1.0/24", VNET, {}, InspectorCollector(), {}, RG
    )
    style_subnet_cluster(without_collector, SUBNET, "10.0.1.0/24", VNET, {})

    assert with_collector.attributes == without_collector.attributes


def test_style_subnet_cluster_with_the_null_collector_records_nothing():
    collector = NullInspectorCollector()

    style_subnet_cluster(_RecordingSubgraph(), SUBNET, "10.0.1.0/24", VNET, {}, collector, {}, RG)

    assert collector.keys() == []


# ─── disabled-mode parity ────────────────────────────────────────────────────


def test_disabled_mode_dot_is_byte_identical_to_a_pre_feature_run(tmp_path):
    """Requirement 1.3/1.4: Inspector_Mode off changes nothing about the DOT."""
    legacy, _, _, _ = run_with_collector(
        [plan_template({"planstorage": "create", "pe-storage": "delete"})],
        pass_change_types=False,
        work_dir=str(tmp_path / "legacy"),
    )
    disabled, _, _, _ = run_with_collector(
        [plan_template({"planstorage": "create", "pe-storage": "delete"})],
        interactive_inspector=False,
        pass_change_types=False,
        work_dir=str(tmp_path / "disabled"),
    )

    assert legacy == disabled
    assert legacy != ""


def test_enabled_mode_emits_the_same_dot_as_disabled_mode(tmp_path):
    """Requirement 1.6: collection is additive, the DOT source is untouched."""
    disabled, _, _, _ = run_with_collector(
        [plan_template({"planstorage": "update"})],
        pass_change_types=False,
        work_dir=str(tmp_path / "off"),
    )
    enabled, _, _, _ = run_with_collector(
        [plan_template({"planstorage": "update"})],
        interactive_inspector=True,
        pass_change_types=False,
        work_dir=str(tmp_path / "on"),
    )

    assert enabled == disabled

# ─── Property 5: element coverage ────────────────────────────────────────────
#
# Task 7.5. The Interaction_Layer is the SVG of the same layout pass that writes
# the PNG, so the identities it carries as `<title>` of a `g.node` / `g.cluster`
# are exactly the node and cluster identifiers of the DOT source the layout
# consumes. This module fakes the layout out (`graphviz.Digraph.render` and the
# dual-format `dot` invocation are both mocked), so the property is asserted
# against that DOT source; `TestEndToEndPipelineGuarantee` in
# `tests/test_inspector_cli.py` closes the loop against a real SVG.
#
# Scope of the coverage half, which is the contract task 7.2 actually
# implemented: the record call sites are the resource-group-level resource node
# and the subnet-placed resource node, plus the VNet and subnet cluster sites.
# Nodes the Diagram draws from a lookup rather than from a Renderer_Template
# resource entry — the private-DNS-zone nodes and the Bastion node, pinned as
# `UNCOLLECTED_SAMPLE_NODES` in `tests/test_inspector_cli.py` — therefore carry
# no Inspector_Record, and the Legend node and the tenant / subscription /
# resource-group containers describe no resource at all. The property is
# consequently quantified over resource-derived Node_Keys and over the
# VNet/subnet Cluster_Keys, not over every `g` element of the layer, and the
# generated resource sets hold no DNS zone and no Bastion host so the carve-out
# never silently absorbs a real regression.

import glob  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
from typing import Set, Tuple  # noqa: E402

from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from conftest import DotAnalyzer  # noqa: E402
from core.inspector import (  # noqa: E402
    INSPECTOR_INDEX_SUFFIX,
    INSPECTOR_RECORDS_SUFFIX,
)

#: The five Change_Categories a Renderer_Template resource entry can carry.
CATEGORIES: Tuple[str, ...] = ("create", "update", "replace", "delete", "unchanged")

#: Cluster_Key prefixes of the containers Requirement 3.3 makes activatable. Every
#: other cluster the Diagram opens (`cluster_parent`, `cluster_tenant`,
#: `cluster_subscription`, `cluster_resource_group`, `cluster_change_legend`) groups
#: a scope rather than a resource and is outside the Inspector's element set.
INSPECTABLE_CLUSTER_PREFIXES: Tuple[str, ...] = ("cluster_vnet", "cluster_subnet")

#: A resource type the Skip_Filter removes from the Diagram (Requirement 4.6).
SKIPPED_TYPE = "Microsoft.Insights/metricAlerts"

#: Alphabet of the generated name suffix: letters, digits and the dash, so a name
#: reaches a Node_Key, a Cluster_Key and an output filename without needing DOT
#: quoting to be the thing under test.
_TOKENS = st.text(alphabet="abcxz019-", min_size=1, max_size=4)

#: Every `subgraph` header of a DOT source, quoted or bare.
_SUBGRAPH_RE = re.compile(r"subgraph\s+(?:\"([^\"]+)\"|([A-Za-z0-9_]+))\s*\{")


def inspectable_clusters(dot_source: str) -> Set[str]:
    """The Cluster_Keys of the VNet and subnet containers the DOT source opens."""
    names = {quoted or bare for quoted, bare in _SUBGRAPH_RE.findall(dot_source)}
    return {name for name in names if name.startswith(INSPECTABLE_CLUSTER_PREFIXES)}


@st.composite
def inspectable_resource_sets(draw):
    """A Renderer_Template plus the element sets its render pass must produce.

    One VNet with one to three subnets, zero to three resource-group-level storage
    accounts, zero to three private endpoints placed in one of the subnets, and
    zero to two resources of a type the Skip_Filter drops. Change_Categories are
    drawn for every resource or for none, which is the Legacy_Mode shape, and the
    Change_Filter is modelled where the builder applies it: a resource whose
    category is not selected never reaches the Renderer_Template
    (Requirement 4.7).

    Returns the template, the Node_Key candidates of every generated resource, and
    the names the two filters removed.
    """
    token = draw(_TOKENS)
    vnet = f"vnet{token}"
    subnets = [f"snet{index}{token}" for index in range(draw(st.integers(1, 3)))]
    storages = [f"st{index}{token}" for index in range(draw(st.integers(0, 3)))]
    endpoints = [
        (f"pe{index}{token}", subnets[choice])
        for index, choice in enumerate(
            draw(st.lists(st.integers(0, len(subnets) - 1), max_size=3))
        )
    ]
    skipped = [f"alert{index}{token}" for index in range(draw(st.integers(0, 2)))]

    drawable = storages + [name for name, _ in endpoints]
    categorized = draw(st.booleans())
    categories = (
        {name: draw(st.sampled_from(CATEGORIES)) for name in drawable} if categorized else {}
    )
    selected = (
        draw(st.lists(st.sampled_from(CATEGORIES), unique=True, max_size=5)) if categories else []
    )
    excluded = (
        {name for name, category in categories.items() if category not in selected}
        if selected
        else set()
    )

    resources = [
        {
            "type": "Microsoft.Network/virtualNetworks",
            "apiVersion": "2023-04-01",
            "name": vnet,
            "location": "westeurope",
            "properties": {
                "addressSpace": {"addressPrefixes": ["10.0.0.0/16"]},
                "subnets": [
                    {"name": name, "properties": {"addressPrefix": f"10.0.{index}.0/24"}}
                    for index, name in enumerate(subnets)
                ],
            },
        }
    ]
    for name in storages:
        if name in excluded:
            continue
        resources.append(
            {
                "type": "Microsoft.Storage/storageAccounts",
                "apiVersion": "2023-01-01",
                "name": name,
                "location": "westeurope",
                "properties": {"accessTier": "Hot"},
            }
        )
    for name, subnet in endpoints:
        if name in excluded:
            continue
        resources.append(
            {
                "type": "Microsoft.Network/privateEndpoints",
                "apiVersion": "2023-04-01",
                "name": name,
                "location": "westeurope",
                "properties": {
                    "subnet": {
                        "id": (
                            f"/subscriptions/{SUB}/resourceGroups/{RG}/providers/"
                            f"Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}"
                        )
                    }
                },
                "dependsOn": [f"[resourceId('Microsoft.Network/virtualNetworks', '{vnet}')]"],
            }
        )
    for name in skipped:
        resources.append(
            {
                "type": SKIPPED_TYPE,
                "apiVersion": "2018-03-01",
                "name": name,
                "location": "global",
                "properties": {},
            }
        )

    for resource in resources:
        category = categories.get(resource["name"])
        if category is not None:
            resource["changeCategory"] = category

    template = {
        "$schema": (
            "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
        ),
        "contentVersion": "1.0.0.0",
        "resources": resources,
    }
    return {
        "template": template,
        "vnet": vnet,
        "subnets": subnets,
        # Every resource the input names, VNet excluded: the VNet is drawn as a
        # container, so its Inspector_Key is a Cluster_Key, not a Node_Key.
        "resource_node_keys": {f"{name}-{RG}" for name in drawable + skipped},
        "removed_node_keys": {f"{name}-{RG}" for name in sorted(excluded) + skipped},
    }


def read_payload(run_dir: str) -> Tuple[dict, int]:
    """Return the Inspector_Index of the run and the JSONL line count beside it."""
    folders = sorted(glob.glob(os.path.join(run_dir, "azure_resources_*")))
    assert folders, f"the run wrote no output folder under {run_dir}"
    folder = folders[-1]
    stem = os.path.join(folder, os.path.basename(folder))

    with open(f"{stem}{INSPECTOR_INDEX_SUFFIX}", "r", encoding="utf-8") as handle:
        index = json.load(handle)
    with open(f"{stem}{INSPECTOR_RECORDS_SUFFIX}", "rb") as handle:
        lines = [line for line in handle.read().split(b"\n") if line]
    return index, len(lines)


# Feature: interactive-resource-inspector, Property 5: For any resource set and any
# combination of Skip_Filter and Change_Filter selections, the Inspector_Key set of
# the Inspector_Index equals the set of g.node and g.cluster identities the
# Interaction_Layer carries, minus the Inspector_Keys that a reported collision
# dropped; recordCount equals the number of lines in the JSONL file; and no
# Inspector_Record exists for a resource the Diagram does not draw.
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(resource_set=inspectable_resource_sets())
def test_property_element_coverage(resource_set):
    """Property 5: one Inspector_Record per drawn element, and none besides.

    **Validates: Requirements 3.2, 3.3, 4.1, 4.2, 4.3, 4.6, 4.7, 9.1, 14.5**
    """
    run_dir = tempfile.mkdtemp(prefix="cloudhorus_inspector_coverage_")
    try:
        source, _, collectors, _ = run_with_collector(
            [resource_set["template"]],
            interactive_inspector=True,
            pass_change_types=False,
            pe_optimization=False,
            work_dir=run_dir,
        )
        index, line_count = read_payload(run_dir)
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

    analyzer = DotAnalyzer(source)
    drawn_nodes = set(analyzer.nodes)
    drawn_clusters = inspectable_clusters(source)
    keys = index["keys"]
    node_keys = {key for key, entry in keys.items() if entry["kind"] == NODE_KIND}
    cluster_keys = set(keys) - node_keys

    # Soundness: no Inspector_Record describes an element the Diagram does not draw
    # (Requirements 4.1, 4.2).
    assert node_keys <= drawn_nodes
    assert cluster_keys <= drawn_clusters
    assert {entry["kind"] for entry in keys.values()} <= {NODE_KIND, VNET_KIND, SUBNET_KIND}

    # Coverage over the elements task 7.2 instruments: every resource-derived node
    # the Diagram draws (Requirement 3.2) and every VNet/subnet container it opens
    # (Requirements 3.3, 9.1).
    assert node_keys == resource_set["resource_node_keys"] & drawn_nodes
    assert cluster_keys == drawn_clusters
    assert f"cluster_vnet{resource_set['vnet']}" in cluster_keys

    # The Skip_Filter and the Change_Filter remove the record with the element
    # (Requirements 4.6, 4.7).
    for removed in resource_set["removed_node_keys"]:
        assert removed not in drawn_nodes
        assert removed not in keys

    # The Inspector_Index describes exactly the payload it indexes, and the layer
    # key set is the collected key set minus the reported collisions
    # (Requirements 4.3, 14.5).
    collector = collectors[0]
    assert index["recordCount"] == len(keys) == line_count
    assert set(collector.keys()) == set(keys)
    assert len(collector.keys()) == len(set(collector.keys()))
    assert index["keyCollisions"] == collector.key_collisions


# ─── 7.6 container source resolution, end to end ─────────────────────────────
#
# `resolve_subnet_inspector_source` is asserted as a function above, which pins
# the resolution order but not the consequence of getting it wrong. A subnet
# cluster is recorded at every one of the four `style_subnet_cluster` sites, so a
# regression in the source it is handed does not lose the Inspector_Record — the
# key is still collected and still indexed — it hands the record the wrong source
# dict, or no source at all, and the Operator gets an *empty* Inspector_Panel.
# That failure mode is invisible to the element-coverage property, so these tests
# drive a full render pass and assert the Attribute_Entry rows the payload on disk
# actually carries for `cluster_subnet<name>`.

#: The `addressPrefix` every subnet source in this section declares, so a test
#: that distinguishes two sources does it through `properties.sourceMarker` rather
#: than through the CIDR the cluster label also carries.
SUBNET_PREFIX = "10.0.1.0/24"

#: Attribute_Path of the marker that names which source a record was built from.
MARKER_PATH = "properties.sourceMarker"

#: Attribute_Path of the prefix every subnet source declares.
PREFIX_PATH = "properties.addressPrefix"


def standalone_subnet_resource(
    name: str,
    marker: str,
    inspector_values: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A Renderer_Template subnet resource entry carrying a source marker.

    `name` is the Renderer_Template name, which the Terraform builder writes as
    the compound `"<vnet>/<subnet>"` and a hand-written template may write as the
    bare subnet name — the two spellings this section plays against each other.
    """
    resource: Dict[str, Any] = {
        "type": SUBNET_RENDERER_TYPE,
        "apiVersion": "2023-04-01",
        "name": name,
        "location": "westeurope",
        "properties": {"addressPrefix": SUBNET_PREFIX, "sourceMarker": marker},
    }
    if inspector_values is not None:
        resource["inspectorValues"] = inspector_values
    return resource


def read_inspector_records(run_dir: str) -> Dict[str, Dict[str, Any]]:
    """Return the Inspector_Records the run wrote, keyed by Inspector_Key."""
    folders = sorted(glob.glob(os.path.join(run_dir, "azure_resources_*")))
    assert folders, f"the run wrote no output folder under {run_dir}"
    folder = folders[-1]
    stem = os.path.join(folder, os.path.basename(folder))

    records: Dict[str, Dict[str, Any]] = {}
    with open(f"{stem}{INSPECTOR_RECORDS_SUFFIX}", "r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[record["key"]] = record
    return records


def run_and_read_records(
    template: Dict[str, Any], work_dir: str
) -> Dict[str, Dict[str, Any]]:
    """Render `template` in Inspector_Mode and read the payload it wrote."""
    run_with_collector(
        [template],
        interactive_inspector=True,
        pass_change_types=False,
        pe_optimization=False,
        work_dir=work_dir,
    )
    return read_inspector_records(work_dir)


def entries_by_path(record: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Return the Attribute_Entry rows of one record, keyed by Attribute_Path."""
    return {entry["path"]: entry for entry in record["attributes"]}


def test_an_embedded_subnet_entry_fills_the_panel(tmp_path):
    """Requirement 9.5: the record of a subnet with no standalone resource.

    `plan_template` draws its subnet purely from the parent VNet's
    `properties["subnets"]` list, which is the shape a Bicep or Live template
    produces, and the record has to be built from that entry.
    """
    template = plan_template()
    assert not [
        resource
        for resource in template["resources"]
        if resource["type"] == SUBNET_RENDERER_TYPE
    ], "the fixture must hold no standalone subnet resource for this case to apply"

    records = run_and_read_records(template, str(tmp_path))
    subnet = records[SUBNET_CLUSTER]
    entries = entries_by_path(subnet)

    assert subnet["kind"] == SUBNET_KIND
    assert subnet["name"] == SUBNET
    assert subnet["resourceType"] == SUBNET_RENDERER_TYPE
    # The panel is not empty: the embedded entry's configuration is the record's.
    assert entries, "the subnet record carries no Attribute_Entry rows"
    assert entries[PREFIX_PATH]["before"] == SUBNET_PREFIX
    assert entries[PREFIX_PATH]["after"] == SUBNET_PREFIX
    assert entries[PREFIX_PATH]["state"] == "unchanged"


def test_the_compound_named_subnet_resource_wins_over_the_bare_name(tmp_path):
    """Requirement 9.6: `<vnet>/<subnet>` first, the bare subnet name second.

    Both spellings are present, so only the rows of the record prove which one the
    render pass resolved.
    """
    template = plan_template()
    template["resources"].append(standalone_subnet_resource(SUBNET, "bare"))
    template["resources"].append(
        standalone_subnet_resource(f"{VNET}/{SUBNET}", "compound")
    )

    entries = entries_by_path(run_and_read_records(template, str(tmp_path))[SUBNET_CLUSTER])

    assert entries[MARKER_PATH]["after"] == "compound"
    assert entries[PREFIX_PATH]["after"] == SUBNET_PREFIX


def test_the_bare_named_subnet_resource_is_used_without_a_compound_name(tmp_path):
    """Requirement 9.6: the bare name still resolves when no compound name exists."""
    template = plan_template()
    template["resources"].append(standalone_subnet_resource(SUBNET, "bare"))

    entries = entries_by_path(run_and_read_records(template, str(tmp_path))[SUBNET_CLUSTER])

    assert entries[MARKER_PATH]["after"] == "bare"


def test_the_resolved_subnet_resource_carries_its_change_states_into_the_panel(tmp_path):
    """Requirements 9.5, 9.6: resolving the standalone resource is what buys the diff.

    Only the standalone Renderer_Template resource carries the `inspectorValues`
    triple, so a resolution that fell back to the embedded entry would render every
    row `unchanged` instead of the plan's actual intra-resource diff.
    """
    template = plan_template()
    template["resources"].append(
        standalone_subnet_resource(
            f"{VNET}/{SUBNET}",
            "compound",
            inspector_values={
                "before": {"address_prefixes": ["10.0.1.0/24"], "service_endpoints": []},
                "after": {"address_prefixes": ["10.0.2.0/24"], "private_endpoint": "id"},
                "afterUnknown": {"private_endpoint": True},
            },
        )
    )

    entries = entries_by_path(run_and_read_records(template, str(tmp_path))[SUBNET_CLUSTER])

    assert entries["address_prefixes.0"]["state"] == "changed"
    assert entries["address_prefixes.0"]["before"] == "10.0.1.0/24"
    assert entries["address_prefixes.0"]["after"] == "10.0.2.0/24"
    assert entries["service_endpoints"]["state"] == "removed"
    assert entries["service_endpoints"]["before"] == "[]"
    assert entries["private_endpoint"]["state"] == "added"
    assert entries["private_endpoint"]["after"] == "(known after apply)"
    # The embedded entry's own shape never reaches a record built from the triple.
    assert MARKER_PATH not in entries
