"""
Shared pytest fixtures for CloudHorus QA testing.

Strategy:
  - Mock `build_bicep_template` to write pre-built ARM JSON to a temp file and return its path.
  - Let `register_multiple_bicep_templates` work normally (it just stores dicts in memory).
  - Let `is_resource_group_in_subscription`, `is_subscription_in_tenant` work via registered mappings.
  - Mock `get_private_dns_zones_without_vnets`, `is_vnet_linked_to_private_dns_zone`,
    `get_bastion_host_name` to return template-aware results.
  - Suppress auto-open of generated PNG.
"""

import json
import os
import re
import shutil
import sys
import tempfile
from itertools import product
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

# Add src/ and tests/ to path so core modules and mock_templates can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from mock_templates.scenarios import (
    RG_APP,
    RG_CROSS,
    RG_DATA,
    RG_NETWORK,
    SUB_1,
    SUB_2,
    TENANT_1,
    TENANT_2,
)

# ─── Helpers ──────────────────────────────────────────────────────────────────


def write_template_to_file(template: dict, directory: str, rg_name: str) -> str:
    """Write an ARM template dict to a JSON file and return the path."""
    path = os.path.join(directory, f"{rg_name}-template.json")
    with open(path, "w") as f:
        json.dump(template, f, indent=2)
    return path


class MockBicepBuilder:
    """
    Intercepts build_bicep_template calls to write pre-built ARM JSON.

    Maps by bicep filename (basename) to template dict.  When the resource_processor
    passes the wrong file path (it uses subscription_index rather than rg_index),
    the mock still returns a valid template path for whatever filename was requested.
    """

    def __init__(self, templates_by_bicep_name: Dict[str, dict], output_dir: str):
        self.templates = templates_by_bicep_name
        self.output_dir = output_dir
        self._built = {}

    def build(self, bicep_file: str, parameters_file: str = None) -> Optional[str]:
        """Mock build_bicep_template: write template JSON and return path."""
        basename = os.path.basename(bicep_file)
        if basename in self.templates:
            outpath = os.path.join(self.output_dir, f"{basename.replace('.bicep', '')}-built-template.json")
            # Return cached path if already written
            if basename in self._built:
                return self._built[basename]
            with open(outpath, "w") as f:
                json.dump(self.templates[basename], f, indent=2)
            self._built[basename] = outpath
            return outpath
        return None


