"""Inspector coverage of the elements the Diagram draws from a lookup.

The four record call sites of task 7.2 cover the resource-group-level node, the
subnet-placed node, and the VNet / subnet containers — every one of them backed by
a Renderer_Template resource entry. The Diagram also draws elements that no
resource entry produces on its own:

* the private-DNS-zone nodes, one per zone linked to a VNet and one per zone of a
  resource group that holds no VNet at all;
* the aggregated `PrivateDNSZones-<vnet>` node that `privateDnsZonesOptimization`
  collapses those zones onto;
* the Bastion node of a VNet;
* the route-table node `<route table>-<subnet>` and the NSG node
  `<nsg>-<resource group>`, both drawn from a subnet's dependencies and neither
  drawn at resource-group level at all;
* a node whose name an optimization rewrote, `privateEndpoints-<subnet>` under
  `peOptimization`, which several real endpoints can collapse onto.

This module covers the helpers that describe those elements and the call sites
that record them, plus the three guards that keep the Inspector_Index honest: the
sourceless-record guard, which leaves an element the Inspector cannot describe
inert rather than activatable-but-empty (Requirement 3.2); the repeat-draw guard,
which records one element drawn in several subnets once rather than counting the
repeats as key collisions (Requirement 4.5); and the stale-subnet prune, which
drops the records of subnet clusters the DOT post-pass deleted.

Every end-to-end assertion reads the Attribute_Entry rows back off the written
`.inspector.jsonl`, following the task-7.6 pattern in
`tests/test_inspector_collector.py`: a regression that hands a record no source
does not lose the record, it empties the panel, and an empty panel has to fail the
test rather than pass it silently.

Requirements covered: 1.3, 1.6, 3.2, 3.3, 3.4, 4.1, 4.2, 4.4, 4.5, 4.8, 10.1,
10.4, 12.2.
"""

import json
import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence, Tuple
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.graph_generator import (  # noqa: E402
    AGGREGATED_COUNT_KEY,
    AGGREGATED_DNS_NODE_PREFIX,
    AGGREGATED_ZONE_CONFIG_KEY,
    AGGREGATED_ZONES_KEY,
    BASTION_RENDERER_TYPE,
    DNS_ZONE_RENDERER_TYPE,
    MERGED_ENDPOINT_COUNT_KEY,
    MERGED_ENDPOINTS_KEY,
    SUBNET_RENDERER_TYPE,
    _remove_stale_subnet_subgraphs,
    build_aggregated_dns_zone_source,
    build_inspector_source_index,
    build_merged_inspector_source,
    inspector_source_config,
    inspector_source_phases,
    prune_stale_inspector_records,
    record_node_once,
    record_optimized_inspector_source,
    resolve_node_inspector_source,
)
from core.inspector import (  # noqa: E402
    AFTER_KEY,
    AFTER_UNKNOWN_KEY,
    BEFORE_KEY,
    INSPECTOR_VALUES_KEY,
    InspectorCollector,
    InspectorPayload,
    InspectorRecord,
)
from test_inspector_collector import entries_by_path, read_inspector_records  # noqa: E402
from test_plan_diff_graph_plumbing import (  # noqa: E402
    RG,
    SUB,
    SUBNET,
    TENANT,
    VNET,
    plan_template,
)

#: Renderer types of the elements this module brings into the Inspector.
ROUTE_TABLE_TYPE = "Microsoft.Network/routeTables"
NSG_TYPE = "Microsoft.Network/networkSecurityGroups"

#: The zone linked to the VNet, drawn inside `cluster_vnet<name>`.
LINKED_ZONE = "privatelink.blob.core.windows.net"

#: The zone of a resource group with no VNet link, drawn at resource-group level.
UNLINKED_ZONE = "privatelink.file.core.windows.net"

ROUTE_TABLE = "rt-cov"
NSG = "nsg-cov"
BASTION = "bastion-cov"

#: Node_Keys the two subnet-dependency call sites give their elements: the route
#: table is keyed per subnet, the NSG per resource group.
ROUTE_TABLE_NODE = f"{ROUTE_TABLE}-{SUBNET}"
NSG_NODE = f"{NSG}-{RG}"

#: A second subnet of the fixture VNet, sharing the route table and the NSG.
SECOND_SUBNET = "snet-b"

#: Node_Key of the aggregated private-DNS-zone node of the fixture VNet.
AGGREGATED_NODE = f"{AGGREGATED_DNS_NODE_PREFIX}{VNET}"


# ─── Fixture template ────────────────────────────────────────────────────────


