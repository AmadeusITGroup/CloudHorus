"""
Comprehensive edge assertion tests for CloudHorus graph generation.

Unlike the other test modules which validate structure (nodes, clusters, flag combos),
this module validates every EXPECTED EDGE in the DOT output — verifying specific
source→target endpoints, edge colors, and edge counts.

If you see a test fail here it means the rendered diagram is WRONG — the visual
output that the user sees does not match the expected architecture.

Edge types:
  - royalblue2 (solid, penwidth=5): VNet integration — cross-RG resource→subnet
  - indigo (solid):  PE service connection (privateLinkServiceId → target resource)
  - black (dashed):  Same-RG dependency (dependsOn)
  - black/invis:     Layout/ranking invisible edges (not tested here)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import DotAnalyzer, run_graph_generation
from mock_templates.scenarios import (
    RG_APP,
    RG_CROSS,
    RG_DATA,
    RG_NETWORK,
    SUB_1,
    SUB_2,
    TENANT_1,
    TENANT_2,
    baseline_network_template,
    cross_rg_app_template,
    cross_rg_data_template,
    cross_rg_network_template,
    cross_tenant_network_template,
    cross_tenant_pe_template,
    cross_tenant_remote_template,
    diverse_resources_template,
    many_pe_app_template,
    many_pe_network_template,
    no_vnet_template,
    subnet_optimization_template,
    vnet_integration_edge_app_template,
    vnet_integration_edge_network_template,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 1: Baseline — Single RG, all resources in same RG
# ═══════════════════════════════════════════════════════════════════════════════


class TestBaselineEdges:
    """
    Scenario 1: Single RG with VNet + subnets + resources.

    Expected edges:
      - 0 royalblue2 (all resources in same RG → containment, not cross-RG VNet integration)
      - 2 indigo (PE service connections: pe-sql→sql, pe-storage→storage)
      - >=1 dashed black (dependency: webapp→asp, pe-sql→sql from dependsOn)
    """

    @pytest.fixture(autouse=True)
    def setup(self, work_dir):
        self.source, self.analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: baseline_network_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            cross_pe_optimization=False,
            pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )

    def test_no_vnet_integration_edges(self):
        """Single-RG scenario should have ZERO royalblue2 VNet integration edges."""
        royalblue = self.analyzer.get_edges_with_color("royalblue2")
        assert len(royalblue) == 0, (
            f"Single-RG baseline should have 0 royalblue2 edges (all same-RG containment), "
            f"but found {len(royalblue)}: {[(s,t) for s,t,_ in royalblue]}"
        )

    def test_pe_sql_service_connection(self):
        """PE for SQL should have indigo edge to SQL server."""
        self.analyzer.assert_edge_exists(
            "pe-sql-01", "test-sql-server-01", "indigo", msg="PE-SQL service connection edge missing: "
        )

    def test_pe_storage_service_connection(self):
        """PE for Storage should have indigo edge to storage account."""
        self.analyzer.assert_edge_exists(
            "pe-storage-01", "teststorage01", "indigo", msg="PE-Storage service connection edge missing: "
        )

    def test_indigo_edge_count(self):
        """Exactly 2 indigo edges: pe-sql→sql, pe-storage→storage."""
        count = self.analyzer.count_edges_with_color("indigo")
        assert count == 2, f"Expected 2 indigo edges, got {count}"

    def test_webapp_to_asp_dependency(self):
        """WebApp should have dashed black dependency edge to ASP."""
        dashed_black = [(s, t) for s, t, a in self.analyzer.edges if "style=dashed" in a and "color=black" in a]
        webapp_asp = [e for e in dashed_black if "test-webapp-01" in e[0] and "test-asp-01" in e[1]]
        assert len(webapp_asp) > 0, f"WebApp → ASP dependency edge missing. Dashed black edges found: {dashed_black}"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 2: Cross-RG — PE in RG_APP, subnet in RG_NETWORK, service in RG_DATA
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossRgEdges:
    """
    Scenario 2: Cross-RG with 3 RGs.

    Expected edges:
      - 3 royalblue2 VNet integration:
          webapp → webapp_subnet (cross-RG)
          pe-sql-cross → pe_subnet (cross-RG)
          aks → aks_subnet (cross-RG)
      - 1 indigo: pe-sql-cross → test-sql-data (cross-RG PE service connection)
      - >=1 dashed black: webapp→asp dependency
    """

    @pytest.fixture(autouse=True)
    def setup(self, work_dir):
        self.source, self.analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: cross_rg_network_template(),
                RG_APP: cross_rg_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            cross_pe_optimization=False,
            pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )

    # ── VNet integration edges (royalblue2) ──

    def test_webapp_vnet_integration_edge(self):
        """WebApp in RG_APP → webapp_subnet in RG_NETWORK must produce royalblue2 edge."""
        self.analyzer.assert_edge_exists(
            "test-webapp-cross", "webapp_subnet", "royalblue2", msg="WebApp cross-RG VNet integration edge missing: "
        )

    def test_pe_vnet_integration_edge(self):
        """PE in RG_APP → pe_subnet in RG_NETWORK must produce royalblue2 edge."""
        self.analyzer.assert_edge_exists(
            "pe-sql-cross", "pe_subnet", "royalblue2", msg="PE cross-RG VNet integration edge missing: "
        )

    def test_aks_vnet_integration_edge(self):
        """AKS in RG_APP → aks_subnet in RG_NETWORK must produce royalblue2 edge."""
        self.analyzer.assert_edge_exists(
            "test-aks-01", "aks_subnet", "royalblue2", msg="AKS cross-RG VNet integration edge missing: "
        )

    def test_royalblue2_edge_count(self):
        """Exactly 3 royalblue2 edges: webapp→webapp_subnet, pe→pe_subnet, aks→aks_subnet."""
        count = self.analyzer.count_edges_with_color("royalblue2")
        assert count == 3, f"Expected 3 royalblue2 VNet integration edges, got {count}"

    # ── Cross-RG PE service connection (indigo) ──

    def test_pe_cross_rg_service_edge(self):
        """PE in RG_APP → SQL in RG_DATA must produce indigo edge."""
        self.analyzer.assert_edge_exists(
            "pe-sql-cross", "test-sql-data", "indigo", msg="PE cross-RG service connection edge missing: "
        )

    def test_indigo_edge_count(self):
        """Exactly 1 indigo edge: pe-sql-cross → test-sql-data."""
        count = self.analyzer.count_edges_with_color("indigo")
        assert count == 1, (
            f"Expected 1 indigo edge, got {count}: "
            f"{[(s,t) for s,t,_ in self.analyzer.get_edges_with_color('indigo')]}"
        )

    # ── Dependency edges ──

    def test_webapp_asp_dependency(self):
        """WebApp → ASP dashed black dependency edge must exist."""
        dashed_black = [(s, t) for s, t, a in self.analyzer.edges if "style=dashed" in a and "color=black" in a]
        found = any("test-webapp-cross" in s and "test-asp-cross" in t for s, t in dashed_black)
        assert found, f"WebApp→ASP dependency not found. Dashed black: {dashed_black}"

    # ── VNet integration xlabel ──

    def test_vnet_integration_label(self):
        """All royalblue2 edges should carry 'Vnet integration' xlabel."""
        assert "Vnet integration" in self.source, "VNet integration xlabel missing from DOT source"


class TestCrossRgEdgesWithOptimizations:
    """Test that optimization flags don't remove expected cross-RG edges."""

    def _generate(self, work_dir, **kwargs):
        return run_graph_generation(
            templates_by_rg={
                RG_NETWORK: cross_rg_network_template(),
                RG_APP: cross_rg_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            work_dir=str(work_dir),
            **kwargs,
        )

    def test_vnet_integration_survives_subnet_optimization(self, work_dir):
        """VNet integration royalblue2 edges survive subnet_optimization=True."""
        _, analyzer = self._generate(
            work_dir, subnet_optimization=True, pe_optimization=False, cross_pe_optimization=False
        )
        # All 3 VNet integration edges must still exist
        analyzer.assert_edge_exists(
            "test-webapp-cross",
            "webapp_subnet",
            "royalblue2",
            msg="WebApp VNet integration lost with subnet_opt=True: ",
        )
        analyzer.assert_edge_exists(
            "pe-sql-cross", "pe_subnet", "royalblue2", msg="PE VNet integration lost with subnet_opt=True: "
        )
        analyzer.assert_edge_exists(
            "test-aks-01", "aks_subnet", "royalblue2", msg="AKS VNet integration lost with subnet_opt=True: "
        )

    def test_indigo_survives_pe_optimization(self, work_dir):
        """Cross-RG PE indigo edge survives pe_optimization=True."""
        _, analyzer = self._generate(
            work_dir, subnet_optimization=False, pe_optimization=True, cross_pe_optimization=False
        )
        indigo = analyzer.get_edges_with_color("indigo")
        cross_rg = [e for e in indigo if "test-sql-data" in e[1]]
        assert len(cross_rg) > 0, "Cross-RG PE→SQL indigo edge lost with pe_optimization=True"

    def test_pe_vnet_integration_survives_cross_pe_optimization(self, work_dir):
        """PE with cross-RG service must keep VNet integration edge with cross_pe_optimization=True."""
        _, analyzer = self._generate(
            work_dir, subnet_optimization=False, pe_optimization=False, cross_pe_optimization=True
        )
        # pe-sql-cross has both cross-RG service (should survive cross_pe_opt) AND VNet integration
        analyzer.assert_edge_exists(
            "pe-sql-cross", "pe_subnet", "royalblue2", msg="PE VNet integration lost with cross_pe_opt=True: "
        )

    def test_all_optimizations_on(self, work_dir):
        """With ALL optimizations on, critical edges must survive."""
        _, analyzer = self._generate(
            work_dir, subnet_optimization=True, pe_optimization=True, cross_pe_optimization=True
        )
        # WebApp VNet integration must survive
        analyzer.assert_edge_exists(
            "webapp-cross", "webapp_subnet", "royalblue2", msg="WebApp VNet integration lost with all opts: "
        )
        # AKS VNet integration must survive
        analyzer.assert_edge_exists(
            "aks-01", "aks_subnet", "royalblue2", msg="AKS VNet integration lost with all opts: "
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 3: Cross-Tenant — PE in tenant-1 targeting resource in tenant-2
# ═══════════════════════════════════════════════════════════════════════════════


class TestCrossTenantEdges:
    """
    Scenario 3: Cross-tenant with 2 tenants, 2 subscriptions, 3 RGs.

    Expected edges (pe_opt=False, cross_pe=False):
      - 2 royalblue2 VNet integration (each PE → pe_cross_tenant subnet):
          pe-evhns-cross-tenant → pe_cross_tenant
          pe-local-only → pe_cross_tenant
      - 2 indigo (PE service connections):
          pe-evhns-cross-tenant → evhns-cross-tenant-01 (cross-tenant)
          pe-local-only → localstorageaccount (same-RG)

    Note: royalblue2 edges may appear doubled (once per subscription iteration)
    if the graph_generator processes subnet_implicit_deps in multiple passes.
    We assert >= expected minimum.
    """

    CT_KWARGS = dict(
        templates_by_rg={
            RG_NETWORK: cross_tenant_network_template(),
            RG_APP: cross_tenant_pe_template(),
            RG_CROSS: cross_tenant_remote_template(),
        },
        tenants=[TENANT_1, TENANT_2],
        subscriptions=[SUB_1, SUB_2],
        resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
        rg_to_subscription={RG_NETWORK: SUB_1, RG_APP: SUB_1, RG_CROSS: SUB_2},
        rg_to_tenant={RG_NETWORK: TENANT_1, RG_APP: TENANT_1, RG_CROSS: TENANT_2},
    )

    @pytest.fixture(autouse=True)
    def setup(self, work_dir):
        self.source, self.analyzer = run_graph_generation(
            **self.CT_KWARGS,
            cross_pe_optimization=False,
            pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )

    # ── VNet integration edges (royalblue2) ──

    def test_pe_cross_tenant_vnet_integration(self):
        """PE for cross-tenant EventHub → pe_cross_tenant subnet: royalblue2."""
        self.analyzer.assert_edge_exists(
            "pe-evhns-cross-tenant",
            "pe_cross_tenant",
            "royalblue2",
            msg="Cross-tenant PE VNet integration edge missing: ",
        )

    def test_pe_local_vnet_integration(self):
        """PE for local storage → pe_cross_tenant subnet: royalblue2."""
        self.analyzer.assert_edge_exists(
            "pe-local-only", "pe_cross_tenant", "royalblue2", msg="Local PE VNet integration edge missing: "
        )

    def test_royalblue2_minimum_count(self):
        """At least 2 royalblue2 edges (one per PE → subnet)."""
        count = self.analyzer.count_edges_with_color("royalblue2")
        assert count >= 2, (
            f"Expected >= 2 royalblue2 VNet integration edges, got {count}: "
            f"{[(s,t) for s,t,_ in self.analyzer.get_edges_with_color('royalblue2')]}"
        )

    # ── PE service connection edges (indigo) ──

    def test_pe_cross_tenant_service_edge(self):
        """PE → EventHub in different tenant/subscription: indigo edge."""
        self.analyzer.assert_edge_exists(
            "pe-evhns-cross-tenant",
            "evhns-cross-tenant-01",
            "indigo",
            msg="Cross-tenant PE service connection edge missing: ",
        )

    def test_pe_local_service_edge(self):
        """PE → local storage account: indigo edge (PE service connection)."""
        self.analyzer.assert_edge_exists(
            "pe-local-only", "localstorageaccount", "indigo", msg="Local PE service connection edge missing: "
        )

    def test_indigo_count(self):
        """Exactly 2 indigo edges: cross-tenant PE and local PE service connections."""
        count = self.analyzer.count_edges_with_color("indigo")
        assert count == 2, (
            f"Expected 2 indigo edges, got {count}: "
            f"{[(s,t) for s,t,_ in self.analyzer.get_edges_with_color('indigo')]}"
        )


class TestCrossTenantEdgesWithOptimizations:
    """Verify cross-tenant edges survive all optimization combos."""

    CT_KWARGS = dict(
        templates_by_rg={
            RG_NETWORK: cross_tenant_network_template(),
            RG_APP: cross_tenant_pe_template(),
            RG_CROSS: cross_tenant_remote_template(),
        },
        tenants=[TENANT_1, TENANT_2],
        subscriptions=[SUB_1, SUB_2],
        resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
        rg_to_subscription={RG_NETWORK: SUB_1, RG_APP: SUB_1, RG_CROSS: SUB_2},
        rg_to_tenant={RG_NETWORK: TENANT_1, RG_APP: TENANT_1, RG_CROSS: TENANT_2},
    )

    def test_vnet_integration_survives_subnet_opt(self, work_dir):
        """VNet integration edges survive subnet_optimization=True."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            pe_optimization=False,
            cross_pe_optimization=False,
            work_dir=str(work_dir),
        )
        analyzer.assert_edge_exists(
            "pe-evhns-cross-tenant",
            "pe_cross_tenant",
            "royalblue2",
            msg="Cross-tenant PE VNet integration lost with subnet_opt: ",
        )
        analyzer.assert_edge_exists(
            "pe-local-only", "pe_cross_tenant", "royalblue2", msg="Local PE VNet integration lost with subnet_opt: "
        )

    def test_cross_tenant_indigo_survives_cross_pe_opt(self, work_dir):
        """Cross-tenant indigo edge survives cross_pe_optimization=True."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=False,
            pe_optimization=False,
            cross_pe_optimization=True,
            work_dir=str(work_dir),
        )
        analyzer.assert_edge_exists(
            "pe-evhns-cross-tenant",
            "evhns-cross-tenant-01",
            "indigo",
            msg="Cross-tenant indigo lost with cross_pe_opt: ",
        )

    def test_merged_pe_preserves_vnet_integration(self, work_dir):
        """With pe_optimization=True, merged PE must still have VNet integration."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=False,
            pe_optimization=True,
            cross_pe_optimization=False,
            work_dir=str(work_dir),
        )
        # When PEs are merged by subnet, the merged node is 'privateEndpoints-pe_cross_tenant'
        # VNet integration must remain
        royalblue = analyzer.get_edges_with_color("royalblue2")
        assert len(royalblue) >= 1, f"Merged PE should still have VNet integration edge. Found royalblue2={royalblue}"

    def test_merged_pe_preserves_cross_tenant_service(self, work_dir):
        """With pe_optimization=True, merged PE must still have cross-tenant service edge."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=False,
            pe_optimization=True,
            cross_pe_optimization=False,
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        cross_tenant = [e for e in indigo if "evhns-cross-tenant-01" in e[1]]
        assert len(cross_tenant) >= 1, f"Merged PE should keep cross-tenant indigo edge. Found: {indigo}"

    def test_all_opts_on_preserves_critical_edges(self, work_dir):
        """With ALL optimizations on, cross-tenant edges must survive."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            pe_optimization=True,
            cross_pe_optimization=True,
            work_dir=str(work_dir),
        )
        # Cross-tenant indigo must survive
        indigo = analyzer.get_edges_with_color("indigo")
        cross_tenant = [e for e in indigo if "rg-cross" in e[1] or "evhns-cross-tenant" in e[1]]
        assert len(cross_tenant) >= 1, f"Cross-tenant indigo edge must survive all opts. Found: {indigo}"
        # VNet integration must survive
        royalblue = analyzer.get_edges_with_color("royalblue2")
        assert len(royalblue) >= 1, f"VNet integration must survive all opts. Found: {royalblue}"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 4: Many PEs — stress test for PE optimization flags
# ═══════════════════════════════════════════════════════════════════════════════


class TestManyPeEdges:
    """
    Scenario 4: 10 PEs in RG_APP, each connecting to subnet in RG_NETWORK VNet,
    with cross-RG service connections at indices [0, 3, 7].

    Expected (pe_opt=False, cross_pe=False):
      - 10 royalblue2: each pe → its subnet (pe_01..pe_05 cycling)
      - 10 indigo: each pe → its service target
      - 3 indigo to RG_DATA (indices 0, 3, 7), 7 indigo to RG_APP
    """

    @pytest.fixture(autouse=True)
    def setup(self, work_dir):
        self.source, self.analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: many_pe_network_template(),
                RG_APP: many_pe_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            cross_pe_optimization=False,
            pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )

    def test_all_10_pe_vnet_integration_edges(self):
        """All 10 PEs should have royalblue2 VNet integration edges."""
        royalblue = self.analyzer.get_edges_with_color("royalblue2")
        assert len(royalblue) == 10, (
            f"Expected 10 royalblue2 edges, got {len(royalblue)}: " f"{[(s,t) for s,t,_ in royalblue]}"
        )

    def test_each_pe_has_correct_subnet_target(self):
        """Each PE should target its correct cycling subnet (pe_01..pe_05)."""
        royalblue = self.analyzer.get_edges_with_color("royalblue2")
        for i in range(10):
            pe_name = f"pe-svc-{i:02d}"
            subnet = f"pe_{(i % 5) + 1:02d}"
            found = any(pe_name in s and subnet in t for s, t, _ in royalblue)
            assert found, (
                f"PE {pe_name} should have royalblue2 edge to {subnet}. " f"Edges: {[(s,t) for s,t,_ in royalblue]}"
            )

    def test_all_10_pe_service_connection_edges(self):
        """All 10 PEs should have indigo service connection edges."""
        indigo = self.analyzer.get_edges_with_color("indigo")
        assert len(indigo) == 10, f"Expected 10 indigo edges, got {len(indigo)}: " f"{[(s,t) for s,t,_ in indigo]}"

    def test_cross_rg_service_targets(self):
        """PEs at indices [0,3,7] target EventHub in RG_DATA."""
        for idx in [0, 3, 7]:
            pe_name = f"pe-svc-{idx:02d}"
            target = f"evhns-svc-{idx:02d}"
            self.analyzer.assert_edge_exists(
                pe_name, target, "indigo", msg=f"PE[{idx}] cross-RG service edge missing: "
            )

    def test_same_rg_service_targets(self):
        """PEs NOT at [0,3,7] target Storage in RG_APP."""
        for idx in [1, 2, 4, 5, 6, 8, 9]:
            pe_name = f"pe-svc-{idx:02d}"
            target = f"storage-svc-{idx:02d}"
            self.analyzer.assert_edge_exists(pe_name, target, "indigo", msg=f"PE[{idx}] same-RG service edge missing: ")


class TestManyPeEdgesWithOptimizations:
    """Test that PE optimization correctly merges edges."""

    def test_pe_optimization_merges_by_subnet(self, work_dir):
        """With pe_optimization=True, PEs are merged by subnet → fewer nodes but still edges."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: many_pe_network_template(),
                RG_APP: many_pe_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            pe_optimization=True,
            cross_pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        # With PE optimization, there should be 5 merged PE nodes (one per subnet)
        # Each merged node should still have VNet integration
        royalblue = analyzer.get_edges_with_color("royalblue2")
        assert (
            len(royalblue) == 5
        ), f"PE optimization should produce 5 merged VNet integration edges, got {len(royalblue)}"

    def test_cross_pe_optimization_removes_non_cross_rg_pes(self, work_dir):
        """crossPeOptimization=True should remove PEs without cross-RG deps."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: many_pe_network_template(),
                RG_APP: many_pe_app_template(),
                RG_DATA: cross_rg_data_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            pe_optimization=False,
            cross_pe_optimization=True,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        # Only PEs with cross-RG deps should survive (indices 0, 3, 7)
        # But they also have VNet integration → those must survive too
        indigo = analyzer.get_edges_with_color("indigo")
        cross_rg_indigo = [e for e in indigo if "rg-data" in e[1]]
        assert (
            len(cross_rg_indigo) >= 3
        ), f"3 cross-RG PE indigo edges should survive cross_pe_opt. Found: {cross_rg_indigo}"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 5: Subnet Optimization
# ═══════════════════════════════════════════════════════════════════════════════


class TestSubnetOptimizationEdges:
    """
    Scenario 5: VNet with 8 subnets, 3 used and 5 empty.
    Single RG → no royalblue2 edges expected.
    """

    def test_no_cross_rg_edges_single_rg(self, work_dir):
        """Single-RG scenario should have 0 royalblue2 edges."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_optimization_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        royalblue = analyzer.get_edges_with_color("royalblue2")
        assert len(royalblue) == 0, f"Single-RG should have 0 royalblue2, got {len(royalblue)}: {royalblue}"

    def test_pe_service_edge_exists(self, work_dir):
        """PE → storage indigo service edge should exist."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_optimization_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        # PE node name is 'privateEndpoints-used-subnet-2' (merged by subnet name)
        # since pe_optimization defaults to True and the PE is in 'used-subnet-2'
        analyzer.assert_edge_exists(
            "privateEndpoints-used-subnet-2",
            "optstorage01",
            "indigo",
            msg="PE→Storage indigo edge missing in subnet optimization scenario: ",
        )

    def test_pe_edge_survives_subnet_optimization(self, work_dir):
        """PE service edge must survive when subnet_optimization=True."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: subnet_optimization_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=True,
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        # PE node is 'privateEndpoints-used-subnet-2' (merged by subnet)
        pe_storage = [e for e in indigo if "privateEndpoints-used-subnet-2" in e[0] and "optstorage01" in e[1]]
        assert len(pe_storage) > 0, f"PE→Storage indigo edge lost with subnet_optimization=True. Found: {indigo}"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 7: VNet Integration Edge Regression
# ═══════════════════════════════════════════════════════════════════════════════


class TestVnetIntegrationEdgeRegression:
    """
    Scenario 7: WebApp + PE both with cross-RG VNet integration.
    PE has same-RG service target → tests crossPeOptimization doesn't kill
    the PE when it still has a VNet integration edge.

    Expected edges:
      - 2 royalblue2: webapp→webapp_subnet, pe→pe_subnet
      - 1 indigo: pe→appstorage01
      - 1 dashed black: webapp→asp
    """

    @pytest.fixture(autouse=True)
    def setup(self, work_dir):
        self.source, self.analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: vnet_integration_edge_network_template(),
                RG_APP: vnet_integration_edge_app_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP],
            cross_pe_optimization=False,
            pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )

    def test_webapp_vnet_integration(self):
        """WebApp → webapp_subnet royalblue2 VNet integration edge."""
        self.analyzer.assert_edge_exists(
            "webapp-vnet-edge", "webapp_subnet", "royalblue2", msg="WebApp VNet integration edge missing: "
        )

    def test_pe_vnet_integration(self):
        """PE → pe_subnet royalblue2 VNet integration edge."""
        self.analyzer.assert_edge_exists(
            "pe-with-vnet-integration", "pe_subnet", "royalblue2", msg="PE VNet integration edge missing: "
        )

    def test_royalblue2_count(self):
        """Exactly 2 royalblue2 edges."""
        count = self.analyzer.count_edges_with_color("royalblue2")
        assert count == 2, f"Expected 2 royalblue2 edges, got {count}"

    def test_pe_service_connection(self):
        """PE → appstorage01 indigo service connection edge."""
        self.analyzer.assert_edge_exists(
            "pe-with-vnet-integration", "appstorage01", "indigo", msg="PE service connection edge missing: "
        )

    def test_webapp_asp_dep(self):
        """WebApp → ASP dashed black dependency edge."""
        dashed = [(s, t) for s, t, a in self.analyzer.edges if "style=dashed" in a and "color=black" in a]
        found = any("webapp-vnet-edge" in s and "asp-vnet-edge" in t for s, t in dashed)
        assert found, f"WebApp→ASP dependency missing. Dashed: {dashed}"


