"""
Test all 16 boolean flag combinations against the baseline scenario.

Tests every combination of:
  - subnet_optimization (True/False)
  - pe_optimization (True/False)
  - cross_pe_optimization (True/False)
  - private_dns_zones_optimization (True/False)

For each combination, verifies:
  1. Graph generates without errors
  2. Core structural elements exist (tenant, subscription, RG subgraphs)
  3. VNet and subnet subgraphs exist as expected
  4. Resource nodes are present
  5. Flag-specific behavior is correct
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import (
    DotAnalyzer,
    flag_combo_id,
    generate_flag_combinations,
    run_graph_generation,
)
from mock_templates.scenarios import (
    RG_APP,
    RG_DATA,
    RG_NETWORK,
    SUB_1,
    TENANT_1,
    baseline_network_template,
)

# ─── Parametrized: All 16 flag combos on Baseline template ───────────────────

ALL_COMBOS = generate_flag_combinations(include_dns=True)


@pytest.fixture(params=ALL_COMBOS, ids=[flag_combo_id(c) for c in ALL_COMBOS])
def flag_combo(request):
    return request.param


class TestBaselineFlagCombinations:
    """Run all 16 flag combos against the single-RG baseline template."""

    def test_generates_without_error(self, flag_combo, work_dir):
        """Graph generation should complete without exceptions for any flag combo."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
            **flag_combo,
        )
        assert source, f"DOT source is empty for flags: {flag_combo}"

    def test_structural_subgraphs_exist(self, flag_combo, work_dir):
        """Tenant, subscription, and RG subgraphs must always exist."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
            **flag_combo,
        )
        assert analyzer.has_cluster(f"tenant{TENANT_1}")
        assert analyzer.has_cluster(f"subscription{SUB_1}")
        assert analyzer.has_cluster(f"resource_group{RG_NETWORK}")

    def test_vnet_subgraph_exists(self, flag_combo, work_dir):
        """The VNet subgraph must always be created."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
            **flag_combo,
        )
        assert analyzer.has_cluster("vnettest-vnet-01")

    def test_webapp_node_exists(self, flag_combo, work_dir):
        """Web App node should always be present."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
            **flag_combo,
        )
        assert analyzer.has_node_containing("test-webapp-01")

    def test_sql_node_exists(self, flag_combo, work_dir):
        """SQL Server node should always be present."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
            **flag_combo,
        )
        assert analyzer.has_node_containing("test-sql-server-01")

    def test_storage_node_exists(self, flag_combo, work_dir):
        """Storage account node should always be present."""
        source, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
            **flag_combo,
        )
        assert analyzer.has_node_containing("teststorage01")


class TestSubnetOptimization:
    """Tests specific to subnet_optimization flag behavior."""

    def test_empty_subnets_hidden_when_optimization_on(self, work_dir):
        """With subnetOptimization=True, subnets with no resources should not appear."""
        from mock_templates.scenarios import subnet_optimization_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_optimization_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=True,
            work_dir=str(work_dir),
        )

        # Empty subnets should NOT have cluster subgraphs
        for empty in ["empty-subnet-1", "empty-subnet-2", "empty-subnet-3", "empty-subnet-4", "empty-subnet-5"]:
            assert not analyzer.has_cluster(
                f"subnet{empty}"
            ), f"Empty subnet {empty} should be hidden when subnetOptimization=True"

    def test_used_subnets_visible_when_optimization_on(self, work_dir):
        """With subnetOptimization=True, subnets WITH resources should still appear."""
        from mock_templates.scenarios import subnet_optimization_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_optimization_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=True,
            work_dir=str(work_dir),
        )

        # Used subnets should have resources placed in them
        assert analyzer.has_node_containing("webapp-in-subnet"), "Web App in used-subnet-1 should be visible"

    def test_all_subnets_shown_when_optimization_off(self, work_dir):
        """With subnetOptimization=False, all subnets should appear (even empty ones)."""
        from mock_templates.scenarios import subnet_optimization_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_optimization_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )

        # Check at least some empty subnets have subgraphs
        for empty in ["empty-subnet-1", "empty-subnet-2"]:
            assert analyzer.has_cluster(
                f"subnet{empty}"
            ), f"Empty subnet {empty} should be visible when subnetOptimization=False"

    def test_infra_only_subnets_hidden_when_optimization_on(self, work_dir):
        """Subnets with only NSGs/route tables (no VNet integration) should be hidden."""
        from mock_templates.scenarios import subnet_with_infra_only_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_with_infra_only_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=True,
            work_dir=str(work_dir),
        )

        # infra-only-subnet has NSG + route table but no VNet integration → hidden
        assert not analyzer.has_cluster(
            "subnetinfra-only-subnet"
        ), "infra-only-subnet should be hidden (only NSG/route table, no VNet integration)"
        # pe-subnet has a PE → PEs count as VNet integration, so subnet survives
        assert analyzer.has_cluster("subnetpe-subnet"), "pe-subnet should be visible (PE keeps the subnet alive)"
        # empty-subnet has nothing → hidden
        assert not analyzer.has_cluster("subnetempty-subnet"), "empty-subnet should be hidden (no resources at all)"

    def test_integrated_subnet_visible_when_optimization_on(self, work_dir):
        """Subnet with VNet integration (Web App) should survive subnetOptimization."""
        from mock_templates.scenarios import subnet_with_infra_only_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_with_infra_only_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=True,
            work_dir=str(work_dir),
        )

        # integrated-subnet has Web App with VNet integration → visible
        assert analyzer.has_cluster(
            "subnetintegrated-subnet"
        ), "integrated-subnet should be visible (has VNet integration via Web App)"

    def test_infra_only_subnets_visible_when_optimization_off(self, work_dir):
        """All subnets (including infra-only) should be visible when optimization is off."""
        from mock_templates.scenarios import subnet_with_infra_only_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_with_infra_only_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )

        for subnet in ["integrated-subnet", "infra-only-subnet", "pe-subnet"]:
            assert analyzer.has_cluster(f"subnet{subnet}"), f"{subnet} should be visible when subnetOptimization=False"