def coverage_template(
    *,
    with_zone_resources: bool = True,
    with_bastion_resource: bool = True,
    with_subnet_dependencies: bool = True,
) -> Dict[str, Any]:
    """`plan_template` plus the resource entries the lookup-drawn nodes describe.

    The DNS zones and the Bastion host are `SKIP_RESOURCE_PATTERNS` types: they are
    never drawn as resource-group nodes, so their entries exist purely as Inspector
    sources for the nodes the VNet lookups draw. The route table and the NSG are
    reached through the standalone subnet resource's `dependsOn`, which is the only
    route by which either is drawn at all.

    The three flags remove one group each, so a test can drive a node whose source
    does not resolve.

    The subnet resource and its two dependency targets are prepended rather than
    appended: the route-table and NSG call sites read the `dependencies` map while
    the VNet is being drawn, so the subnet's `dependsOn` has to have been parsed by
    the time the render pass reaches the VNet entry.
    """
    template = plan_template()
    resources: List[Dict[str, Any]] = template["resources"]
    prefix: List[Dict[str, Any]] = []

    if with_zone_resources:
        for zone, records in ((LINKED_ZONE, 3), (UNLINKED_ZONE, 7)):
            resources.append(
                {
                    "type": DNS_ZONE_RENDERER_TYPE,
                    "apiVersion": "2020-06-01",
                    "name": zone,
                    "location": "global",
                    "properties": {
                        "numberOfRecordSets": records,
                        "numberOfVirtualNetworkLinks": 1,
                    },
                }
            )

    if with_bastion_resource:
        resources.append(
            {
                "type": BASTION_RENDERER_TYPE,
                "apiVersion": "2023-04-01",
                "name": BASTION,
                "location": "westeurope",
                "properties": {"dnsName": "bst.bastion.azure.com", "scaleUnits": 2},
            }
        )

    if with_subnet_dependencies:
        prefix.append(
            {
                "type": ROUTE_TABLE_TYPE,
                "apiVersion": "2023-04-01",
                "name": ROUTE_TABLE,
                "location": "westeurope",
                "properties": {
                    "disableBgpRoutePropagation": True,
                    "routes": [
                        {
                            "name": "to-firewall",
                            "properties": {
                                "addressPrefix": "0.0.0.0/0",
                                "nextHopType": "VirtualAppliance",
                            },
                        }
                    ],
                },
            }
        )
        prefix.append(
            {
                "type": NSG_TYPE,
                "apiVersion": "2023-04-01",
                "name": NSG,
                "location": "westeurope",
                "properties": {
                    "securityRules": [
                        {
                            "name": "allow-https",
                            "properties": {
                                "access": "Allow",
                                "direction": "Inbound",
                                "destinationPortRange": "443",
                            },
                        }
                    ]
                },
            }
        )
        prefix.append(
            {
                "type": SUBNET_RENDERER_TYPE,
                "apiVersion": "2023-04-01",
                "name": f"{VNET}/{SUBNET}",
                "location": "westeurope",
                "properties": {"addressPrefix": "10.0.1.0/24"},
                "dependsOn": [
                    f"[resourceId('Microsoft.Network/routeTables', '{ROUTE_TABLE}')]",
                    f"[resourceId('Microsoft.Network/networkSecurityGroups', '{NSG}')]",
                ],
            }
        )

    template["resources"] = prefix + resources
    return template


# ─── Render harness ──────────────────────────────────────────────────────────


def run_coverage_generation(
    template: Dict[str, Any],
    *,
    work_dir: str,
    interactive_inspector: Optional[bool] = None,
    unlinked_zones: Sequence[str] = (),
    linked_zones: Sequence[str] = (),
    bastion_name: Optional[str] = None,
    private_dns_zones_optimization: bool = False,
    pe_optimization: bool = False,
) -> Tuple[str, List[InspectorCollector]]:
    """Run one terraform-json generation pass with the VNet lookups driven.

    `tests/test_plan_diff_graph_plumbing.run_terraform_json_generation` pins the
    three lookups this module needs to their empty answers, so the harness is
    reproduced here with those answers as parameters. Everything else — the faked
    builder, the faked layout, the working directory the run writes into — is that
    harness unchanged.

    Returns the emitted DOT source and the `InspectorCollector` instances the run
    constructed.
    """
    os.makedirs(work_dir, exist_ok=True)
    plan_path = os.path.join(work_dir, "plan-0.json")
    with open(plan_path, "w") as handle:
        json.dump({"format_version": "1.0"}, handle)
    built_path = os.path.join(work_dir, "template-0.json")
    with open(built_path, "w") as handle:
        json.dump(template, handle)

    collectors: List[InspectorCollector] = []

    def make_collector(*args: Any, **kwargs: Any) -> InspectorCollector:
        collector = InspectorCollector(*args, **kwargs)
        collectors.append(collector)
        return collector

    def fake_build(terraform_json_file, *args, **kwargs):
        return built_path

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
    if interactive_inspector is not None:
        kwargs["interactive_inspector"] = interactive_inspector

    with (
        patch("core.graph_generator.InspectorCollector", side_effect=make_collector),
        patch("core.graph_generator.build_terraform_template", side_effect=fake_build),
        patch(
            "core.graph_generator.get_private_dns_zones_without_vnets",
            return_value=list(unlinked_zones),
        ),
        patch(
            "core.graph_generator.is_vnet_linked_to_private_dns_zone",
            return_value=list(linked_zones),
        ),
        patch("core.graph_generator.get_bastion_host_name", return_value=bastion_name),
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
                peOptimization=[pe_optimization],
                privateDnsZonesOptimization=private_dns_zones_optimization,
                resourcesEdgeLength=1,
                resourceGroupsEdgeLengthListBySubscription=[4],
                crossPeOptimization=[False],
                discoverResourceGroups=None,
                exportDrawio=False,
                use_local_template=True,
                local_template_mode="terraform-json",
                terraform_json_files=[plan_path],
                **kwargs,
            )
        finally:
            os.chdir(previous_dir)

    return captured.get("source", ""), collectors