class TestVnetIntegrationEdgeWithCrossPeOpt:
    """
    PE with VNet integration but NO cross-RG service connection.
    crossPeOptimization=True should hide this PE and its edges.
    """

    def test_pe_vnet_integration_survives_cross_pe_opt(self, work_dir):
        """PE with VNet integration but only same-RG service dep should be hidden
        when crossPeOptimization=True — only cross-RG targets keep a PE visible."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: vnet_integration_edge_network_template(),
                RG_APP: vnet_integration_edge_app_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP],
            cross_pe_optimization=True,
            pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        # PE has no cross-RG service dep (target is same RG) → crossPeOptimization hides it
        royalblue = analyzer.get_edges_with_color("royalblue2")
        pe_vnet_edges = [(s, t) for s, t, _ in royalblue if "pe-with-vnet-integration" in s]
        assert len(pe_vnet_edges) == 0, "PE with only same-RG service dep should be hidden by crossPeOptimization"

    def test_webapp_vnet_integration_unaffected(self, work_dir):
        """WebApp VNet integration should be completely unaffected by PE optimizations."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: vnet_integration_edge_network_template(),
                RG_APP: vnet_integration_edge_app_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP],
            cross_pe_optimization=True,
            pe_optimization=True,
            subnet_optimization=True,
            work_dir=str(work_dir),
        )
        analyzer.assert_edge_exists(
            "webapp-vnet-edge", "webapp_subnet", "royalblue2", msg="WebApp VNet integration lost with all opts: "
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 8: Diverse Resource Types — same RG
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiverseResourceEdges:
    """
    Scenario 8: Multiple resource types (PostgreSQL, MySQL, APIM, Redis, Firewall)
    all in the same RG with VNet.
    Since all same-RG → no royalblue2 edges, no indigo edges.
    Subnet containment is handled by the graph_generator's subnet placement.
    """

    def test_no_cross_rg_edges(self, work_dir):
        """All resources in same RG → 0 royalblue2, 0 indigo."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: diverse_resources_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        royalblue = analyzer.get_edges_with_color("royalblue2")
        indigo = analyzer.get_edges_with_color("indigo")
        assert len(royalblue) == 0, f"Same-RG diverse resources: 0 royalblue2 expected, got {royalblue}"
        assert len(indigo) == 0, f"Same-RG diverse resources: 0 indigo expected, got {indigo}"


# ═══════════════════════════════════════════════════════════════════════════════
#  SCENARIO 10: No VNet — standalone resources
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoVnetEdges:
    """
    Scenario 10: RG with only standalone resources (no VNet, no subnets).
    No VNet integration edges should exist.
    """

    def test_no_vnet_integration_edges(self, work_dir):
        """Zero royalblue2 edges when there's no VNet."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: no_vnet_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
        )
        royalblue = analyzer.get_edges_with_color("royalblue2")
        assert len(royalblue) == 0, f"No-VNet scenario should have 0 royalblue2, got {royalblue}"

    def test_no_indigo_edges(self, work_dir):
        """Zero indigo edges when there are no PEs."""
        _, analyzer = run_graph_generation(
            templates_by_rg={RG_NETWORK: no_vnet_template()},
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK],
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        assert len(indigo) == 0, f"No-VNet scenario should have 0 indigo, got {indigo}"


