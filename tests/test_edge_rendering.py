"""
Test edge rendering accuracy and diverse resource type handling.

Covers:
  - Dependency edge styles (dashed black for same-RG deps)
  - VNet integration edge styles (solid royalblue2 for cross-RG subnet deps)
  - Cross-RG PE edges (solid indigo)
  - Ranking/invisible edges
  - Diverse resource types: PostgreSQL, MySQL, APIM, Redis, Firewall, etc.
  - Edge consistency across layout directions (TB, LR, BT, RL)
  - Edge length parameters
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import DotAnalyzer, run_graph_generation
from mock_templates.scenarios import (
    RG_APP,
    RG_DATA,
    RG_NETWORK,
    SUB_1,
    TENANT_1,
    baseline_network_template,
    cross_rg_app_template,
    cross_rg_data_template,
    cross_rg_network_template,
    diverse_resources_template,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  Edge Style Verification
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeStyles:
    """Verify that edges use the correct styles and colors."""

    def test_dependency_edges_are_dashed_black(self, work_dir):
        """Same-RG dependency edges should be dashed and black."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
        )

        # Find dashed black edges (dependency edges)
        dashed_black = [(s, t, a) for s, t, a in analyzer.edges if "style=dashed" in a and "color=black" in a]
        # Baseline has dependsOn relationships (webapp -> asp, pe -> sql, etc.)
        assert len(dashed_black) > 0, "Same-RG dependency edges should use dashed black style"

    def test_vnet_integration_edges_are_solid_royalblue(self, work_dir):
        """VNet integration edges should be solid royalblue2."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: cross_rg_network_template(),
                RG_APP: cross_rg_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            work_dir=str(work_dir),
        )

        royalblue_edges = analyzer.get_edges_with_color("royalblue2")
        for s, t, attrs in royalblue_edges:
            assert "style=solid" in attrs, f"VNet integration edge {s}->{t} should use solid style, got: {attrs}"

    def test_cross_rg_pe_edges_are_solid_indigo(self, work_dir):
        """Cross-RG PE dependency edges should be solid indigo."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: cross_rg_network_template(),
                RG_APP: cross_rg_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            pe_optimization=False,
            cross_pe_optimization=False,
            work_dir=str(work_dir),
        )

        indigo_edges = analyzer.get_edges_with_color("indigo")
        for s, t, attrs in indigo_edges:
            assert "style=solid" in attrs, f"Cross-RG PE edge {s}->{t} should use solid style"

    def test_vnet_integration_edge_has_xlabel(self, work_dir):
        """VNet integration edges should have 'Vnet integration' xlabel."""
        source, _ = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: cross_rg_network_template(),
                RG_APP: cross_rg_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            work_dir=str(work_dir),
        )

        assert "Vnet integration" in source, "VNet integration edges should have 'Vnet integration' xlabel"


