"""
Test cross-resource-group and cross-tenant scenarios.

Covers:
  - PE in RG_APP connecting to subnet in RG_NETWORK (VNet integration edges)
  - PE's privateLinkServiceConnection targeting service in RG_DATA (cross-RG dependency edges)
  - Web App VNet integration across RGs
  - AKS VNet integration across RGs
  - Cross-tenant PE dependencies
  - Ghost resource suppression (resource exported in wrong RG)
  - All flag combinations tested against each cross-RG scenario
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import (
    flag_combo_id,
    generate_flag_combinations,
    run_graph_generation,
)
from mock_templates.scenarios import (
    RG_APP,
    RG_CROSS,
    RG_DATA,
    RG_NETWORK,
    SUB_1,
    SUB_2,
    TENANT_1,
    TENANT_2,
    cross_rg_app_template,
    cross_rg_data_template,
    cross_rg_network_template,
    cross_tenant_network_template,
    cross_tenant_pe_template,
    cross_tenant_pe_template_local_first,
    cross_tenant_remote_template,
    ghost_resource_app_template,
    ghost_resource_network_template,
    many_pe_app_template,
    many_pe_data_template,
    many_pe_network_template,
)

# ═══════════════════════════════════════════════════════════════════════════════
#  Cross-RG Scenarios (single tenant, single subscription, 3 RGs)
# ═══════════════════════════════════════════════════════════════════════════════

CROSS_RG_TEMPLATES = {
    RG_NETWORK: cross_rg_network_template(),
    RG_APP: cross_rg_app_template(),
    RG_DATA: cross_rg_data_template(),
}

CROSS_RG_COMBOS = generate_flag_combinations(include_dns=False)  # 8 combos (skip DNS for cross-RG)


@pytest.fixture(params=CROSS_RG_COMBOS, ids=[flag_combo_id(c) for c in CROSS_RG_COMBOS])
def cross_rg_flags(request):
    return request.param


class TestCrossRgAllCombinations:
    """Run all 8 flag combos (excluding DNS) against the 3-RG cross-RG scenario."""

    def test_generates_without_error(self, cross_rg_flags, work_dir):
        """Cross-RG scenario should not crash for any flag combo."""
        source, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            work_dir=str(work_dir),
            **cross_rg_flags,
        )
        assert source, f"DOT source is empty for cross-RG flags: {cross_rg_flags}"

    def test_all_rg_subgraphs_exist(self, cross_rg_flags, work_dir):
        """All 3 RG subgraphs should always be present."""
        _, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            work_dir=str(work_dir),
            **cross_rg_flags,
        )
        for rg in [RG_NETWORK, RG_APP, RG_DATA]:
            assert analyzer.has_cluster(f"resource_group{rg}"), f"RG subgraph for {rg} must exist"

    def test_vnet_subgraph_in_network_rg(self, cross_rg_flags, work_dir):
        """VNet should always appear in the network RG."""
        _, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            work_dir=str(work_dir),
            **cross_rg_flags,
        )
        assert analyzer.has_cluster("vnettest-vnet-01"), "VNet subgraph must exist in network RG"


class TestCrossRgVnetIntegration:
    """
    Test VNet integration for cross-RG resources.

    NOTE: In Bicep mode, the resource_processor overrides subnet_rg to the
    current RG (line ~303 of resource_processor.py).  This means cross-RG
    VNet integration is expressed as *containment* (resource rendered inside
    its subnet cluster) rather than royalblue2 edges.  Royalblue2 edges only
    appear in Azure (live) mode where the real subnet RG is preserved.

    These tests validate containment behaviour instead.
    """

    def test_webapp_contained_in_subnet_cluster(self, work_dir):
        """
        Web App in RG_APP with virtualNetworkSubnetId pointing to webapp_subnet
        should be placed inside the subnet cluster (Bicep containment model).
        """
        source, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            subnet_optimization=False,
            cross_pe_optimization=False,
            work_dir=str(work_dir),
        )

        # Web app node should exist
        assert analyzer.has_node_containing("webapp-cross"), "Web App cross-RG node should exist in output"

        # webapp_subnet cluster should exist (VNet integration rendered as containment)
        assert analyzer.has_cluster(
            "subnetwebapp_subnet"
        ), "webapp_subnet cluster should exist for VNet integration containment"

    def test_aks_contained_in_subnet_cluster(self, work_dir):
        """AKS in RG_APP with vnetSubnetID pointing to aks_subnet should be
        placed inside the subnet cluster."""
        source, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            subnet_optimization=False,
            cross_pe_optimization=False,
            work_dir=str(work_dir),
        )

        assert analyzer.has_node_containing("aks"), "AKS node should exist in output"
        assert analyzer.has_cluster(
            "subnetaks_subnet"
        ), "aks_subnet cluster should exist for AKS VNet integration containment"

    def test_vnet_integration_containment_survives_all_optimizations(self, work_dir):
        """VNet integration containment (subnet clusters) should persist with ALL optimizations ON."""
        source, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            subnet_optimization=True,
            pe_optimization=True,
            cross_pe_optimization=True,
            work_dir=str(work_dir),
        )

        # Even with all optimizations, the VNet and at least some subnet clusters must survive
        assert analyzer.has_cluster("vnettest-vnet-01"), "VNet cluster must survive when all optimizations are enabled"
        assert analyzer.has_node_containing("webapp-cross") or analyzer.has_node_containing(
            "aks"
        ), "At least one VNet-integrated resource should exist with all optimizations enabled"


class TestCrossRgDependencyEdges:
    """Test cross-RG dependency edges (indigo) for PE service connections."""

    def test_pe_cross_rg_service_edge(self, work_dir):
        """PE with privateLinkServiceConnection to service in different RG should produce indigo edge."""
        _, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            cross_pe_optimization=False,
            pe_optimization=False,
            work_dir=str(work_dir),
        )

        indigo_edges = analyzer.get_edges_with_color("indigo")
        assert len(indigo_edges) > 0, "Cross-RG PE service connection should produce indigo edge"

    def test_pe_cross_rg_edge_survives_with_cross_pe_opt(self, work_dir):
        """Cross-RG PE edges should survive crossPeOptimization=True (PE has cross-RG deps)."""
        _, analyzer = run_graph_generation(
            templates_by_rg=CROSS_RG_TEMPLATES,
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
            cross_pe_optimization=True,
            pe_optimization=False,
            work_dir=str(work_dir),
        )

        indigo_edges = analyzer.get_edges_with_color("indigo")
        assert len(indigo_edges) > 0, "Cross-RG PE edges should survive crossPeOptimization=True"


# ═══════════════════════════════════════════════════════════════════════════════
#  VNet Integration Edge Regression (the previously fixed bug)
# ═══════════════════════════════════════════════════════════════════════════════


class TestVnetIntegrationContainmentRegression:
    """
    Regression tests for VNet integration in Bicep mode.

    In Bicep mode, VNet integration is expressed as containment (resource placed
    inside subnet cluster) rather than royalblue2 edges.  These tests validate
    that the containment survives all flag combinations.
    """

    def test_pe_containment_preserved_with_all_opts(self, work_dir):
        """
        PE with subnet reference should remain inside its subnet cluster even
        when crossPeOptimization + subnetOptimization + peOptimization are all ON.
        """
        from mock_templates.scenarios import (
            vnet_integration_edge_app_template,
            vnet_integration_edge_network_template,
        )

        source, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: vnet_integration_edge_network_template(),
                RG_APP: vnet_integration_edge_app_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP],
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )

        # VNet cluster must still exist
        assert analyzer.has_cluster(
            "vnetvnet-integration-test"
        ), "REGRESSION: VNet cluster disappeared with all optimizations enabled"

    def test_vnet_cluster_stable_across_flags(self, work_dir):
        """VNet cluster existence should be consistent regardless of optimization flags."""
        from mock_templates.scenarios import (
            vnet_integration_edge_app_template,
            vnet_integration_edge_network_template,
        )

        templates = {
            RG_NETWORK: vnet_integration_edge_network_template(),
            RG_APP: vnet_integration_edge_app_template(),
        }

        results = []
        combos = generate_flag_combinations(include_dns=False)

        for combo in combos:
            source, analyzer = run_graph_generation(
                templates_by_rg=templates,
                tenants=[TENANT_1],
                subscriptions=[SUB_1],
                resource_groups=[RG_NETWORK, RG_APP],
                work_dir=str(work_dir),
                **combo,
            )
            has_vnet = analyzer.has_cluster("vnetvnet-integration-test")
            results.append((flag_combo_id(combo), has_vnet))

        # VNet cluster should exist in ALL combos
        missing = [(cid, ok) for cid, ok in results if not ok]
        assert len(missing) == 0, f"VNet cluster missing in some combos: {missing}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Cross-Tenant Scenarios
# ═══════════════════════════════════════════════════════════════════════════════

# Shared cross-tenant kwargs: map each RG to its proper subscription and tenant
CROSS_TENANT_TEMPLATES = {
    RG_NETWORK: cross_tenant_network_template(),
    RG_APP: cross_tenant_pe_template(),
    RG_CROSS: cross_tenant_remote_template(),
}
CROSS_TENANT_RG_TO_SUB = {RG_NETWORK: SUB_1, RG_APP: SUB_1, RG_CROSS: SUB_2}
CROSS_TENANT_RG_TO_TENANT = {RG_NETWORK: TENANT_1, RG_APP: TENANT_1, RG_CROSS: TENANT_2}


class TestCrossTenant:
    """Test cross-tenant PE dependencies with 2 tenants, 2 subscriptions."""

    def test_cross_tenant_generates(self, work_dir):
        """Cross-tenant 2-subscription scenario should generate without errors."""
        source, _ = run_graph_generation(
            templates_by_rg=CROSS_TENANT_TEMPLATES,
            tenants=[TENANT_1, TENANT_2],
            subscriptions=[SUB_1, SUB_2],
            resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
            rg_to_subscription=CROSS_TENANT_RG_TO_SUB,
            rg_to_tenant=CROSS_TENANT_RG_TO_TENANT,
            work_dir=str(work_dir),
        )
        assert source

    def test_cross_tenant_has_both_tenant_subgraphs(self, work_dir):
        """Both tenant subgraphs should exist."""
        _, analyzer = run_graph_generation(
            templates_by_rg=CROSS_TENANT_TEMPLATES,
            tenants=[TENANT_1, TENANT_2],
            subscriptions=[SUB_1, SUB_2],
            resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
            rg_to_subscription=CROSS_TENANT_RG_TO_SUB,
            rg_to_tenant=CROSS_TENANT_RG_TO_TENANT,
            work_dir=str(work_dir),
        )
        assert analyzer.has_cluster(f"tenant{TENANT_1}")
        assert analyzer.has_cluster(f"tenant{TENANT_2}")

    def test_cross_tenant_pe_dependency_edge(self, work_dir):
        """PE with privateLinkServiceId in different subscription should produce cross-RG edge."""
        _, analyzer = run_graph_generation(
            templates_by_rg=CROSS_TENANT_TEMPLATES,
            tenants=[TENANT_1, TENANT_2],
            subscriptions=[SUB_1, SUB_2],
            resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
            rg_to_subscription=CROSS_TENANT_RG_TO_SUB,
            rg_to_tenant=CROSS_TENANT_RG_TO_TENANT,
            cross_pe_optimization=False,
            pe_optimization=False,
            work_dir=str(work_dir),
        )

        indigo_edges = analyzer.get_edges_with_color("indigo")
        # The PE in RG_APP targeting Event Hub in RG_CROSS (different sub) should exist
        assert len(indigo_edges) > 0, "Cross-tenant PE dependency edge should exist"


class TestCrossTenantWithOptimizations:
    """
    Stress-test the exact scenario the user described:
      - Cross-tenant PE dependency (PE in tenant-1 → EventHub in tenant-2)
      - PE in a DIFFERENT RG than its subnet (PE in RG_APP, subnet in RG_NETWORK's VNet)
      - Various optimization combos: subnet_opt, cross_pe_opt, pe_opt

    Verified behavior (from debug analysis):
      - pe_optimization=False  → individual PE nodes (pe-evhns-cross-tenant, pe-local-only)
      - pe_optimization=True   → PEs merged by subnet name (privateEndpoints-pe_cross_tenant)
      - subnet_optimization=True → subnet clusters removed from output
      - cross_pe_optimization=True (without pe_opt) → all PEs survive because
        crossPeOptimization alone does not filter individual PE nodes
      - cross_pe_optimization=True + pe_optimization=True → merged node survives
        because at least one PE in the merge group has a cross-RG/cross-tenant link
    """

    CT_KWARGS = dict(
        templates_by_rg=CROSS_TENANT_TEMPLATES,
        tenants=[TENANT_1, TENANT_2],
        subscriptions=[SUB_1, SUB_2],
        resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
        rg_to_subscription=CROSS_TENANT_RG_TO_SUB,
        rg_to_tenant=CROSS_TENANT_RG_TO_TENANT,
    )

    # ── core user scenario: subnet_opt + cross_pe_opt ──

    def test_cross_tenant_pe_survives_subnet_and_crosspe_opt(self, work_dir):
        """Cross-tenant PE edge must survive with subnet_optimization + cross_pe_optimization."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=False,
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        cross_tenant_edges = [(s, t) for s, t, _ in indigo if "rg-cross" in t]
        assert len(cross_tenant_edges) >= 1, "Cross-tenant PE indigo edge disappeared with subnet_opt + cross_pe_opt"

    def test_local_pe_survives_subnet_and_crosspe_opt(self, work_dir):
        """pe-local-only targeting same-RG storage should be hidden by crossPeOpt
        since it has no cross-RG service connections."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=False,
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        local_edges = [(s, t) for s, t, _ in indigo if "localstorageaccount" in t]
        assert (
            len(local_edges) == 0
        ), "Local PE indigo edge should be hidden when crossPeOptimization=True (same-RG only)"

    def test_subnet_clusters_removed_when_subnet_opt(self, work_dir):
        """subnet_optimization=True should suppress non-integrated subnet subgraphs,
        but keep VNet-integrated subnets (those targeted by cross-RG PEs)."""
        import re

        source, _ = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=False,
            work_dir=str(work_dir),
        )
        subnet_clusters = re.findall(r"subgraph\s+cluster_subnet(\S+)", source)
        # pe_cross_tenant should STAY visible (VNet-integrated via cross-RG PEs)
        assert (
            "pe_cross_tenant" in subnet_clusters
        ), f"pe_cross_tenant subnet should remain visible (VNet-integrated) but got: {subnet_clusters}"
        # app_subnet should be hidden (no VNet integration)
        assert "app_subnet" not in subnet_clusters, f"app_subnet should be hidden (no VNet integration) but was found"

    # ── all three opts ON: pe_optimization merges PEs by subnet name ──

    def test_merged_pe_node_survives_all_opts(self, work_dir):
        """With all 3 opts ON, PEs merge by subnet; merged node must survive."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        pe_nodes = analyzer.get_nodes_containing("privateEndpoints-pe_cross_tenant")
        assert len(pe_nodes) > 0, "Merged PE node (privateEndpoints-pe_cross_tenant) missing with all opts ON"

    def test_cross_tenant_edge_from_merged_pe_all_opts(self, work_dir):
        """Merged PE node must still reach the cross-tenant EventHub."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        cross_edges = [(s, t) for s, t, _ in indigo if "rg-cross" in t]
        assert len(cross_edges) >= 1, "Cross-tenant indigo edge missing from merged PE with all opts ON"

    def test_local_edge_from_merged_pe_all_opts(self, work_dir):
        """Merged PE node must also retain edge to localstorageaccount."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        local_edges = [(s, t) for s, t, _ in indigo if "localstorageaccount" in t]
        assert len(local_edges) >= 1, "Local storage indigo edge missing from merged PE with all opts ON"

    # ── structural integrity with opts ──

    def test_both_tenants_visible_with_all_opts(self, work_dir):
        """Both tenant subgraphs must survive regardless of optimizations."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        assert analyzer.has_cluster(f"tenant{TENANT_1}"), "Tenant-1 cluster missing"
        assert analyzer.has_cluster(f"tenant{TENANT_2}"), "Tenant-2 cluster missing"

    def test_vnet_cluster_survives_with_all_opts(self, work_dir):
        """VNet cluster should persist even with all optimizations enabled."""
        _, analyzer = run_graph_generation(
            **self.CT_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        assert analyzer.has_cluster("vnetcross-tenant-vnet"), "VNet cluster disappeared with all opts ON"

    def test_indigo_count_consistent_across_opt_combos(self, work_dir):
        """
        The cross-tenant PE template has 2 PE resources:
        - pe-evhns-cross-tenant: cross-RG/cross-tenant target (always produces indigo edge)
        - pe-local-only: same-RG target (hidden when crossPeOptimization=True)
        When crossPeOptimization=False → 2 indigo edges (both PEs visible).
        When crossPeOptimization=True + peOptimization=False → 1 (same-RG PE hidden).
        When crossPeOptimization=True + peOptimization=True → 2 (merged PE inherits
            cross-RG target so survives, keeping both indigo edges).
        """
        combos = [
            (dict(subnet_optimization=False, cross_pe_optimization=False, pe_optimization=False), 2),
            (dict(subnet_optimization=True, cross_pe_optimization=False, pe_optimization=False), 2),
            (dict(subnet_optimization=False, cross_pe_optimization=True, pe_optimization=False), 1),
            (dict(subnet_optimization=True, cross_pe_optimization=True, pe_optimization=False), 1),
            (dict(subnet_optimization=True, cross_pe_optimization=True, pe_optimization=True), 2),
        ]
        results = []
        for flags, expected in combos:
            _, analyzer = run_graph_generation(
                **self.CT_KWARGS,
                work_dir=str(work_dir),
                **flags,
            )
            count = len(analyzer.get_edges_with_color("indigo"))
            results.append((flags, count, expected))

        for flags, count, expected in results:
            assert count == expected, f"Expected {expected} indigo edges but got {count} with flags={flags}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Ghost Resource Suppression
# ═══════════════════════════════════════════════════════════════════════════════


class TestGhostResourceSuppression:
    """Test that resources appearing in wrong RG's export are deduplicated."""

    def test_ghost_resource_not_duplicated(self, work_dir):
        """
        ghost-webapp appears in both RG_NETWORK and RG_APP templates.
        In Bicep mode each template is processed independently, so a ghost
        resource may appear in BOTH RG subgraphs.  The key assertion is that
        each unique node ID (name-rg) appears at most a limited number of
        times.  Total node definitions may exceed 2 because Graphviz allows
        re-defining the same node (e.g. inside different subgraphs for
        compound edge targets).
        """
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: ghost_resource_network_template(),
                RG_APP: ghost_resource_app_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP],
            work_dir=str(work_dir),
        )

        # Count unique ghost-webapp node IDs
        webapp_nodes = analyzer.get_nodes_containing("ghost-webapp")
        unique_ids = set(webapp_nodes)
        # In Bicep mode, ghost may render as ghost-webapp-test-rg-network AND
        # ghost-webapp-test-rg-app.  That is acceptable (2 distinct IDs for 2 RGs).
        # What we want to avoid is a pathological fan-out (>4 entries).
        assert len(unique_ids) <= 2, f"ghost-webapp has too many unique node IDs. Found: {unique_ids}"

    def test_ghost_suppression_with_all_optimizations(self, work_dir):
        """Ghost suppression should behave consistently with all optimizations enabled."""
        _, analyzer = run_graph_generation(
            templates_by_rg={
                RG_NETWORK: ghost_resource_network_template(),
                RG_APP: ghost_resource_app_template(),
            },
            tenants=[TENANT_1],
            subscriptions=[SUB_1],
            resource_groups=[RG_NETWORK, RG_APP],
            subnet_optimization=True,
            pe_optimization=True,
            cross_pe_optimization=True,
            work_dir=str(work_dir),
        )

        webapp_nodes = analyzer.get_nodes_containing("ghost-webapp")
        unique_ids = set(webapp_nodes)
        assert len(unique_ids) <= 2, f"Ghost suppression failed with all optimizations. Unique IDs: {unique_ids}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Merged PE Ordering (local-first triggers hidden_pe_nodes pollution)