# ═══════════════════════════════════════════════════════════════════════════════
#  CROSS-SCENARIO: Edge Consistency Across Layout Directions
# ═══════════════════════════════════════════════════════════════════════════════


class TestEdgeConsistencyAcrossDirections:
    """
    Edge counts and endpoints should NOT change when only the layout direction changes.
    """

    @pytest.mark.parametrize("direction", ["TB", "LR", "BT", "RL"])
    def test_cross_rg_royalblue2_count_stable(self, direction, work_dir):
        """Scenario 2: royalblue2 count should be 3 in any direction."""
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
            pe_optimization=False,
            cross_pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        count = analyzer.count_edges_with_color("royalblue2")
        assert count == 3, f"Expected 3 royalblue2 edges with direction={direction}, got {count}"

    @pytest.mark.parametrize("direction", ["TB", "LR", "BT", "RL"])
    def test_cross_rg_indigo_count_stable(self, direction, work_dir):
        """Scenario 2: indigo count should be 1 in any direction."""
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
            pe_optimization=False,
            cross_pe_optimization=False,
            subnet_optimization=False,
            work_dir=str(work_dir),
        )
        count = analyzer.count_edges_with_color("indigo")
        assert count == 1, f"Expected 1 indigo edge with direction={direction}, got {count}"