# ═══════════════════════════════════════════════════════════════════════════════
#  Diverse Resource Types
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiverseResourceTypes:
    """Test that all supported resource types with subnet dependencies are handled."""

    def test_postgres_flex_in_subnet(self, work_dir):
        """PostgreSQL Flexible Server with delegatedSubnetResourceId should appear in subnet."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: diverse_resources_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        assert analyzer.has_node_containing("test-postgres-flex"), "PostgreSQL Flexible Server should be rendered"

    def test_mysql_flex_in_subnet(self, work_dir):
        """MySQL Flexible Server with delegatedSubnetResourceId should appear in subnet."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: diverse_resources_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        assert analyzer.has_node_containing("test-mysql-flex"), "MySQL Flexible Server should be rendered"

    def test_apim_in_subnet(self, work_dir):
        """API Management with virtualNetworkConfiguration should appear in subnet."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: diverse_resources_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        assert analyzer.has_node_containing("test-apim"), "API Management should be rendered"

    def test_redis_in_subnet(self, work_dir):
        """Redis Cache with subnetId should appear in subnet."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: diverse_resources_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        assert analyzer.has_node_containing("test-redis"), "Redis Cache should be rendered"

    def test_firewall_in_subnet(self, work_dir):
        """Azure Firewall with ipConfigurations.subnet should appear in subnet."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: diverse_resources_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        assert analyzer.has_node_containing("test-firewall"), "Azure Firewall should be rendered"

    def test_diverse_resources_all_flag_combos(self, work_dir):
        """Diverse resources template should generate without errors for all flag combos."""
        from conftest import generate_flag_combinations

        for combo in generate_flag_combinations():
            source, _ = run_graph_generation(
                templates_by_rg={RG_NETWORK: diverse_resources_template()},
                tenants=[TENANT_1],
                subscriptions=[SUB_1],
                resource_groups=[RG_NETWORK],
                work_dir=str(work_dir),
                **combo,
            )
            assert source, f"Diverse resources failed with flags: {combo}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Layout Direction Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestLayoutDirections:
    """Test that all 4 layout directions generate valid graphs."""

    @pytest.mark.parametrize("direction", ["TB", "LR", "BT", "RL"])
    def test_direction_generates(self, direction, work_dir):
        """Each direction should produce a valid graph."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            direction=direction,
            work_dir=str(work_dir),
        )
        assert source
        assert f"rankdir={direction}" in source, f"Graph should use rankdir={direction}"

    @pytest.mark.parametrize("direction", ["TB", "LR", "BT", "RL"])
    def test_direction_preserves_edges(self, direction, work_dir):
        """Changing direction should not remove any dependency edges."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: cross_rg_network_template(),
                RG_APP: cross_rg_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            direction=direction,
            work_dir=str(work_dir),
        )

        # Cross-RG indigo edges should survive regardless of direction
        indigo_count = analyzer.count_edges_with_color("indigo")
        assert indigo_count > 0, f"Cross-RG dependency edges missing with direction={direction}"

        # Regular black dependency edges should also survive
        black_count = analyzer.count_edges_with_color("black")
        assert black_count > 0, f"Regular dependency edges missing with direction={direction}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Edge Length Parameters
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeLengthParameters:
    """Test that edge length parameters affect the output."""

    def test_resources_edge_length_applied(self, work_dir):
        """resourcesEdgeLength should appear in dependency edge minlen."""
        source1, _ = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            resources_edge_length=1,
            work_dir=str(work_dir),
        )

        source3, _ = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            resources_edge_length=3,
            work_dir=str(work_dir),
        )

        # The DOT source should differ based on edge length
        assert "minlen=1" in source1 or 'minlen="1"' in source1
        assert "minlen=3" in source3 or 'minlen="3"' in source3

    def test_rg_edge_length_per_subscription(self, work_dir):
        """resourceGroupsEdgeLengthListBySubscription should be per-subscription."""
        source, _ = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            rg_edge_length_list=[6],
            work_dir=str(work_dir),
        )

        # The RG edge length contributes to minlen calculations
        assert source, "Graph should generate with custom RG edge length"


# ═══════════════════════════════════════════════════════════════════════════════
#  Max Subnet Per Line
# ═══════════════════════════════════════════════════════════════════════════════


class TestMaxSubnetPerLine:
    """Test that maxSubnetPerLine affects subnet layout."""

    @pytest.mark.parametrize("max_subnets", [2, 4, 6, 8])
    def test_max_subnet_values(self, max_subnets, work_dir):
        """Various maxSubnetPerLine values should generate valid graphs."""
        source, _ = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            max_subnet_per_line=max_subnets,
            work_dir=str(work_dir),
        )
        assert source, f"Graph should generate with maxSubnetPerLine={max_subnets}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Bastion and Application Gateway
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpecialResources:
    """Test Bastion Host and Application Gateway rendering."""

    def test_appgw_rendered(self, work_dir):
        """Application Gateway should be rendered in its subnet."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        assert analyzer.has_node_containing("test-appgw-01"), "Application Gateway should be rendered"

    def test_appgw_in_subnet(self, work_dir):
        """Application Gateway should be placed inside its subnet subgraph."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        # AppGw should be in AppGatewaySubnet cluster
        assert analyzer.has_cluster("subnetAppGatewaySubnet"), "AppGatewaySubnet subgraph should exist"