class _RecordSink(logging.Handler):
    """Keep the log records themselves, so the args survive the assertion."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def singleton_log_sink():
    """Collect the singleton logger's records, which do not propagate to `caplog`."""
    logger = logging.getLogger("SingletonLogger")
    sink = _RecordSink()
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(sink)
    try:
        yield sink
    finally:
        logger.removeHandler(sink)
        logger.setLevel(previous_level)


def messages(sink: _RecordSink, level: Optional[int] = None) -> List[str]:
    """The rendered messages of the collected records, optionally at one level."""
    return [
        record.getMessage()
        for record in sink.records
        if level is None or record.levelno == level
    ]


# ─── inspector_source_phases ─────────────────────────────────────────────────


def test_source_phases_returns_the_inspector_values_triple():
    """The builder's `inspectorValues` triple is the plan-diff shape, used as is."""
    resource = {
        "name": "web",
        "type": "Microsoft.Web/sites",
        INSPECTOR_VALUES_KEY: {
            BEFORE_KEY: {"sku": "S1"},
            AFTER_KEY: {"sku": "P1v3"},
            AFTER_UNKNOWN_KEY: {"outbound_ip": True},
        },
    }

    before, after, unknown = inspector_source_phases(resource)

    assert before == {"sku": "S1"}
    assert after == {"sku": "P1v3"}
    assert unknown == {"outbound_ip": True}


def test_source_phases_of_a_partial_triple_keeps_the_absent_phases_absent():
    resource = {"name": "gone", INSPECTOR_VALUES_KEY: {BEFORE_KEY: {"sku": "S1"}}}

    assert inspector_source_phases(resource) == ({"sku": "S1"}, None, None)


def test_source_phases_of_a_legacy_entry_describes_it_on_both_sides():
    """Requirements 6.9, 10.2: no plan, so both phases are the same configuration."""
    resource = {
        "name": "zone",
        "type": DNS_ZONE_RENDERER_TYPE,
        "location": "global",
        "properties": {"numberOfRecordSets": 3},
    }

    before, after, unknown = inspector_source_phases(resource)

    assert before == after == {"properties": {"numberOfRecordSets": 3}, "location": "global"}
    assert unknown is None


@pytest.mark.parametrize("resource", [None, "text", 42, ["a"]])
def test_source_phases_of_a_non_dict_is_that_value_on_both_sides(resource):
    assert inspector_source_phases(resource) == (resource, resource, None)


def test_source_phases_ignores_an_inspector_values_key_that_is_not_a_triple():
    resource = {"name": "web", "properties": {"sku": "S1"}, INSPECTOR_VALUES_KEY: "broken"}

    before, after, _ = inspector_source_phases(resource)

    assert before == after == {"properties": {"sku": "S1"}}


# ─── inspector_source_config ─────────────────────────────────────────────────


def test_source_config_excludes_the_identity_keys_and_retains_properties():
    """The exclusion set is the collector's own, so the paths match either route."""
    resource = {
        "name": "rt-cov",
        "type": ROUTE_TABLE_TYPE,
        "changeCategory": "update",
        "dependsOn": ["[resourceId('x', 'y')]"],
        INSPECTOR_VALUES_KEY: {BEFORE_KEY: {}},
        "apiVersion": "2023-04-01",
        "location": "westeurope",
        "properties": {"disableBgpRoutePropagation": True},
    }

    config = inspector_source_config(resource)

    assert config["properties"] == {"disableBgpRoutePropagation": True}
    assert config["apiVersion"] == "2023-04-01"
    assert config["location"] == "westeurope"
    for excluded in ("name", "type", "changeCategory", "dependsOn", INSPECTOR_VALUES_KEY):
        assert excluded not in config


def test_source_config_drops_an_empty_properties_map_and_null_values():
    resource = {"name": "n", "type": "T", "properties": {}, "location": None, "sku": "S1"}

    assert inspector_source_config(resource) == {"sku": "S1"}


@pytest.mark.parametrize("resource", [None, "text", 42])
def test_source_config_of_a_non_dict_is_that_value(resource):
    assert inspector_source_config(resource) is resource


# ─── build_aggregated_dns_zone_source ────────────────────────────────────────


def aggregated_properties(source: Dict[str, Any]) -> Dict[str, Any]:
    """The `properties` map of a synthesized aggregated DNS zone source."""
    return source["properties"]