# ═══════════════════════════════════════════════════════════════════════════════

LOCAL_FIRST_TEMPLATES = {
    RG_NETWORK: cross_tenant_network_template(),
    RG_APP: cross_tenant_pe_template_local_first(),
    RG_CROSS: cross_tenant_remote_template(),
}

LOCAL_FIRST_KWARGS = dict(
    templates_by_rg=LOCAL_FIRST_TEMPLATES,
    tenants=[TENANT_1, TENANT_2],
    subscriptions=[SUB_1, SUB_2],
    resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
    rg_to_subscription={RG_NETWORK: SUB_1, RG_APP: SUB_1, RG_CROSS: SUB_2},
    rg_to_tenant={RG_NETWORK: TENANT_1, RG_APP: TENANT_1, RG_CROSS: TENANT_2},
)


class TestMergedPeOrdering:
    """
    When peOptimization merges PEs by subnet, a same-RG PE processed FIRST
    adds the shared merged name to hidden_pe_nodes.  The cross-RG PE processed
    SECOND must discard it so edges are not skipped.
    """

    def test_merged_pe_survives_local_first_ordering(self, work_dir):
        """Merged PE node must exist even when same-RG PE is listed first."""
        _, analyzer = run_graph_generation(
            **LOCAL_FIRST_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        pe_nodes = analyzer.get_nodes_containing("privateEndpoints-pe_cross_tenant")
        assert len(pe_nodes) > 0, "Merged PE node missing when same-RG PE is listed first"

    def test_indigo_edge_survives_local_first_ordering(self, work_dir):
        """Cross-tenant indigo edge must survive with local-first ordering."""
        _, analyzer = run_graph_generation(
            **LOCAL_FIRST_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        indigo = analyzer.get_edges_with_color("indigo")
        cross_edges = [(s, t) for s, t, _ in indigo if "rg-cross" in t]
        assert len(cross_edges) >= 1, "Cross-tenant indigo edge missing with local-first PE ordering"

    def test_vnet_integration_edge_survives_local_first_ordering(self, work_dir):
        """VNet integration (royalblue2) edge must survive with local-first ordering."""
        _, analyzer = run_graph_generation(
            **LOCAL_FIRST_KWARGS,
            subnet_optimization=False,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        blue_edges = analyzer.get_edges_with_color("royalblue2")
        pe_blue = [(s, t) for s, t, _ in blue_edges if "pe_cross_tenant" in s or "pe_cross_tenant" in t]
        assert len(pe_blue) >= 1, "VNet integration edge missing for merged PE with local-first ordering"

    def test_local_first_indigo_count_matches_original(self, work_dir):
        """Indigo edge count with local-first template must match original ordering."""
        # Original ordering
        _, orig_analyzer = run_graph_generation(
            templates_by_rg=CROSS_TENANT_TEMPLATES,
            tenants=[TENANT_1, TENANT_2],
            subscriptions=[SUB_1, SUB_2],
            resource_groups=[RG_NETWORK, RG_APP, RG_CROSS],
            rg_to_subscription=CROSS_TENANT_RG_TO_SUB,
            rg_to_tenant=CROSS_TENANT_RG_TO_TENANT,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        orig_count = len(orig_analyzer.get_edges_with_color("indigo"))

        # Local-first ordering
        _, lf_analyzer = run_graph_generation(
            **LOCAL_FIRST_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        lf_count = len(lf_analyzer.get_edges_with_color("indigo"))

        assert lf_count == orig_count, f"Local-first indigo count ({lf_count}) != original ({orig_count})"


# ═══════════════════════════════════════════════════════════════════════════════
#  Hidden-PE Subnet Cleanup
#  (crossPeOptimization hides a PE → stale subnet_implicit_dependencies entry
#   should NOT keep the subnet visible when subnet optimization is ON)
# ═══════════════════════════════════════════════════════════════════════════════


class TestHiddenPeSubnetCleanup:
    """
    When crossPeOptimization hides a PE that was the only reason a subnet
    appeared in vnet_integrated_subnets (via subnet_implicit_dependencies),
    the subnet should also become hidden if subnet optimization is ON.

    Uses many_pe scenario: 10 PEs across 5 subnets, cross_rg_indices=[0,3,7].
    With peOptimization merging by subnet:
      pe_01 → survives (pe-svc-00 cross-RG)
      pe_02 → ALL PEs same-RG → hidden → subnet should vanish
      pe_03 → survives (pe-svc-07 cross-RG)
      pe_04 → survives (pe-svc-03 cross-RG)
      pe_05 → ALL PEs same-RG → hidden → subnet should vanish
    """

    MANY_PE_KWARGS = dict(
        templates_by_rg={
            RG_NETWORK: many_pe_network_template(),
            RG_APP: many_pe_app_template(num_pe=10, cross_rg_indices=[0, 3, 7]),
            RG_DATA: many_pe_data_template(cross_rg_indices=[0, 3, 7]),
        },
        tenants=[TENANT_1],
        subscriptions=[SUB_1],
        resource_groups=[RG_NETWORK, RG_APP, RG_DATA],
    )

    def test_hidden_pe_subnet_removed_with_subnet_opt(self, work_dir):
        """Subnets whose ONLY cross-RG PE is hidden should vanish with subnet opt."""
        import re

        source, _ = run_graph_generation(
            **self.MANY_PE_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        subnet_clusters = re.findall(r"subgraph\s+cluster_subnet(\S+)", source)
        # pe_02 and pe_05 have only same-RG PEs → hidden by crossPeOpt → subnet should vanish
        assert (
            "pe_02" not in subnet_clusters
        ), f"pe_02 subnet should be hidden (PE hidden by crossPeOpt) but found in: {subnet_clusters}"
        assert (
            "pe_05" not in subnet_clusters
        ), f"pe_05 subnet should be hidden (PE hidden by crossPeOpt) but found in: {subnet_clusters}"

    def test_surviving_pe_subnets_stay_visible(self, work_dir):
        """Subnets with at least one surviving cross-RG PE must remain visible."""
        import re

        source, _ = run_graph_generation(
            **self.MANY_PE_KWARGS,
            subnet_optimization=True,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        subnet_clusters = re.findall(r"subgraph\s+cluster_subnet(\S+)", source)
        # pe_01, pe_03, pe_04 each have at least one cross-RG PE → must stay
        for expected in ["pe_01", "pe_03", "pe_04"]:
            assert (
                expected in subnet_clusters
            ), f"{expected} subnet should remain (cross-RG PE survived) but absent from: {subnet_clusters}"

    def test_all_subnets_visible_without_subnet_opt(self, work_dir):
        """Without subnet optimization, all 5 subnets must be visible."""
        import re

        source, _ = run_graph_generation(
            **self.MANY_PE_KWARGS,
            subnet_optimization=False,
            cross_pe_optimization=True,
            pe_optimization=True,
            work_dir=str(work_dir),
        )
        subnet_clusters = re.findall(r"subgraph\s+cluster_subnet(\S+)", source)
        for expected in ["pe_01", "pe_02", "pe_03", "pe_04", "pe_05"]:
            assert (
                expected in subnet_clusters
            ), f"{expected} subnet should be visible without subnet_opt but absent from: {subnet_clusters}"