class DotAnalyzer:
    """
    Parse a Graphviz DOT source string and provide assertion helpers.

    Usage:
        analyzer = DotAnalyzer(dot.source)
        assert analyzer.has_node('test-webapp-01-test-rg-network')
        assert analyzer.has_edge_with_color('royalblue')
        assert analyzer.count_edges_with_color('royalblue2') == 3
    """

    def __init__(self, dot_source: str):
        self.source = dot_source
        self._nodes = None
        self._edges = None

    @property
    def nodes(self) -> List[str]:
        """Extract all node IDs from DOT source."""
        if self._nodes is None:
            # Match node definitions: "nodeId" [attr=...] or "nodeId" [label=...]
            self._nodes = re.findall(r'^\s*"([^"]+)"\s*\[', self.source, re.MULTILINE)
        return self._nodes

    @property
    def edges(self) -> List[Tuple[str, str, str]]:
        """Extract all edges as (source, target, attributes_string) tuples.
        Handles both quoted and unquoted node IDs in DOT format."""
        if self._edges is None:
            # Match edges where source/target may be quoted or unquoted
            self._edges = re.findall(r'"?([^"\s]+)"?\s*->\s*"?([^"\s\[]+)"?\s*\[([^\]]*)\]', self.source)
        return self._edges

    def has_node(self, node_id: str) -> bool:
        """Check if a node with given ID exists."""
        return node_id in self.nodes

    def has_node_containing(self, substring: str) -> bool:
        """Check if any node ID contains the substring."""
        return any(substring in n for n in self.nodes)

    def get_nodes_containing(self, substring: str) -> List[str]:
        """Get all node IDs containing the substring."""
        return [n for n in self.nodes if substring in n]

    def has_edge(self, source: str, target: str) -> bool:
        """Check if an edge exists between source and target."""
        return any(s == source and t == target for s, t, _ in self.edges)

    def has_edge_containing(self, source_sub: str, target_sub: str) -> bool:
        """Check if any edge has source/target containing the substrings."""
        return any(source_sub in s and target_sub in t for s, t, _ in self.edges)

    def has_edge_with_color(self, color: str) -> bool:
        """Check if any edge has the specified color."""
        return any(f"color={color}" in attrs or f'color="{color}"' in attrs for _, _, attrs in self.edges)

    def count_edges_with_color(self, color: str) -> int:
        """Count edges with the specified color."""
        return sum(1 for _, _, attrs in self.edges if f"color={color}" in attrs or f'color="{color}"' in attrs)

    def get_edges_with_color(self, color: str) -> List[Tuple[str, str, str]]:
        """Get all edges with the specified color."""
        return [(s, t, a) for s, t, a in self.edges if f"color={color}" in a or f'color="{color}"' in a]

    def has_subgraph(self, name: str) -> bool:
        """Check if a named subgraph/cluster exists."""
        return f"subgraph {name}" in self.source or f'subgraph "{name}"' in self.source

    def has_cluster(self, suffix: str) -> bool:
        """Check if a cluster with given suffix exists (cluster_xxx)."""
        return f"subgraph cluster_{suffix}" in self.source or f'subgraph "cluster_{suffix}"' in self.source

    def count_subgraphs_containing(self, substring: str) -> int:
        """Count subgraphs whose name contains the substring."""
        return len(re.findall(rf'subgraph\s+["\']?cluster_{re.escape(substring)}', self.source))

    def has_label_containing(self, text: str) -> bool:
        """Check if any label attribute contains the text."""
        return text in self.source

    def get_edge_style(self, source: str, target: str) -> Optional[str]:
        """Get the style attribute of an edge between source and target."""
        for s, t, attrs in self.edges:
            if s == source and t == target:
                m = re.search(r"style=(\w+)", attrs)
                return m.group(1) if m else None
        return None

    def has_edge_with_endpoints(self, source_sub: str, target_sub: str, color: str) -> bool:
        """Check if an edge exists matching source/target substrings with a specific color."""
        for s, t, attrs in self.edges:
            if source_sub in s and target_sub in t:
                if f"color={color}" in attrs or f'color="{color}"' in attrs:
                    return True
        return False

    def get_visible_edges(self) -> List[Tuple[str, str, str, str]]:
        """Get all non-invisible edges as (source, target, color, style) tuples."""
        result = []
        for s, t, attrs in self.edges:
            if "style=invis" in attrs:
                continue
            color_m = re.search(r"color=(\w+)", attrs)
            style_m = re.search(r"style=(\w+)", attrs)
            color = color_m.group(1) if color_m else "unknown"
            style = style_m.group(1) if style_m else "unknown"
            result.append((s, t, color, style))
        return result

    def assert_edge_exists(self, source_sub: str, target_sub: str, color: str, msg: str = ""):
        """Assert that an edge with given source/target substrings and color exists."""
        if not self.has_edge_with_endpoints(source_sub, target_sub, color):
            matching = [(s, t) for s, t, a in self.edges if (f"color={color}" in a or f'color="{color}"' in a)]
            raise AssertionError(
                f"{msg}Expected {color} edge matching '{source_sub}' -> '{target_sub}' "
                f"but found only these {color} edges: {matching}"
            )

    def assert_no_edge(self, source_sub: str, target_sub: str, color: str, msg: str = ""):
        """Assert that NO edge with given source/target substrings and color exists."""
        if self.has_edge_with_endpoints(source_sub, target_sub, color):
            raise AssertionError(f"{msg}Unexpected {color} edge found matching '{source_sub}' -> '{target_sub}'")


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def work_dir(tmp_path):
    """Create a temporary working directory and change to it."""
    orig_dir = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(orig_dir)


@pytest.fixture
def icons_dir():
    """Return the real icons directory path."""
    return os.path.join(os.path.dirname(__file__), "..", "icons")


def _extract_dns_zones_from_template(template: dict) -> List[str]:
    """Extract private DNS zone names from a template."""
    zones = []
    for r in template.get("resources", []):
        if r.get("type") == "Microsoft.Network/privateDnsZones":
            zones.append(r["name"])
    return zones


def _extract_dns_vnet_links(template: dict, vnet_name: str) -> List[str]:
    """Extract DNS zone names linked to a specific VNet."""
    linked_zones = []
    for r in template.get("resources", []):
        if r.get("type") == "Microsoft.Network/privateDnsZones/virtualNetworkLinks":
            vnet_ref = r.get("properties", {}).get("virtualNetwork", {}).get("id", "")
            if vnet_name in vnet_ref:
                # Zone name is the first part of the resource name (zone/link-name)
                zone_name = r["name"].split("/")[0]
                linked_zones.append(zone_name)
    return linked_zones