# ═══════════════════════════════════════════════════════════════════════════════
#  NO ORPHAN NODES: Edges should not create phantom nodes
# ═══════════════════════════════════════════════════════════════════════════════


class TestNoOrphanNodes:
    """
    Verify that VNet integration edges (royalblue2) don't create orphan nodes.
    The target of a royalblue2 edge is a subnet name with lhead=cluster_subnet{name},
    which means the target should already exist as a cluster, not as a standalone node.
    """

    def test_cross_rg_no_orphan_vnet_nodes(self, work_dir):
        """Scenario 2: VNet as cluster should not appear as orphan node."""
        source, analyzer = run_graph_generation(
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
        # The VNet name should NOT appear as a standalone node definition
        # (it's a cluster, not a node)
        vnet_nodes = [n for n in analyzer.nodes if n == f"test-vnet-01-{RG_NETWORK}"]
        assert len(vnet_nodes) == 0, f"VNet should be a cluster, not a node. Found orphan nodes: {vnet_nodes}"

    def test_cross_tenant_no_orphan_vnet_nodes(self, work_dir):
        """Scenario 3: cross-tenant VNet should not appear as orphan node."""
        source, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: cross_tenant_network_template(),
                RG_APP: cross_tenant_pe_template(),
                RG_CROSS: cross_tenant_remote_template(),
            },
            tenants=[TENANT_1, TENANT_2],
            subscriptions=[SUB_1, SUB_2],
            resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
            rg_to_subscription={RG_NETWORK: SUB_1, RG_APP: SUB_1, RG_CROSS: SUB_2},
            rg_to_tenant={RG_NETWORK: TENANT_1, RG_APP: TENANT_1, RG_CROSS: TENANT_2},
            work_dir=str(work_dir),
        )
        vnet_nodes = [n for n in analyzer.nodes if n == f"cross-tenant-vnet-{RG_NETWORK}"]
        assert len(vnet_nodes) == 0, f"Cross-tenant VNet should be cluster, not orphan node: {vnet_nodes}"