def test_aggregated_dns_source_lists_the_zones_and_their_count():
    """Requirement 4.4: the aggregation itself is the configuration of the node."""
    source = build_aggregated_dns_zone_source(VNET, ["zonea", "zoneb"], {})
    properties = aggregated_properties(source)

    assert source["name"] == AGGREGATED_NODE
    assert source["type"] == DNS_ZONE_RENDERER_TYPE
    assert properties[AGGREGATED_ZONES_KEY] == ["zonea", "zoneb"]
    assert properties[AGGREGATED_COUNT_KEY] == 2


def test_aggregated_dns_source_carries_the_configuration_of_a_resolvable_zone():
    resolvable = {
        "name": "zonea",
        "type": DNS_ZONE_RENDERER_TYPE,
        "properties": {"numberOfRecordSets": 4},
    }
    index = build_inspector_source_index([resolvable])

    properties = aggregated_properties(build_aggregated_dns_zone_source(VNET, ["zonea"], index))

    assert properties[AGGREGATED_ZONE_CONFIG_KEY]["zonea"] == {
        "properties": {"numberOfRecordSets": 4}
    }


def test_aggregated_dns_source_omits_the_configuration_of_an_unresolvable_zone():
    resolvable = {
        "name": "zonea",
        "type": DNS_ZONE_RENDERER_TYPE,
        "properties": {"numberOfRecordSets": 4},
    }
    index = build_inspector_source_index([resolvable])

    properties = aggregated_properties(
        build_aggregated_dns_zone_source(VNET, ["zonea", "zoneb"], index)
    )

    assert set(properties[AGGREGATED_ZONE_CONFIG_KEY]) == {"zonea"}
    assert properties[AGGREGATED_ZONES_KEY] == ["zonea", "zoneb"]


def test_aggregated_dns_source_holds_no_configurations_subtree_when_none_resolve():
    properties = aggregated_properties(build_aggregated_dns_zone_source(VNET, ["zonea"], {}))

    assert AGGREGATED_ZONE_CONFIG_KEY not in properties


@pytest.mark.parametrize("zones", [None, [], ["ok", None, 42]])
def test_aggregated_dns_source_keeps_only_the_zone_names_that_are_text(zones):
    properties = aggregated_properties(build_aggregated_dns_zone_source(VNET, zones, {}))

    expected = [zone for zone in (zones or []) if isinstance(zone, str)]
    assert properties[AGGREGATED_ZONES_KEY] == expected
    assert properties[AGGREGATED_COUNT_KEY] == len(expected)


def test_every_row_of_an_aggregated_dns_record_is_unchanged():
    """A synthesized tree is described on both sides, so no row can read changed."""
    index = build_inspector_source_index(
        [{"name": "zonea", "type": DNS_ZONE_RENDERER_TYPE, "properties": {"records": 4}}]
    )
    collector = InspectorCollector()

    collector.record_node(
        AGGREGATED_NODE, build_aggregated_dns_zone_source(VNET, ["zonea", "zoneb"], index), RG
    )
    record = collector.build_payload().records[0]

    assert record.attributes, "the aggregated record carries no Attribute_Entry rows"
    assert {entry.state for entry in record.attributes} == {"unchanged"}
    paths = {entry.path for entry in record.attributes}
    assert f"properties.{AGGREGATED_ZONES_KEY}.0" in paths
    assert f"properties.{AGGREGATED_COUNT_KEY}" in paths
    assert f"properties.{AGGREGATED_ZONE_CONFIG_KEY}.zonea.properties.records" in paths


# ─── the optimization rewrite side map ───────────────────────────────────────


def endpoint(name: str, category: Optional[str] = None, **values: Any) -> Dict[str, Any]:
    """A private endpoint entry, optionally carrying a Change_Category."""
    resource: Dict[str, Any] = {
        "name": name,
        "type": "Microsoft.Network/privateEndpoints",
        "properties": {"groupId": values.get("group", "blob")},
    }
    if category is not None:
        resource["changeCategory"] = category
    return resource


def test_record_optimized_source_collects_every_resource_of_one_rewritten_name():
    optimized: Dict[Any, List[Any]] = {}
    first, second = endpoint("pe-a"), endpoint("pe-b")

    record_optimized_inspector_source(
        optimized, "privateEndpoints-snet", "Microsoft.Network/privateEndpoints", first
    )
    record_optimized_inspector_source(
        optimized, "privateEndpoints-snet", "Microsoft.Network/privateEndpoints", second
    )

    assert optimized[("privateEndpoints-snet", "Microsoft.Network/privateEndpoints")] == [
        first,
        second,
    ]


@pytest.mark.parametrize("name", ["", None, 42])
def test_record_optimized_source_ignores_a_name_that_is_not_usable_text(name):
    optimized: Dict[Any, List[Any]] = {}

    record_optimized_inspector_source(optimized, name, "T", {"name": "x"})

    assert optimized == {}