def _extract_bastion_for_vnet(template: dict, vnet_name: str) -> Optional[str]:
    """Extract bastion host name linked to a VNet."""
    for r in template.get("resources", []):
        if r.get("type") == "Microsoft.Network/bastionHosts":
            for dep in r.get("dependsOn", []):
                if vnet_name in dep:
                    return r["name"]
            # Also check ipConfigurations subnet
            for ipconf in r.get("properties", {}).get("ipConfigurations", []):
                subnet_id = ipconf.get("properties", {}).get("subnet", {}).get("id", "")
                if vnet_name in subnet_id:
                    return r["name"]
    return None


def run_graph_generation(
    templates_by_rg: Dict[str, dict],
    tenants: List[str],
    subscriptions: List[str],
    resource_groups: List[str],
    *,
    rg_to_subscription: Optional[Dict[str, str]] = None,
    rg_to_tenant: Optional[Dict[str, str]] = None,
    subnet_optimization=False,
    pe_optimization=True,
    cross_pe_optimization=False,
    private_dns_zones_optimization=True,
    direction="TB",
    tenant_minlen="LR",
    max_subnet_per_line=4,
    rank_debug="invis",
    resources_edge_length=1,
    rg_edge_length_list=None,
    discover_rgs=None,
    export_drawio=False,
    work_dir=None,
) -> Tuple[str, "DotAnalyzer"]:
    """
    Run generate_resource_graph with mocked Azure calls and pre-built ARM templates.

    Args:
        templates_by_rg: Mapping of RG name -> ARM template dict
        tenants: Unique list of tenant IDs
        subscriptions: Unique list of subscription IDs
        resource_groups: List of resource group names
        rg_to_subscription: Optional mapping of RG name -> subscription ID.
                           If None, all RGs are assigned to subscriptions[0].
        rg_to_tenant: Optional mapping of RG name -> tenant ID.
                     If None, all RGs are assigned to tenants[0].
        All other args: Configuration flags

    Returns:
        Tuple of (dot_source_string, DotAnalyzer)
    """
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="cloudhorus_test_")

    # Build the expanded subscriptions list (one per RG, matching register_multiple_bicep_templates contract)
    if rg_to_subscription is None:
        # Default: all RGs belong to the first subscription
        expanded_subscriptions = [subscriptions[0]] * len(resource_groups)
    else:
        expanded_subscriptions = [rg_to_subscription[rg] for rg in resource_groups]

    # Build the expanded tenants list (one per RG)
    if rg_to_tenant is None:
        expanded_tenants = [tenants[0]] * len(resource_groups)
    else:
        expanded_tenants = [rg_to_tenant[rg] for rg in resource_groups]

    # In production, per-subscription flags are indexed by position in the
    # expanded subscriptions list (one entry per RG).  The graph_generator
    # skips duplicate subscriptions via processed_subscriptions, so only
    # the FIRST occurrence's flag value is actually used.  We must size the
    # flag lists to match len(expanded_subscriptions) to avoid IndexError.
    num_entries = len(expanded_subscriptions)

    if rg_edge_length_list is None:
        rg_edge_length_list = [4] * num_entries

    # Prepare bicep file/param file pairs (one per RG)
    bicep_files = [os.path.join(str(work_dir), f"{rg}.bicep") for rg in resource_groups]
    parameters_files = [os.path.join(str(work_dir), f"{rg}.params.json") for rg in resource_groups]

    # Create dummy bicep and parameter files
    for bf, pf in zip(bicep_files, parameters_files):
        with open(bf, "w") as f:
            f.write("// dummy bicep\n")
        with open(pf, "w") as f:
            json.dump({"$schema": "dummy", "parameters": {}}, f)

    # Build MockBicepBuilder mapping
    bicep_to_template = {}
    for rg, template in templates_by_rg.items():
        bicep_to_template[f"{rg}.bicep"] = template

    builder = MockBicepBuilder(bicep_to_template, str(work_dir))

    # Normalize per-subscription flags to match expanded_subscriptions length.
    # Each position corresponds to a (subscription, RG) entry.
    if isinstance(subnet_optimization, bool):
        subnet_optimization = [subnet_optimization] * num_entries
    if isinstance(pe_optimization, bool):
        pe_optimization = [pe_optimization] * num_entries
    if isinstance(cross_pe_optimization, bool):
        cross_pe_optimization = [cross_pe_optimization] * num_entries

    # Merge all templates for DNS/Bastion mock lookups
    all_templates = {}
    for rg, template in templates_by_rg.items():
        all_templates[rg] = template

    def mock_dns_zones_without_vnets(resource_group, subscription_id, use_local_template=False, template_data=None):
        """Return DNS zones that have no VNet links."""
        t = all_templates.get(resource_group, {"resources": []})
        all_zones = _extract_dns_zones_from_template(t)
        # Find zones that DO have VNet links
        linked_zones = set()
        for r in t.get("resources", []):
            if r.get("type") == "Microsoft.Network/privateDnsZones/virtualNetworkLinks":
                zone_name = r["name"].split("/")[0]
                linked_zones.add(zone_name)
        return [z for z in all_zones if z not in linked_zones]

    def mock_vnet_linked_dns(
        vnet_name, resource_groups_list, subscription_id, use_local_template=False, template_data=None
    ):
        """Return DNS zones linked to the given VNet."""
        linked = []
        for rg in resource_groups_list:
            t = all_templates.get(rg, {"resources": []})
            linked.extend(_extract_dns_vnet_links(t, vnet_name))
        return linked

    def mock_bastion_host(vnet_name, resource_group, subscription_id, use_local_template=False, template_data=None):
        """Return bastion host name if one exists for the VNet."""
        t = all_templates.get(resource_group, {"resources": []})
        return _extract_bastion_for_vnet(t, vnet_name)

    captured_dot = {}

    def mock_render(self, filename=None, format=None, *args, **kwargs):
        """Capture DOT output instead of actually rendering."""
        captured_dot["source"] = self.source
        # Write DOT file for debugging
        if filename:
            dot_path = f"{filename}.dot"
            with open(dot_path, "w") as f:
                f.write(self.source)
            # Write empty PNG to satisfy return path
            png_path = f"{filename}.png"
            with open(png_path, "w") as f:
                f.write("")
        return filename

    def mock_unflatten(self, *args, **kwargs):
        """Pass through unflatten."""
        return self

    # Apply all mocks
    with (
        patch("core.graph_generator.build_bicep_template", side_effect=builder.build),
        patch("core.bicep_builder.build_bicep_template", side_effect=builder.build),
        patch("core.graph_generator.get_private_dns_zones_without_vnets", side_effect=mock_dns_zones_without_vnets),
        patch("core.graph_generator.is_vnet_linked_to_private_dns_zone", side_effect=mock_vnet_linked_dns),
        patch("core.graph_generator.get_bastion_host_name", side_effect=mock_bastion_host),
        patch("graphviz.Digraph.render", mock_render),
        patch("graphviz.Digraph.unflatten", mock_unflatten),
        patch("subprocess.run", return_value=MagicMock()),
    ):  # Suppress auto-open

        from core.graph_generator import generate_resource_graph

        generate_resource_graph(
            tenants=expanded_tenants,
            subscriptions=expanded_subscriptions,
            resource_groups=resource_groups,
            subnet_optimization=subnet_optimization,
            direction=direction,
            tenant_minlen=tenant_minlen,
            max_subnet_in_line=max_subnet_per_line,
            rankDebug=rank_debug,
            peOptimization=pe_optimization,
            privateDnsZonesOptimization=private_dns_zones_optimization,
            resourcesEdgeLength=resources_edge_length,
            resourceGroupsEdgeLengthListBySubscription=rg_edge_length_list,
            crossPeOptimization=cross_pe_optimization,
            discoverResourceGroups=discover_rgs,
            exportDrawio=export_drawio,
            use_local_template=True,
            bicep_files=bicep_files,
            parameters_files=parameters_files,
        )

    dot_source = captured_dot.get("source", "")
    return dot_source, DotAnalyzer(dot_source)


# ─── Flag Combination Generator ──────────────────────────────────────────────

# Boolean optimization flags (per-subscription)
BOOL_FLAGS = ["subnet_optimization", "pe_optimization", "cross_pe_optimization", "private_dns_zones_optimization"]


def generate_flag_combinations(include_dns: bool = True) -> List[Dict[str, bool]]:
    """
    Generate all combinations of the 4 boolean optimization flags.
    Returns list of dicts with flag names as keys.
    """
    flags = BOOL_FLAGS if include_dns else BOOL_FLAGS[:3]
    combos = []
    for values in product([False, True], repeat=len(flags)):
        combos.append(dict(zip(flags, values)))
    return combos


def flag_combo_id(combo: Dict[str, bool]) -> str:
    """Generate a short test ID from a flag combination dict."""
    parts = []
    for flag, val in combo.items():
        short = "".join(w[0] for w in flag.split("_"))  # e.g. 'so', 'po', 'cpo', 'pdzo'
        parts.append(f"{short}={'T' if val else 'F'}")
    return "_".join(parts)