class TestPeOptimization:
    """Tests specific to pe_optimization flag behavior."""

    def test_pe_grouped_by_subnet_when_optimization_on(self, work_dir):
        """With peOptimization=True, PE nodes should be named privateEndpoints-{subnet}."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        # PEs should be grouped: privateEndpoints-PrivateEndpointSubnet
        assert analyzer.has_node_containing(
            "privateEndpoints-PrivateEndpointSubnet"
        ), "PEs should be grouped by subnet when peOptimization=True"

    def test_pe_individual_when_optimization_off(self, work_dir):
        """With peOptimization=False, PE nodes should use their actual names."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            pe_optimization=False,
            work_dir=str(work_dir),
        )
        # PEs should have individual names
        assert analyzer.has_node_containing("pe-sql-01") or analyzer.has_node_containing(
            "pe-storage-01"
        ), "PEs should have individual names when peOptimization=False"


class TestCrossPeOptimization:
    """Tests specific to crossPeOptimization flag behavior."""

    def test_pe_without_cross_deps_hidden_when_optimization_on(self, work_dir):
        """With crossPeOptimization=True, PEs with no cross-RG deps should be hidden."""
        from mock_templates.scenarios import (
            RG_DATA,
            many_pe_app_template,
            many_pe_data_template,
            many_pe_network_template,
        )

        cross_indices = [0, 3, 7]
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: many_pe_network_template(),
                RG_APP: many_pe_app_template(num_pe=10, cross_rg_indices=cross_indices),
                RG_DATA: many_pe_data_template(cross_rg_indices=cross_indices),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            cross_pe_optimization=True,
            pe_optimization=False,  # Use individual PE names for clarity
            work_dir=str(work_dir),
        )

        # PEs with cross-RG deps (indices 0, 3, 7) should exist
        for idx in cross_indices:
            assert analyzer.has_node_containing(
                f"pe-svc-{idx:02d}"
            ), f"PE pe-svc-{idx:02d} has cross-RG dep and should be visible"

        # PEs with same-RG deps only should be hidden
        same_rg_indices = [i for i in range(10) if i not in cross_indices]
        for idx in same_rg_indices:
            assert not analyzer.has_node_containing(
                f"pe-svc-{idx:02d}"
            ), f"PE pe-svc-{idx:02d} has only same-RG dep and should be hidden"

    def test_all_pe_visible_when_optimization_off(self, work_dir):
        """With crossPeOptimization=False, all PEs should be visible."""
        from mock_templates.scenarios import many_pe_app_template, many_pe_network_template

        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: many_pe_network_template(),
                RG_APP: many_pe_app_template(num_pe=5, cross_rg_indices=[0]),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP],
            cross_pe_optimization=False,
            pe_optimization=False,
            work_dir=str(work_dir),
        )

        # All PEs should be visible
        for idx in range(5):
            assert analyzer.has_node_containing(
                f"pe-svc-{idx:02d}"
            ), f"PE pe-svc-{idx:02d} should be visible when crossPeOptimization=False"


class TestDnsZonesOptimization:
    """Tests specific to privateDnsZonesOptimization flag behavior."""

    def test_dns_zones_aggregated_when_optimization_on(self, work_dir):
        """With privateDnsZonesOptimization=True, linked DNS zones should be aggregated into one node."""
        from mock_templates.scenarios import dns_zones_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: dns_zones_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            private_dns_zones_optimization=True,
            work_dir=str(work_dir),
        )

        # Should have aggregated DNS zone node
        assert analyzer.has_node_containing(
            "PrivateDNSZones"
        ), "Aggregated PrivateDNSZones node should exist when optimization=True"

    def test_dns_zones_individual_when_optimization_off(self, work_dir):
        """With privateDnsZonesOptimization=False, each DNS zone should be a separate node."""
        from mock_templates.scenarios import dns_zones_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: dns_zones_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            private_dns_zones_optimization=False,
            work_dir=str(work_dir),
        )

        # Individual DNS zone nodes should exist
        assert analyzer.has_node_containing(
            "privatelink.database"
        ), "Individual DNS zone nodes should exist when optimization=False"


class TestNoVnetScenario:
    """Test graph generation with resources that have no VNet."""

    def test_generates_without_vnet(self, work_dir):
        """Graph should generate successfully even without any VNet."""
        from mock_templates.scenarios import no_vnet_template

        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: no_vnet_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
        )

        # Should have standalone resource nodes
        assert analyzer.has_node_containing("standalone-storage")
        assert analyzer.has_node_containing("standalone-sql")
        assert analyzer.has_node_containing("standalone-kv")

    def test_no_vnet_no_subnet_subgraphs(self, work_dir):
        """Without VNet, there should be no VNet/subnet subgraphs."""
        from mock_templates.scenarios import no_vnet_template

        source, _ = run_graph_generation(
            templates_by_rg={RG_NETWORK: no_vnet_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
        )

        assert "cluster_vnet" not in source, "No VNet subgraphs should exist"
        assert "cluster_subnet" not in source, "No subnet subgraphs should exist"