def test_the_real_index_wins_over_the_rewrite_side_map():
    """The rewrite map is a fallback, never a replacement for a real entry."""
    real = endpoint("privateEndpoints-snet")
    index = build_inspector_source_index([real])
    optimized = {("privateEndpoints-snet", "Microsoft.Network/privateEndpoints"): [endpoint("pe-a")]}

    resolved = resolve_node_inspector_source(
        index, optimized, "privateEndpoints-snet", "Microsoft.Network/privateEndpoints"
    )

    assert resolved is real


def test_one_rewritten_resource_resolves_to_its_own_entry():
    only = endpoint("pe-a")
    optimized = {("privateEndpoints-snet", "Microsoft.Network/privateEndpoints"): [only]}

    resolved = resolve_node_inspector_source(
        {}, optimized, "privateEndpoints-snet", "Microsoft.Network/privateEndpoints"
    )

    assert resolved is only


def test_an_unresolvable_node_name_resolves_to_no_source():
    assert resolve_node_inspector_source({}, {}, "ghost", "T") is None


def test_a_merged_node_carries_every_resource_it_stands_for():
    """Requirement 4.4: each merged endpoint keeps its own subtree and its own rows."""
    optimized: Dict[Any, List[Any]] = {}
    for name in ("pe-a", "pe-b"):
        record_optimized_inspector_source(
            optimized, "privateEndpoints-snet", "Microsoft.Network/privateEndpoints", endpoint(name)
        )

    merged = resolve_node_inspector_source(
        {}, optimized, "privateEndpoints-snet", "Microsoft.Network/privateEndpoints"
    )
    after = merged[INSPECTOR_VALUES_KEY][AFTER_KEY]

    assert merged["name"] == "privateEndpoints-snet"
    assert set(after[MERGED_ENDPOINTS_KEY]) == {"pe-a", "pe-b"}
    assert after[MERGED_ENDPOINT_COUNT_KEY] == 2


def test_a_merged_node_keeps_the_phases_of_each_merged_resource():
    deleted = endpoint("pe-gone")
    deleted[INSPECTOR_VALUES_KEY] = {BEFORE_KEY: {"groupId": "blob"}, AFTER_KEY: None}
    created = endpoint("pe-new")
    created[INSPECTOR_VALUES_KEY] = {
        BEFORE_KEY: None,
        AFTER_KEY: {"groupId": "file"},
        AFTER_UNKNOWN_KEY: {"private_ip": True},
    }

    merged = build_merged_inspector_source(
        "privateEndpoints-snet", "Microsoft.Network/privateEndpoints", [deleted, created]
    )
    values = merged[INSPECTOR_VALUES_KEY]

    assert set(values[BEFORE_KEY][MERGED_ENDPOINTS_KEY]) == {"pe-gone"}
    assert set(values[AFTER_KEY][MERGED_ENDPOINTS_KEY]) == {"pe-new"}
    assert values[AFTER_UNKNOWN_KEY][MERGED_ENDPOINTS_KEY] == {"pe-new": {"private_ip": True}}


def test_a_merged_node_rows_name_each_merged_resource():
    """The rows are what the panel shows, so they are what the test asserts."""
    collector = InspectorCollector()
    collector.record_node(
        "privateEndpoints-snet-rg",
        build_merged_inspector_source(
            "privateEndpoints-snet",
            "Microsoft.Network/privateEndpoints",
            [endpoint("pe-a"), endpoint("pe-b")],
        ),
        RG,
    )

    paths = {entry.path for entry in collector.build_payload().records[0].attributes}

    assert f"{MERGED_ENDPOINTS_KEY}.pe-a.properties.groupId" in paths
    assert f"{MERGED_ENDPOINTS_KEY}.pe-b.properties.groupId" in paths
    assert MERGED_ENDPOINT_COUNT_KEY in paths


def test_a_merged_node_carries_the_change_category_every_entry_agrees_on():
    merged = build_merged_inspector_source(
        "privateEndpoints-snet",
        "Microsoft.Network/privateEndpoints",
        [endpoint("pe-a", "delete"), endpoint("pe-b", "delete")],
    )

    assert merged["changeCategory"] == "delete"


def test_a_merged_node_of_mixed_categories_carries_none():
    """One Change_Category for the node is only meaningful when the entries agree."""
    merged = build_merged_inspector_source(
        "privateEndpoints-snet",
        "Microsoft.Network/privateEndpoints",
        [endpoint("pe-a", "delete"), endpoint("pe-b", "create")],
    )

    assert "changeCategory" not in merged


def test_a_merged_entry_without_a_name_is_keyed_by_its_position():
    merged = build_merged_inspector_source("privateEndpoints-snet", "T", [{"properties": {"a": 1}}])

    assert set(merged[INSPECTOR_VALUES_KEY][AFTER_KEY][MERGED_ENDPOINTS_KEY]) == {"T#0"}


# ─── prune_stale_inspector_records ───────────────────────────────────────────


def payload_of(*keys: str) -> InspectorPayload:
    """A payload holding one identity-only record per key."""
    return InspectorPayload(
        records=[InspectorRecord(key=key, kind="node", name=key) for key in keys]
    )


def test_prune_drops_the_record_of_a_removed_subnet_subgraph_and_nothing_else():
    payload = payload_of(f"cluster_subnet{SUBNET}", "cluster_subnetkept", f"planstorage-{RG}")

    pruned = prune_stale_inspector_records(payload, {SUBNET})

    assert [record.key for record in pruned.records] == ["cluster_subnetkept", f"planstorage-{RG}"]
    assert pruned.record_count == 2


def test_prune_matches_the_subgraph_the_dot_post_pass_actually_removed():
    """The prune and `_remove_stale_subnet_subgraphs` have to agree on one name set."""
    source = (
        "digraph {\n"
        f'\tsubgraph "cluster_subnet{SUBNET}" {{\n\t\t"pe-storage-{RG}" [label="pe"]\n\t}}\n'
        '\tsubgraph "cluster_subnetkept" {\n\t\t"kept" [label="kept"]\n\t}\n'
        "}\n"
    )
    stale = {SUBNET}

    cleaned = _remove_stale_subnet_subgraphs(source, stale)
    pruned = prune_stale_inspector_records(
        payload_of(f"cluster_subnet{SUBNET}", "cluster_subnetkept"), stale
    )

    assert f"cluster_subnet{SUBNET}" not in cleaned
    assert "cluster_subnetkept" in cleaned
    assert [record.key for record in pruned.records] == ["cluster_subnetkept"]


@pytest.mark.parametrize("stale", [None, set(), []])
def test_prune_returns_the_payload_untouched_when_no_subgraph_was_removed(stale):
    payload = payload_of(f"cluster_subnet{SUBNET}")

    pruned = prune_stale_inspector_records(payload, stale)

    assert pruned is payload
    assert [record.key for record in pruned.records] == [f"cluster_subnet{SUBNET}"]


# ─── the sourceless-record guard (Requirement 3.2) ───────────────────────────


def test_an_element_with_no_source_is_not_recorded():
    """An element the Inspector cannot describe stays inert rather than empty."""
    collector = InspectorCollector()

    with singleton_log_sink() as sink:
        collector.record_node("ghost-host", None, RG)

    assert collector.keys() == []
    assert collector.build_payload().records == []
    assert collector.key_collisions == 0
    assert any("ghost-host" in message for message in messages(sink, logging.DEBUG))
    assert not messages(sink, logging.WARNING)


def test_a_sourceless_element_does_not_block_the_key_it_shares():
    """Dropping the record leaves the key free, so a later real source still lands."""
    collector = InspectorCollector()

    collector.record_node("rt-cov-snet", None, RG)
    collector.record_node("rt-cov-snet", {"name": ROUTE_TABLE, "properties": {"routes": []}}, RG)

    assert collector.keys() == ["rt-cov-snet"]
    assert collector.build_payload().records[0].attributes


# ─── end to end: every lookup-drawn element carries a filled record ──────────


def run_and_read(tmp_path, **kwargs) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    """Render the coverage template in Inspector_Mode and read the payload back."""
    work_dir = str(tmp_path)
    source, _ = run_coverage_generation(
        kwargs.pop("template", None) or coverage_template(),
        work_dir=work_dir,
        interactive_inspector=True,
        **kwargs,
    )
    return source, read_inspector_records(work_dir)


def assert_filled(records: Dict[str, Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    """Assert `key` has a record with rows, and return those rows by path."""
    assert key in records, f"no Inspector_Record for the drawn element '{key}'"
    entries = entries_by_path(records[key])
    assert entries, f"the record of '{key}' carries no Attribute_Entry rows"
    return entries


def test_the_vnet_linked_dns_zone_node_carries_a_filled_record(tmp_path):
    """Requirements 3.2, 4.1: the zone node is drawn from a lookup, not an entry."""
    source, records = run_and_read(tmp_path, linked_zones=[LINKED_ZONE])

    assert f'"{LINKED_ZONE}"' in source
    entries = assert_filled(records, LINKED_ZONE)
    assert entries["properties.numberOfRecordSets"]["after"] == "3"
    assert records[LINKED_ZONE]["resourceType"] == DNS_ZONE_RENDERER_TYPE
    assert records[LINKED_ZONE]["resourceGroup"] == RG


def test_the_unlinked_dns_zone_node_carries_a_filled_record(tmp_path):
    """The zones of a resource group with no VNet link are drawn once each."""
    source, records = run_and_read(tmp_path, unlinked_zones=[UNLINKED_ZONE])

    assert f'"{UNLINKED_ZONE}"' in source
    entries = assert_filled(records, UNLINKED_ZONE)
    assert entries["properties.numberOfRecordSets"]["after"] == "7"


def test_the_aggregated_dns_zone_node_carries_a_filled_record(tmp_path):
    """Requirement 4.4: `PrivateDNSZones-<vnet>` is described by the aggregation."""
    source, records = run_and_read(
        tmp_path,
        linked_zones=[LINKED_ZONE, UNLINKED_ZONE],
        private_dns_zones_optimization=True,
    )

    assert f'"{AGGREGATED_NODE}"' in source
    entries = assert_filled(records, AGGREGATED_NODE)
    assert entries[f"properties.{AGGREGATED_COUNT_KEY}"]["after"] == "2"
    assert entries[f"properties.{AGGREGATED_ZONES_KEY}.0"]["after"] == LINKED_ZONE
    assert any(
        path.startswith(f"properties.{AGGREGATED_ZONE_CONFIG_KEY}.{LINKED_ZONE}.")
        for path in entries
    )
    # The per-zone nodes are not drawn in this mode, so they carry no record.
    assert LINKED_ZONE not in records


def test_the_bastion_node_carries_a_filled_record(tmp_path):
    """Requirements 3.2, 3.4: the Bastion node is keyed by the bare host name."""
    source, records = run_and_read(tmp_path, bastion_name=BASTION)

    assert f'"{BASTION}"' in source
    entries = assert_filled(records, BASTION)
    assert entries["properties.dnsName"]["after"] == "bst.bastion.azure.com"
    assert records[BASTION]["resourceType"] == BASTION_RENDERER_TYPE


def test_the_route_table_and_nsg_nodes_carry_filled_records(tmp_path):
    """Requirements 3.2, 4.1: both are drawn from a subnet dependency only."""
    source, records = run_and_read(tmp_path)

    assert f'"{ROUTE_TABLE_NODE}"' in source
    assert f'"{NSG_NODE}"' in source

    route_table = assert_filled(records, ROUTE_TABLE_NODE)
    assert route_table["properties.routes.0.properties.nextHopType"]["after"] == "VirtualAppliance"
    assert records[ROUTE_TABLE_NODE]["resourceType"] == ROUTE_TABLE_TYPE

    nsg = assert_filled(records, NSG_NODE)
    assert nsg["properties.securityRules.0.properties.destinationPortRange"]["after"] == "443"
    assert records[NSG_NODE]["resourceType"] == NSG_TYPE


def test_every_lookup_drawn_element_of_one_run_carries_a_filled_record(tmp_path):
    """The five new call sites together, in the one run that reaches all of them."""
    _, records = run_and_read(
        tmp_path, linked_zones=[LINKED_ZONE], unlinked_zones=[UNLINKED_ZONE], bastion_name=BASTION
    )

    for key in (LINKED_ZONE, UNLINKED_ZONE, BASTION, ROUTE_TABLE_NODE, NSG_NODE):
        assert_filled(records, key)


# ─── end to end: the guard leaves an undescribable element inert ─────────────


def test_a_node_whose_source_does_not_resolve_yields_no_record(tmp_path):
    """Requirement 3.2: no activatable element with an empty panel.

    The Bastion host and the DNS zone the VNet lookups report are absent from the
    exported resource list, which is the Live and Bicep mode shape. Both nodes are
    still drawn — the Diagram is unaffected — and neither is recorded.
    """
    with singleton_log_sink() as sink:
        source, records = run_and_read(
            tmp_path,
            template=coverage_template(with_zone_resources=False, with_bastion_resource=False),
            linked_zones=[LINKED_ZONE],
            bastion_name=BASTION,
        )

    assert f'"{BASTION}"' in source
    assert f'"{LINKED_ZONE}"' in source
    assert BASTION not in records
    assert LINKED_ZONE not in records
    # The gap is traceable and it is not an anomaly: debug, naming the key.
    debug = messages(sink, logging.DEBUG)
    assert any(BASTION in message for message in debug)
    assert any(LINKED_ZONE in message for message in debug)
    assert not [message for message in messages(sink, logging.WARNING) if BASTION in message]
    # The elements that do resolve are unaffected.
    assert_filled(records, ROUTE_TABLE_NODE)


# ─── end to end: one record per drawn element, no duplicate-key noise ────────


def test_the_unlinked_zone_nodes_are_recorded_once_per_drawn_node(tmp_path):
    """The zone nodes are drawn once per resource; the records are one per node.

    Recording at the draw site fired once per resource per zone, so every resource
    past the first logged a `Duplicate Inspector_Key` warning for every zone — noise
    rather than the genuine key collision Requirement 4.5 describes.
    """
    template = coverage_template()
    template["resources"].append(
        {
            "type": "Microsoft.Storage/storageAccounts",
            "apiVersion": "2023-01-01",
            "name": "planstorage2",
            "location": "westeurope",
            "properties": {"accessTier": "Cool"},
        }
    )

    with singleton_log_sink() as sink:
        _, collectors = run_coverage_generation(
            template,
            work_dir=str(tmp_path),
            interactive_inspector=True,
            unlinked_zones=[UNLINKED_ZONE, LINKED_ZONE],
        )

    keys = collectors[0].keys()
    assert keys.count(UNLINKED_ZONE) == 1
    assert keys.count(LINKED_ZONE) == 1

    duplicates = [message for message in messages(sink, logging.WARNING) if "Duplicate" in message]
    assert not [
        message for message in duplicates if UNLINKED_ZONE in message or LINKED_ZONE in message
    ]


# ─── disabled-mode parity (Requirements 1.3, 1.6) ────────────────────────────


@pytest.mark.parametrize("interactive_inspector", [None, False, True])
def test_the_new_call_sites_leave_the_dot_source_byte_identical(
    interactive_inspector, tmp_path
):
    """Collection is additive: the DOT of every mode is the pre-feature DOT."""
    lookups = {
        "linked_zones": [LINKED_ZONE],
        "unlinked_zones": [UNLINKED_ZONE],
        "bastion_name": BASTION,
    }
    baseline, _ = run_coverage_generation(
        coverage_template(), work_dir=str(tmp_path / "baseline"), **lookups
    )
    candidate, _ = run_coverage_generation(
        coverage_template(),
        work_dir=str(tmp_path / "candidate"),
        interactive_inspector=interactive_inspector,
        **lookups,
    )

    assert baseline == candidate
    assert baseline != ""


def test_the_aggregated_dns_node_leaves_the_dot_source_byte_identical(tmp_path):
    """The aggregated node's synthesized source changes no byte of the Diagram."""
    lookups = {"linked_zones": [LINKED_ZONE, UNLINKED_ZONE], "private_dns_zones_optimization": True}
    disabled, _ = run_coverage_generation(
        coverage_template(), work_dir=str(tmp_path / "off"), interactive_inspector=False, **lookups
    )
    enabled, _ = run_coverage_generation(
        coverage_template(), work_dir=str(tmp_path / "on"), interactive_inspector=True, **lookups
    )

    assert enabled == disabled
    assert AGGREGATED_NODE in enabled


def two_subnet_template() -> Dict[str, Any]:
    """The coverage template with a second subnet sharing the route table and NSG."""
    template = coverage_template()
    for resource in template["resources"]:
        if resource["type"] == "Microsoft.Network/virtualNetworks":
            resource["properties"]["subnets"].append(
                {"name": SECOND_SUBNET, "properties": {"addressPrefix": "10.0.2.0/24"}}
            )
    template["resources"].insert(
        0,
        {
            "type": SUBNET_RENDERER_TYPE,
            "apiVersion": "2023-04-01",
            "name": f"{VNET}/{SECOND_SUBNET}",
            "location": "westeurope",
            "properties": {"addressPrefix": "10.0.2.0/24"},
            "dependsOn": [
                f"[resourceId('Microsoft.Network/routeTables', '{ROUTE_TABLE}')]",
                f"[resourceId('Microsoft.Network/networkSecurityGroups', '{NSG}')]",
            ],
        },
    )
    return template


def test_record_node_once_ignores_a_repeated_node_key():
    """The repeat draw of one element is not the key collision of two elements."""
    collector = InspectorCollector()
    drawn: set = set()
    source = {"name": NSG, "type": NSG_TYPE, "properties": {"securityRules": []}}

    with singleton_log_sink() as sink:
        record_node_once(collector, drawn, NSG_NODE, source, RG)
        record_node_once(collector, drawn, NSG_NODE, source, RG)

    assert collector.keys() == [NSG_NODE]
    assert collector.key_collisions == 0
    assert not [message for message in messages(sink, logging.WARNING) if "Duplicate" in message]


def test_an_nsg_shared_by_two_subnets_is_recorded_once(tmp_path):
    """Requirement 4.5: the NSG is keyed per resource group but drawn per subnet."""
    with singleton_log_sink() as sink:
        _, collectors = run_coverage_generation(
            two_subnet_template(), work_dir=str(tmp_path), interactive_inspector=True
        )

    keys = collectors[0].keys()
    assert keys.count(NSG_NODE) == 1
    assert keys.count(ROUTE_TABLE_NODE) == 1
    assert f"{ROUTE_TABLE}-{SECOND_SUBNET}" in keys
    assert not [
        message
        for message in messages(sink, logging.WARNING)
        if "Duplicate" in message and (NSG in message or ROUTE_TABLE in message)
    ]


def test_the_second_subnet_route_table_node_carries_a_filled_record(tmp_path):
    """Both drawn route-table nodes are described by the one route table resource."""
    work_dir = str(tmp_path)
    run_coverage_generation(two_subnet_template(), work_dir=work_dir, interactive_inspector=True)
    records = read_inspector_records(work_dir)

    for key in (ROUTE_TABLE_NODE, f"{ROUTE_TABLE}-{SECOND_SUBNET}"):
        entries = assert_filled(records, key)
        assert entries["properties.disableBgpRoutePropagation"]["after"] == "true"


def test_the_repeat_draw_guard_leaves_the_dot_source_byte_identical(tmp_path):
    """Requirements 1.3, 1.6: the guard is about records, not about the Diagram."""
    disabled, _ = run_coverage_generation(
        two_subnet_template(), work_dir=str(tmp_path / "off"), interactive_inspector=False
    )
    enabled, _ = run_coverage_generation(
        two_subnet_template(), work_dir=str(tmp_path / "on"), interactive_inspector=True
    )

    assert enabled == disabled
    assert NSG_NODE in enabled
